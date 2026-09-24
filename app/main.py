import hashlib
import hmac
import logging
import secrets
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .audio import SUPPORTED_EXTENSIONS, check_ffmpeg
from .config import Settings
from .db import Database, now
from .security import hash_password, verify_password
from .worker import TranscriptionWorker

settings = Settings(); settings.ensure_directories()
log_dir = settings.data_dir / "logs"; log_dir.mkdir(parents=True, exist_ok=True)
handler = RotatingFileHandler(log_dir / "transcribe.log", maxBytes=10_000_000, backupCount=5, encoding="utf-8")
logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler()])
logger = logging.getLogger(__name__)
database = Database(settings.db_path)
worker = TranscriptionWorker(settings, database)
sessions: dict[str, dict[str, str]] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    check_ffmpeg(settings.ffmpeg_path)
    if database.count_users() == 0 and settings.admin_user and settings.admin_password:
        database.create_user(settings.admin_user, hash_password(settings.admin_password), "admin", None)
        logger.info("Bootstrap admin account created for %s.", settings.admin_user)
    worker.start()
    yield
    worker.stop()


app = FastAPI(title="Zingsa Files Center", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


def current_user(session: str | None = Cookie(default=None)) -> str:
    if not session or session not in sessions:
        raise HTTPException(status_code=401, detail="Authentication required")
    username = sessions[session]["username"]
    user = database.get_user(username)
    if not user or not user["active"]:
        sessions.pop(session, None)
        raise HTTPException(status_code=401, detail="Authentication required")
    return username


def current_admin(user: str = Depends(current_user)) -> str:
    account = database.get_user(user)
    if not account or account["role"] != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "admin-login.html")


@app.get("/admin", response_class=HTMLResponse)
def admin_page(session: str | None = Cookie(default=None)) -> Response:
    try:
        current_admin(current_user(session))
    except HTTPException:
        return RedirectResponse("/", status_code=303)
    return FileResponse(Path(__file__).parent / "static" / "admin.html")


@app.post("/api/login")
def login(username: str = Form(...), password: str = Form(...)):
    with database.connect() as connection:
        row = connection.execute("SELECT password_hash, role, active FROM users WHERE username = ?", (username,)).fetchone()
    if not row or not row["active"] or not verify_password(password, row["password_hash"]):
        details = "inactive account" if row and not row["active"] else "invalid credentials"
        database.add_audit_log(username, "login_failed", None, details)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = secrets.token_urlsafe(32); sessions[token] = {"username": username, "role": row["role"]}
    response = {"ok": True, "username": username}
    from fastapi.responses import JSONResponse
    result = JSONResponse(response); result.set_cookie("session", token, httponly=True, samesite="strict")
    return result


@app.post("/api/admin/login")
def admin_login(username: str = Form(...), password: str = Form(...)):
    account = database.get_user(username)
    if not account or not account["active"] or account["role"] != "admin" or not verify_password(password, account["password_hash"]):
        details = "inactive account" if account and not account["active"] else "invalid credentials"
        database.add_audit_log(username, "login_failed", None, details)
        raise HTTPException(status_code=401, detail="Invalid administrator credentials")
    token = secrets.token_urlsafe(32); sessions[token] = {"username": username, "role": "admin"}
    from fastapi.responses import JSONResponse
    result = JSONResponse({"ok": True, "username": username}); result.set_cookie("session", token, httponly=True, samesite="strict")
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


@app.get("/documents", response_class=HTMLResponse)
def documents_page(_: str = Depends(current_user)) -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "documents.html")


def _document_folder(folder_id: str | None) -> str | None:
    if folder_id and not database.get_folder(folder_id):
        raise HTTPException(status_code=404, detail="Folder not found")
    return folder_id


def _tags(value: str) -> list[str]:
    return sorted({tag.strip() for tag in value.split(",") if tag.strip()})


