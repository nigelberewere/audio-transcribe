import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    source_path TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_model TEXT NOT NULL,
    selected_model TEXT,
    language TEXT NOT NULL,
    initial_prompt TEXT NOT NULL,
    diarization INTEGER NOT NULL DEFAULT 0,
    formats TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    elapsed_seconds REAL NOT NULL DEFAULT 0,
    eta_seconds REAL,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def create_job(self, job: dict[str, Any]) -> None:
        timestamp = now()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO jobs (id, filename, source_path, status, requested_model, language, initial_prompt, diarization, formats, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job["id"], job["filename"], job["source_path"], "waiting", job.get("requested_model", "auto"), job.get("language", "auto"), job.get("initial_prompt", ""), int(job.get("diarization", False)), json.dumps(job.get("formats", [])), timestamp, timestamp),
            )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._decode(row) if row else None

    def list_jobs(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM jobs ORDER BY created_at").fetchall()
        return [self._decode(row) for row in rows]

    def update_job(self, job_id: str, **fields: Any) -> None:
        fields["updated_at"] = now()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = [json.dumps(value) if key == "formats" else value for key, value in fields.items()]
        values.append(job_id)
        with self.connect() as connection:
            connection.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", values)

    def waiting_count(self, exclude_id: str | None = None) -> int:
        query = "SELECT COUNT(*) FROM jobs WHERE status = 'waiting'"
        values: tuple[str, ...] = ()
        if exclude_id:
            query += " AND id != ?"
            values = (exclude_id,)
        with self.connect() as connection:
            return int(connection.execute(query, values).fetchone()[0])

    def next_waiting(self) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE status = 'waiting' ORDER BY created_at LIMIT 1").fetchone()
        return self._decode(row) if row else None

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["formats"] = json.loads(result["formats"])
        result["diarization"] = bool(result["diarization"])
        return result
