"""SMS / WhatsApp alerts: opt-in, phone numbers, allowed kinds, providers and the shared outbox."""
import json

import pytest

from conftest import add_member, register
from test_monitoring import make_agent, make_check, send, ts

from app.config import get_settings
from app.services import notify as nt

N = "/api/v1/notifications"


@pytest.fixture()
def twilio(monkeypatch):
    s = get_settings()
    for k, v in {"sms_provider": "twilio", "twilio_account_sid": "AC123", "twilio_auth_token": "tok",
                 "twilio_from": "+14155550100", "app_url": "https://netcare.example.com"}.items():
        monkeypatch.setattr(s, k, v)


def db_session():
    from app.db import get_db
    from app.main import app
    return next(app.dependency_overrides[get_db]())


def test_opt_in_phone_and_allowed_kinds(client, twilio):
    owner = register(client)
    prefs = owner.get(f"{N}/preferences").json()
    assert prefs["sms_configured"] and prefs["phone"] is None
    allowed = {k["kind"] for k in prefs["kinds"] if k["sms_allowed"]}
    assert allowed == {"monitor_down", "endpoint_critical", "ticket_assigned"} & {k["kind"] for k in prefs["kinds"]}
    assert owner.put(f"{N}/phone", json={"phone": "98400 12345"}).status_code == 422  # needs +country code
    assert owner.put(f"{N}/phone", json={"phone": "+91 98400-12345"}).json()["phone"] == "+919840012345"
    # SMS cannot be switched on for a non-urgent kind
    owner.put(f"{N}/preferences", json=[{"kind": "low_stock", "in_app": True, "email": False, "sms": True},
                                        {"kind": "monitor_down", "in_app": True, "email": False, "sms": True}])
    kinds = {k["kind"]: k for k in owner.get(f"{N}/preferences").json()["kinds"]}
    assert kinds["low_stock"]["sms"] is False and kinds["monitor_down"]["sms"] is True

    tech = add_member(owner, "technician")  # opted out by default
    a = make_agent(owner)
    c = make_check(owner, a, name="Gate NVR", failure_threshold=1)
    send(client, a["token"], (c["id"], ts(1), False, None))
    box = owner.get(f"{N}/outbox").json()["items"]
    texts = [e for e in box if e["channel"] == "sms"]
    assert len(texts) == 1 and texts[0]["to"] == "+919840012345"  # only the owner opted in
    assert tech.get(N).json()["total"] == 1  # the technician still gets the in-app alert

    sent = []
    db = db_session()
    assert nt.deliver_emails(db, text_sender=lambda ch, to, body: sent.append((ch, to, body))) == {"sent": 1, "failed": 0}
    db.close()
    assert sent[0][0] == "sms" and sent[0][1] == "+919840012345"
    assert sent[0][2].startswith("NetCare: Down: Gate NVR") and "https://netcare.example.com/monitoring" in sent[0][2]
    assert len(sent[0][2]) <= 300


def test_no_phone_or_no_provider_means_no_text(client, monkeypatch):
    owner = register(client)
    owner.put(f"{N}/preferences", json=[{"kind": "monitor_down", "in_app": True, "email": False, "sms": True}])
    a = make_agent(owner)
    c = make_check(owner, a, failure_threshold=1)
    send(client, a["token"], (c["id"], ts(2), False, None))  # provider off
    assert owner.get(f"{N}/outbox").json()["items"] == []
    monkeypatch.setattr(get_settings(), "sms_provider", "webhook")
    monkeypatch.setattr(get_settings(), "sms_webhook_url", "https://bridge.example.com/send")
    send(client, a["token"], (c["id"], ts(1), True, 3))  # provider on, but no phone saved
    assert owner.get(f"{N}/outbox").json()["items"] == []


def test_whatsapp_and_failures_retry(client, twilio, monkeypatch):
    monkeypatch.setattr(get_settings(), "sms_channel", "whatsapp")
    owner = register(client)
    owner.put(f"{N}/phone", json={"phone": "+919840012345"})
    owner.put(f"{N}/preferences", json=[{"kind": "monitor_down", "in_app": False, "email": False, "sms": True}])
    a = make_agent(owner)
    c = make_check(owner, a, failure_threshold=1)
    send(client, a["token"], (c["id"], ts(1), False, None))
    assert owner.get(N, params={"unread": True}).json()["total"] == 0  # in-app off: text only
    db = db_session()

    def broken(*_):
        raise ConnectionError("provider down")

    assert nt.deliver_emails(db, text_sender=broken) == {"sent": 0, "failed": 0}
    row = owner.get(f"{N}/outbox").json()["items"][0]
    assert row["channel"] == "whatsapp" and row["attempts"] == 1 and "provider down" in row["last_error"]
    db.close()


def test_providers_build_correct_requests(monkeypatch, twilio):
    calls = []

    class Resp:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        calls.append(req)
        return Resp()

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    nt._send_text("whatsapp", "+919840012345", "NetCare: Down: Router")
    req = calls[-1]
    assert req.full_url == "https://api.twilio.com/2010-04-01/Accounts/AC123/Messages.json"
    body = req.data.decode()
    assert "To=whatsapp%3A%2B919840012345" in body and "From=whatsapp%3A%2B14155550100" in body
    assert req.get_header("Authorization").startswith("Basic ")

    s = get_settings()
    monkeypatch.setattr(s, "sms_provider", "webhook")
    monkeypatch.setattr(s, "sms_webhook_url", "https://bridge.example.com/send")
    monkeypatch.setattr(s, "sms_webhook_secret", "hook-secret")
    nt._send_text("sms", "+919840012345", "hello")
    req = calls[-1]
    assert json.loads(req.data) == {"to": "+919840012345", "message": "hello", "channel": "sms"}
    assert req.get_header("Authorization") == "Bearer hook-secret"
