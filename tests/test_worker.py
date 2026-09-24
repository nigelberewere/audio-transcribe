import json

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