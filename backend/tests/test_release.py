"""Phase 10: module switches, onboarding, an end-to-end business day, and an automated tenant-isolation
sweep over every endpoint."""
import io
import re
import zipfile

import pytest

from conftest import add_member, register
from test_documents import PDF
from test_endpoint_security import endpoint_agent, report, threat
from test_finance import sell, stock_in
from test_monitoring import make_check, send, ts
from test_service import employee, ticket
from test_trade import TODAY, receive_stock, setup

from app.main import app


# ---------------- modules ----------------
def test_module_switches(client):
    owner = register(client)
    sales = add_member(owner, "salesperson")
    mods = {m["key"]: m["enabled"] for m in owner.get("/api/v1/organization/modules").json()}
    assert all(mods.values()) and set(mods) >= {"trade", "service", "monitoring", "security"}

    assert owner.put("/api/v1/organization/modules", json={"enabled": ["finance"]}).status_code == 422  # needs trade
    assert owner.put("/api/v1/organization/modules", json={"enabled": ["nope"]}).status_code == 422
    assert sales.put("/api/v1/organization/modules", json={"enabled": []}).status_code == 403
    r = owner.put("/api/v1/organization/modules", json={"enabled": ["trade", "documents"]})
    assert r.status_code == 200 and [m["key"] for m in r.json() if m["enabled"]] == ["trade", "documents"]

    # The API refuses switched-off modules for everyone, owner included, with a clear message
    r = owner.get("/api/v1/service-tickets")
    assert r.status_code == 403 and "switched off" in r.json()["detail"]
    assert owner.get("/api/v1/monitoring/overview").status_code == 403
    assert owner.get("/api/v1/invoices").status_code == 200 and owner.get("/api/v1/customers").status_code == 200
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {owner.token}"}).json()["memberships"][0]
    assert "service.view" not in me["permissions"] and me["modules"] == ["documents", "trade"]
    keys = [r["key"] for r in owner.get("/api/v1/reports").json()]
    assert "sales-register" in keys and "service-performance" not in keys and "uptime" not in keys
    assert owner.get("/api/v1/reports/uptime").status_code == 403

    # Editing business details without sending modules does not switch everything back on
    org = owner.get("/api/v1/organization").json()
    body = {k: org[k] for k in ("name", "legal_name", "gstin", "state_code", "phone", "address")}
    assert owner.put("/api/v1/organization", json=body).status_code == 200
    assert owner.get("/api/v1/service-tickets").status_code == 403


def test_switched_off_monitoring_stops_agents(client):
    owner = register(client)
    a = endpoint_agent(owner)
    c = make_check(owner, a)
    owner.put("/api/v1/organization/modules", json={"enabled": ["trade", "monitoring"]})
    assert report(client, a["token"]).status_code == 403  # security off: no Defender reports
    send(client, a["token"], (c["id"], ts(1), True, 3))  # monitoring still on
    owner.put("/api/v1/organization/modules", json={"enabled": ["trade"]})
    r = client.get("/api/v1/agent/config", headers={"Authorization": f"Bearer {a['token']}"})
    assert r.status_code == 403
    # Data is kept and returns when switched back on
    owner.put("/api/v1/organization/modules", json={"enabled": ["trade", "monitoring"]})
    assert owner.get(f"/api/v1/monitoring/checks/{c['id']}").json()["stored_status"] == "up"


def test_notifications_respect_modules(client):
    owner = register(client)
    loc, sup, cam, svc, cust = setup(owner)
    tech_user = add_member(owner, "technician")
    tech = employee(owner, tech_user, "Arun")
    owner.put("/api/v1/organization/modules", json={"enabled": ["trade", "service"]})
    ticket(owner, cust, assigned_to=tech["id"])
    assert len(tech_user.get("/api/v1/notifications").json()["items"]) == 1
    owner.put("/api/v1/organization/modules", json={"enabled": ["trade"]})
    assert tech_user.get("/api/v1/notifications/preferences").status_code == 200


