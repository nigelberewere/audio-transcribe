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

    def get_smtp_config(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        """Resolve SMTP settings: overrides -> database -> environment variables -> defaults."""
        db_settings: dict[str, str] = {}
        if self.database:
            try:
                db_settings = self.database.get_settings([
                    "smtp_host", "smtp_port", "smtp_username", "smtp_password",
                    "smtp_from_address", "smtp_use_tls"
                ])
            except Exception:
                db_settings = {}

        # 1. Host
        host = ""
        if overrides and overrides.get("smtp_host") is not None:
            host = str(overrides["smtp_host"]).strip()
        elif "smtp_host" in db_settings:
            host = str(db_settings["smtp_host"]).strip()
        elif getattr(self.settings, "smtp_host", None):
            host = str(self.settings.smtp_host).strip()

        # 2. Port
        port = 587
        if overrides and overrides.get("smtp_port") is not None:
            try:
                port = int(overrides["smtp_port"])
            except (ValueError, TypeError):
                port = 587
        elif "smtp_port" in db_settings:
            try:
                port = int(db_settings["smtp_port"])
            except (ValueError, TypeError):
                port = 587
        elif getattr(self.settings, "smtp_port", None):
            try:
                port = int(self.settings.smtp_port)
            except (ValueError, TypeError):
                port = 587

        # 3. Username
        username = ""
        if overrides and overrides.get("smtp_username") is not None:
            username = str(overrides["smtp_username"]).strip()
        elif "smtp_username" in db_settings:
            username = str(db_settings["smtp_username"]).strip()
        elif getattr(self.settings, "smtp_username", None):
            username = str(self.settings.smtp_username).strip()

        # 4. Password (write-only / sensitive)
        password = ""
        if overrides and overrides.get("smtp_password"):
            password = str(overrides["smtp_password"])
        elif "smtp_password" in db_settings:
            password = str(db_settings["smtp_password"])
        elif getattr(self.settings, "smtp_password", None):
            password = str(self.settings.smtp_password)

        # 5. From Address
        from_addr = ""
        if overrides and overrides.get("smtp_from_address") is not None:
            from_addr = str(overrides["smtp_from_address"]).strip()
        elif "smtp_from_address" in db_settings:
            from_addr = str(db_settings["smtp_from_address"]).strip()
        elif getattr(self.settings, "smtp_from_address", None):
            from_addr = str(self.settings.smtp_from_address).strip()
        if not from_addr:
            from_addr = username or "noreply@transcribe.local"

        # 6. Use TLS
        use_tls = True
        if overrides and overrides.get("smtp_use_tls") is not None:
            val = overrides["smtp_use_tls"]
            use_tls = str(val).strip().lower() in ("true", "1", "yes", "on") if not isinstance(val, bool) else val
        elif "smtp_use_tls" in db_settings:
            val = db_settings["smtp_use_tls"]
            use_tls = str(val).strip().lower() in ("true", "1", "yes", "on")
        elif getattr(self.settings, "smtp_use_tls", None) is not None:
            use_tls = bool(self.settings.smtp_use_tls)

        timeout = getattr(self.settings, "smtp_timeout", 10.0)

        return {
            "smtp_host": host,
            "smtp_port": port,
            "smtp_username": username,
            "smtp_password": password,
            "smtp_from_address": from_addr,
            "smtp_use_tls": use_tls,
            "smtp_timeout": timeout,
        }

    @property
    def is_enabled(self) -> bool:
        cfg = self.get_smtp_config()
        return bool(cfg["smtp_host"])

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

    def send_notification(
        self,
        recipient_email: str,
        subject: str,
        text_body: str,
        target_id: str | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> bool:
        """Send email via SMTP with timeout, error handling, and audit logging."""
        cfg = self.get_smtp_config(overrides)
        if not cfg["smtp_host"]:
            return False

        masked = mask_email(recipient_email)
        from_addr = cfg["smtp_from_address"] or "noreply@transcribe.local"

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = recipient_email
        msg.set_content(text_body)

        try:
            server = smtplib.SMTP(host=cfg["smtp_host"], port=cfg["smtp_port"], timeout=cfg["smtp_timeout"])
            try:
                if cfg["smtp_use_tls"]:
                    server.starttls()
                if cfg["smtp_username"] and cfg["smtp_password"]:
                    server.login(cfg["smtp_username"], cfg["smtp_password"])
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

    def send_test_email(
        self,
        recipient_email: str,
        actor: str,
        overrides: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        """Send an immediate test email, independent of any job, logging test_notification_sent/failed to audit_log."""
        if not recipient_email or "@" not in recipient_email:
            if self.database:
                self.database.add_audit_log(actor=actor, action="test_notification_failed", target="invalid_email", details="Invalid recipient email address")
            return False, "Invalid recipient email address"

        cfg = self.get_smtp_config(overrides)
        if not cfg["smtp_host"]:
            masked = mask_email(recipient_email)
            if self.database:
                self.database.add_audit_log(actor=actor, action="test_notification_failed", target=masked, details="SMTP host is not configured")
            return False, "SMTP host is not configured"

        masked = mask_email(recipient_email)
        from_addr = cfg["smtp_from_address"] or "noreply@transcribe.local"

        msg = EmailMessage()
        msg["Subject"] = "Test Email: Zingsa Files Center Notification"
        msg["From"] = from_addr
        msg["To"] = recipient_email
        msg.set_content(
            "Hello,\n\n"
            "This is a test notification from Zingsa Files Center.\n\n"
            f"Sent at: {format_timestamp()}\n"
            f"SMTP Host: {cfg['smtp_host']}:{cfg['smtp_port']}\n"
            f"TLS: {'Enabled' if cfg['smtp_use_tls'] else 'Disabled'}\n\n"
            "If you received this message, your notification settings are functioning correctly."
        )

        try:
            server = smtplib.SMTP(host=cfg["smtp_host"], port=cfg["smtp_port"], timeout=cfg["smtp_timeout"])
            try:
                if cfg["smtp_use_tls"]:
                    server.starttls()
                if cfg["smtp_username"] and cfg["smtp_password"]:
                    server.login(cfg["smtp_username"], cfg["smtp_password"])
                server.send_message(msg)
            finally:
                try:
                    server.quit()
                except Exception:
                    pass

            LOGGER.info("Test notification email sent to %s by actor %s", masked, actor)
            if self.database:
                self.database.add_audit_log(actor=actor, action="test_notification_sent", target=masked, details=f"Host: {cfg['smtp_host']}")
            return True, f"Test email sent successfully to {recipient_email}."

        except Exception as exc:
            err_msg = str(exc)
            LOGGER.warning("Test notification email to %s failed: %s", masked, err_msg)
            if self.database:
                self.database.add_audit_log(actor=actor, action="test_notification_failed", target=masked, details=f"Error: {categorize_error(err_msg)}")
            return False, f"SMTP Error: {err_msg}"

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

