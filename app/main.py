import hashlib
import hmac
import logging
import secrets
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
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
        reason = "unknown user" if not row else "inactive account" if not row["active"] else "invalid password"
        database.add_audit_log(username, "login_failed", details=reason)
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
        reason = "unknown user" if not account else "inactive account" if not account["active"] else "not an administrator" if account["role"] != "admin" else "invalid password"
        database.add_audit_log(username, "login_failed", details=reason)
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
    database.add_audit_log(user, "job_deleted", job_id, f"filename: {job['filename']}")
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
        if active is not None and active != account["active"]:
            database.add_audit_log(admin, "user_enabled" if active else "user_disabled", username)
    return {"ok": True}


@app.post("/api/admin/users/{username}/reset-password")
def reset_user_password(username: str, new_password: str = Form(...), confirm_password: str = Form(...), admin: str = Depends(current_admin)):
    if not database.get_user(username):
        raise HTTPException(status_code=404, detail="User not found")
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if new_password != confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    database.update_user(username, password_hash=hash_password(new_password))
    database.add_audit_log(admin, "user_password_reset", username)
    return {"ok": True}


@app.get("/api/admin/overview")
def admin_overview(_: str = Depends(current_admin)):
    return {"total_users": database.count_users(), "active_jobs": database.count_active_jobs(), "completed_jobs_today": database.count_completed_jobs_today()}


@app.get("/api/admin/audit-log")
def admin_audit_log(
    actor: str | None = Query(None),
    action: str | None = Query(None),
    limit: int = Query(50, ge=1, le=50),
    offset: int = Query(0, ge=0),
    _: str = Depends(current_admin),
):
    entries, has_more = database.list_audit_log(limit, offset, actor, action)
    return {
        "entries": entries,
        "has_more": has_more,
        "actors": database.audit_log_actors(),
        "actions": database.audit_log_actions(),
    }
