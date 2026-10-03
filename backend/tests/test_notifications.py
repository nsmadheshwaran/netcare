"""Phase 9: notifications (events, digests, preferences, email outbox)."""
from datetime import timedelta

from conftest import add_member, register
from test_documents import PDF
from test_endpoint_security import endpoint_agent, report, threat
from test_monitoring import make_agent, make_check, send, ts
from test_service import employee, ticket
from test_trade import setup

from app.config import get_settings
from app.services import notify as nt
from app.services.timeutil import today

N = "/api/v1/notifications"


def titles(t, unread=False):
    return [n["title"] for n in t.get(N, params={"unread": unread}).json()["items"]]


def test_monitor_down_and_up(client):
    owner = register(client)
    tech = add_member(owner, "technician")
    sales = add_member(owner, "salesperson")
    a = make_agent(owner)
    c = make_check(owner, a, name="Gate NVR", failure_threshold=2)
    send(client, a["token"], (c["id"], ts(5), False, None))
    assert titles(owner) == []  # one failure is not an outage
    send(client, a["token"], (c["id"], ts(4), False, None), (c["id"], ts(3), False, None))
    assert titles(owner) == ["Down: Gate NVR"] and titles(tech) == ["Down: Gate NVR"]
    assert titles(sales) == []  # no monitoring permission
    n = owner.get(N).json()["items"][0]
    assert n["severity"] == "critical" and n["link"] == "/monitoring" and "2 checks in a row" in n["body"]
    send(client, a["token"], (c["id"], ts(1), True, 5))
    assert titles(owner)[0] == "Back up: Gate NVR"
    assert owner.get(f"{N}/unread-count").json() == {"unread": 2}


def test_read_state_and_isolation(client):
    owner = register(client)
    other = register(client, "Other")
    a = make_agent(owner)
    c = make_check(owner, a, failure_threshold=1)
    send(client, a["token"], (c["id"], ts(2), False, None))
    nid = owner.get(N).json()["items"][0]["id"]
    assert other.post(f"{N}/{nid}/read").status_code == 404
    mgr = add_member(owner, "manager")
    assert mgr.post(f"{N}/{nid}/read").status_code == 404  # someone else's copy
    assert owner.post(f"{N}/{nid}/read").json()["read_at"]
    assert owner.get(f"{N}/unread-count").json()["unread"] == 0
    send(client, a["token"], (c["id"], ts(1), True, 2))
    assert owner.post(f"{N}/read-all").json()["marked"] == 1
    assert titles(owner, unread=True) == []


def test_people_events(client):
    owner = register(client)
    loc, sup, cam, svc, cust = setup(owner)
    tech_user = add_member(owner, "technician")
    tech = employee(owner, tech_user, "Arun")
    t = ticket(owner, cust, assigned_to=tech["id"])
    assert titles(tech_user) == [f"Job {t['number']} assigned to you"]
    t2 = ticket(owner, cust)
    owner.post(f"/api/v1/service-tickets/{t2['id']}/assign", json={"employee_id": tech["id"]})
    owner.post(f"/api/v1/service-tickets/{t2['id']}/assign", json={"employee_id": tech["id"]})  # unchanged
    assert titles(tech_user).count(f"Job {t2['number']} assigned to you") == 1

    owner.post("/api/v1/tasks", json={"title": "Call the school", "assigned_to": tech["id"]})
    assert titles(tech_user)[0] == "Task for you: Call the school"

    r = tech_user.post("/api/v1/leave-requests", json={"start_date": str(today() + timedelta(days=7)),
                                                       "end_date": str(today() + timedelta(days=8)),
                                                       "leave_type": "casual"})
    assert r.status_code == 201, r.text
    assert titles(owner)[0] == "Leave request: Arun"
    assert not any(x.startswith("Leave request") for x in titles(tech_user))  # not to the requester
    owner.post(f"/api/v1/leave-requests/{r.json()['id']}/decide", json={"decision": "approved"})
    assert titles(tech_user)[0] == "Leave approved"
    # Assigning work to yourself does not notify you
    me = employee(owner, owner, "Owner", technician=True)
    ticket(owner, cust, assigned_to=me["id"])
    assert not any("assigned to you" in x for x in titles(owner))


def test_endpoint_critical_once(tenant, client):
    a = endpoint_agent(tenant)
    report(client, a["token"])
    assert titles(tenant) == []
    report(client, a["token"], threats=[threat("X1", status=1)])
    report(client, a["token"], threats=[threat("X1", status=1)])
    assert titles(tenant) == ["Security critical: FRONTDESK"]
    assert "Active threat" in tenant.get(N).json()["items"][0]["body"]


