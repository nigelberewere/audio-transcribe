import hashlib
import hmac
import logging
import os
import secrets
import shutil
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
from . import pdf_tools

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


def _is_authenticated(session: str | None) -> bool:
    if not session or session not in sessions:
        return False
    user = database.get_user(sessions[session]["username"])
    return bool(user and user["active"])


@app.get("/", response_class=HTMLResponse)
def index(session: str | None = Cookie(default=None)) -> Response:
    if _is_authenticated(session):
        return RedirectResponse("/home", status_code=303)
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/home", response_class=HTMLResponse)
def home_page(session: str | None = Cookie(default=None)) -> Response:
    if not _is_authenticated(session):
        return RedirectResponse("/", status_code=303)
    return FileResponse(Path(__file__).parent / "static" / "home.html")


@app.get("/transcription", response_class=HTMLResponse)
def transcription_page(session: str | None = Cookie(default=None)) -> Response:
    if not _is_authenticated(session):
        return RedirectResponse("/", status_code=303)
    return FileResponse(Path(__file__).parent / "static" / "transcription.html")


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(session: str | None = Cookie(default=None)) -> Response:
    if session and session in sessions and sessions[session].get("role") == "admin":
        user = database.get_user(sessions[session]["username"])
        if user and user.get("active") and user.get("role") == "admin":
            return RedirectResponse("/admin", status_code=303)
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
    account = database.get_user(username)
    if not account or not account["active"] or not verify_password(password, account["password_hash"]):
        details = "inactive account" if account and not account["active"] else "invalid credentials"
        database.add_audit_log(username, "login_failed", None, details)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = secrets.token_urlsafe(32)
    sessions[token] = {"username": username, "role": account["role"]}
    first_name = (account.get("first_name") or "").strip()
    surname = (account.get("surname") or "").strip()
    full_name = f"{first_name} {surname}".strip()
    display_name = full_name if full_name else username
    response = {
        "ok": True,
        "username": username,
        "name": display_name,
        "email": account.get("email") or "",
        "role": account["role"],
    }
    from fastapi.responses import JSONResponse
    result = JSONResponse(response)
    result.set_cookie("session", token, httponly=True, samesite="strict")
    return result


@app.post("/api/admin/login")
def admin_login(username: str = Form(...), password: str = Form(...)):
    account = database.get_user(username)
    if not account or not account["active"] or account["role"] != "admin" or not verify_password(password, account["password_hash"]):
        details = "inactive account" if account and not account["active"] else "invalid credentials"
        database.add_audit_log(username, "login_failed", None, details)
        raise HTTPException(status_code=401, detail="Invalid administrator credentials")
    token = secrets.token_urlsafe(32)
    sessions[token] = {"username": username, "role": "admin"}
    first_name = (account.get("first_name") or "").strip()
    surname = (account.get("surname") or "").strip()
    full_name = f"{first_name} {surname}".strip()
    display_name = full_name if full_name else username
    from fastapi.responses import JSONResponse
    result = JSONResponse({
        "ok": True,
        "username": username,
        "name": display_name,
        "email": account.get("email") or "",
        "role": "admin",
    })
    result.set_cookie("session", token, httponly=True, samesite="strict")
    return result


@app.get("/api/me")
def me(user: str = Depends(current_user)):
    account = database.get_user(user)
    if not account:
        raise HTTPException(status_code=404, detail="User not found")
    first_name = (account.get("first_name") or "").strip()
    surname = (account.get("surname") or "").strip()
    full_name = f"{first_name} {surname}".strip()
    display_name = full_name if full_name else account["username"]
    return {
        "username": account["username"],
        "first_name": first_name,
        "surname": surname,
        "name": display_name,
        "email": account.get("email") or "",
        "role": account.get("role", "user"),
    }


@app.post("/api/logout")
def logout(session: str | None = Cookie(default=None), user: str = Depends(current_user)):
    sessions.pop(session, None)
    from fastapi.responses import JSONResponse
    response = JSONResponse({"ok": True}); response.delete_cookie("session"); return response


