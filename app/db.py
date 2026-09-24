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
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    created_by TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT,
    details TEXT,
    created_at TEXT NOT NULL
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
            columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
            migrations = {
                "role": "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'",
                "active": "ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1",
                "created_at": "ALTER TABLE users ADD COLUMN created_at TEXT NOT NULL DEFAULT ''",
                "created_by": "ALTER TABLE users ADD COLUMN created_by TEXT",
            }
            for name, statement in migrations.items():
                if name not in columns:
                    connection.execute(statement)

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

    def get_user(self, username: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None

    def list_users(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT username, role, active, created_at, created_by FROM users ORDER BY username").fetchall()
        return [dict(row) for row in rows]

    def create_user(self, username: str, password_hash: str, role: str, created_by: str | None) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO users (username, password_hash, role, active, created_at, created_by) VALUES (?, ?, ?, 1, ?, ?)",
                (username, password_hash, role, now(), created_by),
            )

    def update_user(self, username: str, **fields: Any) -> None:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self.connect() as connection:
            connection.execute(f"UPDATE users SET {assignments} WHERE username = ?", [*fields.values(), username])

    def add_audit_log(self, actor: str, action: str, target: str | None = None, details: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO audit_log (actor, action, target, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (actor, action, target, details, now()),
            )

    def list_audit_log(
        self,
        limit: int = 50,
        offset: int = 0,
        actor: str | None = None,
        action: str | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        filters: list[str] = []
        values: list[Any] = []
        if actor:
            filters.append("actor = ?")
            values.append(actor)
        if action:
            filters.append("action = ?")
            values.append(action)
        where = f" WHERE {' AND '.join(filters)}" if filters else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT id, actor, action, target, details, created_at FROM audit_log{where} ORDER BY id DESC LIMIT ? OFFSET ?",
                [*values, limit + 1, offset],
            ).fetchall()
        return [dict(row) for row in rows[:limit]], len(rows) > limit

    def audit_log_actors(self) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute("SELECT DISTINCT actor FROM audit_log ORDER BY actor").fetchall()
        return [row[0] for row in rows]

    def audit_log_actions(self) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute("SELECT DISTINCT action FROM audit_log ORDER BY action").fetchall()
        return [row[0] for row in rows]

    def count_users(self) -> int:
        with self.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def count_active_jobs(self) -> int:
        with self.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('waiting', 'processing')").fetchone()[0])

    def count_completed_jobs_today(self) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        with self.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM jobs WHERE status = 'done' AND completed_at LIKE ?", (f"{today}%",)).fetchone()[0])

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
