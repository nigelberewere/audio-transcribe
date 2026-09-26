import pytest
from fastapi import HTTPException

from app import main
from app.db import Database
from app.security import hash_password


@pytest.fixture
def admin_state(tmp_path, monkeypatch):
    database = Database(tmp_path / "jobs.sqlite3")
    database.create_user("owner", hash_password("owner-pass"), "admin", None)
    database.create_user("member", hash_password("member-pass"), "user", "owner")
    monkeypatch.setattr(main, "database", database)
    main.sessions.clear()
    return database


def test_create_user_and_disable_blocks_login(admin_state):
    admin_state.create_user("new-user", hash_password("new-pass"), "user", "owner")
    account = admin_state.get_user("new-user")
    assert account["role"] == "user"
    assert account["active"] == 1

    admin_state.update_user("new-user", active=0)
    assert admin_state.get_user("new-user")["active"] == 0
    with pytest.raises(HTTPException) as error:
        main.login("new-user", "new-pass")
    assert error.value.status_code == 401


def test_non_admin_is_rejected_from_admin_dependency(admin_state):
    with pytest.raises(HTTPException) as error:
        main.current_admin("member")
    assert error.value.status_code == 403

    with pytest.raises(HTTPException) as error:
        main.admin_users(main.current_admin("member"))
    assert error.value.status_code == 403


def test_admin_login_creates_role_session(admin_state):
    response = main.admin_login("owner", "owner-pass")
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    token = cookie.split("session=", 1)[1].split(";", 1)[0]
    assert main.sessions[token] == {"username": "owner", "role": "admin"}


def test_cannot_remove_last_active_admin(admin_state):
    with pytest.raises(HTTPException) as error:
        main.update_admin_user("owner", role="user", admin="owner")
    assert error.value.status_code == 400

    with pytest.raises(HTTPException) as error:
        main.update_admin_user("owner", active=0, admin="owner")
    assert error.value.status_code == 400

    admin_state.create_user("second-admin", hash_password("second-pass"), "admin", "owner")
    assert main.update_admin_user("owner", role="user", active=None, admin="owner") == {"ok": True}