@app.get("/api/jobs")
def jobs(user: str = Depends(current_user)):
    results = database.list_jobs()
    waiting_jobs = sorted(
        [item for item in results if item["status"] == "waiting"],
        key=lambda item: item["created_at"],
    )
    waiting_positions = {item["id"]: idx + 1 for idx, item in enumerate(waiting_jobs)}
    for item in results:
        item["queue_position"] = waiting_positions.get(item["id"])
    return results


@app.get("/documents", response_class=HTMLResponse)
def documents_page(session: str | None = Cookie(default=None)) -> Response:
    if not _is_authenticated(session):
        return RedirectResponse("/", status_code=303)
    return FileResponse(Path(__file__).parent / "static" / "documents.html")


def _document_folder(folder_id: str | None) -> str | None:
    if folder_id and not database.get_folder(folder_id):
        raise HTTPException(status_code=404, detail="Folder not found")
    return folder_id


def _tags(value: str) -> list[str]:
    return sorted({tag.strip() for tag in value.split(",") if tag.strip()})


ALLOWED_DOCUMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".ppt", ".pptx", ".txt", ".csv", ".rtf",
    ".odt", ".ods", ".odp", ".jpg", ".jpeg", ".png"
}
MAX_DOCUMENT_SIZE_BYTES = 50 * 1024 * 1024  # 50MB


def _validate_document_filename(filename: str | None) -> tuple[str, str]:
    cleaned = Path(filename or "unnamed-file").name
    ext = Path(cleaned).suffix.lower()
    if not ext or ext not in ALLOWED_DOCUMENT_EXTENSIONS:
        types_list = "pdf, doc, docx, xls, xlsx, ppt, pptx, txt, csv, rtf, odt, ods, odp, jpg, jpeg, png"
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext or 'unknown'}' is not allowed. Allowed types: {types_list}."
        )
    return cleaned, ext


@app.get("/api/search")
def search(q: str = "", user: str = Depends(current_user)):
    query = q.strip()
    if not query:
        return {"transcripts": [], "documents": []}
    database.add_audit_log(user, "search_performed", None, query)
    return database.search(query)


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
    filename, _ = _validate_document_filename(file.filename)
    document_id = uuid4().hex
    uploaded_at = now()
    destination = settings.documents_storage_path / document_id / "1"
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / filename
    size = 0
    try:
        with target.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_DOCUMENT_SIZE_BYTES:
                    raise ValueError("File exceeds maximum allowed size of 50MB.")
                output.write(chunk)
    except Exception as exc:
        if target.exists():
            target.unlink()
        shutil.rmtree(settings.documents_storage_path / document_id, ignore_errors=True)
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=400, detail=str(exc))
        raise

    document = {"id": document_id, "filename": filename, "storage_path": str(target), "folder_id": folder_id, "uploaded_by": user, "uploaded_at": uploaded_at, "file_size": size, "mime_type": file.content_type, "current_version": 1, "deleted": 0}
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
    filename, _ = _validate_document_filename(file.filename or document["filename"])
    version_number = document["current_version"] + 1
    destination = settings.documents_storage_path / document_id / str(version_number)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / filename
    size = 0
    try:
        with target.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_DOCUMENT_SIZE_BYTES:
                    raise ValueError("File exceeds maximum allowed size of 50MB.")
                output.write(chunk)
    except Exception as exc:
        if target.exists():
            target.unlink()
        shutil.rmtree(destination, ignore_errors=True)
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=400, detail=str(exc))
        raise

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


class MergeDocumentsRequest(BaseModel):
    document_ids: list[str]
    output_filename: str | None = None


class SplitDocumentRequest(BaseModel):
    document_id: str | None = None
    document_ids: list[str] | None = None
    page_ranges: str | None = None


class WatermarkDocumentRequest(BaseModel):
    document_ids: list[str]
    watermark_text: str


class ConvertDocumentRequest(BaseModel):
    document_id: str
    target_format: str