def test_digests(client):
    owner = register(client)
    loc, sup, cam, svc, cust = setup(owner)
    sales = add_member(owner, "salesperson")
    inv = owner.post("/api/v1/invoices", json={"customer_id": cust["id"], "location_id": loc,
                                               "invoice_date": "2026-08-01", "due_date": "2026-08-31",
                                               "lines": [{"product_id": svc["id"], "quantity": "1",
                                                          "unit_price": "500"}]})
    assert inv.status_code == 201, inv.text
    assert owner.post(f"/api/v1/invoices/{inv.json()['id']}/issue").status_code == 200
    owner.post("/api/v1/products", json={"name": "Cable", "sku": "CBL", "min_stock": "10",
                                         "selling_price": "10"})
    emp = employee(owner, None, "Priya", technician=False)
    owner.upload(PDF, "id.pdf", entity_type="employee", entity_id=emp["id"], expires_on=str(today()))
    owner.upload(PDF + b"1", "general.pdf", expires_on=str(today()))

    assert owner.post(f"{N}/run-digests").json()["created"] >= 3
    got = titles(owner)
    assert "1 invoice(s) overdue" in got and any("below minimum stock" in x for x in got)
    assert "2 document(s) expired or expiring soon" in got
    # The salesperson cannot see employee records, so only the general document counts for them
    s = titles(sales)
    assert "1 document(s) expired or expiring soon" in s and "2 document(s) expired or expiring soon" not in s
    # Running again the same day repeats nothing
    assert owner.post(f"{N}/run-digests").json()["created"] == 0
    assert sales.post(f"{N}/run-digests").status_code == 403


def test_preferences(client, monkeypatch):
    owner = register(client)
    sales = add_member(owner, "salesperson")
    kinds = {k["kind"] for k in sales.get(f"{N}/preferences").json()["kinds"]}
    assert "monitor_down" not in kinds and "ticket_assigned" in kinds  # only what they can receive
    prefs = owner.get(f"{N}/preferences").json()
    assert prefs["email_configured"] is False
    assert owner.put(f"{N}/preferences", json=[{"kind": "nope", "in_app": True, "email": False}]).status_code == 422
    owner.put(f"{N}/preferences", json=[{"kind": "monitor_down", "in_app": False, "email": False}])
    a = make_agent(owner)
    c = make_check(owner, a, failure_threshold=1)
    send(client, a["token"], (c["id"], ts(1), False, None))
    assert titles(owner) == []  # muted


def test_email_outbox_and_retries(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(s, "smtp_from", "netcare@example.com")
    monkeypatch.setattr(s, "app_url", "https://netcare.example.com")
    owner = register(client)
    a = make_agent(owner)
    c = make_check(owner, a, name="Router", failure_threshold=1)
    send(client, a["token"], (c["id"], ts(1), False, None))  # monitor_down emails by default
    box = owner.get(f"{N}/outbox").json()["items"]
    assert len(box) == 1 and box[0]["status"] == "pending" and box[0]["subject"] == "[NetCare] Down: Router"

    from app.db import get_db
    from app.main import app
    db = next(app.dependency_overrides[get_db]())
    sent = []
    assert nt.deliver_emails(db, sender=sent.append) == {"sent": 1, "failed": 0}
    assert sent[0]["To"] == owner.email and "https://netcare.example.com/monitoring" in sent[0].get_content()

    assert owner.post(f"{N}/test-email").json()["queued_to"] == owner.email

    def broken(_msg):
        raise ConnectionRefusedError("smtp down")

    r = nt.deliver_emails(db, sender=broken)
    assert r == {"sent": 0, "failed": 0}  # will retry
    row = owner.get(f"{N}/outbox", params={"status": "pending"}).json()["items"][0]
    assert row["attempts"] == 1 and "smtp down" in row["last_error"]
    assert nt.deliver_emails(db, sender=broken) == {"sent": 0, "failed": 0}  # backing off: not due yet
    from app.models_notify import EmailOutbox
    for _ in range(nt.MAX_ATTEMPTS):
        e = db.get(EmailOutbox, row["id"])
        db.refresh(e)
        e.next_attempt_at = e.created_at
        db.commit()
        nt.deliver_emails(db, sender=broken)
    assert owner.get(f"{N}/outbox", params={"status": "failed"}).json()["items"][0]["attempts"] == nt.MAX_ATTEMPTS
    db.close()


def test_test_email_needs_smtp(tenant):
    assert tenant.post(f"{N}/test-email").status_code == 409
    assert tenant.get(f"{N}/outbox").json()["email_configured"] is False
