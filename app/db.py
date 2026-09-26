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
    created_by TEXT,
    first_name TEXT NOT NULL DEFAULT '',
    surname TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT,
    details TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS folders (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    parent_folder_id TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (parent_folder_id) REFERENCES folders(id)
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    folder_id TEXT,
    uploaded_by TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    mime_type TEXT,
    current_version INTEGER NOT NULL DEFAULT 1,
    deleted INTEGER NOT NULL DEFAULT 0,
    source_document_ids TEXT,
    FOREIGN KEY (folder_id) REFERENCES folders(id)
);
CREATE TABLE IF NOT EXISTS document_versions (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    storage_path TEXT NOT NULL,
    uploaded_by TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    change_note TEXT,
    FOREIGN KEY (document_id) REFERENCES documents(id)
);
CREATE TABLE IF NOT EXISTS document_tags (
    document_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (document_id, tag),
    FOREIGN KEY (document_id) REFERENCES documents(id)
);
CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
    item_type UNINDEXED,
    item_id UNINDEXED,
    filename,
    tags,
    content,
    tokenize = 'porter unicode61'
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
                "first_name": "ALTER TABLE users ADD COLUMN first_name TEXT NOT NULL DEFAULT ''",
                "surname": "ALTER TABLE users ADD COLUMN surname TEXT NOT NULL DEFAULT ''",
                "email": "ALTER TABLE users ADD COLUMN email TEXT NOT NULL DEFAULT ''",
            }
            for name, statement in migrations.items():
                if name not in columns:
                    connection.execute(statement)
            doc_columns = {row[1] for row in connection.execute("PRAGMA table_info(documents)")}
            if "source_document_ids" not in doc_columns:
                connection.execute("ALTER TABLE documents ADD COLUMN source_document_ids TEXT")

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
            rows = connection.execute("SELECT username, first_name, surname, email, role, active, created_at, created_by FROM users ORDER BY username").fetchall()
        return [dict(row) for row in rows]

    def create_user(
        self,
        username: str,
        password_hash: str,
        role: str = "user",
        created_by: str | None = None,
        first_name: str = "",
        surname: str = "",
        email: str = "",
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO users (username, password_hash, role, active, created_at, created_by, first_name, surname, email) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)",
                (username, password_hash, role, now(), created_by, first_name.strip(), surname.strip(), email.strip().lower()),
            )

    def add_audit_log(self, actor: str, action: str, target: str | None, details: str | None) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO audit_log (actor, action, target, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (actor, action, target, details, now()),
            )

    def list_audit_log(self, actor: str | None = None, action: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[dict[str, Any]], bool, list[str], list[str]]:
        filters = []
        values: list[Any] = []
        if actor:
            filters.append("actor = ?")
            values.append(actor)
        if action:
            filters.append("action = ?")
            values.append(action)
        where = f" WHERE {' AND '.join(filters)}" if filters else ""
        page_size = max(1, min(limit, 100))
        query = f"SELECT * FROM audit_log{where} ORDER BY id LIMIT ? OFFSET ?"
        with self.connect() as connection:
            rows = connection.execute(query, [*values, page_size + 1, max(0, offset)]).fetchall()
            actors = [row[0] for row in connection.execute("SELECT DISTINCT actor FROM audit_log ORDER BY actor")]
            actions = [row[0] for row in connection.execute("SELECT DISTINCT action FROM audit_log ORDER BY action")]
        return [dict(row) for row in rows[:page_size]], len(rows) > page_size, actors, actions

    def update_user(self, username: str, **fields: Any) -> None:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self.connect() as connection:
            connection.execute(f"UPDATE users SET {assignments} WHERE username = ?", [*fields.values(), username])

    def delete_user(self, username: str) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM users WHERE username = ?", (username,))

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

    def create_folder(self, folder_id: str, name: str, parent_folder_id: str | None, created_by: str) -> dict[str, Any]:
        folder = {"id": folder_id, "name": name, "parent_folder_id": parent_folder_id, "created_by": created_by, "created_at": now()}
        with self.connect() as connection:
            connection.execute("INSERT INTO folders (id, name, parent_folder_id, created_by, created_at) VALUES (?, ?, ?, ?, ?)", tuple(folder.values()))
        return folder

    def list_folders(self, parent_folder_id: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM folders WHERE parent_folder_id IS ? ORDER BY name", (parent_folder_id,)).fetchall()
        return [dict(row) for row in rows]

    def get_folder(self, folder_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM folders WHERE id = ?", (folder_id,)).fetchone()
        return dict(row) if row else None

    def create_document(self, document: dict[str, Any], version: dict[str, Any], tags: list[str]) -> None:
        source_ids = document.get("source_document_ids")
        if isinstance(source_ids, (list, tuple)):
            source_ids = json.dumps(source_ids)
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO documents (id, filename, storage_path, folder_id, uploaded_by, uploaded_at, file_size, mime_type, current_version, deleted, source_document_ids) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    document["id"],
                    document["filename"],
                    document["storage_path"],
                    document.get("folder_id"),
                    document["uploaded_by"],
                    document["uploaded_at"],
                    document["file_size"],
                    document.get("mime_type"),
                    document.get("current_version", 1),
                    document.get("deleted", 0),
                    source_ids,
                ),
            )
            connection.execute(
                "INSERT INTO document_versions (id, document_id, version_number, storage_path, uploaded_by, uploaded_at, change_note) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    version["id"],
                    version["document_id"],
                    version["version_number"],
                    version["storage_path"],
                    version["uploaded_by"],
                    version["uploaded_at"],
                    version.get("change_note"),
                ),
            )
            connection.executemany("INSERT INTO document_tags (document_id, tag) VALUES (?, ?)", [(document["id"], tag) for tag in tags])
        try:
            from .pdf_tools import extract_text_from_file
            text = extract_text_from_file(document.get("storage_path", ""))
            self.index_document(document["id"], document["filename"], tags, text)
        except Exception:
            pass

    def get_document(self, document_id: str, include_deleted: bool = False) -> dict[str, Any] | None:
        query = "SELECT d.*, GROUP_CONCAT(t.tag) AS tags FROM documents d LEFT JOIN document_tags t ON t.document_id = d.id WHERE d.id = ?"
        values: list[Any] = [document_id]
        if not include_deleted:
            query += " AND d.deleted = 0"
        query += " GROUP BY d.id"
        with self.connect() as connection:
            row = connection.execute(query, values).fetchone()
        return self._document(row) if row else None

    def list_documents(self, folder_id: str | None = None, include_deleted: bool = False) -> list[dict[str, Any]]:
        query = "SELECT d.*, GROUP_CONCAT(t.tag) AS tags FROM documents d LEFT JOIN document_tags t ON t.document_id = d.id WHERE d.folder_id IS ?"
        values: list[Any] = [folder_id]
        if not include_deleted:
            query += " AND d.deleted = 0"
        query += " GROUP BY d.id ORDER BY d.filename"
        with self.connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._document(row) for row in rows]

    def list_deleted_documents(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT d.*, GROUP_CONCAT(t.tag) AS tags FROM documents d LEFT JOIN document_tags t ON t.document_id = d.id WHERE d.deleted = 1 GROUP BY d.id ORDER BY d.filename").fetchall()
        return [self._document(row) for row in rows]

    def add_document_version(self, document_id: str, version: dict[str, Any], file_size: int, mime_type: str | None) -> None:
        with self.connect() as connection:
            connection.execute("INSERT INTO document_versions (id, document_id, version_number, storage_path, uploaded_by, uploaded_at, change_note) VALUES (?, ?, ?, ?, ?, ?, ?)", tuple(version.values()))
            connection.execute("UPDATE documents SET storage_path = ?, uploaded_by = ?, uploaded_at = ?, file_size = ?, mime_type = ?, current_version = ? WHERE id = ?", (version["storage_path"], version["uploaded_by"], version["uploaded_at"], file_size, mime_type, version["version_number"], document_id))
        doc = self.get_document(document_id)
        try:
            from .pdf_tools import extract_text_from_file
            text = extract_text_from_file(version.get("storage_path", ""))
            self.index_document(document_id, doc["filename"] if doc else Path(version["storage_path"]).name, doc.get("tags", []) if doc else [], text)
        except Exception:
            pass

    def list_document_versions(self, document_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM document_versions WHERE document_id = ? ORDER BY version_number DESC", (document_id,)).fetchall()
        return [dict(row) for row in rows]

    def set_document_tags(self, document_id: str, tags: list[str]) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM document_tags WHERE document_id = ?", (document_id,))
            connection.executemany("INSERT INTO document_tags (document_id, tag) VALUES (?, ?)", [(document_id, tag) for tag in tags])
        doc = self.get_document(document_id)
        if doc and not doc.get("deleted"):
            try:
                from .pdf_tools import extract_text_from_file
                text = extract_text_from_file(doc.get("storage_path", ""))
                self.index_document(document_id, doc["filename"], tags, text)
            except Exception:
                pass

    def set_document_deleted(self, document_id: str, deleted: bool) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE documents SET deleted = ? WHERE id = ?", (int(deleted), document_id))
            if deleted:
                connection.execute("DELETE FROM search_index WHERE item_type = 'document' AND item_id = ?", (document_id,))
        if not deleted:
            doc = self.get_document(document_id)
            if doc:
                try:
                    from .pdf_tools import extract_text_from_file
                    text = extract_text_from_file(doc.get("storage_path", ""))
                    self.index_document(document_id, doc["filename"], doc.get("tags", []), text)
                except Exception:
                    pass

    def document_stats(self) -> dict[str, int]:
        today = datetime.now(timezone.utc).date().isoformat()
        with self.connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM documents WHERE deleted = 0").fetchone()[0]
            storage = connection.execute("SELECT COALESCE(SUM(file_size), 0) FROM documents WHERE deleted = 0").fetchone()[0]
            today_count = connection.execute("SELECT COUNT(*) FROM documents WHERE deleted = 0 AND uploaded_at LIKE ?", (f"{today}%",)).fetchone()[0]
        return {"total_documents": int(total), "total_storage_used": int(storage), "documents_uploaded_today": int(today_count)}

    @staticmethod
    def _document(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["tags"] = [tag for tag in (result.pop("tags") or "").split(",") if tag]
        result["deleted"] = bool(result["deleted"])
        if result.get("source_document_ids"):
            try:
                result["source_document_ids"] = json.loads(result["source_document_ids"])
            except Exception:
                pass
        else:
            result["source_document_ids"] = None
        return result

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
            if fields.get("status") == "deleted":
                connection.execute("DELETE FROM search_index WHERE item_type = 'transcript' AND item_id = ?", (job_id,))

    def index_transcript(self, job_id: str, filename: str, initial_prompt: str | None, transcript_text: str) -> None:
        tags = initial_prompt or ""
        content = transcript_text or ""
        with self.connect() as connection:
            connection.execute("DELETE FROM search_index WHERE item_type = 'transcript' AND item_id = ?", (job_id,))
            connection.execute(
                "INSERT INTO search_index (item_type, item_id, filename, tags, content) VALUES ('transcript', ?, ?, ?, ?)",
                (job_id, filename, tags, content),
            )

    def index_document(self, document_id: str, filename: str, tags: list[str] | str, text_content: str) -> None:
        tag_str = ", ".join(tags) if isinstance(tags, (list, tuple)) else (tags or "")
        content = text_content or ""
        with self.connect() as connection:
            connection.execute("DELETE FROM search_index WHERE item_type = 'document' AND item_id = ?", (document_id,))
            connection.execute(
                "INSERT INTO search_index (item_type, item_id, filename, tags, content) VALUES ('document', ?, ?, ?, ?)",
                (document_id, filename, tag_str, content),
            )

    def remove_from_search_index(self, item_type: str, item_id: str) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM search_index WHERE item_type = ? AND item_id = ?", (item_type, item_id))

    def search(self, query: str) -> dict[str, list[dict[str, Any]]]:
        import re
        tokens = re.findall(r"\w+", query)
        if not tokens:
            return {"transcripts": [], "documents": []}
        fts_query = " ".join(f'"{t}"*' for t in tokens)
        with self.connect() as connection:
            try:
                rows = connection.execute(
                    """
                    SELECT item_type, item_id, filename, tags,
                           snippet(search_index, -1, '<mark>', '</mark>', '...', 15) as snippet
                    FROM search_index
                    WHERE search_index MATCH ?
                    ORDER BY rank
                    LIMIT 50
                    """,
                    (fts_query,),
                ).fetchall()
            except sqlite3.OperationalError:
                return {"transcripts": [], "documents": []}

        transcripts: list[dict[str, Any]] = []
        documents: list[dict[str, Any]] = []
        for row in rows:
            item_type = row["item_type"]
            item_id = row["item_id"]
            snippet = row["snippet"]
            if item_type == "transcript":
                job = self.get_job(item_id)
                if job is not None and job.get("status") != "done":
                    continue
                transcripts.append({
                    "id": item_id,
                    "filename": job["filename"] if job else row["filename"],
                    "snippet": snippet,
                    "created_at": job.get("created_at") if job else None,
                    "duration": job.get("duration", 0.0) if job else 0.0,
                    "selected_model": job.get("selected_model") if job else None,
                })
            elif item_type == "document":
                doc = self.get_document(item_id, include_deleted=True)
                if doc is not None and doc.get("deleted"):
                    continue
                documents.append({
                    "id": item_id,
                    "filename": doc["filename"] if doc else row["filename"],
                    "tags": doc.get("tags", [t.strip() for t in (row["tags"] or "").split(",") if t.strip()]) if doc else [t.strip() for t in (row["tags"] or "").split(",") if t.strip()],
                    "snippet": snippet,
                    "uploaded_at": doc.get("uploaded_at") if doc else None,
                    "file_size": doc.get("file_size") if doc else 0,
                    "current_version": doc.get("current_version", 1) if doc else 1,
                })
        return {"transcripts": transcripts, "documents": documents}

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
