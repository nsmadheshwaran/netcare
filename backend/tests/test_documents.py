"""Phase 5: document library, analytics, report pack."""
import io
import zipfile
from datetime import timedelta
from decimal import Decimal as D

from conftest import add_member, register
from test_finance import sell, stock_in
from test_service import employee, ticket
from test_trade import TODAY, setup

from app.config import get_settings
from app.services.timeutil import today as local_today

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def office(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in entries.items():
            z.writestr(k, v)
    return buf.getvalue()


def test_upload_attach_list_download(tenant, storage_dir):
    loc, sup, cam, svc, cust = setup(tenant)
    r = tenant.upload(PDF, "Warranty card.PDF", entity_type="customer", entity_id=cust["id"], category="warranty",
                      title="NVR warranty", expires_on=TODAY)
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["content_type"] == "application/pdf" and doc["original_name"] == "Warranty card.pdf"
    assert doc["entity_label"] == "Local School" and doc["size_bytes"] == len(PDF)
    assert len(list(storage_dir.rglob("*"))) == 2  # org folder + file, nothing else left behind

    page = tenant.get("/api/v1/documents", params={"entity_type": "customer", "entity_id": cust["id"]}).json()
    assert page["total"] == 1 and page["items"][0]["title"] == "NVR warranty"
    assert tenant.get("/api/v1/documents", params={"q": "warranty"}).json()["total"] == 1
    assert tenant.get("/api/v1/documents", params={"q": "nothing"}).json()["total"] == 0

    d = tenant.get(f"/api/v1/documents/{doc['id']}/download")
    assert d.status_code == 200 and d.content == PDF
    assert d.headers["content-disposition"].startswith("attachment;")
    assert "sandbox" in d.headers["content-security-policy"]
    assert tenant.get(f"/api/v1/documents/{doc['id']}/download?inline=true").headers[
        "content-disposition"].startswith("inline;")

    # Same file on the same record is refused; on another record it is fine
    assert tenant.upload(PDF, "again.pdf", entity_type="customer", entity_id=cust["id"]).status_code == 409
    assert tenant.upload(PDF, "again.pdf").status_code == 201
    assert len(list(storage_dir.rglob("*"))) == 3  # the refused duplicate left no orphan file

    audit = tenant.get("/api/v1/audit-logs").json()
    items = audit["items"] if isinstance(audit, dict) else audit
    assert any(a["action"] == "download" and a["entity_type"] == "document" for a in items)


def test_content_checks(tenant):
    # Type comes from the bytes: a PNG named .pdf is stored as PNG
    r = tenant.upload(PNG, "photo.pdf")
    assert r.status_code == 201 and r.json()["content_type"] == "image/png" and r.json()["extension"] == "png"
    assert tenant.upload(b"MZ\x90\x00\x03\x00", "setup.exe").status_code == 422  # binary
    assert tenant.upload(b"", "empty.pdf").status_code == 422
    assert tenant.upload("Name,Phone\nRavi,98400\n".encode(), "list.csv").json()["content_type"] == "text/csv"
    assert tenant.upload(b"\xff\xfe\x00bad", "x.txt").status_code == 422
    assert tenant.upload(office({"a.txt": b"x"}), "files.zip").status_code == 422
    macro = office({"[Content_Types].xml": b"<x/>", "word/document.xml": b"<x/>", "word/vbaProject.bin": b"x"})
    assert "macros" in tenant.upload(macro, "m.docx").json()["detail"]
    docx = office({"[Content_Types].xml": b"<x/>", "word/document.xml": b"<x/>"})
    r = tenant.upload(docx, "letter.docx")
    assert r.status_code == 201 and r.json()["extension"] == "docx"
    bomb = office({"[Content_Types].xml": b"<x/>", "xl/a.xml": b"0" * 5_000_000})
    assert tenant.upload(bomb, "big.xlsx").status_code == 422
    # Path tricks in the name are dropped
    assert tenant.upload(PDF, "..\\..\\etc/passwd.pdf").json()["original_name"] == "passwd.pdf"
    # Validation of category and target
    assert tenant.upload(PDF, category="nonsense").status_code == 422
    assert tenant.upload(PDF, entity_type="customer", entity_id=999999).status_code == 422
    assert tenant.upload(PDF, entity_type="general", entity_id=1).status_code == 422


def test_size_limit_and_quota(tenant, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "max_upload_mb", 1)
    assert tenant.upload(PDF + b"0" * (1 << 20), "big.pdf").status_code == 413
    monkeypatch.setattr(s, "org_storage_quota_mb", 1)
    assert tenant.upload(PDF + b"0" * 700_000, "a.pdf").status_code == 201
    assert tenant.upload(PDF + b"1" * 700_000, "b.pdf").status_code == 507


def test_isolation_permissions_and_sensitive(client):
    owner = register(client)
    other = register(client, "Other Shop")
    loc, sup, cam, svc, cust = setup(owner)
    emp = employee(owner, name="Priya", technician=False)
    id_proof = owner.upload(PDF, "aadhaar.pdf", entity_type="employee", entity_id=emp["id"], category="id_proof",
                            is_sensitive=True).json()
    general = owner.upload(PNG, "shop.png").json()

    # Another business sees nothing, and cannot attach to our records
    assert other.get(f"/api/v1/documents/{general['id']}").status_code == 404
    assert other.get(f"/api/v1/documents/{general['id']}/download").status_code == 404
    assert other.get("/api/v1/documents").json()["total"] == 0
    assert other.upload(PDF, entity_type="customer", entity_id=cust["id"]).status_code == 422

    sales = add_member(owner, "salesperson")
    acct = add_member(owner, "accountant")
    viewer = add_member(owner, "viewer")
    mgr = add_member(owner, "manager")
    plain = owner.upload(PDF + b"x", "contract.pdf", entity_type="employee", entity_id=emp["id"]).json()
    # Salesperson cannot see employee records, so not their documents either
    assert sales.get(f"/api/v1/documents/{plain['id']}").status_code == 404
    assert sales.upload(PDF, entity_type="employee", entity_id=emp["id"]).status_code == 403
    assert {d["id"] for d in sales.get("/api/v1/documents").json()["items"]} == {general["id"]}
    # Accountant sees employee documents but not sensitive ones; cannot mark files sensitive
    ids = {d["id"] for d in acct.get("/api/v1/documents").json()["items"]}
    assert plain["id"] in ids and id_proof["id"] not in ids
    assert acct.get(f"/api/v1/documents/{id_proof['id']}/download").status_code == 404
    assert acct.upload(PDF + b"y", is_sensitive=True).status_code == 403
    assert acct.patch(f"/api/v1/documents/{plain['id']}", json={"is_sensitive": True}).status_code == 403
    assert mgr.get(f"/api/v1/documents/{id_proof['id']}/download").status_code == 200
    # Viewer reads but cannot upload
    assert viewer.get(f"/api/v1/documents/{general['id']}/download").status_code == 200
    assert viewer.upload(PDF + b"z").status_code == 403


def test_technician_only_own_tickets(client):
    owner = register(client)
    loc, sup, cam, svc, cust = setup(owner)
    tech_user = add_member(owner, "technician")
    tech = employee(owner, tech_user, "Arun")
    mine = ticket(owner, cust, assigned_to=tech["id"])
    theirs = ticket(owner, cust)
    r = tech_user.upload(PNG, "before.png", entity_type="service_ticket", entity_id=mine["id"], category="photo")
    assert r.status_code == 201, r.text
    assert tech_user.upload(PNG, "x.png", entity_type="service_ticket",
                            entity_id=theirs["id"]).status_code == 403
    assert r.json()["entity_label"] == mine["number"]


def test_delete_restore_purge(client, storage_dir):
    owner = register(client)
    mgr = add_member(owner, "manager")
    sales = add_member(owner, "salesperson")
    doc = sales.upload(PDF, "quote.pdf", category="quotation").json()
    assert sales.post(f"/api/v1/documents/{doc['id']}/delete", json={"reason": "x"}).status_code == 422
    r = sales.post(f"/api/v1/documents/{doc['id']}/delete", json={"reason": "Wrong customer"})
    assert r.status_code == 200 and r.json()["deleted_at"]
    assert sales.get(f"/api/v1/documents/{doc['id']}").status_code == 404
    assert sales.get("/api/v1/documents", params={"deleted": True}).status_code == 403
    assert mgr.get("/api/v1/documents", params={"deleted": True}).json()["total"] == 1
    assert mgr.post(f"/api/v1/documents/{doc['id']}/restore").status_code == 200
    assert sales.get(f"/api/v1/documents/{doc['id']}/download").content == PDF

    # Purge: owner only, only after delete, removes the file, keeps the row out of every listing
    assert owner.post(f"/api/v1/documents/{doc['id']}/purge").status_code == 409
    owner.post(f"/api/v1/documents/{doc['id']}/delete", json={"reason": "Duplicate copy"})
    assert mgr.post(f"/api/v1/documents/{doc['id']}/purge").status_code == 403
    assert owner.post(f"/api/v1/documents/{doc['id']}/purge").status_code == 204
    assert [p for p in storage_dir.rglob("*") if p.is_file()] == []
    assert owner.get(f"/api/v1/documents/{doc['id']}").status_code == 404
    assert owner.get("/api/v1/documents", params={"deleted": True}).json()["total"] == 0
    assert owner.get("/api/v1/documents/meta").json()["used_bytes"] == 0


def test_edit_and_expiring(tenant):
    t = local_today()
    soon = tenant.upload(PDF, "amc.pdf", category="contract", expires_on=t + timedelta(days=10)).json()
    tenant.upload(PDF + b"1", "later.pdf", expires_on=t + timedelta(days=400))
    old = tenant.upload(PDF + b"2", "old.pdf", expires_on=t - timedelta(days=3)).json()
    r = tenant.patch(f"/api/v1/documents/{soon['id']}", json={"title": "AMC 2026", "tags": "amc, school"})
    assert r.status_code == 200 and r.json()["title"] == "AMC 2026" and r.json()["tags"] == "amc, school"
    page = tenant.get("/api/v1/documents", params={"expiring_days": 30}).json()
    assert [d["id"] for d in page["items"]] == [old["id"], soon["id"]]  # soonest first
    rep = tenant.get("/api/v1/reports/documents-expiring").json()
    assert [(r["title"], r["days"]) for r in rep["rows"]] == [("old", -3), ("AMC 2026", 10)]


def test_documents_expiring_report_needs_documents_permission(client):
    owner = register(client)
    acct = add_member(owner, "accountant")
    owner.upload(PDF, "x.pdf", expires_on=TODAY)
    # Accountants have both permissions; a role without documents.view is refused
    assert acct.get("/api/v1/reports/documents-expiring").status_code == 200
    from app import permissions
    permissions.ROLE_PERMISSIONS["accountant"].discard("documents.view")
    try:
        assert acct.get("/api/v1/reports/documents-expiring").status_code == 403
        assert "documents-expiring" not in [c["key"] for c in acct.get("/api/v1/reports").json()]
    finally:
        permissions.ROLE_PERMISSIONS["accountant"].add("documents.view")


def test_report_pack(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    stock_in(tenant, loc, cam["id"], "5", "1000")
    sell(tenant, cust, loc, [{"product_id": cam["id"], "quantity": "1", "unit_price": "1500"}])
    r = tenant.get("/api/v1/reports/pack", params={"date_from": TODAY, "date_to": TODAY, "format": "xlsx"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "README.txt" in names and "01_sales-register.xlsx" in names
    assert not any("daily-closing" in n for n in names)
    r = tenant.get("/api/v1/reports/pack", params={"keys": "profit-loss,gst-summary", "format": "pdf"})
    assert sorted(zipfile.ZipFile(io.BytesIO(r.content)).namelist()) == [
        "01_profit-loss.pdf", "02_gst-summary.pdf", "README.txt"]
    assert tenant.get("/api/v1/reports/pack", params={"keys": "nope"}).status_code == 422


def test_analytics_overview(client):
    owner = register(client)
    loc, sup, cam, svc, cust = setup(owner)
    stock_in(owner, loc, cam["id"], "10", "1000")
    inv = sell(owner, cust, loc, [{"product_id": cam["id"], "quantity": "2", "unit_price": "1500"},
                                  {"product_id": svc["id"], "quantity": "1", "unit_price": "500"}])
    owner.post("/api/v1/payments", json={"direction": "in", "customer_id": cust["id"], "payment_date": TODAY,
                                         "amount": "1000", "method": "upi"})
    ticket(owner, cust)
    # TODAY is a fixed document date; the ticket is stamped now, so the period runs to the real today
    r = owner.get("/api/v1/analytics/overview", params={"date_from": TODAY, "date_to": str(local_today())})
    assert r.status_code == 200, r.text
    a = r.json()
    k = {x["key"]: x for x in a["kpis"]}
    assert D(k["net_sales"]["value"]) == D("3500.00") and k["invoices"]["value"] == 1
    assert D(k["gross_profit"]["value"]) == D("1000.00")  # camera 2 x (1500 - 1000); service has no cost
    assert D(k["collections"]["value"]) == D("1000") and k["tickets_opened"]["value"] == 1
    assert k["net_sales"]["change_pct"] is None  # nothing in the previous period
    assert a["period"]["granularity"] == "day" and a["trend"][0]["bucket"] == TODAY
    assert a["top_products"][0]["name"] == "Camera" and D(a["top_products"][0]["profit"]) == D("1000.00")
    assert a["top_customers"][0]["invoices"] == 1 and inv["total"]
    assert a["collections_by_method"] == [{"method": "upi", "amount": "1000.00"}]
    assert a["service_by_type"] == [{"type": "repair", "opened": 1, "completed": 0}]
    # A long period is grouped by month
    assert owner.get("/api/v1/analytics/overview").json()["period"]["granularity"] == "month"
    assert owner.get("/api/v1/analytics/overview",
                     params={"date_from": TODAY, "date_to": "2020-01-01"}).status_code == 422
    # Permission: salesperson has no analytics
    assert add_member(owner, "salesperson").get("/api/v1/analytics/overview").status_code == 403


def test_document_patch_nulls_do_not_break(tenant):
    d = tenant.upload(PDF, "x.pdf").json()
    r = tenant.patch(f"/api/v1/documents/{d['id']}", json={"title": None, "category": None, "is_sensitive": None,
                                                           "notes": None})
    assert r.status_code == 200 and r.json()["title"] == "x" and r.json()["category"] == "other"
