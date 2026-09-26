import io
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from docx import Document
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from app import main
from app.db import Database
from app.security import hash_password


@pytest.fixture
def search_state(tmp_path, monkeypatch):
    database = Database(tmp_path / "jobs.sqlite3")
    database.create_user("owner", hash_password("owner-pass"), "admin", None)
    database.create_user("member", hash_password("member-pass"), "user", "owner")
    monkeypatch.setattr(main, "database", database)
    monkeypatch.setattr(main.settings, "data_dir", tmp_path)
    monkeypatch.setattr(main.settings, "documents_storage_path", tmp_path / "documents")
    main.settings.documents_storage_path.mkdir(parents=True, exist_ok=True)
    main.settings.job_dir.mkdir(parents=True, exist_ok=True)
    main.sessions.clear()
    return database


def upload(name, content, content_type="text/plain"):
    return UploadFile(io.BytesIO(content), filename=name, headers={"content-type": content_type})


def make_pdf(pages=1, text="Sample"):
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=letter)
    for i in range(pages):
        can.drawString(100, 700, f"{text} Page {i + 1}")
        can.showPage()
    can.save()
    packet.seek(0)
    return packet.getvalue()


def make_docx(text="Hello docx world"):
    doc = Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def make_png():
    img = Image.new("RGB", (60, 60), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# --- Part 4: Integration Tests for Full-Text Search ---

def test_transcript_indexed_and_findable_by_transcript_word(search_state):
    """Indexing a completed transcription job makes it findable by a word from its transcript."""
    job_id = "job-trans-1"
    search_state.create_job({
        "id": job_id,
        "filename": "quarterly_allhands.mp4",
        "source_path": "quarterly_allhands.mp4",
        "initial_prompt": "Merger discussion",
    })
    search_state.update_job(job_id, status="done")
    transcript_text = "The leadership team has officially finalized the acquisition of NorthTech telemetry solutions."
    search_state.index_transcript(job_id, "quarterly_allhands.mp4", "Merger discussion", transcript_text)

    # Findable by a word from its transcript
    results = main.search("acquisition", user="member")
    assert len(results["transcripts"]) == 1
    matched = results["transcripts"][0]
    assert matched["id"] == job_id
    assert matched["filename"] == "quarterly_allhands.mp4"
    assert "acquisition" in matched["snippet"].lower()
    assert "<mark>" in matched["snippet"].lower()
    assert len(results["documents"]) == 0

    # Also findable by initial_prompt
    results_prompt = main.search("Merger", user="member")
    assert any(t["id"] == job_id for t in results_prompt["transcripts"])


def test_document_indexed_and_findable_by_extracted_text_or_tags(search_state):
    """Indexing a document makes it findable by a word from its extracted text or its tags."""
    # 1. PDF extracted text search
    pdf_bytes = make_pdf(pages=1, text="Autonomous propulsion navigation guidelines")
    doc_pdf = main.upload_document(upload("flight_manual.pdf", pdf_bytes, "application/pdf"), None, "aerospace, guidance", "member")

    res_pdf = main.search("propulsion", user="member")
    assert any(d["id"] == doc_pdf["id"] for d in res_pdf["documents"])
    matched_pdf = next(d for d in res_pdf["documents"] if d["id"] == doc_pdf["id"])
    assert "propulsion" in matched_pdf["snippet"].lower()

    # 2. DOCX extracted text search
    docx_bytes = make_docx("Capital expenditure allocation and fiscal projections")
    doc_docx = main.upload_document(upload("budget_plan.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"), None, "finance", "member")

    res_docx = main.search("expenditure", user="member")
    assert any(d["id"] == doc_docx["id"] for d in res_docx["documents"])
    matched_docx = next(d for d in res_docx["documents"] if d["id"] == doc_docx["id"])
    assert "expenditure" in matched_docx["snippet"].lower()

    # 3. Plain text extracted text search
    txt_bytes = b"Detailed encryption standards and cryptographic keys"
    doc_txt = main.upload_document(upload("security.txt", txt_bytes, "text/plain"), None, "infosec", "member")

    res_txt = main.search("cryptographic", user="member")
    assert any(d["id"] == doc_txt["id"] for d in res_txt["documents"])

    # 4. Findable by tags
    res_tag = main.search("aerospace", user="member")
    assert any(d["id"] == doc_pdf["id"] for d in res_tag["documents"])

    res_tag2 = main.search("infosec", user="member")
    assert any(d["id"] == doc_txt["id"] for d in res_tag2["documents"])

    # 5. Image files: no text extraction possible, but indexed by filename and tags
    img_bytes = make_png()
    doc_img = main.upload_document(upload("satellite_orbit.png", img_bytes, "image/png"), None, "earthobs, optics", "member")

    res_img_tag = main.search("earthobs", user="member")
    assert any(d["id"] == doc_img["id"] for d in res_img_tag["documents"])

    res_img_name = main.search("satellite_orbit", user="member")
    assert any(d["id"] == doc_img["id"] for d in res_img_name["documents"])


def test_document_delete_removes_from_search_and_restore_recovers(search_state):
    """Deleting a document removes it from search results; restoring it makes it findable again."""
    doc = main.upload_document(upload("spec_v1.txt", b"Quantum cryptography hardware specifications"), None, "physics", "member")
    doc_id = doc["id"]

    # Initially findable
    res_before = main.search("quantum", user="member")
    assert any(d["id"] == doc_id for d in res_before["documents"])

    # Delete document -> removed from search results
    main.delete_document(doc_id, user="member")
    res_after_delete = main.search("quantum", user="member")
    assert not any(d["id"] == doc_id for d in res_after_delete["documents"])

    # Restore document -> findable again
    main.restore_document(doc_id, admin="owner")
    res_after_restore = main.search("quantum", user="member")
    assert any(d["id"] == doc_id for d in res_after_restore["documents"])


def test_search_no_matches_returns_empty_cleanly(search_state):
    """A search with no matches returns an empty result set cleanly, not an error."""
    res_nomatch = main.search("completelyunmatchedrandomquery98765", user="member")
    assert res_nomatch == {"transcripts": [], "documents": []}

    res_empty = main.search("", user="member")
    assert res_empty == {"transcripts": [], "documents": []}

    res_whitespace = main.search("    ", user="member")
    assert res_whitespace == {"transcripts": [], "documents": []}

    # Malformed FTS queries / punctuation should not raise exceptions
    for special in ['hello*("', 'AND OR NOT', ':::()', '!!!@@@###$$$', '""', 'syntax error (']:
        res_special = main.search(special, user="member")
        assert isinstance(res_special, dict)
        assert "transcripts" in res_special
        assert "documents" in res_special


def test_unauthenticated_search_rejected(search_state):
    """Unauthenticated search requests are rejected."""
    with pytest.raises(HTTPException) as error:
        main.search("query", user=main.current_user(None))
    assert error.value.status_code == 401


def test_search_performed_audit_logged(search_state):
    """A search_performed audit log entry is created with the correct actor and query."""
    query_str = "telemetry calibration"
    main.search(query_str, user="member")

    with search_state.connect() as conn:
        rows = conn.execute(
            "SELECT actor, action, details FROM audit_log WHERE action = 'search_performed' ORDER BY id DESC"
        ).fetchall()

    assert len(rows) >= 1
    last_log = rows[0]
    assert last_log[0] == "member"
    assert last_log[1] == "search_performed"
    assert last_log[2] == query_str


def test_cross_module_search_returns_both_transcripts_and_documents(search_state):
    """Searches across both transcripts and documents in one query, returning grouped results."""
    # Create transcript
    search_state.create_job({"id": "j-cross", "filename": "strategy.mp4", "source_path": "strategy.mp4"})
    search_state.update_job("j-cross", status="done")
    search_state.index_transcript("j-cross", "strategy.mp4", "", "Our primary objective is orbital cybersecurity defense.")

    # Create document
    main.upload_document(upload("guidelines.txt", b"Mandatory cybersecurity compliance protocols"), None, "security", "member")

    # Search word present in both
    results = main.search("cybersecurity", user="member")
    assert len(results["transcripts"]) == 1
    assert results["transcripts"][0]["id"] == "j-cross"
    assert "cybersecurity" in results["transcripts"][0]["snippet"].lower()

    assert len(results["documents"]) == 1
    assert "cybersecurity" in results["documents"][0]["snippet"].lower()
