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
    assert main.create_admin_user("new-user", "new-pass", "user", "owner") == {"ok": True}
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
