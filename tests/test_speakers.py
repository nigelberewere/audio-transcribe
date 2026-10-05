import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from docx import Document

from app import main
from app.config import Settings
from app.db import Database
from app.security import hash_password


@pytest.fixture
def speaker_state(tmp_path, monkeypatch):
    settings = Settings()
    settings.data_dir = tmp_path / "storage"
    settings.model_dir = tmp_path / "models"
    settings.ensure_directories()
    database = Database(settings.db_path)
    database.create_user("alice", hash_password("pass"), role="user")
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(main, "database", database)
    return settings, database


def create_job(speaker_state, job_id="speaker-job", diarization=True, status="done"):
    settings, database = speaker_state
    database.create_job({
        "id": job_id,
        "filename": "meeting.wav",
        "source_path": str(settings.upload_dir / "meeting.wav"),
        "requested_model": "medium",
        "language": "en",
        "initial_prompt": "",
        "diarization": diarization,
        "formats": ["txt", "srt", "docx", "json"],
        "created_by": "alice",
    })
    database.update_job(job_id, status=status, completed_at="2026-10-01T12:00:00+00:00", selected_model="medium")
    segments = [
        {"start": 0.0, "end": 1.0, "speaker": "Speaker 1", "text": "Welcome."},
        {"start": 1.2, "end": 2.0, "speaker": "Speaker 2", "text": "Thank you."},
    ]
    job_dir = settings.job_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "segments.json").write_text(json.dumps(segments), encoding="utf-8")
    return job_id, segments


def test_speaker_rename_regenerates_exports_without_worker_processing(speaker_state, monkeypatch):
    settings, database = speaker_state
    job_id, original_segments = create_job(speaker_state)
    called = []
    monkeypatch.setattr(main.worker, "_transcribe", lambda *args: called.append("transcribe"))
    monkeypatch.setattr(main.worker, "process", lambda *args: called.append("process"))

    listing = main.list_speakers(job_id, user="alice")
    assert [item["speaker_label"] for item in listing["speakers"]] == ["Speaker 1", "Speaker 2"]
    assert listing["speakers"][0]["sample"] == "Welcome."

    main.update_speakers(job_id, main.SpeakerNamesEdit(names={"Speaker 1": "Alice"}), user="alice")
    result = main.regenerate_speaker_outputs(job_id, user="alice")

    output_dir = settings.job_dir / job_id / "outputs"
    assert set(result["outputs"]) == {"meeting.txt", "meeting.srt", "meeting.docx", "meeting.json"}
    assert "Alice: Welcome." in (output_dir / "meeting.txt").read_text(encoding="utf-8")
    assert "Speaker 2: Thank you." in (output_dir / "meeting.txt").read_text(encoding="utf-8")
    assert "Alice: Welcome." in (output_dir / "meeting.srt").read_text(encoding="utf-8")
    docx_text = "\n".join(paragraph.text for paragraph in Document(output_dir / "meeting.docx").paragraphs)
    assert "Alice: Welcome." in docx_text
    exported_json = json.loads((output_dir / "meeting.json").read_text(encoding="utf-8"))
    assert exported_json["segments"][0]["speaker"] == "Alice"
    assert json.loads((settings.job_dir / job_id / "segments.json").read_text(encoding="utf-8")) == original_segments
    assert called == []

    with database.connect() as connection:
        audit = connection.execute(
            "SELECT actor, action, target, details FROM audit_log WHERE action = 'speakers_renamed'"
        ).fetchone()
    assert tuple(audit) == ("alice", "speakers_renamed", job_id, "labels: Speaker 1")


def test_speaker_operations_require_done_diarized_job(speaker_state):
    settings, _ = speaker_state
    job_id, _ = create_job(speaker_state, job_id="plain-job", diarization=False)
    (settings.job_dir / job_id / "segments.json").write_text(
        json.dumps([{"start": 0.0, "end": 1.0, "text": "Plain transcript."}]),
        encoding="utf-8",
    )
    with pytest.raises(HTTPException, match="no speaker diarization data"):
        main.list_speakers(job_id, user="alice")

    waiting_id, _ = create_job(speaker_state, job_id="waiting-job", status="waiting")
    with pytest.raises(HTTPException, match="completed jobs"):
        main.list_speakers(waiting_id, user="alice")


def test_speaker_update_rejects_unknown_label(speaker_state):
    job_id, _ = create_job(speaker_state)
    with pytest.raises(HTTPException, match="Unknown speaker label"):
        main.update_speakers(job_id, main.SpeakerNamesEdit(names={"Speaker 9": "Nobody"}), user="alice")