# ---------------- onboarding ----------------
def test_onboarding_checklist(tenant):
    ob = tenant.get("/api/v1/organization/onboarding").json()
    assert ob["done"] == 0 and not ob["complete"] and ob["steps"][0]["key"] == "profile"
    loc, sup, cam, svc, cust = setup(tenant)
    tenant.put("/api/v1/organization", json={"name": "Shop", "state_code": "33", "address": "1 Main Road"})
    done = {s["key"] for s in tenant.get("/api/v1/organization/onboarding").json()["steps"] if s["done"]}
    assert done == {"profile", "products", "customers"}
    tenant.put("/api/v1/organization/modules", json={"enabled": ["trade"]})
    add_member(tenant, "salesperson")
    stock_in(tenant, loc, cam["id"], "2", "1000")
    sell(tenant, cust, loc, [{"product_id": cam["id"], "quantity": "1", "unit_price": "1500"}])
    ob = tenant.get("/api/v1/organization/onboarding").json()
    assert ob["complete"] and ob["total"] == 6  # monitoring step hidden: module off


# ---------------- end-to-end business day ----------------
def build_business_day(owner):
    """Exercise every module once through the public API, as a shop would in a day."""
    loc, sup, cam, svc, cust = setup(owner)
    receive_stock(owner, loc, sup, cam, "10")
    inv = sell(owner, cust, loc, [{"product_id": cam["id"], "quantity": "2", "unit_price": "1500"},
                                  {"product_id": svc["id"], "quantity": "1", "unit_price": "500"}])
    r = owner.post("/api/v1/payments", json={"direction": "in", "customer_id": cust["id"], "payment_date": TODAY,
                                             "amount": inv["total"], "method": "upi",
                                             "allocations": [{"invoice_id": inv["id"], "amount": inv["total"]}]})
    assert r.status_code == 201, r.text
    assert owner.get(f"/api/v1/invoices/{inv['id']}").json()["status"] == "paid"
    q = owner.post("/api/v1/quotations", json={"customer_id": cust["id"], "location_id": loc, "quote_date": TODAY,
                                               "lines": [{"product_id": cam["id"], "quantity": "4",
                                                          "unit_price": "1450"}]})
    assert q.status_code == 201, q.text
    acct = owner.get("/api/v1/accounts").json()[0]
    cats = owner.get("/api/v1/finance-categories").json()
    exp_cat = next(c for c in cats if c["kind"] == "expense")
    r = owner.post("/api/v1/finance-entries", json={"kind": "expense", "entry_date": TODAY, "category_id": exp_cat["id"],
                                                    "amount": "300", "account_id": acct["id"], "payee": "Tea shop"})
    assert r.status_code == 201, r.text
    tech_user = add_member(owner, "technician")
    tech = employee(owner, tech_user, "Arun")
    tk = ticket(owner, cust, assigned_to=tech["id"])
    asset = owner.post("/api/v1/assets", json={"customer_id": cust["id"], "asset_type": "nvr", "name": "NVR",
                                               "ip_address": "192.168.1.50"}).json()
    doc = owner.upload(PDF, "warranty.pdf", entity_type="asset", entity_id=asset["id"], category="warranty")
    assert doc.status_code == 201
    a = endpoint_agent(owner, customer_id=cust["id"])
    c = make_check(owner, a, asset_id=asset["id"], host=None, kind="tcp", port=554, failure_threshold=1)
    send(owner.client, a["token"], (c["id"], ts(1), False, None))
    report(owner.client, a["token"], threats=[threat("E1", status=3)])
    owner.post("/api/v1/tasks", json={"title": "Follow up quote", "assigned_to": tech["id"]})
    return {"cust": cust, "inv": inv, "ticket": tk, "asset": asset, "agent": a, "check": c, "tech": tech_user}


