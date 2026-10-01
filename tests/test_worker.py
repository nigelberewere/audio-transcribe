import json
import pytest

from app.config import Settings
from app.db import Database
from app import worker as worker_module


def test_diarization_labels_segments_before_outputs(tmp_path, monkeypatch):
    settings = Settings()
    settings.data_dir = tmp_path / "storage"
    settings.model_dir = tmp_path / "models"
    settings.ensure_directories()
    database = Database(settings.db_path)
    source_path = settings.upload_dir / "source.mp3"
    source_path.write_bytes(b"audio")
    job = {
        "id": "job-1",
        "filename": "meeting.mp3",
        "source_path": str(source_path),
        "requested_model": "tiny",
        "language": "en",
        "initial_prompt": "",
        "diarization": True,
        "formats": ["txt"],
    }
    database.create_job(job)
    events = []

    def fake_convert(_, source, destination):
        events.append("convert")
        destination.write_bytes(source.read_bytes())

    def fake_transcribe(self, job, model_name, wav_path, checkpoint, segments):
        events.append("transcribe")
        checkpoint.write_text(json.dumps([{"start": 0.0, "end": 1.0, "text": "Hello."}]))

    def fake_diarize(path):
        events.append("diarize")
        assert path.name == "audio.wav"
        return [(0.0, 1.0, "SPEAKER_00")]

    def fake_assign(segments, speaker_turns):
        events.append("assign")
        assert speaker_turns == [(0.0, 1.0, "SPEAKER_00")]
        segments[0]["speaker"] = "Speaker 1"
        return segments

    def fake_outputs(job, segments, output_dir):
        events.append("outputs")
        assert segments[0]["speaker"] == "Speaker 1"
        return []

    monkeypatch.setattr(worker_module, "convert_to_wav", fake_convert)
    monkeypatch.setattr(worker_module.TranscriptionWorker, "_transcribe", fake_transcribe)
    monkeypatch.setattr(worker_module, "diarize_audio", fake_diarize)
    monkeypatch.setattr(worker_module, "assign_speakers_to_segments", fake_assign)
    monkeypatch.setattr(worker_module, "write_outputs", fake_outputs)

    worker_module.TranscriptionWorker(settings, database).process(database.get_job("job-1"))

    assert events == ["convert", "transcribe", "diarize", "assign", "outputs"]
    assert database.get_job("job-1")["status"] == "done"
    assert database.get_job("job-1")["error"] is None


def test_list_jobs_most_recent_first(tmp_path):
    settings = Settings()
    settings.data_dir = tmp_path / "storage"
    database = Database(settings.db_path)

    database.create_job({
        "id": "job-old",
        "filename": "old.mp3",
        "source_path": "old.mp3",
        "requested_model": "tiny",
        "language": "en",
        "initial_prompt": "",
        "diarization": False,
        "formats": ["txt"],
    })
    database.update_job("job-old", created_at="2026-01-01T10:00:00+00:00")

    database.create_job({
        "id": "job-new",
        "filename": "new.mp3",
        "source_path": "new.mp3",
        "requested_model": "tiny",
        "language": "en",
        "initial_prompt": "",
        "diarization": False,
        "formats": ["txt"],
    })
    database.update_job("job-new", created_at="2026-01-02T10:00:00+00:00")

    jobs = database.list_jobs()
    assert len(jobs) == 2
    assert jobs[0]["id"] == "job-new"
    assert jobs[1]["id"] == "job-old"


def test_job_claim_and_restart_recovery_are_atomic(tmp_path):
    settings = Settings()
    settings.data_dir = tmp_path / "storage"
    database = Database(settings.db_path)
    database.create_job({
        "id": "job-recover",
        "filename": "recover.mp3",
        "source_path": "recover.mp3",
        "requested_model": "tiny",
        "language": "en",
        "initial_prompt": "",
        "diarization": False,
        "formats": ["txt"],
    })

    claimed = database.claim_next_waiting()
    assert claimed["id"] == "job-recover"
    assert database.get_job("job-recover")["status"] == "processing"

    assert database.recover_processing_jobs() == 1
    assert database.get_job("job-recover")["status"] == "waiting"
    assert database.claim_next_waiting()["id"] == "job-recover"


def test_database_rejects_dynamic_sql_field_names(tmp_path):
    database = Database(tmp_path / "jobs.sqlite3")
    database.create_user("member", "hash")
    with pytest.raises(ValueError):
        database.update_user("member", **{"role = 'admin', password_hash": "bad"})
    with pytest.raises(ValueError):
        database.update_job("missing", **{"status = 'done'": "bad"})