@app.get("/api/documents")
def list_documents(folder_id: str | None = None, user: str = Depends(current_user)):
    return {"folders": database.list_folders(_document_folder(folder_id)), "documents": database.list_documents(folder_id)}


@app.post("/api/documents/folders")
def create_document_folder(name: str = Form(...), parent_folder_id: str | None = Form(None), user: str = Depends(current_user)):
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Folder name is required")
    folder = database.create_folder(uuid4().hex, name, _document_folder(parent_folder_id), user)
    return folder


@app.post("/api/documents")
def upload_document(file: UploadFile = File(...), folder_id: str | None = Form(None), tags: str = Form(""), user: str = Depends(current_user)):
    folder_id = _document_folder(folder_id)
    document_id = uuid4().hex
    uploaded_at = now()
    destination = settings.documents_storage_path / document_id / "1"
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / Path(file.filename or "unnamed-file").name
    size = 0
    with target.open("wb") as output:
        while chunk := file.file.read(1024 * 1024):
            output.write(chunk)
            size += len(chunk)
    document = {"id": document_id, "filename": Path(file.filename or "unnamed-file").name, "storage_path": str(target), "folder_id": folder_id, "uploaded_by": user, "uploaded_at": uploaded_at, "file_size": size, "mime_type": file.content_type, "current_version": 1, "deleted": 0}
    version = {"id": uuid4().hex, "document_id": document_id, "version_number": 1, "storage_path": str(target), "uploaded_by": user, "uploaded_at": uploaded_at, "change_note": None}
    database.create_document(document, version, _tags(tags))
    database.add_audit_log(user, "document_uploaded", document_id, f"filename: {document['filename']}")
    return database.get_document(document_id)


@app.get("/api/documents/{document_id}")
def get_document(document_id: str, user: str = Depends(current_user)):
    document = database.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    document["versions"] = database.list_document_versions(document_id)
    return document


@app.get("/api/documents/{document_id}/download")
def download_document(document_id: str, version: int | None = None, user: str = Depends(current_user)):
    document = database.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    path = document["storage_path"]
    if version is not None:
        selected = next((item for item in database.list_document_versions(document_id) if item["version_number"] == version), None)
        if not selected:
            raise HTTPException(status_code=404, detail="Version not found")
        path = selected["storage_path"]
    target = Path(path).resolve()
    root = (settings.documents_storage_path / document_id).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target, filename=document["filename"])


@app.post("/api/documents/{document_id}/versions")
def upload_document_version(document_id: str, file: UploadFile = File(...), change_note: str = Form(""), user: str = Depends(current_user)):
    document = database.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    version_number = document["current_version"] + 1
    destination = settings.documents_storage_path / document_id / str(version_number)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / document["filename"]
    size = 0
    with target.open("wb") as output:
        while chunk := file.file.read(1024 * 1024):
            output.write(chunk)
            size += len(chunk)
    uploaded_at = now()
    version = {"id": uuid4().hex, "document_id": document_id, "version_number": version_number, "storage_path": str(target), "uploaded_by": user, "uploaded_at": uploaded_at, "change_note": change_note.strip() or None}
    database.add_document_version(document_id, version, size, file.content_type or document["mime_type"])
    database.add_audit_log(user, "document_version_added", document_id, f"version: {version_number}")
    return database.get_document(document_id)


@app.put("/api/documents/{document_id}/tags")
def update_document_tags(document_id: str, tags: str = Form(""), user: str = Depends(current_user)):
    if not database.get_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    database.set_document_tags(document_id, _tags(tags))
    return database.get_document(document_id)


@app.delete("/api/documents/{document_id}")
def delete_document(document_id: str, user: str = Depends(current_user)):
    if not database.get_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    database.set_document_deleted(document_id, True)
    database.add_audit_log(user, "document_deleted", document_id, None)
    return {"ok": True}


@app.get("/api/admin/documents/deleted")
def deleted_documents(_: str = Depends(current_admin)):
    return database.list_deleted_documents()


