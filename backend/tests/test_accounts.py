"""Stay signed in (refresh tokens), emailed invites and password resets."""
import re

import pytest

from conftest import add_member, register

from app.config import get_settings

A = "/api/v1/auth"


@pytest.fixture()
def smtp(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(s, "smtp_from", "netcare@example.com")
    monkeypatch.setattr(s, "app_url", "https://netcare.example.com")


def login(client, email, password="correct-horse-battery"):
    r = client.post(f"{A}/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def outbox_link(client, to):
    """Read the newest emailed link for `to` straight from the outbox table."""
    from app.db import get_db
    from app.main import app
    from app.models_notify import EmailOutbox
    db = next(app.dependency_overrides[get_db]())
    e = db.query(EmailOutbox).filter(EmailOutbox.to_address == to).order_by(EmailOutbox.id.desc()).first()
    db.close()
    if e is None:
        return None, None
    m = re.search(r"/set-password#token=([A-Za-z0-9_-]+)", e.body)
    return e, m.group(1) if m else None


def test_refresh_rotation_and_reuse_detection(client):
    owner = register(client)
    t = login(client, owner.email)
    assert t["refresh_token"] and t["expires_in"] == 3600
    r1 = client.post(f"{A}/refresh", json={"refresh_token": t["refresh_token"]})
    assert r1.status_code == 200
    new = r1.json()
    assert new["refresh_token"] != t["refresh_token"]
    me = client.get(f"{A}/me", headers={"Authorization": f"Bearer {new['access_token']}"})
    assert me.status_code == 200
    # Replaying the old (already rotated) token means it was copied: the whole sign-in is revoked
    assert client.post(f"{A}/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401
    assert client.post(f"{A}/refresh", json={"refresh_token": new["refresh_token"]}).status_code == 401
    # Other sign-ins are unaffected
    other = login(client, owner.email)
    assert client.post(f"{A}/refresh", json={"refresh_token": other["refresh_token"]}).status_code == 200
    assert client.post(f"{A}/refresh", json={"refresh_token": "x" * 40}).status_code == 401


def test_logout_password_change_and_deactivation_end_sessions(client):
    owner = register(client)
    sales = add_member(owner, "salesperson")
    a = login(client, owner.email)
    b = login(client, owner.email)
    assert client.post(f"{A}/logout", json={"refresh_token": a["refresh_token"]}).status_code == 204
    assert client.post(f"{A}/refresh", json={"refresh_token": a["refresh_token"]}).status_code == 401
    assert client.post(f"{A}/refresh", json={"refresh_token": b["refresh_token"]}).status_code == 200
    s = login(client, sales.email, "temporary-pass-123")
    client.post(f"{A}/change-password", headers={"Authorization": f"Bearer {s['access_token']}"},
                json={"current_password": "temporary-pass-123", "new_password": "a-brand-new-pass"})
    assert client.post(f"{A}/refresh", json={"refresh_token": s["refresh_token"]}).status_code == 401
    s = login(client, sales.email, "a-brand-new-pass")
    mid = next(m["id"] for m in owner.get("/api/v1/organization/members").json() if m["email"] == sales.email)
    owner.patch(f"/api/v1/organization/members/{mid}", json={"is_active": False})
    # Deactivating a membership does not deactivate the login; it simply has no business left to open
    r = client.post(f"{A}/refresh", json={"refresh_token": s["refresh_token"]})
    assert r.status_code == 200
    assert client.get(f"{A}/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()[
        "memberships"] == []
    c = login(client, owner.email)
    client.post(f"{A}/logout-all", headers={"Authorization": f"Bearer {c['access_token']}"})
    assert client.post(f"{A}/refresh", json={"refresh_token": c["refresh_token"]}).status_code == 401


def test_invite_by_email(client, smtp):
    owner = register(client)
    assert client.get(f"{A}/config").json() == {"email_enabled": True}
    r = owner.post("/api/v1/organization/members", json={"email": "new.tech@example.com", "full_name": "New Tech",
                                                         "role": "technician"})
    assert r.status_code == 201, r.text
    email, token = outbox_link(client, "new.tech@example.com")
    assert token and "invited you" in email.body and email.body.count(token) == 1
    # The invite cannot be used to sign in with any password; it must be accepted first
    assert client.post(f"{A}/login", json={"email": "new.tech@example.com", "password": "anything-here"}).status_code == 401
    r = client.post(f"{A}/set-password", json={"token": token, "password": "my-own-password"})
    assert r.status_code == 200 and r.json()["refresh_token"]
    assert client.post(f"{A}/set-password", json={"token": token, "password": "again-password"}).status_code == 400
    login(client, "new.tech@example.com", "my-own-password")
    # Resend for someone locked out: the old link stops working, the new one works
    mid = next(m["id"] for m in owner.get("/api/v1/organization/members").json() if m["email"] == "new.tech@example.com")
    assert owner.post(f"/api/v1/organization/members/{mid}/send-invite").status_code == 202
    _, t2 = outbox_link(client, "new.tech@example.com")
    assert owner.post(f"/api/v1/organization/members/{mid}/send-invite").status_code == 202
    _, t3 = outbox_link(client, "new.tech@example.com")
    assert client.post(f"{A}/set-password", json={"token": t2, "password": "xxxxxxxxxxxx"}).status_code == 400
    assert client.post(f"{A}/set-password", json={"token": t3, "password": "newer-password"}).status_code == 200


def test_invite_needs_email_or_temporary_password(tenant):
    r = tenant.post("/api/v1/organization/members", json={"email": "x@example.com", "full_name": "X",
                                                          "role": "viewer"})
    assert r.status_code == 422 and "temporary password" in r.json()["detail"]
    assert tenant.client.get(f"{A}/config").json() == {"email_enabled": False}


def test_forgot_password(client, smtp):
    owner = register(client)
    sessions = login(client, owner.email)
    same = {"detail": "If an account exists for that email, a reset link has been sent."}
    assert client.post(f"{A}/forgot-password", json={"email": "nobody@example.com"}).json() == same
    assert outbox_link(client, "nobody@example.com") == (None, None)
    r = client.post(f"{A}/forgot-password", json={"email": owner.email.upper()})
    assert r.status_code == 202 and r.json() == same
    email, token = outbox_link(client, owner.email)
    assert "reset" in email.subject.lower() and email.organization_id is None
    assert client.post(f"{A}/set-password", json={"token": token, "password": "short"}).status_code == 422
    assert client.post(f"{A}/set-password", json={"token": token, "password": "a-reset-password"}).status_code == 200
    login(client, owner.email, "a-reset-password")
    # Other sessions ended by the reset
    assert client.post(f"{A}/refresh", json={"refresh_token": sessions["refresh_token"]}).status_code == 401
    # Flooding is quietly limited: no more emails after the limit
    for _ in range(10):
        client.post(f"{A}/forgot-password", json={"email": owner.email})
    from app.db import get_db
    from app.main import app
    from app.models_notify import EmailOutbox
    db = next(app.dependency_overrides[get_db]())
    assert db.query(EmailOutbox).filter(EmailOutbox.to_address == owner.email).count() <= get_settings().login_max_attempts
    db.close()


def test_expired_link(client, smtp, monkeypatch):
    owner = register(client)
    monkeypatch.setattr(get_settings(), "reset_minutes", -1)
    client.post(f"{A}/forgot-password", json={"email": owner.email})
    _, token = outbox_link(client, owner.email)
    r = client.post(f"{A}/set-password", json={"token": token, "password": "a-reset-password"})
    assert r.status_code == 400 and "expired" in r.json()["detail"]
