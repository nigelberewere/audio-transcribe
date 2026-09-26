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