@app.post("/api/documents/tools/merge")
def merge_documents_endpoint(req: MergeDocumentsRequest, user: str = Depends(current_user)):
    if len(req.document_ids) < 2:
        raise HTTPException(status_code=400, detail="Merge requires at least 2 PDF documents.")
    docs = []
    for doc_id in req.document_ids:
        d = database.get_document(doc_id)
        if not d or d.get("deleted"):
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found.")
        if Path(d["filename"]).suffix.lower() != ".pdf":
            raise HTTPException(status_code=400, detail=f"Document '{d['filename']}' is not a PDF. All files must be PDFs.")
        docs.append(d)

    new_id = uuid4().hex
    destination = settings.documents_storage_path / new_id / "1"
    destination.mkdir(parents=True, exist_ok=True)
    out_filename = (req.output_filename or "").strip()
    if not out_filename:
        stem = Path(docs[0]["filename"]).stem
        out_filename = f"{stem}_merged.pdf"
    if not out_filename.lower().endswith(".pdf"):
        out_filename += ".pdf"

    target = destination / out_filename
    try:
        pdf_tools.merge_pdfs([Path(d["storage_path"]) for d in docs], target)
    except Exception as exc:
        shutil.rmtree(settings.documents_storage_path / new_id, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Merge failed: {exc}")

    size = target.stat().st_size
    uploaded_at = now()
    folder_id = docs[0].get("folder_id")
    doc_record = {
        "id": new_id,
        "filename": out_filename,
        "storage_path": str(target),
        "folder_id": folder_id,
        "uploaded_by": user,
        "uploaded_at": uploaded_at,
        "file_size": size,
        "mime_type": "application/pdf",
        "current_version": 1,
        "deleted": 0,
        "source_document_ids": req.document_ids,
    }
    version_record = {
        "id": uuid4().hex,
        "document_id": new_id,
        "version_number": 1,
        "storage_path": str(target),
        "uploaded_by": user,
        "uploaded_at": uploaded_at,
        "change_note": f"Merged from {len(docs)} documents",
    }
    database.create_document(doc_record, version_record, [])
    database.add_audit_log(user, "document_merged", new_id, f"sources: {', '.join(req.document_ids)}")
    return database.get_document(new_id)


@app.post("/api/documents/tools/split")
def split_document_endpoint(req: SplitDocumentRequest, user: str = Depends(current_user)):
    if req.document_ids and len(req.document_ids) > 1:
        raise HTTPException(status_code=400, detail="Split requires exactly 1 PDF document.")
    doc_id = req.document_id or (req.document_ids[0] if req.document_ids and len(req.document_ids) == 1 else None)
    if not doc_id:
        raise HTTPException(status_code=400, detail="Split requires exactly 1 PDF document.")
    doc = database.get_document(doc_id)
    if not doc or doc.get("deleted"):
        raise HTTPException(status_code=404, detail="Document not found.")
    if Path(doc["filename"]).suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Document must be a PDF to split.")

    temp_id = uuid4().hex
    temp_dir = settings.documents_storage_path / "_temp_split" / temp_id
    try:
        split_results = pdf_tools.split_pdf(Path(doc["storage_path"]), temp_dir, doc["filename"], req.page_ranges)
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Split failed: {exc}")

    created_docs = []
    for split_path, page_count, suggested_name in split_results:
        new_id = uuid4().hex
        destination = settings.documents_storage_path / new_id / "1"
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / suggested_name
        shutil.move(str(split_path), str(target))
        size = target.stat().st_size
        uploaded_at = now()
        doc_record = {
            "id": new_id,
            "filename": suggested_name,
            "storage_path": str(target),
            "folder_id": doc.get("folder_id"),
            "uploaded_by": user,
            "uploaded_at": uploaded_at,
            "file_size": size,
            "mime_type": "application/pdf",
            "current_version": 1,
            "deleted": 0,
            "source_document_ids": [doc_id],
        }
        version_record = {
            "id": uuid4().hex,
            "document_id": new_id,
            "version_number": 1,
            "storage_path": str(target),
            "uploaded_by": user,
            "uploaded_at": uploaded_at,
            "change_note": f"Split from {doc['filename']}",
        }
        database.create_document(doc_record, version_record, [])
        database.add_audit_log(user, "document_split", new_id, f"source: {doc_id}, pages: {page_count}")
        created_docs.append(database.get_document(new_id))

    shutil.rmtree(temp_dir.parent, ignore_errors=True)
    return {"documents": created_docs}


@app.post("/api/documents/tools/watermark")
def watermark_documents_endpoint(req: WatermarkDocumentRequest, user: str = Depends(current_user)):
    if not req.document_ids:
        raise HTTPException(status_code=400, detail="Watermark requires at least 1 PDF document.")
    text = (req.watermark_text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Watermark text cannot be empty.")

    created_docs = []
    for doc_id in req.document_ids:
        doc = database.get_document(doc_id)
        if not doc or doc.get("deleted"):
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found.")
        if Path(doc["filename"]).suffix.lower() != ".pdf":
            raise HTTPException(status_code=400, detail=f"Document '{doc['filename']}' is not a PDF.")

        new_id = uuid4().hex
        destination = settings.documents_storage_path / new_id / "1"
        destination.mkdir(parents=True, exist_ok=True)
        stem = Path(doc["filename"]).stem
        out_filename = f"{stem}_watermarked.pdf"
        target = destination / out_filename

        try:
            pdf_tools.watermark_pdf(Path(doc["storage_path"]), target, text)
        except Exception as exc:
            shutil.rmtree(settings.documents_storage_path / new_id, ignore_errors=True)
            raise HTTPException(status_code=400, detail=f"Watermarking failed: {exc}")

        size = target.stat().st_size
        uploaded_at = now()
        doc_record = {
            "id": new_id,
            "filename": out_filename,
            "storage_path": str(target),
            "folder_id": doc.get("folder_id"),
            "uploaded_by": user,
            "uploaded_at": uploaded_at,
            "file_size": size,
            "mime_type": "application/pdf",
            "current_version": 1,
            "deleted": 0,
            "source_document_ids": [doc_id],
        }
        version_record = {
            "id": uuid4().hex,
            "document_id": new_id,
            "version_number": 1,
            "storage_path": str(target),
            "uploaded_by": user,
            "uploaded_at": uploaded_at,
            "change_note": f"Watermarked with '{text}'",
        }
        database.create_document(doc_record, version_record, [])
        database.add_audit_log(user, "document_watermarked", new_id, f"source: {doc_id}, text: {text}")
        created_docs.append(database.get_document(new_id))

    return {"documents": created_docs}


@app.post("/api/documents/tools/convert")
def convert_document_endpoint(req: ConvertDocumentRequest, user: str = Depends(current_user)):
    if not req.document_id:
        raise HTTPException(status_code=400, detail="Convert requires a document ID.")
    doc = database.get_document(req.document_id)
    if not doc or doc.get("deleted"):
        raise HTTPException(status_code=404, detail="Document not found.")

    source_path = Path(doc["storage_path"])
    source_ext = source_path.suffix.lower()
    target_format = req.target_format.lower().strip().lstrip(".")

    new_id = uuid4().hex
    destination = settings.documents_storage_path / new_id / "1"
    destination.mkdir(parents=True, exist_ok=True)
    stem = Path(doc["filename"]).stem
    out_filename = f"{stem}.{target_format}"
    target = destination / out_filename

    try:
        if source_ext == ".docx" and target_format == "pdf":
            pdf_tools.convert_docx_to_pdf(source_path, target)
            mime = "application/pdf"
        elif source_ext == ".pdf" and target_format == "docx":
            pdf_tools.convert_pdf_to_docx(source_path, target)
            mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif source_ext in (".jpg", ".jpeg", ".png") and target_format == "pdf":
            pdf_tools.convert_image_to_pdf(source_path, target)
            mime = "application/pdf"
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Conversion from '{source_ext}' to '{target_format}' is not supported."
            )
    except HTTPException:
        shutil.rmtree(settings.documents_storage_path / new_id, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(settings.documents_storage_path / new_id, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Conversion failed: {exc}")

    size = target.stat().st_size
    uploaded_at = now()
    doc_record = {
        "id": new_id,
        "filename": out_filename,
        "storage_path": str(target),
        "folder_id": doc.get("folder_id"),
        "uploaded_by": user,
        "uploaded_at": uploaded_at,
        "file_size": size,
        "mime_type": mime,
        "current_version": 1,
        "deleted": 0,
        "source_document_ids": [doc["id"]],
    }
    version_record = {
        "id": uuid4().hex,
        "document_id": new_id,
        "version_number": 1,
        "storage_path": str(target),
        "uploaded_by": user,
        "uploaded_at": uploaded_at,
        "change_note": f"Converted from {source_ext} to {target_format}",
    }
    database.create_document(doc_record, version_record, [])
    database.add_audit_log(user, "document_converted", new_id, f"source: {doc['id']}, format: {target_format}")
    return database.get_document(new_id)


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


@app.get("/api/diarization/status")
def diarization_status(user: str = Depends(current_user)):
    from .diarizer import is_diarization_available
    has_token = bool(os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN"))
    available, message = is_diarization_available()
    return {
        "available": available,
        "has_token": has_token,
        "message": message,
    }


@app.post("/api/jobs")
def upload(file: UploadFile = File(...), model: str = Form("auto"), language: str = Form("auto"), initial_prompt: str = Form(""), diarization: bool = Form(False), hf_token: str = Form(""), formats: str = Form("txt,txt_timestamps,srt,vtt,docx,json"), user: str = Depends(current_user)):
    extension = Path(file.filename or "").suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Unsupported format. Allowed: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
    if hf_token and hf_token.strip():
        token_val = hf_token.strip()
        os.environ["HF_TOKEN"] = token_val
        try:
            env_file = getattr(settings, "env_file", Path(".env"))
            if env_file.exists():
                lines = []
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    if line.startswith("HF_TOKEN="):
                        lines.append(f"HF_TOKEN={token_val}")
                    else:
                        lines.append(line)
                env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception:
            pass
    job_id = uuid4().hex; destination = settings.upload_dir / f"{job_id}{extension}"
    with destination.open("wb") as output:
        while chunk := file.file.read(1024 * 1024):
            output.write(chunk)
    database.create_job({
        "id": job_id,
        "filename": file.filename,
        "source_path": str(destination),
        "requested_model": model,
        "language": language,
        "initial_prompt": initial_prompt,
        "diarization": diarization,
        "formats": [item.strip() for item in formats.split(",") if item.strip()],
        "created_by": user,
    })
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
    job = database.get_job(job_id)
    if not job: raise HTTPException(404, "Job not found")
    target = settings.job_dir / job_id / "edited.txt"; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(edit.text, encoding="utf-8")
    database.index_transcript(job_id, job["filename"], job.get("initial_prompt", ""), edit.text)
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
    database.remove_from_search_index("transcript", job_id)
    return {"ok": True}


@app.get("/api/admin/users")
def admin_users(_: str = Depends(current_admin)):
    return database.list_users()


@app.post("/api/admin/users")
def create_admin_user(
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    role: str = Form("user"),
    first_name: str = Form(""),
    surname: str = Form(""),
    email: str = Form(""),
    admin: str = Depends(current_admin),
):
    username = username.strip() if isinstance(username, str) else ""
    first_name = first_name.strip() if isinstance(first_name, str) else ""
    surname = surname.strip() if isinstance(surname, str) else ""
    email = email.strip().lower() if isinstance(email, str) else ""
    role = role if isinstance(role, str) else "user"
    if role not in {"admin", "user"}:
        raise HTTPException(status_code=400, detail="Invalid role")
    if not username or not password or not isinstance(password, str):
        raise HTTPException(status_code=400, detail="Username and password are required")
    if not first_name or not surname:
        raise HTTPException(status_code=400, detail="Name and surname are required")
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email address is required")
    if password != confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if database.get_user(username):
        raise HTTPException(status_code=409, detail="Username already exists")
    database.create_user(
        username=username,
        password_hash=hash_password(password),
        role=role,
        created_by=admin,
        first_name=first_name,
        surname=surname,
        email=email,
    )
    database.add_audit_log(admin, "user_created", username, f"role: {role}")
    return {"ok": True}


def _would_remove_last_admin(username: str, role: str | None = None, active: int | None = None) -> bool:
    account = database.get_user(username)
    if not account:
        return False
    becomes_admin = role if isinstance(role, str) else account["role"]
    remains_active = active if isinstance(active, int) else account["active"]
    if becomes_admin == "admin" and remains_active:
        return False
    return sum(user["role"] == "admin" and user["active"] for user in database.list_users()) <= 1 and account["role"] == "admin" and account["active"]


@app.patch("/api/admin/users/{username}")
def update_admin_user(
    username: str,
    role: str | None = Form(None),
    active: int | None = Form(None),
    first_name: str | None = Form(None),
    surname: str | None = Form(None),
    email: str | None = Form(None),
    admin: str = Depends(current_admin),
):
    account = database.get_user(username)
    if not account:
        raise HTTPException(status_code=404, detail="User not found")
    if isinstance(role, str) and role not in {"admin", "user"}:
        raise HTTPException(status_code=400, detail="Invalid role")
    if isinstance(active, int) and active not in {0, 1}:
        raise HTTPException(status_code=400, detail="Invalid active status")
    if isinstance(email, str) and email.strip() and "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email address is required")
    if username == admin and role == "user" and _would_remove_last_admin(username, role=role):
        raise HTTPException(status_code=400, detail="Cannot remove the last active administrator")
    if username == admin and active == 0 and _would_remove_last_admin(username, active=active):
        raise HTTPException(status_code=400, detail="Cannot disable the last active administrator")
    fields = {}
    if isinstance(role, str):
        fields["role"] = role
    if isinstance(active, int):
        fields["active"] = active
    if isinstance(first_name, str) and first_name.strip():
        fields["first_name"] = first_name.strip()
    if isinstance(surname, str) and surname.strip():
        fields["surname"] = surname.strip()
    if isinstance(email, str) and email.strip():
        fields["email"] = email.strip().lower()
    if fields:
        database.update_user(username, **fields)
        if isinstance(role, str) and role != account["role"]:
            database.add_audit_log(admin, "user_role_changed", username, f"{account['role']} -> {role}")
        if isinstance(active, int) and active == 0 and account["active"]:
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


@app.delete("/api/admin/users/{username}")
def delete_admin_user(username: str, admin: str = Depends(current_admin)):
    account = database.get_user(username)
    if not account:
        raise HTTPException(status_code=404, detail="User not found")
    if username == admin:
        raise HTTPException(status_code=400, detail="Cannot delete your own administrator account")
    if account["role"] == "admin" and sum(u["role"] == "admin" and u["active"] for u in database.list_users()) <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the last active administrator")
    database.delete_user(username)
    for token, sess in list(sessions.items()):
        if sess.get("username") == username:
            sessions.pop(token, None)
    database.add_audit_log(admin, "user_deleted", username, f"role: {account['role']}")
    return {"ok": True}


@app.get("/api/admin/audit-log")
@app.get("/api/admin/audit")
def admin_audit_log(actor: str | None = None, action: str | None = None, limit: int = 50, offset: int = 0, _: str = Depends(current_admin)):
    entries, has_more, actors, actions = database.list_audit_log(actor, action, limit, offset)
    return {"entries": entries, "has_more": has_more, "actors": actors, "actions": actions}


@app.get("/api/admin/overview")
def admin_overview(_: str = Depends(current_admin)):
    return {"total_users": database.count_users(), "active_jobs": database.count_active_jobs(), "completed_jobs_today": database.count_completed_jobs_today(), **database.document_stats()}


class AdminSettingsPayload(BaseModel):
    hf_token: str = ""


@app.get("/api/admin/settings")
def get_admin_settings(_: str = Depends(current_admin)):
    from .diarizer import is_diarization_available
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN") or ""
    available, message = is_diarization_available()
    masked_token = f"{token[:4]}...{token[-4:]}" if len(token) > 8 else ("***" if token else "")
    return {
        "has_token": bool(token),
        "masked_token": masked_token,
        "available": available,
        "message": message,
    }


@app.post("/api/admin/settings")
def update_admin_settings(payload: AdminSettingsPayload, admin: str = Depends(current_admin)):
    token = payload.hf_token.strip()
    os.environ["HF_TOKEN"] = token
    env_file = getattr(settings, "env_file", Path(".env"))
    try:
        if env_file.exists():
            lines = []
            found = False
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("HF_TOKEN="):
                    lines.append(f"HF_TOKEN={token}")
                    found = True
                else:
                    lines.append(line)
            if not found:
                lines.append(f"HF_TOKEN={token}")
            env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            env_file.write_text(f"HF_TOKEN={token}\n", encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {exc}")

    database.add_audit_log(admin, "settings_updated", "hf_token", "Configured Hugging Face token" if token else "Removed Hugging Face token")
    return {"ok": True, "has_token": bool(token)}
