from decimal import Decimal


def test_customer_crud_search_archive(tenant):
    r = tenant.post("/api/v1/customers", json={"name": "Ravi Kumar", "phone": "9876543210", "city": "Chennai",
                                              "customer_type": "business", "business_name": "Ravi Traders",
                                              "gstin": "33abcde1234f1z5", "pincode": "600001"})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["gstin"] == "33ABCDE1234F1Z5"
    assert tenant.post("/api/v1/customers", json={"name": "x", "gstin": "BADGSTIN"}).status_code == 422
    assert tenant.post("/api/v1/customers", json={"name": "x", "pincode": "12"}).status_code == 422
    # duplicate detection by phone
    assert tenant.post("/api/v1/customers", json={"name": "Other", "phone": "9876543210"}).status_code == 409
    assert tenant.post("/api/v1/customers?allow_duplicate=true",
                       json={"name": "Other", "phone": "9876543210"}).status_code == 201
    assert tenant.get("/api/v1/customers?q=traders").json()["total"] == 1
    assert tenant.get("/api/v1/customers?q=98765").json()["total"] == 2
    upd = tenant.put(f"/api/v1/customers/{c['id']}", json={**{k: c[k] for k in ("name", "customer_type")},
                                                           "city": "Madurai"}).json()
    assert upd["city"] == "Madurai"
    tenant.post(f"/api/v1/customers/{c['id']}/archive")
    assert tenant.get("/api/v1/customers").json()["total"] == 1
    assert tenant.get("/api/v1/customers?archived=true").json()["total"] == 1
    tenant.post(f"/api/v1/customers/{c['id']}/restore")
    assert tenant.get("/api/v1/customers").json()["total"] == 2


def test_customer_pagination_and_sort(tenant):
    for n in ["Charlie", "alpha", "Bravo"]:
        tenant.post("/api/v1/customers", json={"name": n})
    p = tenant.get("/api/v1/customers?size=2&page=1&sort=name").json()
    assert p["total"] == 3 and len(p["items"]) == 2
    assert tenant.get("/api/v1/customers?size=2&page=2").json()["items"][0]["name"] in {"Charlie", "alpha"}


def test_customer_csv_import_preview_and_commit(tenant):
    tenant.post("/api/v1/customers", json={"name": "Existing", "phone": "9000000001"})
    csv_text = ("Full Name,Mobile,email,city\n"
                "New One,9000000002,new1@example.com,Salem\n"
                "Dup Existing,9000000001,,\n"
                ",9000000003,,\n"                           # missing name -> error
                "Dup In File,9000000002,,\n"
                "=cmd,9000000004,bad-email,\n")             # invalid email -> error
    files = {"file": ("c.csv", csv_text, "text/csv")}
    mapping = '{"Full Name": "name", "Mobile": "phone"}'
    prev = tenant.post("/api/v1/customers/import", files=files, data={"mapping": mapping}).json()
    assert prev["committed"] is False and prev["created"] == 0
    assert prev["summary"] == {"ok": 1, "duplicate": 2, "error": 2}
    assert tenant.get("/api/v1/customers").json()["total"] == 1  # preview wrote nothing
    files = {"file": ("c.csv", csv_text, "text/csv")}
    done = tenant.post("/api/v1/customers/import", files=files, data={"mapping": mapping, "commit": "true"}).json()
    assert done["created"] == 1
    assert tenant.get("/api/v1/customers").json()["total"] == 2


def test_csv_export_neutralises_formulas(tenant):
    tenant.post("/api/v1/customers", json={"name": "=HYPERLINK(\"x\")"})
    body = tenant.get("/api/v1/customers/export.csv").text
    assert "'=HYPERLINK" in body


def test_products_and_unique_sku(tenant):
    cat = tenant.post("/api/v1/product-categories", json={"name": "CCTV"}).json()
    p = tenant.post("/api/v1/products", json={"name": "Dome Camera 2MP", "sku": "CAM-2MP", "category_id": cat["id"],
                                             "purchase_price": "1450.50", "selling_price": "1999.00",
                                             "gst_rate": "18", "hsn_sac": "8525", "min_stock": "5"})
    assert p.status_code == 201, p.text
    assert p.json()["category_name"] == "CCTV"
    assert Decimal(p.json()["selling_price"]) == Decimal("1999.00")
    assert tenant.post("/api/v1/products", json={"name": "dup", "sku": "cam-2mp"}).status_code == 409
    assert tenant.post("/api/v1/products", json={"name": "neg", "sku": "N1",
                                                "selling_price": "-1"}).status_code == 422
    assert tenant.post("/api/v1/products", json={"name": "frac", "sku": "N2",
                                                "selling_price": "1.234"}).status_code == 422


def _setup_stock(t):
    loc = t.get("/api/v1/organization/locations").json()[0]["id"]
    p = t.post("/api/v1/products", json={"name": "SSD 512GB", "sku": "SSD512", "purchase_price": "2500",
                                        "min_stock": "3"}).json()
    return p["id"], loc