def test_api_jobs_endpoint_ordering_and_queue_positions(tmp_path, monkeypatch):
    from app import main
    settings = Settings()
    settings.data_dir = tmp_path / "storage"
    database = Database(settings.db_path)
    monkeypatch.setattr(main, "database", database)

    # 1. Old waiting job
    database.create_job({
        "id": "job-1",
        "filename": "first.mp3",
        "source_path": "first.mp3",
        "requested_model": "tiny",
        "language": "en",
        "initial_prompt": "",
        "diarization": False,
        "formats": ["txt"],
        "created_by": "user",
    })
    database.update_job("job-1", status="waiting", created_at="2026-01-01T10:00:00+00:00")

    # 2. Done job
    database.create_job({
        "id": "job-2",
        "filename": "second.mp3",
        "source_path": "second.mp3",
        "requested_model": "tiny",
        "language": "en",
        "initial_prompt": "",
        "diarization": False,
        "formats": ["txt"],
        "created_by": "user",
    })
    database.update_job("job-2", status="done", created_at="2026-01-01T11:00:00+00:00")

    # 3. Newest waiting job
    database.create_job({
        "id": "job-3",
        "filename": "third.mp3",
        "source_path": "third.mp3",
        "requested_model": "tiny",
        "language": "en",
        "initial_prompt": "",
        "diarization": False,
        "formats": ["txt"],
        "created_by": "user",
    })
    database.update_job("job-3", status="waiting", created_at="2026-01-01T12:00:00+00:00")

    result = main.jobs(user="user")

    # Most recent job is on top (job-3, then job-2, then job-1)
    assert [j["id"] for j in result] == ["job-3", "job-2", "job-1"]

    # FIFO queue positions:
    # job-1 was created first, so queue position is 1
    # job-3 was created later, so queue position is 2
    # job-2 is done, so queue position is None
    job_map = {j["id"]: j for j in result}
    assert job_map["job-1"]["queue_position"] == 1
    assert job_map["job-2"]["queue_position"] is None
    assert job_map["job-3"]["queue_position"] == 2


def test_api_jobs_user_isolation_and_queue_positions(tmp_path, monkeypatch):
    from app import main
    from app.security import hash_password
    from fastapi import HTTPException
    settings = Settings()
    settings.data_dir = tmp_path / "storage"
    database = Database(settings.db_path)
    monkeypatch.setattr(main, "database", database)
    monkeypatch.setattr(main, "settings", settings)

    database.create_user("admin_user", hash_password("pass"), role="admin")
    database.create_user("alice", hash_password("pass"), role="user")
    database.create_user("bob", hash_password("pass"), role="user")

    # Alice uploads a waiting job at 10:00
    database.create_job({
        "id": "job-alice",
        "filename": "alice_meeting.mp3",
        "source_path": "alice_meeting.mp3",
        "requested_model": "medium",
        "language": "en",
        "initial_prompt": "",
        "diarization": False,
        "formats": ["txt"],
        "created_by": "alice",
    })
    database.update_job("job-alice", status="waiting", created_at="2026-01-01T10:00:00+00:00")

    # Bob uploads a waiting job at 10:30
    database.create_job({
        "id": "job-bob",
        "filename": "bob_meeting.mp3",
        "source_path": "bob_meeting.mp3",
        "requested_model": "large-v3",
        "language": "en",
        "initial_prompt": "",
        "diarization": False,
        "formats": ["txt"],
        "created_by": "bob",
    })
    database.update_job("job-bob", status="waiting", created_at="2026-01-01T10:30:00+00:00")

    # Alice fetches /api/jobs -> only sees alice's job, queue position 1
    alice_jobs = main.jobs(user="alice")
    assert len(alice_jobs) == 1
    assert alice_jobs[0]["id"] == "job-alice"
    assert alice_jobs[0]["queue_position"] == 1

    # Bob fetches /api/jobs -> only sees bob's job, queue position 2 in global FIFO line
    bob_jobs = main.jobs(user="bob")
    assert len(bob_jobs) == 1
    assert bob_jobs[0]["id"] == "job-bob"
    assert bob_jobs[0]["queue_position"] == 2

    # Bob tries all_jobs=True -> regular users cannot bypass isolation
    bob_all = main.jobs(all_jobs=True, user="bob")
    assert len(bob_all) == 1
    assert bob_all[0]["id"] == "job-bob"

    # Admin with all_jobs=False -> sees only admin's own jobs (0 jobs)
    admin_my = main.jobs(all_jobs=False, user="admin_user")
    assert len(admin_my) == 0

    # Admin with all_jobs=True -> sees all department jobs
    admin_all = main.jobs(all_jobs=True, user="admin_user")
    assert len(admin_all) == 2
    assert {j["id"] for j in admin_all} == {"job-alice", "job-bob"}

    # Access control: Bob cannot access Alice's job
    with pytest.raises(HTTPException) as exc:
        main.preview("job-alice", user="bob")
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        main.delete_job("job-alice", user="bob")
    assert exc.value.status_code == 404

    # Alice can delete her own job
    res = main.delete_job("job-alice", user="alice")
    assert res == {"ok": True}


def test_diarization_status_and_upload_does_not_accept_user_token(tmp_path, monkeypatch):
    import os
    from io import BytesIO
    from fastapi import UploadFile
    from app import main

    settings = Settings()
    settings.data_dir = tmp_path / "storage"
    settings.model_dir = tmp_path / "models"
    settings.ensure_directories()
    database = Database(settings.db_path)
    settings.env_file = tmp_path / ".env"
    monkeypatch.setattr(main, "database", database)
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    # Status endpoint returns availability
    status = main.diarization_status(user="user")
    assert "available" in status
    assert "has_token" in status

    # Upload endpoint keeps diarization settings but never changes the global token.
    file_obj = UploadFile(filename="meeting.mp3", file=BytesIO(b"audio content"))
    job = main.upload(
        file=file_obj,
        model="large-v3",
        language="en",
        initial_prompt="",
        diarization=True,
        formats="txt,srt",
        user="user",
    )
    assert job["diarization"] is True
    assert os.environ.get("HF_TOKEN") is None


