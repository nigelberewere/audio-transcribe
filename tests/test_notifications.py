import json
from unittest.mock import MagicMock, patch
import pytest

from app.config import Settings
from app.db import Database
from app.notifications import NotificationService, mask_email, categorize_error, format_timestamp
from app.worker import TranscriptionWorker


def test_mask_email():
    assert mask_email("user@example.com") == "***@example.com"
    assert mask_email("john.doe@company.org") == "***@company.org"
    assert mask_email("alice@sub.domain.co.zw") == "***@sub.domain.co.zw"
    assert mask_email("") == "***"
    assert mask_email(None) == "***"
    assert mask_email("invalid-email") == "***"


def test_categorize_error():
    # Audio conversion errors
    assert categorize_error("ffmpeg returned code 1: corrupt file") == "Audio conversion failed"
    assert categorize_error("wav conversion failed: bad audio format") == "Audio conversion failed"

    # Diarization errors
    assert categorize_error("pyannote diarization failed: missing token") == "Speaker diarization failed"
    assert categorize_error("speaker diarization exception in pipeline") == "Speaker diarization failed"

    # Transcription errors
    assert categorize_error("WhisperModel failed: cuda out of memory") == "Audio transcription failed"
    assert categorize_error("transcribe model loading error") == "Audio transcription failed"

    # Generic errors
    assert categorize_error("Unexpected OS error occurred") == "Processing failed"
    assert categorize_error(None) == "Processing failed"
    assert categorize_error("") == "Processing failed"

    # Ensure internal file paths or stack traces are not returned
    error_with_path = "ffmpeg error in C:\\Users\\Administrator\\data\\uploads\\job123.mp3"
    result = categorize_error(error_with_path)
    assert "C:\\Users" not in result
    assert result == "Audio conversion failed"


def test_unconfigured_smtp_sends_nothing_and_completes_cleanly(tmp_path):
    settings = Settings()
    settings.data_dir = tmp_path / "storage"
    settings.model_dir = tmp_path / "models"
    settings.smtp_host = ""  # Unconfigured
    settings.ensure_directories()
    database = Database(settings.db_path)

    database.create_user("alice", "passhash", "user", email="alice@example.com")
    job = {
        "id": "job-unconfigured",
        "filename": "unconfigured.mp3",
        "source_path": "unconfigured.mp3",
        "created_by": "alice",
    }
    database.create_job(job)

    service = NotificationService(settings, database)
    assert service.is_enabled is False

    with patch("smtplib.SMTP") as mock_smtp:
        sent = service.notify_job_completion(job, status="done")
        assert sent is False
        mock_smtp.assert_not_called()

    # Ensure no audit log entry was created
    audit_entries, _, _, _ = database.list_audit_log(target="job-unconfigured")
    assert len(audit_entries) == 0


def test_configured_smtp_sends_email_to_job_owner_and_logs_audit(tmp_path):
    settings = Settings()
    settings.data_dir = tmp_path / "storage"
    settings.model_dir = tmp_path / "models"
    settings.smtp_host = "smtp.example.com"
    settings.smtp_port = 587
    settings.smtp_username = "notifier@example.com"
    settings.smtp_password = "secretpassword"
    settings.smtp_from_address = "noreply@company.com"
    settings.smtp_use_tls = True
    settings.app_url = "http://my-transcribe-app.org:8420"
    settings.ensure_directories()
    database = Database(settings.db_path)

    database.create_user("alice", "passhash", "user", email="alice@company.com")
    job = {
        "id": "job-succ-1",
        "filename": "quarterly_results.mp3",
        "source_path": "dummy.mp3",
        "created_by": "alice",
        "completed_at": "2026-09-27T08:30:00Z",
    }
    database.create_job(job)

    service = NotificationService(settings, database)
    assert service.is_enabled is True

    mock_server = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_server) as mock_smtp_cls:
        sent = service.notify_job_completion(job, status="done")
        assert sent is True

        mock_smtp_cls.assert_called_once_with(host="smtp.example.com", port=587, timeout=10.0)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("notifier@example.com", "secretpassword")
        mock_server.send_message.assert_called_once()
        mock_server.quit.assert_called_once()

        # Inspect the message sent
        sent_msg = mock_server.send_message.call_args[0][0]
        assert sent_msg["To"] == "alice@company.com"
        assert sent_msg["From"] == "noreply@company.com"
        assert "quarterly_results.mp3" in sent_msg["Subject"]
        assert "Completed" in sent_msg["Subject"]

        body = sent_msg.get_content()
        assert "quarterly_results.mp3" in body
        assert "Status: done" in body
        assert "http://my-transcribe-app.org:8420/transcription#job-job-succ-1" in body
        assert "Sep 27, 2026" in body

        # Strict confidentiality: NO transcript content should ever be present
        secret_text = "Highly confidential earnings data"
        assert secret_text not in body

    # Verify audit log
    entries, _, _, _ = database.list_audit_log(target="job-succ-1")
    assert len(entries) == 1
    log = entries[0]
    assert log["actor"] == "system"
    assert log["action"] == "notification_sent"
    assert log["target"] == "job-succ-1"
    assert log["details"] == "***@company.com"  # Must be masked, not full alice@company.com!