def test_stock_movements_and_no_negative(tenant):
    pid, loc = _setup_stock(tenant)
    mv = lambda t, q, **kw: tenant.post("/api/v1/inventory/movements", json={
        "product_id": pid, "location_id": loc, "movement_type": t, "quantity": q, **kw})
    assert mv("stock_in", "10").status_code == 201
    r = mv("stock_out", "4")
    assert Decimal(r.json()["balance_after"]) == 6 and Decimal(r.json()["quantity_change"]) == -4
    assert mv("stock_out", "7").status_code == 409  # insufficient
    assert mv("stock_out", "-1").status_code == 422
    assert mv("adjustment", "-2").json()["balance_after"] in ("4", "4.000")
    assert mv("damaged", "1").status_code == 201
    assert mv("customer_return", "1").status_code == 201
    assert Decimal(tenant.get(f"/api/v1/products/{pid}").json()["stock_on_hand"]) == 4
    hist = tenant.get(f"/api/v1/inventory/movements?product_id={pid}").json()
    assert hist["total"] == 5  # rejected movements left no trace


def test_idempotent_movement(tenant):
    pid, loc = _setup_stock(tenant)
    body = {"product_id": pid, "location_id": loc, "movement_type": "stock_in", "quantity": "5",
            "idempotency_key": "grn-001"}
    a = tenant.post("/api/v1/inventory/movements", json=body).json()
    b = tenant.post("/api/v1/inventory/movements", json=body).json()
    assert a["id"] == b["id"]
    assert Decimal(tenant.get(f"/api/v1/products/{pid}").json()["stock_on_hand"]) == 5


def test_transfer_between_locations(tenant):
    pid, main = _setup_stock(tenant)
    shop2 = tenant.post("/api/v1/organization/locations", json={"name": "Branch 2"}).json()["id"]
    tenant.post("/api/v1/inventory/movements", json={"product_id": pid, "location_id": main,
                                                     "movement_type": "stock_in", "quantity": "8"})
    r = tenant.post("/api/v1/inventory/transfers", json={"product_id": pid, "from_location_id": main,
                                                         "to_location_id": shop2, "quantity": "3"})
    assert r.status_code == 201
    levels = {lv["location_name"]: Decimal(lv["quantity"]) for lv in tenant.get("/api/v1/inventory/levels").json()}
    assert levels == {"Main": 5, "Branch 2": 3}
    # Over-transfer fails atomically: neither side changes
    r = tenant.post("/api/v1/inventory/transfers", json={"product_id": pid, "from_location_id": main,
                                                         "to_location_id": shop2, "quantity": "50"})
    assert r.status_code == 409
    levels = {lv["location_name"]: Decimal(lv["quantity"]) for lv in tenant.get("/api/v1/inventory/levels").json()}
    assert levels == {"Main": 5, "Branch 2": 3}


def test_service_products_have_no_stock(tenant):
    loc = tenant.get("/api/v1/organization/locations").json()[0]["id"]
    s = tenant.post("/api/v1/products", json={"name": "Installation", "sku": "SVC-INST", "is_service": True}).json()
    r = tenant.post("/api/v1/inventory/movements", json={"product_id": s["id"], "location_id": loc,
                                                         "movement_type": "stock_in", "quantity": "1"})
    assert r.status_code == 422


def test_dashboard_uses_real_data(tenant):
    empty = tenant.get("/api/v1/dashboard/summary").json()
    assert empty["customers"]["total"] == 0 and empty["inventory"]["stock_valuation_at_cost"] == "0.00"
    tenant.post("/api/v1/customers", json={"name": "C1"})
    pid, loc = _setup_stock(tenant)
    tenant.post("/api/v1/inventory/movements", json={"product_id": pid, "location_id": loc,
                                                     "movement_type": "stock_in", "quantity": "2"})
    d = tenant.get("/api/v1/dashboard/summary?period=day").json()
    assert d["customers"] == {"total": 1, "new_in_period": 1}
    assert d["inventory"]["stock_valuation_at_cost"] == "5000.00"
    assert d["inventory"]["low_stock_count"] == 1  # 2 <= min 3
    assert "expenses" in d["not_yet_available"] and "sales" not in d["not_yet_available"]
    for period in ("week", "month", "quarter", "year"):
        assert tenant.get(f"/api/v1/dashboard/summary?period={period}").status_code == 200
    assert tenant.get("/api/v1/dashboard/summary?period=bogus").status_code == 422


def test_timestamps_are_utc_aware(tenant):
    c = tenant.post("/api/v1/customers", json={"name": "TZ"}).json()
    assert c["created_at"].endswith(("Z", "+00:00"))
    d = tenant.get("/api/v1/dashboard/summary").json()
    assert d["recent_activity"][0]["at"].endswith("+00:00")