def test_business_day_end_to_end(client):
    owner = register(client)
    d = build_business_day(owner)
    dash = owner.get("/api/v1/dashboard/summary", params={"period": "year"})
    assert dash.status_code == 200
    assert owner.get("/api/v1/monitoring/overview").json()["checks"]["down"] == 1
    assert owner.get("/api/v1/endpoints/summary").json()["endpoints"] == 1
    assert owner.get(f"/api/v1/assets/{d['asset']['id']}").json()["monitor_status"] == "down"
    titles = [n["title"] for n in owner.get("/api/v1/notifications").json()["items"]]
    assert any(t.startswith("Down:") for t in titles)
    assert any(n["title"].startswith("Job ") for n in d["tech"].get("/api/v1/notifications").json()["items"])
    pack = owner.get("/api/v1/reports/pack", params={"date_from": TODAY, "date_to": TODAY, "format": "csv"})
    assert pack.status_code == 200 and len(zipfile.ZipFile(io.BytesIO(pack.content)).namelist()) >= 15
    assert owner.get("/api/v1/analytics/overview", params={"date_from": TODAY, "date_to": TODAY}).status_code == 200
    assert owner.get(f"/api/v1/service-tickets/{d['ticket']['id']}/pdf").headers["content-type"] == "application/pdf"
    assert owner.get(f"/api/v1/invoices/{d['inv']['id']}/pdf").headers["content-type"] == "application/pdf"


# ---------------- security review: tenant isolation of every endpoint ----------------
SKIP = re.compile(r"^/api/v1/(auth|agent)/")


def _routes():
    for path, ops in app.openapi()["paths"].items():
        if not path.startswith("/api/v1/") or SKIP.match(path) or "{" not in path:
            continue
        for method in ops:
            yield method.upper(), path


@pytest.mark.parametrize("seed", [1])
def test_no_endpoint_reaches_another_business(client, seed):
    """Business A has data in every module (ids start at 1). Business B, logged in as owner, calls every
    endpoint that takes an id, with A's ids. Nothing may succeed: B must get 403/404/409/422, never 2xx/5xx."""
    a = register(client, "Victim")
    build_business_day(a)
    b = register(client, "Attacker")
    routes = list(_routes())
    assert len(routes) > 80
    leaks = {}
    for method, path in routes:
        url = re.sub(r"\{[^}]+\}", str(seed), path)
        kw = {} if method in ("GET", "DELETE") else {"json": {}}
        r = b.client.request(method, url, headers=b.h, **kw)
        if r.status_code < 300 or r.status_code >= 500:
            leaks[f"{method} {path}"] = (r.status_code, r.text[:120])
    assert leaks == {}


# ---------------- password reset by the business ----------------
def test_member_password_reset(client):
    owner = register(client)
    mgr = add_member(owner, "manager")
    sales = add_member(owner, "salesperson")
    members = {m["email"]: m["id"] for m in owner.get("/api/v1/organization/members").json()}
    url = f"/api/v1/organization/members/{members[sales.email]}/reset-password"
    assert sales.post(url, json={"temporary_password": "new-temp-pass-1"}).status_code == 403
    assert mgr.post(url, json={"temporary_password": "short"}).status_code == 422
    assert mgr.post(url, json={"temporary_password": "new-temp-pass-1"}).status_code == 204
    assert sales.get("/api/v1/customers").status_code == 401  # old sessions are signed out
    r = client.post("/api/v1/auth/login", json={"email": sales.email, "password": "new-temp-pass-1"})
    assert r.status_code == 200
    # Managers cannot reset owners; nobody resets themselves here
    assert mgr.post(f"/api/v1/organization/members/{members[owner.email]}/reset-password",
                    json={"temporary_password": "new-temp-pass-1"}).status_code == 403
    assert owner.post(f"/api/v1/organization/members/{members[owner.email]}/reset-password",
                      json={"temporary_password": "new-temp-pass-1"}).status_code == 409
    # A login that also belongs to another business cannot be taken over from here
    other = register(client, "Other")
    other.post("/api/v1/organization/members", json={"email": mgr.email, "full_name": "x", "role": "viewer",
                                                     "temporary_password": "ignored-pass-123"})
    r = owner.post(f"/api/v1/organization/members/{members[mgr.email]}/reset-password",
                   json={"temporary_password": "new-temp-pass-1"})
    assert r.status_code == 409 and "another business" in r.json()["detail"]
    assert other.post(url, json={"temporary_password": "new-temp-pass-1"}).status_code == 404
