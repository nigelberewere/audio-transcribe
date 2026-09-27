import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

LOGGER = logging.getLogger(__name__)


def mask_email(email: str | None) -> str:
    """Mask email address to domain only for secure audit logging (e.g. ***@company.com)."""
    if not email:
        return "***"
    email = email.strip()
    if "@" in email:
        _, domain = email.split("@", 1)
        return f"***@{domain}"
    return "***"


def categorize_error(error: Any) -> str:
    """Map internal errors/exceptions to a high-level safe category without leaking internal paths or stack traces."""
    if not error:
        return "Processing failed"
    msg = str(error).lower()
    if any(k in msg for k in ("ffmpeg", "convert", "wav", "audio format", "codec", "corrupt")):
        return "Audio conversion failed"
    if any(k in msg for k in ("diariz", "pyannote", "hf_token", "speaker")):
        return "Speaker diarization failed"
    if any(k in msg for k in ("whisper", "model", "transcribe", "cuda", "cpu", "out of memory", "oom")):
        return "Audio transcription failed"
    return "Processing failed"


def format_timestamp(ts: str | None = None) -> str:
    """Format completion timestamp in a human-readable format."""
    if not ts:
        return datetime.now(timezone.utc).strftime("%b %d, %Y, %I:%M %p UTC")
    try:
        clean = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        return dt.strftime("%b %d, %Y, %I:%M %p UTC")
    except Exception:
        return str(ts)


class NotificationService:
    """Notification service for dispatching email updates on job completions and actions."""

    def __init__(self, settings: Any, database: Any = None):
        self.settings = settings
        self.database = database

    @property
    def is_enabled(self) -> bool:
        return bool(self.settings.smtp_host and self.settings.smtp_host.strip())

    def resolve_recipient_email(self, job: dict[str, Any]) -> str | None:
        """Resolve recipient email from job owner's user account."""
        owner_username = job.get("created_by") or job.get("user")
        if owner_username and self.database:
            user = self.database.get_user(owner_username)
            if user and user.get("email"):
                return user["email"].strip()
            if "@" in owner_username:
                return owner_username.strip()
        if job.get("email"):
            return str(job["email"]).strip()
        return None

    def send_notification(self, recipient_email: str, subject: str, text_body: str, target_id: str | None = None) -> bool:
        """Send email via SMTP with timeout, error handling, and audit logging."""
        if not self.is_enabled:
            return False

        masked = mask_email(recipient_email)
        from_addr = (
            getattr(self.settings, "smtp_from_address", "")
            or getattr(self.settings, "smtp_username", "")
            or "noreply@transcribe.local"
        )

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = recipient_email
        msg.set_content(text_body)

        try:
            timeout = getattr(self.settings, "smtp_timeout", 10.0)
            host = self.settings.smtp_host
            port = getattr(self.settings, "smtp_port", 587)
            use_tls = getattr(self.settings, "smtp_use_tls", True)

            server = smtplib.SMTP(host=host, port=port, timeout=timeout)
            try:
                if use_tls:
                    server.starttls()
                smtp_user = getattr(self.settings, "smtp_username", "")
                smtp_pass = getattr(self.settings, "smtp_password", "")
                if smtp_user and smtp_pass:
                    server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            finally:
                try:
                    server.quit()
                except Exception:
                    pass

            LOGGER.info("Notification email sent to %s for target %s", masked, target_id)
            if self.database and target_id:
                self.database.add_audit_log(actor="system", action="notification_sent", target=target_id, details=masked)
            return True

        except Exception as exc:
            LOGGER.warning("Failed to send notification email to %s for target %s: %s", masked, target_id, exc)
            if self.database and target_id:
                self.database.add_audit_log(actor="system", action="notification_failed", target=target_id, details=masked)
            return False

    def notify_job_completion(
        self, job: dict[str, Any], status: str, error: Any = None, job_type: str = "transcription"
    ) -> bool:
        """Trigger completion notification for a job (success or failure)."""
        if not self.is_enabled:
            return False

        recipient_email = self.resolve_recipient_email(job)
        if not recipient_email:
            LOGGER.info("No recipient email found for job %s, skipping notification", job.get("id"))
            return False

        filename = job.get("filename", "audio recording")
        job_id = job.get("id", "")
        completion_time = format_timestamp(job.get("completed_at"))
        status_norm = "done" if status in ("done", "completed") else "failed"

        app_url = getattr(self.settings, "app_url", "http://localhost:8420").rstrip("/")
        view_url = f"{app_url}/transcription#job-{job_id}"

        if status_norm == "done":
            subject = f"Transcription Completed: {filename}"
            lines = [
                "Your transcription job has completed successfully.",
                "",
                f"File: {filename}",
                "Status: done",
                f"Completed: {completion_time}",
                f"View transcript: {view_url}",
                "",
                "Please sign in to the application to review or export your transcription.",
            ]
        else:
            err_category = categorize_error(error or job.get("error"))
            subject = f"Transcription Failed: {filename}"
            lines = [
                "Your transcription job could not be completed.",
                "",
                f"File: {filename}",
                "Status: failed",
                f"Completed: {completion_time}",
                f"Error details: {err_category}",
                f"View job details: {view_url}",
                "",
                "Please sign in to the application to inspect the job status or retry your upload.",
            ]

        body = "\n".join(lines)
        return self.send_notification(recipient_email, subject, body, target_id=job_id)