@app.post("/api/admin/documents/{document_id}/restore")
def restore_document(document_id: str, admin: str = Depends(current_admin)):
    document = database.get_document(document_id, include_deleted=True)
    if not document or not document["deleted"]:
        raise HTTPException(status_code=404, detail="Deleted document not found")
    database.set_document_deleted(document_id, False)
    database.add_audit_log(admin, "document_restored", document_id, None)
    return database.get_document(document_id)


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


@app.get("/api/admin/users")
def admin_users(_: str = Depends(current_admin)):
    return database.list_users()


@app.post("/api/admin/users")
def create_admin_user(username: str = Form(...), password: str = Form(...), role: str = Form("user"), admin: str = Depends(current_admin)):
    username = username.strip()
    if role not in {"admin", "user"}:
        raise HTTPException(status_code=400, detail="Invalid role")
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required")
    if database.get_user(username):
        raise HTTPException(status_code=409, detail="Username already exists")
    database.create_user(username, hash_password(password), role, admin)
    database.add_audit_log(admin, "user_created", username, f"role: {role}")
    return {"ok": True}


def _would_remove_last_admin(username: str, role: str | None = None, active: int | None = None) -> bool:
    account = database.get_user(username)
    if not account:
        return False
    becomes_admin = role if role is not None else account["role"]
    remains_active = active if active is not None else account["active"]
    if becomes_admin == "admin" and remains_active:
        return False
    return sum(user["role"] == "admin" and user["active"] for user in database.list_users()) <= 1 and account["role"] == "admin" and account["active"]


@app.patch("/api/admin/users/{username}")
def update_admin_user(username: str, role: str | None = Form(None), active: int | None = Form(None), admin: str = Depends(current_admin)):
    account = database.get_user(username)
    if not account:
        raise HTTPException(status_code=404, detail="User not found")
    if role is not None and role not in {"admin", "user"}:
        raise HTTPException(status_code=400, detail="Invalid role")
    if active is not None and active not in {0, 1}:
        raise HTTPException(status_code=400, detail="Invalid active status")
    if username == admin and role == "user" and _would_remove_last_admin(username, role=role):
        raise HTTPException(status_code=400, detail="Cannot remove the last active administrator")
    if username == admin and active == 0 and _would_remove_last_admin(username, active=active):
        raise HTTPException(status_code=400, detail="Cannot disable the last active administrator")
    fields = {key: value for key, value in {"role": role, "active": active}.items() if value is not None}
    if fields:
        database.update_user(username, **fields)
        if role is not None and role != account["role"]:
            database.add_audit_log(admin, "user_role_changed", username, f"{account['role']} -> {role}")
        if active == 0 and account["active"]:
            database.add_audit_log(admin, "user_disabled", username, None)
    return {"ok": True}


@app.post("/api/admin/users/{username}/reset-password")
def reset_user_password(username: str, password: str = Form(...), confirm_password: str = Form(...), admin: str = Depends(current_admin)):
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if password != confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    if not database.get_user(username):
        raise HTTPException(status_code=404, detail="User not found")
    database.update_user(username, password_hash=hash_password(password))
    database.add_audit_log(admin, "user_password_reset", username, None)
    return {"ok": True}


@app.get("/api/admin/audit-log")
@app.get("/api/admin/audit")
def admin_audit_log(actor: str | None = None, action: str | None = None, limit: int = 50, offset: int = 0, _: str = Depends(current_admin)):
    entries, has_more, actors, actions = database.list_audit_log(actor, action, limit, offset)
    return {"entries": entries, "has_more": has_more, "actors": actors, "actions": actions}


@app.get("/api/admin/overview")
def admin_overview(_: str = Depends(current_admin)):
    return {"total_users": database.count_users(), "active_jobs": database.count_active_jobs(), "completed_jobs_today": database.count_completed_jobs_today(), **database.document_stats()}
