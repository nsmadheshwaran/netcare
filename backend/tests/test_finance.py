"""Phase 3: costing, expenses/accounts, tax rates, inclusive pricing, reports, exports, PDFs."""
import io
from decimal import Decimal as D

from openpyxl import load_workbook

from conftest import add_member, register
from test_trade import TODAY, receive_stock, setup

from app.services.pdf_docs import amount_in_words, words_indian


def stock_in(t, loc, pid, qty, cost):
    r = t.post("/api/v1/inventory/movements", json={"product_id": pid, "location_id": loc,
                                                    "movement_type": "stock_in", "quantity": qty, "unit_cost": cost})
    assert r.status_code == 201, r.text


def sell(t, cust, loc, lines, **kw):
    inv = t.post("/api/v1/invoices", json={"customer_id": cust["id"], "location_id": loc, "invoice_date": TODAY,
                                           "lines": lines, **kw})
    assert inv.status_code == 201, inv.text
    r = t.post(f"/api/v1/invoices/{inv.json()['id']}/issue")
    assert r.status_code == 200, r.text
    return r.json()


def report(t, key, **params):
    r = t.get(f"/api/v1/reports/{key}", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def rows_by(rep, key="item"):
    return {r[key]: r for r in rep["rows"]}


# ---------------- costing ----------------
def test_moving_average_cost_and_cogs(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    stock_in(tenant, loc, cam["id"], "10", "1000")
    stock_in(tenant, loc, cam["id"], "10", "1200")  # avg -> 1100
    assert D(tenant.get(f"/api/v1/products/{cam['id']}").json()["stock_on_hand"]) == 20
    inv = sell(tenant, cust, loc, [{"product_id": cam["id"], "quantity": "4", "unit_price": "1500"},
                                   {"product_id": svc["id"], "quantity": "1", "unit_price": "500"}])
    stock_in(tenant, loc, cam["id"], "4", "1400")  # later purchase must not change the earlier sale's cost
    pl = rows_by(report(tenant, "profit-loss", date_from=TODAY, date_to=TODAY))
    assert D(pl["Sales (taxable value of issued invoices)"]["amount"]) == D("6500.00")
    assert D(pl["Less: cost of goods sold"]["amount"]) == D("-4400.00")  # 4 x 1100
    assert D(pl["Gross profit"]["amount"]) == D("2100.00")

    # Credit note with restock: cost comes back at the original 1100, not the new average
    tenant.post(f"/api/v1/invoices/{inv['id']}/credit-notes", json={
        "note_date": TODAY, "reason": "Returned", "restock": True,
        "lines": [{"sales_invoice_line_id": inv["lines"][0]["id"], "quantity": "1"}]})
    pl = rows_by(report(tenant, "profit-loss", date_from=TODAY, date_to=TODAY))
    assert D(pl["Less: sales returns and credit notes"]["amount"]) == D("-1500.00")
    assert D(pl["Less: cost of goods sold"]["amount"]) == D("-3300.00")
    # avg before return: (16 x 1100 + 4 x 1400) / 20 = 1160; return 1 @ 1100 -> (20 x 1160 + 1100) / 21
    assert D(tenant.get("/api/v1/reports/stock-valuation").json()["rows"][0]["avg_cost"]) == D("1157.14")
    sv = report(tenant, "stock-valuation")
    assert D(sv["totals"]["value"]) == D(sv["rows"][0]["quantity"]) * D(sv["rows"][0]["avg_cost"])


def test_transfers_do_not_change_average_cost(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    other = tenant.post("/api/v1/organization/locations", json={"name": "Branch"}).json()["id"]
    stock_in(tenant, loc, cam["id"], "5", "900")
    tenant.post("/api/v1/inventory/transfers", json={"product_id": cam["id"], "from_location_id": loc,
                                                     "to_location_id": other, "quantity": "2"})
    p = tenant.get(f"/api/v1/products/{cam['id']}").json()
    # new product starts at its purchase price (1000); first costed receipt into empty stock sets 900
    assert D(tenant.get("/api/v1/reports/stock-valuation").json()["rows"][0]["avg_cost"]) == D("900.00")
    assert D(p["stock_on_hand"]) == 5


# ---------------- expenses, accounts, cash flow ----------------
def test_expenses_income_transfers_and_cash_flow(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    cats = {(c["kind"], c["name"]): c["id"] for c in tenant.get("/api/v1/finance-categories").json()}
    assert ("expense", "Rent") in cats and ("income", "Interest") in cats
    bank = tenant.post("/api/v1/accounts", json={"name": "SBI Current", "kind": "bank", "opening_balance": "50000",
                                                 "is_default": True}).json()
    accts = {a["name"]: a for a in tenant.get("/api/v1/accounts").json()}
    assert accts["SBI Current"]["is_default"]

    def entry(**kw):
        r = tenant.post("/api/v1/finance-entries", json={"entry_date": TODAY, **kw})
        assert r.status_code == 201, r.text
        return r.json()

    rent = entry(kind="expense", category_id=cats[("expense", "Rent")], amount="15000", method="bank_transfer",
                 payee="Landlord")
    assert rent["number"].startswith("EXP/2026-27/") and rent["account_name"] == "SBI Current"
    elec = entry(kind="expense", category_id=cats[("expense", "Electricity")], amount="1180", tax_amount="180",
                 method="cash")
    assert elec["account_name"] == "Cash in hand"  # auto-created default cash account
    entry(kind="income", category_id=cats[("income", "Interest")], amount="250", method="bank_transfer")
    cash = next(a for a in tenant.get("/api/v1/accounts").json() if a["kind"] == "cash")
    entry(kind="transfer", amount="5000", account_id=bank["id"], to_account_id=cash["id"], method="bank_transfer")
    # customer pays cash
    inv = sell(tenant, cust, loc, [{"product_id": svc["id"], "quantity": "2"}])
    tenant.post("/api/v1/payments", json={"customer_id": cust["id"], "payment_date": TODAY, "amount": inv["total"],
                                          "method": "cash", "allocations": [{"invoice_id": inv["id"],
                                                                             "amount": inv["total"]}]})
    cf = report(tenant, "cash-flow", date_from=TODAY, date_to=TODAY)
    acc = {r["account"]: r for r in cf["rows"]}
    assert D(acc["SBI Current"]["opening"]) == D("50000.00")
    assert D(acc["SBI Current"]["closing"]) == D("50000") - 15000 + 250 - 5000
    assert D(acc["Cash in hand"]["closing"]) == D("5000") - 1180 + D(inv["total"])
    assert D(cf["totals"]["closing"]) == D("50000") - 15000 - 1180 + 250 + D(inv["total"])

    pl = rows_by(report(tenant, "profit-loss", date_from=TODAY, date_to=TODAY))
    assert D(pl["Expense: Rent"]["amount"]) == D("-15000.00")
    assert D(pl["Expense: Electricity"]["amount"]) == D("-1000.00")  # claimable GST excluded
    assert D(pl["Other income: Interest"]["amount"]) == D("250.00")

    # Void keeps the record but removes it from reports
    r = tenant.post(f"/api/v1/finance-entries/{rent['id']}/void", json={"reason": "duplicate"})
    assert r.status_code == 200 and r.json()["voided_at"]
    pl = rows_by(report(tenant, "profit-loss", date_from=TODAY, date_to=TODAY))
    assert "Expense: Rent" not in pl
    assert tenant.post(f"/api/v1/finance-entries/{rent['id']}/void", json={"reason": "again"}).status_code == 409

    closing = report(tenant, "daily-closing", day=TODAY)
    items = rows_by(closing)
    assert items["Received: Cash"]["count"] == 1 and D(items["Expenses paid"]["amount"]) == D("-1180.00")


def test_entry_validation(tenant):
    setup(tenant)
    cats = {(c["kind"], c["name"]): c["id"] for c in tenant.get("/api/v1/finance-categories").json()}
    post = lambda **kw: tenant.post("/api/v1/finance-entries", json={"entry_date": TODAY, **kw})
    assert post(kind="expense", amount="10").status_code == 422  # no category
    assert post(kind="expense", category_id=cats[("income", "Interest")], amount="10").status_code == 422
    assert post(kind="expense", category_id=cats[("expense", "Rent")], amount="10", tax_amount="11").status_code == 422
    assert post(kind="expense", category_id=cats[("expense", "Rent")], amount="-5").status_code == 422
    acc = tenant.post("/api/v1/accounts", json={"name": "Till", "kind": "cash"}).json()
    assert post(kind="transfer", amount="5", account_id=acc["id"], to_account_id=acc["id"]).status_code == 422
    body = {"kind": "expense", "category_id": cats[("expense", "Rent")], "amount": "10", "idempotency_key": "e1"}
    assert post(**body).json()["id"] == post(**body).json()["id"]


# ---------------- tax ----------------
def test_tax_rate_master_is_versioned_and_enforced(tenant):
    loc, sup, cam, svc, cust = setup(tenant)  # products carry 18%
    line = [{"product_id": svc["id"], "quantity": "1"}]
    mk = lambda d="2026-10-02": tenant.post("/api/v1/invoices", json={
        "customer_id": cust["id"], "location_id": loc, "invoice_date": d, "lines": line})
    assert mk().status_code == 201  # no rates configured -> no validation
    r18 = tenant.post("/api/v1/tax-rates", json={"name": "GST 18%", "rate": "18", "effective_from": "2025-01-01"}).json()
    assert tenant.post("/api/v1/tax-rates", json={"name": "dup", "rate": "18", "effective_from": "2026-01-01"}
                       ).status_code == 409
    tenant.post("/api/v1/tax-rates", json={"name": "GST 5%", "rate": "5", "effective_from": "2025-01-01"})
    assert mk().status_code == 201
    retire = tenant.post(f"/api/v1/tax-rates/{r18['id']}/retire", json={"effective_to": "2026-09-30",
                                                                        "reason": "Rate changed"})
    assert retire.status_code == 200
    bad = mk("2026-10-02")
    assert bad.status_code == 422 and "not in your tax rate list" in bad.json()["detail"]
    assert mk("2026-09-30").status_code == 201  # still valid on its last day
    hist = tenant.get("/api/v1/tax-rates?include_history=true").json()
    assert len(hist) == 2 and any(r["effective_to"] == "2026-09-30" for r in hist)
    viewer = add_member(tenant, "accountant")
    assert viewer.post("/api/v1/tax-rates", json={"name": "x", "rate": "1", "effective_from": TODAY}).status_code == 403


def test_tax_inclusive_invoice(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    tenant.put("/api/v1/organization", json={"name": "Shop", "state_code": "33", "prices_include_tax_default": True})
    inv = sell(tenant, cust, loc, [{"product_id": svc["id"], "quantity": "1", "unit_price": "590"}])
    assert inv["prices_include_tax"] and D(inv["total"]) == D("590.00") and D(inv["taxable_total"]) == D("500.00")
    ex = sell(tenant, cust, loc, [{"product_id": svc["id"], "quantity": "1", "unit_price": "590"}],
              prices_include_tax=False)
    assert D(ex["total"]) == D("696.20")


def test_gst_summary_is_draft_and_correct(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    biz = tenant.post("/api/v1/customers", json={"name": "Biz", "gstin": "29ABCDE1234F1Z5", "state_code": "29"}).json()
    sell(tenant, cust, loc, [{"product_id": svc["id"], "quantity": "2"}])          # B2C intra 1000 @18
    sell(tenant, biz, loc, [{"product_id": svc["id"], "quantity": "1", "tax_rate": "5"}])  # B2B inter 500 @5
    g = report(tenant, "gst-summary", date_from=TODAY, date_to=TODAY)
    assert g["draft"] is True and any("not a GSTR" in n for n in g["notes"])
    out = {(r["type"], r["rate"]): r for r in g["sections"][0]["rows"]}
    assert D(out[("B2C", "18%")]["taxable_value"]) == D("1000.00") and D(out[("B2C", "18%")]["cgst"]) == D("90.00")
    assert D(out[("B2B", "5%")]["igst"]) == D("25.00")
    for fmt, magic in (("csv", b"\xef\xbb\xbf"), ("xlsx", b"PK"), ("pdf", b"%PDF")):
        r = tenant.get(f"/api/v1/reports/gst-summary?format={fmt}&date_from={TODAY}&date_to={TODAY}")
        assert r.status_code == 200 and r.content.startswith(magic), fmt
    assert b"DRAFT - NOT FOR FILING" in tenant.get("/api/v1/reports/gst-summary?format=csv").content


# ---------------- reports & exports ----------------
def test_every_report_in_every_format(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    tenant.put("/api/v1/organization", json={"name": "A & B <Traders>", "state_code": "33"})  # needs escaping
    receive_stock(tenant, loc, sup, cam, "3")
    sell(tenant, cust, loc, [{"product_id": cam["id"], "quantity": "1"}], due_date=TODAY)
    keys = [c["key"] for c in tenant.get("/api/v1/reports").json()]
    assert len(keys) == 17
    for key in keys:
        for fmt in ("json", "csv", "xlsx", "pdf"):
            r = tenant.get(f"/api/v1/reports/{key}?format={fmt}")
            assert r.status_code == 200, (key, fmt, r.text[:200])
            if fmt == "xlsx":
                load_workbook(io.BytesIO(r.content))  # opens cleanly
            if fmt == "pdf":
                assert r.content.startswith(b"%PDF")
    assert tenant.get("/api/v1/reports/nope").status_code == 404
    assert tenant.get("/api/v1/reports/sales-register?date_from=2026-10-02&date_to=2026-01-01").status_code == 422


def test_receivables_ageing(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    tenant.post("/api/v1/invoices", json={"customer_id": cust["id"], "location_id": loc, "invoice_date": "2026-06-01",
                                          "due_date": "2026-06-15", "lines": [{"product_id": svc["id"], "quantity": "1"}]})
    inv_id = tenant.get("/api/v1/invoices").json()["items"][0]["id"]
    tenant.post(f"/api/v1/invoices/{inv_id}/issue")
    sell(tenant, cust, loc, [{"product_id": svc["id"], "quantity": "1"}], due_date="2026-10-20")
    a = report(tenant, "receivables-ageing", as_of="2026-10-02")
    row = a["rows"][0]
    assert D(row["d90"]) == D("590.00") and D(row["not_due"]) == D("590.00") and D(row["total"]) == D("1180.00")


def test_csv_export_neutralises_formulas_in_reports(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    evil = tenant.post("/api/v1/customers", json={"name": "=HYPERLINK(\"http://x\")", "state_code": "33"}).json()
    sell(tenant, evil, loc, [{"product_id": svc["id"], "quantity": "1"}])
    body = tenant.get("/api/v1/reports/sales-register?format=csv").content.decode("utf-8-sig")
    assert "'=HYPERLINK" in body


def test_report_permissions_and_isolation(client):
    a, b = register(client, "A"), register(client, "B")
    loc, sup, cam, svc, cust = setup(a)
    sell(a, cust, loc, [{"product_id": svc["id"], "quantity": "1"}])
    assert D(report(b, "sales-register")["totals"].get("total", "0")) == 0
    sales = add_member(a, "salesperson")
    assert sales.get("/api/v1/reports/profit-loss").status_code == 403
    assert sales.get("/api/v1/finance-entries").status_code == 403
    assert add_member(a, "accountant").get("/api/v1/reports/profit-loss").status_code == 200


# ---------------- PDFs ----------------
def test_invoice_quotation_receipt_pdfs(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    tenant.put("/api/v1/organization", json={"name": "Shree & Sons", "state_code": "33", "gstin": "33ABCDE1234F1Z5",
                                             "payment_instructions": "UPI: shop@bank"})
    inv = sell(tenant, cust, loc, [{"product_id": svc["id"], "quantity": "3"}])
    for layout in ("a4", "thermal"):
        r = tenant.get(f"/api/v1/invoices/{inv['id']}/pdf?layout={layout}")
        assert r.status_code == 200 and r.content.startswith(b"%PDF") and "inline" in r.headers["content-disposition"]
    assert "attachment" in tenant.get(f"/api/v1/invoices/{inv['id']}/pdf?download=true").headers["content-disposition"]
    q = tenant.post("/api/v1/quotations", json={"customer_id": cust["id"], "quote_date": TODAY,
                                                "lines": [{"product_id": svc["id"], "quantity": "1"}]}).json()
    assert tenant.get(f"/api/v1/quotations/{q['id']}/pdf").content.startswith(b"%PDF")
    p = tenant.post("/api/v1/payments", json={"customer_id": cust["id"], "payment_date": TODAY, "amount": "2000",
                                              "method": "upi", "allocations": [{"invoice_id": inv["id"],
                                                                                "amount": inv["total"]}]}).json()
    assert tenant.get(f"/api/v1/payments/{p['id']}/pdf").content.startswith(b"%PDF")


def test_logo_upload_validation(tenant):
    png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
           b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")
    up = lambda data, name="logo.png": tenant.post("/api/v1/organization/logo", files={"file": (name, data, "image/png")})
    assert up(b"<svg onload=alert(1)>", "logo.png").status_code == 422  # content, not filename, decides
    assert up(b"GIF89a....").status_code == 422
    assert up(b"\x89PNG\r\n\x1a\n" + b"0" * 400_000).status_code == 413
    assert up(png).status_code == 204
    assert tenant.get("/api/v1/organization").json()["has_logo"] is True
    assert tenant.get("/api/v1/organization/logo").content == png
    setup(tenant)
    assert tenant.get("/api/v1/organization").json()["has_logo"] is True


def test_amount_in_words():
    assert words_indian(0) == "Zero"
    assert words_indian(1_23_45_678) == "One Crore Twenty-Three Lakh Forty-Five Thousand Six Hundred Seventy-Eight"
    assert words_indian(1_00_000) == "One Lakh"
    assert words_indian(250_00_00_000) == "Two Hundred Fifty Crore"
    assert amount_in_words("28192.56") == "Rupees Twenty-Eight Thousand One Hundred Ninety-Two and Fifty-Six Paise Only"
    assert amount_in_words("100") == "Rupees One Hundred Only"


def test_new_product_cost_starts_at_purchase_price(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    tenant.post("/api/v1/inventory/movements", json={"product_id": cam["id"], "location_id": loc,
                                                     "movement_type": "stock_in", "quantity": "2"})  # no cost given
    inv = sell(tenant, cust, loc, [{"product_id": cam["id"], "quantity": "1"}])
    pl = rows_by(report(tenant, "profit-loss", date_from=TODAY, date_to=TODAY))
    assert D(pl["Less: cost of goods sold"]["amount"]) == D("-1000.00")  # not zero
    assert inv["number"]
