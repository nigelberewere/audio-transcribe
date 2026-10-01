import json
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")


def validate_session_id(session_id: str) -> None:
    if not session_id or not SESSION_ID_PATTERN.match(session_id) or len(session_id) > 64:
        raise ValueError("Invalid session ID format")


class RecordingDraftManager:
    """Manages draft recording sessions, incoming chunks, concatenation, and abandoned session cleanup."""

    def __init__(self, draft_dir: Path):
        self.draft_dir = draft_dir
        self.draft_dir.mkdir(parents=True, exist_ok=True)

    def get_session_dir(self, session_id: str) -> Path:
        validate_session_id(session_id)
        session_dir = (self.draft_dir / session_id).resolve()
        if self.draft_dir.resolve() not in session_dir.parents:
            raise ValueError("Invalid session ID path traversal")
        return session_dir

    def save_chunk(self, session_id: str, chunk_index: int, chunk_bytes: bytes, user: str) -> dict[str, Any]:
        if chunk_index < 0:
            raise ValueError("chunk_index must be greater than or equal to 0")

        session_dir = self.get_session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)

        meta_file = session_dir / "meta.json"
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
            if meta.get("user") and meta["user"] != user:
                raise PermissionError("Access denied to recording session")
        else:
            meta = {
                "session_id": session_id,
                "user": user,
                "created_at": time.time(),
                "chunks": [],
            }

        meta["user"] = user
        meta["updated_at"] = time.time()
        chunks_list = meta.setdefault("chunks", [])
        if chunk_index not in chunks_list:
            chunks_list.append(chunk_index)

        chunk_path = session_dir / f"chunk_{chunk_index:06d}.part"
        chunk_path.write_bytes(chunk_bytes)
        meta_file.write_text(json.dumps(meta), encoding="utf-8")

        return {
            "session_id": session_id,
            "chunk_index": chunk_index,
            "chunks_count": len(chunks_list),
        }

    def assemble_recording(self, session_id: str, user: str, output_path: Path) -> int:
        session_dir = self.get_session_dir(session_id)
        if not session_dir.exists():
            raise FileNotFoundError(f"Recording session '{session_id}' not found")

        meta_file = session_dir / "meta.json"
        if not meta_file.exists():
            raise FileNotFoundError(f"Recording session metadata missing for '{session_id}'")

        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        if meta.get("user") and meta["user"] != user:
            raise PermissionError("Access denied to recording session")

        chunk_files = sorted(session_dir.glob("chunk_*.part"))
        if not chunk_files:
            raise ValueError("No audio chunks found for this recording session")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        total_bytes = 0
        with output_path.open("wb") as outfile:
            for c_file in chunk_files:
                with c_file.open("rb") as infile:
                    shutil.copyfileobj(infile, outfile)
                    total_bytes += c_file.stat().st_size

        return total_bytes

    def delete_session(self, session_id: str, user: str | None = None) -> bool:
        try:
            session_dir = self.get_session_dir(session_id)
            if not session_dir.exists():
                return False
            if user:
                meta_file = session_dir / "meta.json"
                if meta_file.exists():
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    if meta.get("user") and meta["user"] != user:
                        raise PermissionError("Access denied to recording session")
            shutil.rmtree(session_dir, ignore_errors=True)
            return True
        except PermissionError:
            raise
        except Exception as exc:
            LOGGER.warning("Could not delete recording session %s: %s", session_id, exc)
            return False

    def cleanup_abandoned_sessions(self, max_age_hours: int = 24) -> int:
        if not self.draft_dir.exists():
            return 0
        cutoff = time.time() - (max_age_hours * 3600)
        cleaned = 0
        for entry in self.draft_dir.iterdir():
            if entry.is_dir():
                try:
                    mtime = entry.stat().st_mtime
                    meta_path = entry / "meta.json"
                    if meta_path.exists():
                        mtime = max(mtime, meta_path.stat().st_mtime)
                    if mtime < cutoff:
                        shutil.rmtree(entry, ignore_errors=True)
                        cleaned += 1
                except Exception as exc:
                    LOGGER.warning("Error cleaning draft session %s: %s", entry.name, exc)
        return cleaned
