import hashlib
import hmac
import logging
import secrets
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .audio import SUPPORTED_EXTENSIONS, check_ffmpeg
from .config import Settings
from .db import Database
from .security import hash_password, verify_password
from .worker import TranscriptionWorker

settings = Settings(); settings.ensure_directories()
log_dir = settings.data_dir / "logs"; log_dir.mkdir(parents=True, exist_ok=True)
handler = RotatingFileHandler(log_dir / "transcribe.log", maxBytes=10_000_000, backupCount=5, encoding="utf-8")
logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler()])
logger = logging.getLogger(__name__)
database = Database(settings.db_path)
worker = TranscriptionWorker(settings, database)
sessions: dict[str, str] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    check_ffmpeg(settings.ffmpeg_path)
    if settings.admin_password and not database_user_exists(settings.admin_user):
        with database.connect() as connection:
            connection.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (settings.admin_user, hash_password(settings.admin_password)))
    worker.start()
    yield
    worker.stop()


app = FastAPI(title="Offline Legal Transcription", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


def database_user_exists(username: str) -> bool:
    with database.connect() as connection:
        return connection.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone() is not None


def current_user(session: str | None = Cookie(default=None)) -> str:
    if not session or session not in sessions:
        raise HTTPException(status_code=401, detail="Authentication required")
    return sessions[session]


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.post("/api/login")
def login(username: str = Form(...), password: str = Form(...)):
    with database.connect() as connection:
        row = connection.execute("SELECT password_hash FROM users WHERE username = ?", (username,)).fetchone()
    if not row or not verify_password(password, row[0]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = secrets.token_urlsafe(32); sessions[token] = username
    response = {"ok": True, "username": username}
    from fastapi.responses import JSONResponse
    result = JSONResponse(response); result.set_cookie("session", token, httponly=True, samesite="strict")
    return result


@app.post("/api/logout")
def logout(session: str | None = Cookie(default=None), user: str = Depends(current_user)):
    sessions.pop(session, None)
    from fastapi.responses import JSONResponse
    response = JSONResponse({"ok": True}); response.delete_cookie("session"); return response


@app.get("/api/jobs")
def jobs(user: str = Depends(current_user)):
    results = database.list_jobs()
    for item in results:
        item["queue_position"] = next((index + 1 for index, other in enumerate(results) if other["status"] == "waiting" and other["created_at"] <= item["created_at"]), None) if item["status"] == "waiting" else None
    return results


@app.post("/api/jobs")
def upload(file: UploadFile = File(...), model: str = Form("auto"), language: str = Form("auto"), initial_prompt: str = Form(""), diarization: bool = Form(False), formats: str = Form("txt,txt_timestamps,srt,vtt,docx,json"), user: str = Depends(current_user)):
    extension = Path(file.filename or "").suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Unsupported format. Allowed: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
    job_id = uuid4().hex; destination = settings.upload_dir / f"{job_id}{extension}"
    with destination.open("wb") as output:
        while chunk := file.file.read(1024 * 1024): output.write(chunk)
    database.create_job({"id": job_id, "filename": file.filename, "source_path": str(destination), "requested_model": model, "language": language, "initial_prompt": initial_prompt, "diarization": diarization, "formats": [item.strip() for item in formats.split(",") if item.strip()]})
    return database.get_job(job_id)


class TranscriptEdit(BaseModel):
    text: str


@app.get("/api/jobs/{job_id}/preview")
def preview(job_id: str, user: str = Depends(current_user)):
    job = database.get_job(job_id)
    if not job: raise HTTPException(404, "Job not found")
    checkpoint = settings.job_dir / job_id / "segments.json"
    return {"segments": checkpoint.exists() and checkpoint.read_text(encoding="utf-8") or "[]"}


@app.put("/api/jobs/{job_id}/preview")
def edit_preview(job_id: str, edit: TranscriptEdit, user: str = Depends(current_user)):
    if not database.get_job(job_id): raise HTTPException(404, "Job not found")
    target = settings.job_dir / job_id / "edited.txt"; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(edit.text, encoding="utf-8")
    return {"ok": True}


@app.get("/api/jobs/{job_id}/outputs/{filename}")
def download(job_id: str, filename: str, user: str = Depends(current_user)):
    target = (settings.job_dir / job_id / "outputs" / filename).resolve()
    output_root = (settings.job_dir / job_id / "outputs").resolve()
    if output_root not in target.parents or not target.exists(): raise HTTPException(404, "Output not found")
    return FileResponse(target, filename=target.name)


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str, user: str = Depends(current_user)):
    import shutil
    job = database.get_job(job_id)
    if not job: raise HTTPException(404, "Job not found")
    for path in (Path(job["source_path"]), settings.job_dir / job_id):
        if path.is_dir(): shutil.rmtree(path, ignore_errors=True)
        else: path.unlink(missing_ok=True)
    database.update_job(job_id, status="deleted")
    return {"ok": True}