def test_audio_upload_enforces_server_side_size_limit(tmp_path, monkeypatch):
    from io import BytesIO
    from fastapi import HTTPException, UploadFile
    from app import main

    settings = Settings()
    settings.data_dir = tmp_path / "storage"
    settings.ensure_directories()
    database = Database(settings.db_path)
    monkeypatch.setattr(main, "database", database)
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(main, "MAX_AUDIO_SIZE_BYTES", 4)

    with pytest.raises(HTTPException) as exc:
        main.upload(UploadFile(BytesIO(b"12345"), filename="too-large.mp3"), user="user")

    assert exc.value.status_code == 400
    assert not list(settings.upload_dir.iterdir())


def test_transcription_heartbeat_interpolates_progress_smoothly(tmp_path, monkeypatch):
    import time
    from types import SimpleNamespace

    settings = Settings()
    settings.data_dir = tmp_path / "storage"
    settings.model_dir = tmp_path / "models"
    settings.ensure_directories()
    database = Database(settings.db_path)

    source_path = settings.upload_dir / "short_sample.mp3"
    source_path.write_bytes(b"dummy audio")

    job_id = "job-heartbeat-test"
    database.create_job({
        "id": job_id,
        "filename": "short_sample.mp3",
        "source_path": str(source_path),
        "requested_model": "tiny",
        "language": "en",
        "initial_prompt": "",
        "diarization": False,
        "formats": ["txt"],
    })

    progress_writes = []
    real_segment_events = []
    original_update = database.update_job

    def tracking_update(target_id, **fields):
        if target_id == job_id and "progress" in fields:
            progress_writes.append({
                "progress": fields["progress"],
                "elapsed": fields.get("elapsed_seconds"),
                "eta": fields.get("eta_seconds"),
                "timestamp": time.monotonic(),
            })
        return original_update(target_id, **fields)

    monkeypatch.setattr(database, "update_job", tracking_update)
    monkeypatch.setattr(worker_module, "convert_to_wav", lambda *a, **k: None)
    monkeypatch.setattr(worker_module, "write_outputs", lambda *a, **k: [])

    class FakeSegment:
        def __init__(self, start, end, text):
            self.start = start
            self.end = end
            self.text = text

    def fake_transcribe_generator():
        # Segment 1 arrives at 40% (4.0s / 10.0s) after a short delay
        time.sleep(0.08)
        real_segment_events.append(("segment_1", 40.0, time.monotonic()))
        yield FakeSegment(0.0, 4.0, "First segment.")

        # Segment 2 (final segment, 10.0s / 10.0s -> 99.0%) arrives after another delay
        # During this delay, the heartbeat fires and interpolates progress
        time.sleep(0.25)
        real_segment_events.append(("segment_2", 99.0, time.monotonic()))
        yield FakeSegment(4.0, 10.0, "Second segment.")

    class FakeWhisperModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, *args, **kwargs):
            info = SimpleNamespace(duration=10.0, language="en")
            return fake_transcribe_generator(), info

    monkeypatch.setattr("faster_whisper.WhisperModel", FakeWhisperModel)

    # Use a fast heartbeat interval of 0.05s so multiple heartbeat pulses run during the 0.25s sleep
    worker = worker_module.TranscriptionWorker(settings, database, heartbeat_interval=0.05)
    worker.process(database.get_job(job_id))

    # Real segments yielded: 2
    assert len(real_segment_events) == 2
    seg1_name, seg1_progress, seg1_time = real_segment_events[0]
    seg2_name, seg2_progress, seg2_time = real_segment_events[1]

    # Confirm progress values are written to DB at higher frequency than the number of real segments
    # Filter out initial progress=0 and final job-done progress=100
    intermediate_writes = [w for w in progress_writes if 0.0 < w["progress"] < 100.0]
    assert len(intermediate_writes) > 2, f"Expected more than 2 intermediate writes, got {len(intermediate_writes)}"

    # Confirm that all interpolated progress values written before segment 2 arrives do NOT exceed segment 2's reported progress (99.0%)
    for w in intermediate_writes:
        if w["timestamp"] < seg2_time:
            assert w["progress"] <= seg2_progress, (
                f"Interpolated progress {w['progress']}% exceeded segment 2 progress {seg2_progress}%"
            )

    # Confirm monotonic non-decreasing progress
    values = [w["progress"] for w in progress_writes]
    for i in range(1, len(values)):
        assert values[i] >= values[i - 1], f"Progress went backwards: {values[i-1]} -> {values[i]}"

    # Final job status in database is done
    final_job = database.get_job(job_id)
    assert final_job["status"] == "done"
    assert final_job["progress"] == 100

