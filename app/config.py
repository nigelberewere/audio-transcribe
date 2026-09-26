from pathlib import Path
import json
import os


def _load_dotenv(path: Path | None = None) -> None:
    env_file = path or Path(".env")
    if not env_file.is_file():
        return
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = val
    except Exception:
        pass


class Settings:
    def __init__(self) -> None:
        _load_dotenv()
        values = {"default_model": "large-v3", "fallback_model": "medium", "queue_threshold": 2, "auto_delete_days": 0}
        config_path = Path(os.getenv("TRANSCRIBE_CONFIG", "config.json"))
        if config_path.exists():
            values.update(json.loads(config_path.read_text(encoding="utf-8")))
        self.host = os.getenv("TRANSCRIBE_HOST", "0.0.0.0")
        self.port = int(os.getenv("TRANSCRIBE_PORT", "8420"))
        self.data_dir = Path(os.getenv("TRANSCRIBE_DATA_DIR", "storage"))
        self.documents_storage_path = Path(os.getenv("DOCUMENTS_STORAGE_PATH", values.get("documents_storage_path", str(self.data_dir / "documents"))))
        self.model_dir = Path(os.getenv("TRANSCRIBE_MODEL_DIR", "models"))
        self.ffmpeg_path = os.getenv("TRANSCRIBE_FFMPEG", "ffmpeg")
        self.default_model = os.getenv("TRANSCRIBE_DEFAULT_MODEL", values["default_model"])
        self.fallback_model = os.getenv("TRANSCRIBE_FALLBACK_MODEL", values["fallback_model"])
        self.queue_threshold = int(os.getenv("TRANSCRIBE_QUEUE_THRESHOLD", values["queue_threshold"]))
        self.auto_delete_days = int(os.getenv("TRANSCRIBE_AUTO_DELETE_DAYS", values["auto_delete_days"]))
        self.session_secret = os.getenv("TRANSCRIBE_SESSION_SECRET", "change-this-secret")
        self.admin_user = os.getenv("TRANSCRIBE_ADMIN_USER", "")
        self.admin_password = os.getenv("TRANSCRIBE_ADMIN_PASSWORD", "")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jobs.sqlite3"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def job_dir(self) -> Path:
        return self.data_dir / "jobs"

    def ensure_directories(self) -> None:
        for path in (self.data_dir, self.upload_dir, self.job_dir, self.model_dir, self.documents_storage_path):
            path.mkdir(parents=True, exist_ok=True)