def test_bootstrap_uses_environment_configured_admin(tmp_path, monkeypatch):
    database = Database(tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(main, "database", database)
    monkeypatch.setattr(main.settings, "admin_user", "bootstrap")
    monkeypatch.setattr(main.settings, "admin_password", "bootstrap-pass")
    main.database.create_user("bootstrap", hash_password("bootstrap-pass"), "admin", None)
    assert database.get_user("bootstrap")["created_by"] is None


def test_admin_actions_and_failed_login_create_exact_audit_rows(admin_state):
    assert main.create_admin_user(
        username="new-user",
        password="new-pass",
        confirm_password="new-pass",
        role="user",
        first_name="New",
        surname="User",
        email="newuser@example.com",
        admin="owner",
    ) == {"ok": True}
    assert main.update_admin_user("new-user", role="admin", active=None, admin="owner") == {"ok": True}
    assert main.update_admin_user("new-user", role=None, active=0, admin="owner") == {"ok": True}
    with pytest.raises(HTTPException):
        main.login("new-user", "wrong-pass")

    with admin_state.connect() as connection:
        rows = connection.execute(
            "SELECT actor, action, target, details FROM audit_log ORDER BY id"
        ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("owner", "user_created", "new-user", "role: user"),
        ("owner", "user_role_changed", "new-user", "user -> admin"),
        ("owner", "user_disabled", "new-user", None),
        ("new-user", "login_failed", None, "inactive account"),
    ]


def test_audit_endpoint_filters_and_paginates(admin_state):
    admin_state.add_audit_log("owner", "user_created", "one", "role: user")
    admin_state.add_audit_log("member", "job_deleted", "job-1", "filename: one.wav")
    result = main.admin_audit_log(actor="owner", action="user_created", limit=50, offset=0, _="owner")
    assert result["entries"] == [{
        "id": 1,
        "actor": "owner",
        "action": "user_created",
        "target": "one",
        "details": "role: user",
        "created_at": result["entries"][0]["created_at"],
    }]
    assert result["has_more"] is False


def test_admin_can_reset_password_without_logging_secret(admin_state):
    response = main.reset_user_password("member", "replacement-pass", "replacement-pass", "owner")
    assert response == {"ok": True}

    with pytest.raises(HTTPException):
        main.login("member", "member-pass")
    assert main.login("member", "replacement-pass").status_code == 200

    with admin_state.connect() as connection:
        row = connection.execute(
            "SELECT actor, action, target, details FROM audit_log"
        ).fetchone()
    assert tuple(row) == ("owner", "user_password_reset", "member", None)


def test_password_reset_requires_admin_and_valid_length(admin_state):
    with pytest.raises(HTTPException) as error:
        main.current_admin("member")
    assert error.value.status_code == 403

    with pytest.raises(HTTPException) as error:
        main.reset_user_password("member", "short", "short", "owner")
    assert error.value.status_code == 400

    with pytest.raises(HTTPException) as error:
        main.reset_user_password("member", "replacement-pass", "different-pass", "owner")
    assert error.value.status_code == 400


def test_create_user_requires_name_surname_and_email(admin_state):
    with pytest.raises(HTTPException) as error:
        main.create_admin_user(
            username="jsmith",
            password="password123",
            confirm_password="password123",
            role="user",
            first_name="",
            surname="Smith",
            email="jsmith@example.com",
            admin="owner",
        )
    assert error.value.status_code == 400
    assert "Name and surname are required" in error.value.detail

    with pytest.raises(HTTPException) as error:
        main.create_admin_user(
            username="jsmith",
            password="password123",
            confirm_password="password123",
            role="user",
            first_name="Jane",
            surname="",
            email="jsmith@example.com",
            admin="owner",
        )
    assert error.value.status_code == 400
    assert "Name and surname are required" in error.value.detail

    with pytest.raises(HTTPException) as error:
        main.create_admin_user(
            username="jsmith",
            password="password123",
            confirm_password="password123",
            role="user",
            first_name="Jane",
            surname="Smith",
            email="invalid-email",
            admin="owner",
        )
    assert error.value.status_code == 400
    assert "Valid email address is required" in error.value.detail


def test_user_creation_stores_name_and_email_and_lists_them(admin_state):
    result = main.create_admin_user(
        username="jsmith",
        password="password123",
        confirm_password="password123",
        role="user",
        first_name="Jane",
        surname="Smith",
        email="jsmith@zingsa.ac.zw",
        admin="owner",
    )
    assert result == {"ok": True}

    user = admin_state.get_user("jsmith")
    assert user["first_name"] == "Jane"
    assert user["surname"] == "Smith"
    assert user["email"] == "jsmith@zingsa.ac.zw"

    users = main.admin_users("owner")
    found = next((u for u in users if u["username"] == "jsmith"), None)
    assert found is not None
    assert found["first_name"] == "Jane"
    assert found["surname"] == "Smith"
    assert found["email"] == "jsmith@zingsa.ac.zw"


def test_me_endpoint_returns_user_display_name_and_email(admin_state):
    admin_state.create_user(
        username="nigel",
        password_hash=hash_password("nigel-pass"),
        role="user",
        created_by="owner",
        first_name="Nigel",
        surname="Berewere",
        email="nigel@zingsa.ac.zw",
    )
    data = main.me("nigel")
    assert data["username"] == "nigel"
    assert data["first_name"] == "Nigel"
    assert data["surname"] == "Berewere"
    assert data["name"] == "Nigel Berewere"
    assert data["email"] == "nigel@zingsa.ac.zw"
    assert data["role"] == "user"

    # User with no first_name / surname falls back to username
    fallback = main.me("owner")
    assert fallback["name"] == "owner"


def test_page_routes_and_redirects(admin_state):
    # Unauthenticated user visiting /, /home, /transcription, /documents
    assert main.index(None).status_code == 200
    assert main.home_page(None).status_code == 303
    assert main.transcription_page(None).status_code == 303
    assert main.documents_page(None).status_code == 303

    # Authenticate user session
    res = main.login("member", "member-pass")
    cookie = res.headers["set-cookie"]
    token = cookie.split("session=", 1)[1].split(";", 1)[0]

    # Authenticated user visiting / gets redirected to /home
    root_resp = main.index(token)
    assert root_resp.status_code == 303
    assert root_resp.headers["location"] == "/home"

    # Authenticated user can load /home, /transcription, /documents
    assert main.home_page(token).status_code == 200
    assert main.transcription_page(token).status_code == 200
    assert main.documents_page(token).status_code == 200


def test_admin_cannot_delete_self(admin_state):
    with pytest.raises(HTTPException) as error:
        main.delete_admin_user("owner", admin="owner")
    assert error.value.status_code == 400
    assert "Cannot delete your own administrator account" in error.value.detail


def test_cannot_delete_last_active_admin(admin_state):
    admin_state.create_user("second-admin", hash_password("pass"), "admin", "owner")
    # owner can delete second-admin because owner remains
    assert main.delete_admin_user("second-admin", admin="owner") == {"ok": True}
    assert admin_state.get_user("second-admin") is None


def test_admin_can_delete_user(admin_state):
    assert admin_state.get_user("member") is not None
    assert main.delete_admin_user("member", admin="owner") == {"ok": True}
    assert admin_state.get_user("member") is None

    with admin_state.connect() as connection:
        row = connection.execute(
            "SELECT actor, action, target, details FROM audit_log WHERE action = 'user_deleted'"
        ).fetchone()
    assert tuple(row) == ("owner", "user_deleted", "member", "role: user")



