import io
import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.db import Database
from app.recordings import RecordingDraftManager, validate_session_id
from app.security import hash_password


@pytest.fixture
def recording_test_env(tmp_path, monkeypatch):
    settings = Settings()
    settings.data_dir = tmp_path / "storage"
    settings.model_dir = tmp_path / "models"
    settings.ensure_directories()

    database = Database(settings.db_path)
    database.create_user("alice", hash_password("pass"), role="user")
    database.create_user("bob", hash_password("pass"), role="user")
    database.create_user("admin_user", hash_password("pass"), role="admin")

    draft_mgr = RecordingDraftManager(settings.recording_draft_dir)

    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(main, "database", database)
    monkeypatch.setattr(main, "draft_manager", draft_mgr)

    return {
        "settings": settings,
        "database": database,
        "draft_manager": draft_mgr,
    }


def make_upload_file(content: bytes, filename: str = "chunk.part") -> UploadFile:
    return UploadFile(io.BytesIO(content), filename=filename)


def test_session_id_validation():
    # Valid IDs
    validate_session_id("rec_123456789_abcdef")
    validate_session_id("valid-session-id-01")

    # Invalid IDs
    with pytest.raises(ValueError):
        validate_session_id("")
    with pytest.raises(ValueError):
        validate_session_id("../traversal")
    with pytest.raises(ValueError):
        validate_session_id("invalid/char")
    with pytest.raises(ValueError):
        validate_session_id("a" * 70)


def test_save_chunks_and_assemble(recording_test_env):
    draft_mgr = recording_test_env["draft_manager"]
    session_id = "test_session_assemble"

    chunk1 = b"PART_1_AUDIO_HEADER_"
    chunk2 = b"PART_2_AUDIO_BODY_"
    chunk3 = b"PART_3_AUDIO_FOOTER"

    res1 = draft_mgr.save_chunk(session_id, 0, chunk1, "alice")
    assert res1["chunks_count"] == 1

    res2 = draft_mgr.save_chunk(session_id, 1, chunk2, "alice")
    assert res2["chunks_count"] == 2

    res3 = draft_mgr.save_chunk(session_id, 2, chunk3, "alice")
    assert res3["chunks_count"] == 3

    out_file = recording_test_env["settings"].upload_dir / "assembled.webm"
    total_bytes = draft_mgr.assemble_recording(session_id, "alice", out_file)

    assert total_bytes == len(chunk1) + len(chunk2) + len(chunk3)
    assert out_file.read_bytes() == chunk1 + chunk2 + chunk3


def test_assemble_rejects_missing_chunk(recording_test_env):
    draft_mgr = recording_test_env["draft_manager"]
    session_id = "test_session_missing_chunk"
    draft_mgr.save_chunk(session_id, 0, b"first", "alice")
    draft_mgr.save_chunk(session_id, 2, b"third", "alice")

    with pytest.raises(ValueError, match="incomplete"):
        draft_mgr.assemble_recording(session_id, "alice", recording_test_env["settings"].upload_dir / "out.webm")


def test_finalize_complete_recording_creates_valid_job(recording_test_env):
    session_id = "rec_session_finalize_ok"
    database = recording_test_env["database"]

    # Upload 2 chunks via endpoint
    chunk1 = b"RIFF____WAVEfmt "
    chunk2 = b"data____AUDIO_SAMPLES"

    res1 = main.upload_recording_chunk(
        session_id=session_id,
        chunk_index=0,
        chunk=make_upload_file(chunk1),
        user="alice",
    )
    assert res1["ok"] is True
    assert res1["chunks_count"] == 1

    res2 = main.upload_recording_chunk(
        session_id=session_id,
        chunk_index=1,
        chunk=make_upload_file(chunk2),
        user="alice",
    )
    assert res2["ok"] is True
    assert res2["chunks_count"] == 2

    # Finalize recording
    job = main.finalize_recording(
        session_id=session_id,
        filename="Weekly_Sync.webm",
        model="medium",
        language="en",
        initial_prompt="Quarterly planning",
        diarization=True,
        formats="txt,srt,docx",
        user="alice",
    )

    # 1. Structure is identical to a normal file upload
    assert job is not None
    assert job["filename"] == "Weekly_Sync.webm"
    assert job["status"] == "waiting"
    assert job["requested_model"] == "medium"
    assert job["language"] == "en"
    assert job["initial_prompt"] == "Quarterly planning"
    assert job["diarization"] is True
    assert job["formats"] == ["txt", "srt", "docx"]
    assert job["created_by"] == "alice"
    assert Path(job["source_path"]).exists()
    assert Path(job["source_path"]).read_bytes() == chunk1 + chunk2

    # 2. Audit log recorded same pattern as uploads
    entries, _, _, _ = database.list_audit_log(actor="alice", action="job_created")
    assert len(entries) >= 1
    assert entries[0]["target"] == job["id"]
    assert "Weekly_Sync.webm" in entries[0]["details"]

    # 3. Draft chunks are cleaned up after finalization
    session_dir = recording_test_env["settings"].recording_draft_dir / session_id
    assert not session_dir.exists()


def test_abandoned_recording_cleanup(recording_test_env):
    draft_mgr = recording_test_env["draft_manager"]
    database = recording_test_env["database"]
    old_session = "rec_abandoned_old"
    recent_session = "rec_active_recent"

    # Save a chunk for old session
    draft_mgr.save_chunk(old_session, 0, b"OLD_ABANDONED_AUDIO", "bob")
    old_folder = draft_mgr.get_session_dir(old_session)
    old_meta = old_folder / "meta.json"

    # Artificially age the old session to 30 hours ago
    past_time = time.time() - (30 * 3600)
    import os
    os.utime(old_folder, (past_time, past_time))
    os.utime(old_meta, (past_time, past_time))

    # Save a chunk for recent session
    draft_mgr.save_chunk(recent_session, 0, b"RECENT_AUDIO", "bob")
    recent_folder = draft_mgr.get_session_dir(recent_session)

    # Run cleanup with 24 hours threshold
    cleaned = draft_mgr.cleanup_abandoned_sessions(max_age_hours=24)
    assert cleaned == 1

    # Old abandoned folder is cleaned up
    assert not old_folder.exists()
    # Recent active folder remains
    assert recent_folder.exists()

    # Never created a job in the database
    bob_jobs = database.list_jobs(username="bob")
    assert len(bob_jobs) == 0


def test_recording_user_isolation(recording_test_env):
    session_id = "rec_alice_private"
    draft_mgr = recording_test_env["draft_manager"]
    draft_mgr.save_chunk(session_id, 0, b"ALICE_CONFIDENTIAL_AUDIO", "alice")

    # Bob cannot upload chunk to Alice's session
    with pytest.raises(HTTPException) as exc:
        main.upload_recording_chunk(
            session_id=session_id,
            chunk_index=1,
            chunk=make_upload_file(b"BOB_INTRUDER_CHUNK"),
            user="bob",
        )
    assert exc.value.status_code == 403

    # Bob cannot finalize Alice's session
    with pytest.raises(HTTPException) as exc:
        main.finalize_recording(
            session_id=session_id,
            filename="stolen.webm",
            user="bob",
        )
    assert exc.value.status_code == 403

    # Bob cannot cancel/delete Alice's session
    with pytest.raises(HTTPException) as exc:
        main.cancel_recording(session_id=session_id, user="bob")
    assert exc.value.status_code == 403

    # Alice can cancel/delete her own session
    res = main.cancel_recording(session_id=session_id, user="alice")
    assert res == {"ok": True}
    assert not (recording_test_env["settings"].recording_draft_dir / session_id).exists()
