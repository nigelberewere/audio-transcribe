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


def test_admin_settings_get_and_update(admin_state, tmp_path, monkeypatch):
    test_env = tmp_path / ".env"
    monkeypatch.setattr(main.settings, "env_file", test_env)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)

    # Initial state: no token
    settings_data = main.get_admin_settings(_="owner")
    assert settings_data["has_token"] is False
    assert settings_data["masked_token"] == ""

    # Set token
    payload = main.AdminSettingsPayload(hf_token="hf_1234567890abcdef")
    res = main.update_admin_settings(payload, admin="owner")
    assert res == {"ok": True, "has_token": True}
    assert test_env.exists()
    assert "HF_TOKEN=hf_1234567890abcdef" in test_env.read_text(encoding="utf-8")

    # Read back masked token
    settings_data = main.get_admin_settings(_="owner")
    assert settings_data["has_token"] is True
    assert settings_data["masked_token"] == "hf_1...cdef"

    # Verify audit log
    with admin_state.connect() as connection:
        row = connection.execute(
            "SELECT actor, action, target FROM audit_log WHERE action = 'settings_updated'"
        ).fetchone()
    assert tuple(row) == ("owner", "settings_updated", "hf_token")

    # Clear token
    clear_payload = main.AdminSettingsPayload(hf_token="")
    res_clear = main.update_admin_settings(clear_payload, admin="owner")
    assert res_clear == {"ok": True, "has_token": False}
    assert main.get_admin_settings(_="owner")["has_token"] is False


def test_notification_settings_crud_and_password_privacy(admin_state, monkeypatch):
    monkeypatch.setattr(main.notification_service, "database", admin_state)

    # 1. Initial state without DB settings
    init_res = main.get_notification_settings(_="owner")
    assert "smtp_password" not in init_res
    assert isinstance(init_res["has_password"], bool)

    # 2. Save new notification settings
    payload = main.NotificationSettingsPayload(
        smtp_host="smtp.sendgrid.net",
        smtp_port=587,
        smtp_username="apikey",
        smtp_password="SG.SecretKey123456",
        smtp_from_address="transcribe@company.com",
        smtp_use_tls=True,
    )
    save_res = main.update_notification_settings(payload, admin="owner")
    assert save_res["ok"] is True

    # 3. GET settings: password is write-only, NEVER present in response
    get_res = main.get_notification_settings(_="owner")
    assert get_res["smtp_host"] == "smtp.sendgrid.net"
    assert get_res["smtp_port"] == 587
    assert get_res["smtp_username"] == "apikey"
    assert get_res["smtp_from_address"] == "transcribe@company.com"
    assert get_res["smtp_use_tls"] is True
    assert get_res["has_password"] is True
    assert get_res["is_enabled"] is True
    assert "smtp_password" not in get_res
    assert "SG.SecretKey123456" not in str(get_res)

    # 4. Update settings with BLANK password -> preserves existing stored password
    update_payload = main.NotificationSettingsPayload(
        smtp_host="smtp.updated-relay.net",
        smtp_port=465,
        smtp_username="apikey",
        smtp_password="",  # Blank: means do not overwrite!
        smtp_from_address="transcribe@company.com",
        smtp_use_tls=True,
    )
    update_res = main.update_notification_settings(update_payload, admin="owner")
    assert update_res["ok"] is True

    # Verify password was preserved in DB
    cfg = main.notification_service.get_smtp_config()
    assert cfg["smtp_host"] == "smtp.updated-relay.net"
    assert cfg["smtp_port"] == 465
    assert cfg["smtp_password"] == "SG.SecretKey123456"  # Preserved!

    # 5. Check audit logs for notification_settings_updated (ensure NO password in details)
    entries, _, _, _ = admin_state.list_audit_log(action="notification_settings_updated")
    assert len(entries) == 2
    assert entries[0]["actor"] == "owner"
    assert "SG.SecretKey123456" not in str(entries[0]["details"])
    assert "SG.SecretKey123456" not in str(entries[1]["details"])


