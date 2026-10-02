"""Phase 2 end-to-end workflows: purchasing, sales, payments, returns, numbering, isolation."""
from decimal import Decimal as D

from conftest import add_member, register

TODAY = "2026-10-02"


def stock(t, pid):
    return D(t.get(f"/api/v1/products/{pid}").json()["stock_on_hand"])


def setup(t, state="33"):
    t.put("/api/v1/organization", json={"name": "Shop", "state_code": state})
    loc = t.get("/api/v1/organization/locations").json()[0]["id"]
    sup = t.post("/api/v1/suppliers", json={"name": "Distributor", "state_code": "33",
                                            "payment_terms_days": 30}).json()
    cam = t.post("/api/v1/products", json={"name": "Camera", "sku": "CAM", "purchase_price": "1000",
                                          "selling_price": "1500", "gst_rate": "18", "hsn_sac": "8525"}).json()
    svc = t.post("/api/v1/products", json={"name": "Installation", "sku": "INST", "selling_price": "500",
                                          "gst_rate": "18", "is_service": True}).json()
    cust = t.post("/api/v1/customers", json={"name": "Local School", "state_code": "33"}).json()
    return loc, sup, cam, svc, cust


def receive_stock(t, loc, sup, cam, qty="10"):
    po = t.post("/api/v1/purchase-orders", json={"supplier_id": sup["id"], "location_id": loc, "order_date": TODAY,
                                                 "lines": [{"product_id": cam["id"], "quantity": qty}]}).json()
    assert t.post(f"/api/v1/purchase-orders/{po['id']}/approve").status_code == 200
    r = t.post(f"/api/v1/purchase-orders/{po['id']}/receipts", json={
        "received_date": TODAY, "lines": [{"purchase_order_line_id": po["lines"][0]["id"], "quantity": qty}]})
    assert r.status_code == 201, r.text
    return po


# ---------------- purchasing ----------------
def test_purchase_workflow(tenant):
    loc, sup, cam, _, _ = setup(tenant)
    po = tenant.post("/api/v1/purchase-orders", json={
        "supplier_id": sup["id"], "location_id": loc, "order_date": TODAY,
        "lines": [{"product_id": cam["id"], "quantity": "10"}]}).json()
    assert po["number"] == "PO/2026-27/00001" and po["status"] == "draft"
    assert D(po["total"]) == D("11800.00") and D(po["cgst_total"]) == D("900.00")
    line_id = po["lines"][0]["id"]
    rcv = lambda q, key=None: tenant.post(f"/api/v1/purchase-orders/{po['id']}/receipts", json={
        "received_date": TODAY, "idempotency_key": key, "lines": [{"purchase_order_line_id": line_id, "quantity": q}]})

    assert rcv("1").status_code == 409  # not approved yet: no stock change
    assert stock(tenant, cam["id"]) == 0
    tenant.post(f"/api/v1/purchase-orders/{po['id']}/approve")
    assert tenant.put(f"/api/v1/purchase-orders/{po['id']}", json={
        "supplier_id": sup["id"], "location_id": loc, "order_date": TODAY,
        "lines": [{"product_id": cam["id"], "quantity": "1"}]}).status_code == 409  # approved = locked

    first = rcv("4", key="grn-a")
    assert first.status_code == 201 and rcv("4", key="grn-a").json()["id"] == first.json()["id"]  # idempotent
    assert stock(tenant, cam["id"]) == 4
    assert tenant.get(f"/api/v1/purchase-orders/{po['id']}").json()["status"] == "partially_received"
    assert rcv("7").status_code == 409  # over-receipt
    assert rcv("6").status_code == 201
    po2 = tenant.get(f"/api/v1/purchase-orders/{po['id']}").json()
    assert po2["status"] == "received" and D(po2["lines"][0]["received_quantity"]) == 10
    assert stock(tenant, cam["id"]) == 10
    moves = tenant.get(f"/api/v1/inventory/movements?product_id={cam['id']}").json()["items"]
    assert {m["movement_type"] for m in moves} == {"purchase_receipt"} and D(moves[0]["unit_cost"]) == 1000

    bill = tenant.post("/api/v1/purchase-invoices", json={
        "supplier_id": sup["id"], "supplier_invoice_number": "D-778", "purchase_order_id": po["id"],
        "invoice_date": TODAY, "lines": [{"product_id": cam["id"], "quantity": "10"}]}).json()
    assert bill["status"] == "open" and D(bill["balance_due"]) == D("11800.00")
    assert bill["due_date"] == "2026-11-01"  # supplier terms 30 days
    dup = tenant.post("/api/v1/purchase-invoices", json={
        "supplier_id": sup["id"], "supplier_invoice_number": "D-778", "invoice_date": TODAY,
        "lines": [{"product_id": cam["id"], "quantity": "1"}]})
    assert dup.status_code == 409

    pay = tenant.post("/api/v1/payments", json={
        "supplier_id": sup["id"], "payment_date": TODAY, "amount": "5000", "method": "bank_transfer",
        "allocations": [{"invoice_id": bill["id"], "amount": "5000"}]}).json()
    assert pay["number"].startswith("PAY/2026-27/") and pay["direction"] == "out"
    b = tenant.get(f"/api/v1/purchase-invoices/{bill['id']}").json()
    assert b["status"] == "partially_paid" and D(b["balance_due"]) == D("6800.00")
    assert D(tenant.get(f"/api/v1/suppliers/{sup['id']}").json()["balance_due"]) == D("6800.00")

    # Return 2 cameras to the supplier against the bill: stock and payable both drop.
    ret = tenant.post("/api/v1/purchase-returns", json={
        "supplier_id": sup["id"], "purchase_invoice_id": bill["id"], "location_id": loc, "return_date": TODAY,
        "lines": [{"product_id": cam["id"], "quantity": "2", "unit_cost": "1000", "tax_rate": "18"}]})
    assert ret.status_code == 201 and D(ret.json()["total"]) == D("2360.00")
    assert stock(tenant, cam["id"]) == 8
    assert D(tenant.get(f"/api/v1/purchase-invoices/{bill['id']}").json()["balance_due"]) == D("4440.00")