def test_failure_notification_contains_error_category_and_no_stack_traces(tmp_path):
    settings = Settings()
    settings.data_dir = tmp_path / "storage"
    settings.model_dir = tmp_path / "models"
    settings.smtp_host = "smtp.example.com"
    settings.ensure_directories()
    database = Database(settings.db_path)

    database.create_user("bob", "passhash", "user", email="bob@firm.org")
    job = {
        "id": "job-fail-1",
        "filename": "interview.m4a",
        "source_path": "dummy.m4a",
        "created_by": "bob",
        "completed_at": "2026-09-27T09:15:00Z",
    }
    database.create_job(job)

    service = NotificationService(settings, database)

    raw_error = RuntimeError("ffmpeg error in /private/users/bob/storage/audio.wav: frame header corrupted")
    mock_server = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_server):
        sent = service.notify_job_completion(job, status="failed", error=raw_error)
        assert sent is True

        sent_msg = mock_server.send_message.call_args[0][0]
        assert sent_msg["To"] == "bob@firm.org"
        assert "interview.m4a" in sent_msg["Subject"]
        assert "Failed" in sent_msg["Subject"]

        body = sent_msg.get_content()
        assert "interview.m4a" in body
        assert "Status: failed" in body
        assert "Audio conversion failed" in body
        assert "/private/users/bob" not in body  # NO internal paths!
        assert "RuntimeError" not in body

    # Verify audit log
    entries, _, _, _ = database.list_audit_log(target="job-fail-1")
    assert len(entries) == 1
    assert entries[0]["action"] == "notification_sent"
    assert entries[0]["details"] == "***@firm.org"


def test_smtp_failure_logs_notification_failed_and_does_not_fail_job(tmp_path, monkeypatch):
    settings = Settings()
    settings.data_dir = tmp_path / "storage"
    settings.model_dir = tmp_path / "models"
    settings.smtp_host = "smtp.example.com"
    settings.ensure_directories()
    database = Database(settings.db_path)

    database.create_user("carol", "passhash", "user", email="carol@example.com")
    source_path = settings.upload_dir / "source.mp3"
    source_path.write_bytes(b"audio")
    job = {
        "id": "job-smtp-fail",
        "filename": "recording.mp3",
        "source_path": str(source_path),
        "requested_model": "tiny",
        "language": "en",
        "initial_prompt": "",
        "diarization": False,
        "formats": ["txt"],
        "created_by": "carol",
    }
    database.create_job(job)

    # Worker mocks
    monkeypatch.setattr("app.worker.convert_to_wav", lambda *args: None)
    monkeypatch.setattr(TranscriptionWorker, "_transcribe", lambda self, j, m, w, c, s: c.write_text(json.dumps([{"start": 0, "end": 1, "text": "Confidential transcript"}])))
    monkeypatch.setattr("app.worker.write_outputs", lambda *args: [])

    # Mock SMTP to raise a connection/timeout error
    with patch("smtplib.SMTP", side_effect=TimeoutError("SMTP connection timed out after 10s")):
        worker = TranscriptionWorker(settings, database)
        # Process should succeed without raising!
        worker.process(database.get_job("job-smtp-fail"))

    # The transcription job must still be 'done'! SMTP failure must NEVER break the job.
    db_job = database.get_job("job-smtp-fail")
    assert db_job["status"] == "done"
    assert db_job["error"] is None

    # Audit log must reflect notification_failed with masked email
    entries, _, _, _ = database.list_audit_log(target="job-smtp-fail")
    assert len(entries) == 1
    assert entries[0]["actor"] == "system"
    assert entries[0]["action"] == "notification_failed"
    assert entries[0]["details"] == "***@example.com"
