"""Emailing invoices and credit note PDFs."""
import pytest

from conftest import add_member, register
from test_trade import TODAY, receive_stock, setup

from app.config import get_settings


@pytest.fixture()
def smtp(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(s, "smtp_from", "netcare@example.com")


def make_invoice(t, email="school@example.com", issue=True):
    loc, sup, cam, _svc, cust = setup(t)
    receive_stock(t, loc, sup, cam, "10")
    if email:
        t.put(f"/api/v1/customers/{cust['id']}", json={"name": "Local School", "state_code": "33", "email": email})
    inv = t.post("/api/v1/invoices", json={"customer_id": cust["id"], "location_id": loc, "invoice_date": TODAY,
                                           "lines": [{"product_id": cam["id"], "quantity": "2",
                                                      "unit_price": "999.99"}]}).json()
    if issue:
        t.post(f"/api/v1/invoices/{inv['id']}/issue")
    return inv, inv["lines"][0]["id"]


def test_email_invoice_rules(client, smtp):
    owner = register(client)
    inv, _ = make_invoice(owner)
    url = f"/api/v1/invoices/{inv['id']}/email"
    r = owner.post(url)
    assert r.status_code == 200 and r.json() == {"queued_to": "school@example.com"}
    assert owner.post(url, params={"email": "not-an-email"}).status_code == 422
    assert owner.post(url, params={"email": "other@example.com"}).json()["queued_to"] == "other@example.com"
    box = owner.get("/api/v1/notifications/outbox").json()["items"]
    assert len(box) == 2 and "Invoice" in box[0]["subject"]
    # Viewers cannot send mail on the business's behalf
    assert add_member(owner, "viewer").post(url).status_code == 403


def test_email_invoice_blocked_cases(client, monkeypatch):
    owner = register(client)
    inv, _ = make_invoice(owner)
    url = f"/api/v1/invoices/{inv['id']}/email"
    assert owner.post(url).status_code == 422  # SMTP not configured
    s = get_settings()
    monkeypatch.setattr(s, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(s, "smtp_from", "netcare@example.com")
    draft = owner.post("/api/v1/invoices", json={"customer_id": inv["customer_id"], "location_id": inv["location_id"],
                                                 "invoice_date": TODAY, "lines": [
                                                     {"product_id": inv["lines"][0]["product_id"], "quantity": "1",
                                                      "unit_price": "10"}]}).json()
    assert owner.post(f"/api/v1/invoices/{draft['id']}/email").status_code == 422  # drafts are not sent


def test_credit_note_pdf(tenant):
    inv, lid = make_invoice(tenant)
    cn = tenant.post(f"/api/v1/invoices/{inv['id']}/credit-notes", json={
        "note_date": TODAY, "reason": "Defective", "restock": True,
        "lines": [{"sales_invoice_line_id": lid, "quantity": "1"}]}).json()
    r = tenant.get(f"/api/v1/credit-notes/{cn['id']}/pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert tenant.get("/api/v1/credit-notes/99999/pdf").status_code == 404