def test_notification_test_endpoint_and_audit(admin_state, monkeypatch):
    from unittest.mock import MagicMock, patch
    monkeypatch.setattr(main.notification_service, "database", admin_state)

    # Save working config in DB
    admin_state.set_settings({
        "smtp_host": "smtp.office365.com",
        "smtp_port": "587",
        "smtp_username": "notifications@legal.org",
        "smtp_password": "RealPassword123",
        "smtp_from_address": "notifications@legal.org",
        "smtp_use_tls": "true",
    })

    # Test send with mock SMTP
    mock_server = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_server) as mock_smtp:
        payload = main.TestNotificationPayload(recipient_email="test.reviewer@legal.org")
        test_res = main.send_test_notification(payload, admin="owner")
        assert test_res["ok"] is True

        mock_smtp.assert_called_once_with(host="smtp.office365.com", port=587, timeout=10.0)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("notifications@legal.org", "RealPassword123")
        mock_server.send_message.assert_called_once()

    # Check audit log
    entries, _, _, _ = admin_state.list_audit_log(action="test_notification_sent")
    assert len(entries) == 1
    assert entries[0]["actor"] == "owner"
    assert entries[0]["target"] == "***@legal.org"
    assert "RealPassword123" not in entries[0]["details"]


def test_non_admin_cannot_access_notification_endpoints(admin_state):
    # Non-admin user "member" must be rejected
    with pytest.raises(HTTPException) as err1:
        main.get_notification_settings(_=main.current_admin("member"))
    assert err1.value.status_code == 403

    with pytest.raises(HTTPException) as err2:
        payload = main.NotificationSettingsPayload(smtp_host="evil.com")
        main.update_notification_settings(payload, admin=main.current_admin("member"))
    assert err2.value.status_code == 403

    with pytest.raises(HTTPException) as err3:
        test_payload = main.TestNotificationPayload(recipient_email="admin@test.com")
        main.send_test_notification(test_payload, admin=main.current_admin("member"))
    assert err3.value.status_code == 403


def test_dedicated_settings_pages_access_control(admin_state):
    main.sessions["admin-session"] = {"username": "owner", "role": "admin"}
    main.sessions["user-session"] = {"username": "member", "role": "user"}

    # Unauthenticated requests redirect to login / index
    assert main.settings_redirect_page(None).headers["location"] == "/"
    assert main.diarization_settings_page(None).headers["location"] == "/"
    assert main.notification_settings_page(None).headers["location"] == "/"
    assert main.logs_settings_page(None).headers["location"] == "/"

    # Non-admin user sessions redirect to /
    assert main.settings_redirect_page("user-session").headers["location"] == "/"
    assert main.diarization_settings_page("user-session").headers["location"] == "/"
    assert main.notification_settings_page("user-session").headers["location"] == "/"
    assert main.logs_settings_page("user-session").headers["location"] == "/"

    # Admin sessions succeed
    redirect_res = main.settings_redirect_page("admin-session")
    assert redirect_res.headers["location"] == "/admin/settings/diarization"

    diar_res = main.diarization_settings_page("admin-session")
    assert diar_res.status_code == 200
    assert "settings-diarization.html" in str(diar_res.path)

    notif_res = main.notification_settings_page("admin-session")
    assert notif_res.status_code == 200
    assert "settings-notifications.html" in str(notif_res.path)

    logs_res = main.logs_settings_page("admin-session")
    assert logs_res.status_code == 200
    assert "settings-logs.html" in str(logs_res.path)


def test_log_retention_settings_and_sorting(admin_state):
    from datetime import datetime, timezone, timedelta

    # Check default retention is 1
    settings = main.get_log_settings("owner")
    assert settings["retention_days"] == 1
    assert settings["available_options"] == [1, 3, 7]

    # Reject invalid retention
    with pytest.raises(HTTPException) as err:
        main.update_log_settings(main.LogRetentionPayload(retention_days=5), admin="owner")
    assert err.value.status_code == 400

    # Update retention to 3
    res = main.update_log_settings(main.LogRetentionPayload(retention_days=3), admin="owner")
    assert res["ok"] is True
    assert res["retention_days"] == 3
    assert main.get_log_settings("owner")["retention_days"] == 3

    # Add logs with distinct timestamps and check sorting: latest must be on top
    admin_state.add_audit_log("actor1", "action1", "target1", "first")
    admin_state.add_audit_log("actor2", "action2", "target2", "second")

    result = main.admin_audit_log(limit=50, offset=0, _="owner")
    entries = result["entries"]
    assert len(entries) >= 2
    # Verify latest on top: entries[0].id > entries[1].id
    assert entries[0]["id"] > entries[1]["id"]

    # Test retention pruning of old logs
    cutoff_old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    with admin_state.connect() as conn:
        conn.execute("UPDATE audit_log SET created_at = ? WHERE action = 'action1'", (cutoff_old,))

    # Cleanup with retention=3 should delete the 5-day old log
    deleted = admin_state.cleanup_old_audit_logs(3)
    assert deleted >= 1

    remaining_actions = [e["action"] for e in main.admin_audit_log(limit=50, offset=0, _="owner")["entries"]]
    assert "action1" not in remaining_actions