def test_cancel_and_close_po(tenant):
    loc, sup, cam, svc, _ = setup(tenant)
    bad = tenant.post("/api/v1/purchase-orders", json={"supplier_id": sup["id"], "location_id": loc,
                                                       "order_date": TODAY,
                                                       "lines": [{"product_id": svc["id"], "quantity": "1"}]})
    assert bad.status_code == 422  # services can't be stocked
    po = tenant.post("/api/v1/purchase-orders", json={"supplier_id": sup["id"], "location_id": loc,
                                                      "order_date": TODAY,
                                                      "lines": [{"product_id": cam["id"], "quantity": "5"}]}).json()
    assert tenant.post(f"/api/v1/purchase-orders/{po['id']}/close").status_code == 409
    assert tenant.post(f"/api/v1/purchase-orders/{po['id']}/cancel", json={"reason": "wrong item"}).json()[
        "status"] == "cancelled"
    assert tenant.post(f"/api/v1/purchase-orders/{po['id']}/approve").status_code == 409


# ---------------- sales ----------------
def test_quote_to_invoice_to_payment(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    receive_stock(tenant, loc, sup, cam, "10")
    q = tenant.post("/api/v1/quotations", json={
        "customer_id": cust["id"], "quote_date": TODAY, "document_discount": "100",
        "lines": [{"product_id": cam["id"], "quantity": "4", "line_discount_pct": "10"},
                  {"product_id": svc["id"], "quantity": "1"}]}).json()
    assert q["number"] == "QT/2026-27/00001"
    # 4*1500=6000 -10% =5400 ; +500 = 5900 ; doc discount 100 split 91.53/8.47
    assert D(q["subtotal"]) == D("6500.00") and D(q["discount_total"]) == D("700.00")
    assert D(q["taxable_total"]) == D("5800.00") and D(q["total"]) == D("6844.00")
    assert tenant.post(f"/api/v1/quotations/{q['id']}/status", json={"status": "accepted"}).json()["status"] == "accepted"
    assert stock(tenant, cam["id"]) == 10  # quotes don't touch stock

    inv = tenant.post(f"/api/v1/quotations/{q['id']}/convert?location_id={loc}").json()
    again = tenant.post(f"/api/v1/quotations/{q['id']}/convert?location_id={loc}")
    assert again.status_code == 409  # already converted
    assert inv["status"] == "draft" and inv["number"] is None and D(inv["total"]) == D("6844.00")
    assert stock(tenant, cam["id"]) == 10  # drafts don't touch stock
    assert D(inv["balance_due"]) == 0  # drafts aren't receivables

    issued = tenant.post(f"/api/v1/invoices/{inv['id']}/issue").json()
    assert issued["number"] == "INV/2026-27/00001" and issued["status"] == "issued"
    assert D(issued["balance_due"]) == D("6844.00")
    assert stock(tenant, cam["id"]) == 6  # service line didn't move stock
    assert tenant.post(f"/api/v1/invoices/{inv['id']}/issue").status_code == 409  # no double deduction
    assert stock(tenant, cam["id"]) == 6
    edit = tenant.put(f"/api/v1/invoices/{inv['id']}", json={
        "customer_id": cust["id"], "location_id": loc, "invoice_date": TODAY,
        "lines": [{"product_id": cam["id"], "quantity": "1"}]})
    assert edit.status_code == 409

    # Payment larger than due: 6844 due, pay 7000 -> 156 stays as an advance
    p = tenant.post("/api/v1/payments", json={
        "customer_id": cust["id"], "payment_date": TODAY, "amount": "7000", "method": "upi",
        "allocations": [{"invoice_id": inv["id"], "amount": "6844"}]}).json()
    assert p["number"] == "RCPT/2026-27/00001" and D(p["unallocated"]) == D("156.00")
    assert tenant.get(f"/api/v1/invoices/{inv['id']}").json()["status"] == "paid"
    over = tenant.post("/api/v1/payments", json={
        "customer_id": cust["id"], "payment_date": TODAY, "amount": "10", "method": "cash",
        "allocations": [{"invoice_id": inv["id"], "amount": "10"}]})
    assert over.status_code == 409  # nothing left to pay

    acct = tenant.get(f"/api/v1/customers/{cust['id']}/account").json()
    assert D(acct["outstanding"]) == 0 and D(acct["unallocated_payments"]) == D("156.00")
    assert len(acct["invoices"]) == 1 and len(acct["quotations"]) == 1

    # Void the receipt (e.g. UPI reversed): invoice is due again, audit trail kept
    v = tenant.post(f"/api/v1/payments/{p['id']}/void", json={"reason": "UPI reversal"}).json()
    assert v["voided_at"] and D(v["unallocated"]) == 0
    assert tenant.get(f"/api/v1/invoices/{inv['id']}").json()["status"] == "issued"
    assert tenant.post(f"/api/v1/payments/{p['id']}/void", json={"reason": "again"}).status_code == 409


def test_insufficient_stock_blocks_issue_atomically(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    receive_stock(tenant, loc, sup, cam, "2")
    inv = tenant.post("/api/v1/invoices", json={
        "customer_id": cust["id"], "location_id": loc, "invoice_date": TODAY,
        "lines": [{"product_id": cam["id"], "quantity": "1"}, {"product_id": cam["id"], "quantity": "5"}]}).json()
    r = tenant.post(f"/api/v1/invoices/{inv['id']}/issue")
    assert r.status_code == 409 and "Insufficient stock" in r.json()["detail"]
    after = tenant.get(f"/api/v1/invoices/{inv['id']}").json()
    assert after["status"] == "draft" and after["number"] is None
    assert stock(tenant, cam["id"]) == 2  # first line's deduction rolled back too
    # The failed attempt must not burn an invoice number
    ok = tenant.post("/api/v1/invoices", json={"customer_id": cust["id"], "location_id": loc,
                                               "invoice_date": TODAY,
                                               "lines": [{"product_id": svc["id"], "quantity": "1"}]}).json()
    assert tenant.post(f"/api/v1/invoices/{ok['id']}/issue").json()["number"] == "INV/2026-27/00001"


def test_interstate_and_unknown_state(tenant):
    loc, sup, cam, svc, cust = setup(tenant, state="33")
    other = tenant.post("/api/v1/customers", json={"name": "Bengaluru Office", "state_code": "29"}).json()
    unknown = tenant.post("/api/v1/customers", json={"name": "No State"}).json()
    line = [{"product_id": svc["id"], "quantity": "1"}]
    a = tenant.post("/api/v1/invoices", json={"customer_id": other["id"], "location_id": loc,
                                              "invoice_date": TODAY, "lines": line}).json()
    assert a["is_interstate"] and D(a["igst_total"]) == D("90.00") and D(a["cgst_total"]) == 0
    b = tenant.post("/api/v1/invoices", json={"customer_id": unknown["id"], "location_id": loc,
                                              "invoice_date": TODAY, "lines": line}).json()
    assert not b["is_interstate"] and b["place_of_supply"] is None
    c = tenant.post("/api/v1/invoices", json={"customer_id": unknown["id"], "location_id": loc,
                                              "invoice_date": TODAY, "place_of_supply": "27", "lines": line}).json()
    assert c["is_interstate"]


def test_credit_note_partial_and_full(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    receive_stock(tenant, loc, sup, cam, "10")
    inv = tenant.post("/api/v1/invoices", json={"customer_id": cust["id"], "location_id": loc,
                                                "invoice_date": TODAY,
                                                "lines": [{"product_id": cam["id"], "quantity": "3",
                                                           "unit_price": "999.99"}]}).json()
    tenant.post(f"/api/v1/invoices/{inv['id']}/issue")
    total = D(tenant.get(f"/api/v1/invoices/{inv['id']}").json()["total"])
    lid = inv["lines"][0]["id"]
    cn = lambda q, restock=True: tenant.post(f"/api/v1/invoices/{inv['id']}/credit-notes", json={
        "note_date": TODAY, "reason": "Defective", "restock": restock,
        "lines": [{"sales_invoice_line_id": lid, "quantity": q}]})
    a = cn("1").json()
    assert a["number"] == "CN/2026-27/00001" and stock(tenant, cam["id"]) == 8
    b = cn("1", restock=False).json()
    assert stock(tenant, cam["id"]) == 8  # damaged return: no restock
    c = cn("1").json()
    assert cn("1").status_code == 409  # nothing left to credit
    # Three credits sum to the invoice total exactly, no paisa drift
    assert D(a["total"]) + D(b["total"]) + D(c["total"]) == total
    after = tenant.get(f"/api/v1/invoices/{inv['id']}").json()
    assert after["status"] == "paid" and D(after["balance_due"]) == 0
    assert tenant.post(f"/api/v1/invoices/{inv['id']}/cancel", json={"reason": "x" * 5}).status_code == 409


def test_cancel_issued_invoice_restores_stock(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    receive_stock(tenant, loc, sup, cam, "5")
    inv = tenant.post("/api/v1/invoices", json={"customer_id": cust["id"], "location_id": loc,
                                                "invoice_date": TODAY,
                                                "lines": [{"product_id": cam["id"], "quantity": "2"}]}).json()
    tenant.post(f"/api/v1/invoices/{inv['id']}/issue")
    pay = tenant.post("/api/v1/payments", json={"customer_id": cust["id"], "payment_date": TODAY, "amount": "100",
                                                "method": "cash",
                                                "allocations": [{"invoice_id": inv["id"], "amount": "100"}]}).json()
    assert tenant.post(f"/api/v1/invoices/{inv['id']}/cancel", json={"reason": "typo"}).status_code == 409
    tenant.post(f"/api/v1/payments/{pay['id']}/void", json={"reason": "refund"})
    r = tenant.post(f"/api/v1/invoices/{inv['id']}/cancel", json={"reason": "customer cancelled"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert stock(tenant, cam["id"]) == 5
    # Cancelled number is not reused
    nxt = tenant.post("/api/v1/invoices", json={"customer_id": cust["id"], "location_id": loc,
                                                "invoice_date": TODAY,
                                                "lines": [{"product_id": svc["id"], "quantity": "1"}]}).json()
    assert tenant.post(f"/api/v1/invoices/{nxt['id']}/issue").json()["number"] == "INV/2026-27/00002"


def test_numbering_per_fiscal_year_and_prefix(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    tenant.put("/api/v1/organization", json={"name": "Shop", "state_code": "33",
                                             "numbering_prefixes": {"sales_invoice": "SHOP"}})
    mk = lambda d: tenant.post("/api/v1/invoices", json={"customer_id": cust["id"], "location_id": loc,
                                                         "invoice_date": d,
                                                         "lines": [{"product_id": svc["id"], "quantity": "1"}]}).json()
    nums = [tenant.post(f"/api/v1/invoices/{mk(d)['id']}/issue").json()["number"]
            for d in ("2026-03-31", "2026-04-01", "2026-04-02")]
    assert nums == ["SHOP/2025-26/00001", "SHOP/2026-27/00001", "SHOP/2026-27/00002"]
    bad = tenant.put("/api/v1/organization", json={"name": "Shop", "numbering_prefixes": {"bogus": "X"}})
    assert bad.status_code == 422


def test_idempotent_invoice_and_payment(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    body = {"customer_id": cust["id"], "location_id": loc, "invoice_date": TODAY, "idempotency_key": "pos-1",
            "lines": [{"product_id": svc["id"], "quantity": "1"}]}
    a, b = tenant.post("/api/v1/invoices", json=body).json(), tenant.post("/api/v1/invoices", json=body).json()
    assert a["id"] == b["id"]
    pay = {"customer_id": cust["id"], "payment_date": TODAY, "amount": "50", "method": "cash",
           "idempotency_key": "rcpt-1"}
    assert tenant.post("/api/v1/payments", json=pay).json()["id"] == tenant.post("/api/v1/payments", json=pay).json()["id"]
    assert tenant.get("/api/v1/payments").json()["total"] == 1


def test_payment_validation(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    other = tenant.post("/api/v1/customers", json={"name": "Other"}).json()
    inv = tenant.post("/api/v1/invoices", json={"customer_id": cust["id"], "location_id": loc,
                                                "invoice_date": TODAY,
                                                "lines": [{"product_id": svc["id"], "quantity": "1"}]}).json()
    pay = lambda **kw: tenant.post("/api/v1/payments", json={"payment_date": TODAY, "method": "cash", **kw})
    # can't pay a draft
    assert pay(customer_id=cust["id"], amount="10", allocations=[{"invoice_id": inv["id"], "amount": "10"}]
               ).status_code == 409
    tenant.post(f"/api/v1/invoices/{inv['id']}/issue")
    assert pay(customer_id=other["id"], amount="10", allocations=[{"invoice_id": inv["id"], "amount": "10"}]
               ).status_code == 422  # wrong customer
    assert pay(customer_id=cust["id"], supplier_id=sup["id"], amount="10").status_code == 422
    assert pay(customer_id=cust["id"], amount="10", allocations=[{"invoice_id": inv["id"], "amount": "20"}]
               ).status_code == 422  # allocation > payment
    assert pay(customer_id=cust["id"], amount="0").status_code == 422
    assert pay(customer_id=cust["id"], amount="10", method="bitcoin").status_code == 422
    # advance, then allocate later
    adv = pay(customer_id=cust["id"], amount="590").json()
    r = tenant.post(f"/api/v1/payments/{adv['id']}/allocate", json={"allocations": [{"invoice_id": inv["id"],
                                                                                     "amount": "590"}]})
    assert r.status_code == 200 and tenant.get(f"/api/v1/invoices/{inv['id']}").json()["status"] == "paid"


def test_dashboard_sales_figures(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    inv = tenant.post("/api/v1/invoices", json={"customer_id": cust["id"], "location_id": loc,
                                                "invoice_date": TODAY,
                                                "lines": [{"product_id": svc["id"], "quantity": "2"}]}).json()
    d = tenant.get("/api/v1/dashboard/summary?period=year").json()
    assert D(d["sales"]["invoiced_in_period"]) == 0  # drafts excluded
    tenant.post(f"/api/v1/invoices/{inv['id']}/issue")
    tenant.post("/api/v1/payments", json={"customer_id": cust["id"], "payment_date": TODAY, "amount": "180",
                                          "method": "cash", "allocations": [{"invoice_id": inv["id"],
                                                                             "amount": "180"}]})
    d = tenant.get("/api/v1/dashboard/summary?period=year").json()
    assert D(d["sales"]["invoiced_in_period"]) == D("1180.00")
    assert D(d["sales"]["received_in_period"]) == D("180.00")
    assert D(d["sales"]["receivable_outstanding"]) == D("1000.00")


# ---------------- isolation & roles ----------------
def test_trade_isolation(client):
    a, b = register(client, "A"), register(client, "B")
    loc, sup, cam, svc, cust = setup(a)
    inv = a.post("/api/v1/invoices", json={"customer_id": cust["id"], "location_id": loc, "invoice_date": TODAY,
                                           "lines": [{"product_id": svc["id"], "quantity": "1"}]}).json()
    a.post(f"/api/v1/invoices/{inv['id']}/issue")
    po = a.post("/api/v1/purchase-orders", json={"supplier_id": sup["id"], "location_id": loc, "order_date": TODAY,
                                                 "lines": [{"product_id": cam["id"], "quantity": "1"}]}).json()
    for url in (f"/api/v1/invoices/{inv['id']}", f"/api/v1/purchase-orders/{po['id']}",
                f"/api/v1/suppliers/{sup['id']}", f"/api/v1/customers/{cust['id']}/account"):
        assert b.get(url).status_code == 404, url
    assert b.post(f"/api/v1/invoices/{inv['id']}/cancel", json={"reason": "steal"}).status_code == 404
    assert b.post(f"/api/v1/purchase-orders/{po['id']}/approve").status_code == 404
    b_loc = b.get("/api/v1/organization/locations").json()[0]["id"]
    b_cust = b.post("/api/v1/customers", json={"name": "B cust"}).json()
    # B can't bill A's product or customer, or pay A's invoice
    assert b.post("/api/v1/invoices", json={"customer_id": b_cust["id"], "location_id": b_loc,
                                            "invoice_date": TODAY,
                                            "lines": [{"product_id": svc["id"], "quantity": "1"}]}).status_code == 422
    assert b.post("/api/v1/invoices", json={"customer_id": cust["id"], "location_id": b_loc, "invoice_date": TODAY,
                                            "lines": [{"description": "x", "unit_price": "1", "quantity": "1"}]}
                  ).status_code == 422
    assert b.post("/api/v1/payments", json={"customer_id": b_cust["id"], "payment_date": TODAY, "amount": "1",
                                            "method": "cash",
                                            "allocations": [{"invoice_id": inv["id"], "amount": "1"}]}
                  ).status_code == 422
    assert b.get("/api/v1/invoices").json()["total"] == 0
    # Numbering is per organization
    bi = b.post("/api/v1/invoices", json={"customer_id": b_cust["id"], "location_id": b_loc, "invoice_date": TODAY,
                                          "lines": [{"description": "Labour", "unit_price": "100", "quantity": "1"}]}
                ).json()
    assert b.post(f"/api/v1/invoices/{bi['id']}/issue").json()["number"] == "INV/2026-27/00001"


def test_trade_roles(client):
    owner = register(client)
    loc, sup, cam, svc, cust = setup(owner)
    sales = add_member(owner, "salesperson")
    inv_mgr = add_member(owner, "inventory_manager")
    acct = add_member(owner, "accountant")
    tech = add_member(owner, "technician")
    po = inv_mgr.post("/api/v1/purchase-orders", json={"supplier_id": sup["id"], "location_id": loc,
                                                       "order_date": TODAY,
                                                       "lines": [{"product_id": cam["id"], "quantity": "1"}]})
    assert po.status_code == 201
    assert inv_mgr.post(f"/api/v1/purchase-orders/{po.json()['id']}/approve").status_code == 403  # needs approver
    assert sales.post("/api/v1/purchase-orders", json={}).status_code == 403
    inv = sales.post("/api/v1/invoices", json={"customer_id": cust["id"], "location_id": loc,
                                               "invoice_date": TODAY,
                                               "lines": [{"product_id": svc["id"], "quantity": "1"}]})
    assert inv.status_code == 201
    assert acct.post("/api/v1/invoices", json={}).status_code == 403
    assert acct.get("/api/v1/invoices").status_code == 200
    assert tech.get("/api/v1/invoices").status_code == 403
    assert tech.get("/api/v1/payments").status_code == 403
