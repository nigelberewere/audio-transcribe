from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile

from app import main
from app.db import Database
from app.security import hash_password


@pytest.fixture
def document_state(tmp_path, monkeypatch):
    database = Database(tmp_path / "jobs.sqlite3")
    database.create_user("owner", hash_password("owner-pass"), "admin", None)
    database.create_user("member", hash_password("member-pass"), "user", "owner")
    monkeypatch.setattr(main, "database", database)
    monkeypatch.setattr(main.settings, "documents_storage_path", tmp_path / "documents")
    main.settings.documents_storage_path.mkdir()
    main.sessions.clear()
    return database


def upload(name, content, content_type="text/plain"):
    return UploadFile(BytesIO(content), filename=name, headers={"content-type": content_type})


def test_upload_creates_document_version_and_audit(document_state):
    document = main.upload_document(upload("policy.txt", b"one"), None, "policy, public", "member")
    assert document["current_version"] == 1
    assert document["tags"] == ["policy", "public"]
    assert len(document_state.list_document_versions(document["id"])) == 1
    with document_state.connect() as connection:
        audit = connection.execute("SELECT action, target FROM audit_log").fetchone()
    assert tuple(audit) == ("document_uploaded", document["id"])


def test_new_version_preserves_old_file(document_state):
    document = main.upload_document(upload("minutes.txt", b"old"), None, "", "member")
    old_path = document["storage_path"]
    updated = main.upload_document_version(document["id"], upload("minutes.txt", b"new"), "updated", "member")
    assert updated["current_version"] == 2
    assert open(old_path, "rb").read() == b"old"
    assert len(document_state.list_document_versions(document["id"])) == 2


def test_soft_delete_hides_from_users_and_admin_can_restore(document_state):
    document = main.upload_document(upload("contract.txt", b"contract"), None, "", "member")
    main.delete_document(document["id"], "member")
    assert document_state.list_documents() == []
    assert document_state.list_deleted_documents()[0]["id"] == document["id"]
    restored = main.restore_document(document["id"], "owner")
    assert restored["deleted"] is False
    assert document_state.list_documents()[0]["id"] == document["id"]


def test_document_routes_require_login(document_state):
    with pytest.raises(HTTPException) as error:
        main.current_user(None)
    assert error.value.status_code == 401
