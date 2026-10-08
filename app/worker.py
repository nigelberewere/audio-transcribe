import json
import logging
import os
import threading
import time
from pathlib import Path

from .audio import convert_to_wav
from .config import Settings
from .db import Database
from .diarizer import assign_speakers_to_segments, diarize_audio
from .formats import write_outputs
from .notifications import NotificationService
from .queue_policy import QueuePolicy

LOGGER = logging.getLogger(__name__)
INITIAL_PROMPT_STYLE_ANCHOR = (
    "This is a professionally transcribed meeting recording with proper capitalization and punctuation."
)


class TranscriptionWorker:
    def __init__(self, settings: Settings, database: Database, heartbeat_interval: float = 1.0):
        self.settings = settings
        self.database = database
        self.heartbeat_interval = heartbeat_interval
        self.policy = QueuePolicy(settings.default_model, settings.fallback_model, settings.queue_threshold)
        self.notifier = NotificationService(settings, database)
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.database.recover_processing_jobs()
        self.thread = threading.Thread(target=self._run, name="transcription-worker", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
        if self.thread:
            self.thread.join(timeout=10)
            if self.thread.is_alive():
                LOGGER.error("Transcription worker did not stop within 10 seconds")

    def wake(self) -> None:
        self.wake_event.set()

    def _run(self) -> None:
        while not self.stop_event.is_set():
            job = self.database.claim_next_waiting()
            if job:
                try:
                    self.process(job)
                except Exception as exc:
                    LOGGER.exception("Job %s failed", job["id"])
                    self.database.update_job(job["id"], status="failed", error=str(exc), completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ"))
            else:
                self.wake_event.wait(1)
                self.wake_event.clear()

    def process(self, job: dict) -> None:
        try:
            waiting = self.database.waiting_count(exclude_id=job["id"])
            model = self.policy.choose_model(job["requested_model"], waiting)
            self.database.update_job(job["id"], status="processing", selected_model=model, progress=0, error=None)
            job["selected_model"] = model
            job_root = self.settings.job_dir / job["id"]
            job_root.mkdir(parents=True, exist_ok=True)
            wav_path = job_root / "audio.wav"
            checkpoint = job_root / "segments.json"
            convert_to_wav(self.settings.ffmpeg_path, Path(job["source_path"]), wav_path)
            segments = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else []
            self._transcribe(job, model, wav_path, checkpoint, segments)
            segments = json.loads(checkpoint.read_text(encoding="utf-8"))
            if job.get("diarization"):
                speaker_turns = diarize_audio(wav_path)
                segments = assign_speakers_to_segments(segments, speaker_turns)
                checkpoint.write_text(json.dumps(segments, indent=2), encoding="utf-8")
            completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ")
            job["completed_at"] = completed_at
            raw_formats = self.database.get_settings(["allowed_export_formats"]).get("allowed_export_formats")
            if raw_formats:
                try:
                    configured = json.loads(raw_formats)
                except json.JSONDecodeError:
                    configured = raw_formats.split(",")
                job["formats"] = [fmt for fmt in ("txt", "txt_timestamps", "srt", "vtt", "docx", "json") if fmt in configured]
                if not job["formats"]:
                    job["formats"] = ["txt", "txt_timestamps", "srt", "vtt", "docx", "json"]
            self.database.update_job(job["id"], formats=job["formats"])
            write_outputs(job, segments, job_root / "outputs")
            self.database.update_job(job["id"], status="done", progress=100, elapsed_seconds=0, eta_seconds=0, completed_at=completed_at)
            transcript_text = "\n".join(s.get("text", "").strip() for s in segments if s.get("text", "").strip())
            self.database.index_transcript(job["id"], job["filename"], job.get("initial_prompt", ""), transcript_text)
            try:
                self.notifier.notify_job_completion(job, status="done")
            except Exception as notify_exc:
                LOGGER.warning("Failed to dispatch notification for job %s: %s", job["id"], notify_exc)
        except Exception as exc:
            if "completed_at" not in job or not job["completed_at"]:
                job["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                self.notifier.notify_job_completion(job, status="failed", error=exc)
            except Exception as notify_exc:
                LOGGER.warning("Failed to dispatch notification for job %s: %s", job["id"], notify_exc)
            raise

    def _transcribe(self, job: dict, model_name: str, wav_path: Path, checkpoint: Path, segments: list[dict]) -> None:
        from faster_whisper import WhisperModel
        local_model = self.settings.model_dir / f"faster-whisper-{model_name}"
        cached_snapshots = self.settings.model_dir / "huggingface" / "hub" / f"models--Systran--faster-whisper-{model_name}" / "snapshots"
        snapshots = sorted(cached_snapshots.glob("*")) if cached_snapshots.is_dir() else []
        model_source = str(local_model) if local_model.is_dir() else str(snapshots[0]) if snapshots else model_name
        model = WhisperModel(model_source, device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 1, download_root=str(self.settings.model_dir))
        audio_offset = segments[-1]["end"] if segments else 0
        language = None if job["language"] == "auto" else job["language"]
        user_prompt = (job.get("initial_prompt") or "").strip()
        # A short style anchor is more predictable than rewriting user terminology, at the cost of some prompt context.
        initial_prompt = f"{INITIAL_PROMPT_STYLE_ANCHOR} {user_prompt}" if user_prompt else None
        whisper_segments, info = model.transcribe(str(wav_path), language=language, initial_prompt=initial_prompt, vad_filter=True, condition_on_previous_text=True, without_timestamps=False)
        job["duration"] = getattr(info, "duration", 0.0) or 0.0
        job["detected_language"] = getattr(info, "language", job["language"]) or job["language"]
        job["device"] = "cpu"
        job["compute_type"] = "int8"
        duration = job["duration"]
        started = time.monotonic()
        initial_progress = (audio_offset / duration * 100) if duration and audio_offset else 0.0

        state = {
            "last_real_progress": initial_progress,
            "last_real_elapsed": 0.0,
            "current_eta": None,
            "last_written_progress": initial_progress,
        }
        state_lock = threading.Lock()
        stop_heartbeat = threading.Event()

        def _heartbeat_worker():
            while not stop_heartbeat.wait(timeout=self.heartbeat_interval):
                with state_lock:
                    current_eta = state["current_eta"]
                    last_real_progress = state["last_real_progress"]
                    last_real_elapsed = state["last_real_elapsed"]

                if current_eta is None or current_eta <= 0 or duration <= 0 or last_real_elapsed <= 0:
                    continue

                now = time.monotonic()
                dt = now - (started + last_real_elapsed)
                if dt <= 0:
                    continue

                remaining_progress = 100.0 - last_real_progress
                if remaining_progress <= 0:
                    continue

                # Progress delta from elapsed time vs current ETA
                # Damping factor ensures estimate stays slightly conservative
                fraction = dt / (dt + current_eta)
                delta = fraction * remaining_progress * 0.85
                interpolated = min(99.0, round(last_real_progress + delta, 1))

                total_elapsed = now - started
                remaining_eta = max(0.0, round(current_eta - dt, 1))

                with state_lock:
                    if interpolated > state["last_written_progress"]:
                        state["last_written_progress"] = interpolated
                        self.database.update_job(
                            job["id"],
                            progress=interpolated,
                            elapsed_seconds=round(total_elapsed, 1),
                            eta_seconds=remaining_eta,
                        )

        heartbeat_thread = threading.Thread(
            target=_heartbeat_worker,
            name=f"transcribe-heartbeat-{job['id']}",
            daemon=True,
        )
        heartbeat_thread.start()

        try:
            for segment in whisper_segments:
                if segment.end <= audio_offset:
                    continue
                segments.append({"start": segment.start, "end": segment.end, "text": segment.text.strip()})
                checkpoint.write_text(json.dumps(segments, indent=2), encoding="utf-8")

                real_progress = min(99.0, segment.end / duration * 100) if duration else 0.0
                elapsed = time.monotonic() - started
                eta = elapsed * (100 / real_progress - 1) if real_progress > 0 else None

                with state_lock:
                    # Real data always takes precedence over the estimate
                    state["last_real_progress"] = real_progress
                    state["last_real_elapsed"] = elapsed
                    state["current_eta"] = eta
                    state["last_written_progress"] = real_progress
                    self.database.update_job(
                        job["id"],
                        progress=real_progress,
                        elapsed_seconds=elapsed,
                        eta_seconds=eta,
                    )
        finally:
            stop_heartbeat.set()
            heartbeat_thread.join()
