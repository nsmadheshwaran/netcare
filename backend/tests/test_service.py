"""Phase 4: service tickets, parts, approval, billing, assets, maintenance, employees, attendance, leave, tasks."""
from decimal import Decimal as D

from conftest import add_member, register
from test_trade import setup

from app.routers.service import add_months
from app.services.timeutil import today as local_today


def stock(t, pid):
    return D(t.get(f"/api/v1/products/{pid}").json()["stock_on_hand"])


def employee(owner, member=None, name="Tech", technician=True):
    body = {"name": name, "is_technician": technician, "job_role": "Technician" if technician else "Staff"}
    if member is not None:
        uid = next(m["user_id"] for m in owner.get("/api/v1/organization/members").json() if m["email"] == member.email)
        body["user_id"] = uid
    r = owner.post("/api/v1/employees", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def stock_in(t, loc, pid, qty, cost):
    t.post("/api/v1/inventory/movements", json={"product_id": pid, "location_id": loc, "movement_type": "stock_in",
                                                "quantity": qty, "unit_cost": cost})


def ticket(t, cust, **kw):
    body = {"ticket_type": "repair", "customer_id": cust["id"], "reported_problem": "Laptop not booting",
            "equipment": "Dell Inspiron 15", "serial_number": "SN-LAP-1", "accessories_received": "Charger", **kw}
    r = t.post("/api/v1/service-tickets", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def status(t, tid, s, **kw):
    return t.post(f"/api/v1/service-tickets/{tid}/status", json={"status": s, **kw})


# ---------------- repair workflow ----------------
def test_repair_flow_parts_approval_invoice(client):
    owner = register(client)
    loc, sup, cam, svc, cust = setup(owner)
    ssd = owner.post("/api/v1/products", json={"name": "SSD 512GB", "sku": "SSD512", "purchase_price": "2500",
                                              "selling_price": "3200", "gst_rate": "18", "hsn_sac": "8523"}).json()
    stock_in(owner, loc, ssd["id"], "5", "2500")
    tech_user = add_member(owner, "technician")
    tech = employee(owner, tech_user, "Arun")

    tk = ticket(owner, cust, assigned_to=tech["id"], estimate_amount="4500")
    assert tk["number"] == "SRV/2026-27/00001" and tk["status"] == "assigned"
    assert tk["customer_approval"] == "pending" and tk["technician_name"] == "Arun"
    tid = tk["id"]

    # Technician cannot start work before the customer approves the estimate
    assert status(tech_user, tid, "in_progress").status_code == 409
    r = tech_user.post(f"/api/v1/service-tickets/{tid}/approval", json={"decision": "approved",
                                                                        "note": "Approved by phone"})
    assert r.status_code == 200 and r.json()["customer_approval"] == "approved"
    assert status(tech_user, tid, "in_progress").status_code == 200
    tech_user.patch(f"/api/v1/service-tickets/{tid}", json={"diagnosis": "Failed SSD", "labour_charge": "800"})

    # Parts come out of stock immediately; a returned part goes back
    r = tech_user.post(f"/api/v1/service-tickets/{tid}/parts", json={"product_id": ssd["id"], "quantity": "1"})
    assert r.status_code == 201 and stock(owner, ssd["id"]) == 4
    extra = tech_user.post(f"/api/v1/service-tickets/{tid}/parts",
                           json={"product_id": ssd["id"], "quantity": "1"}).json()
    assert stock(owner, ssd["id"]) == 3
    pid = extra["parts"][-1]["id"]
    assert tech_user.post(f"/api/v1/service-tickets/{tid}/parts/{pid}/return").status_code == 200
    assert stock(owner, ssd["id"]) == 4
    assert tech_user.post(f"/api/v1/service-tickets/{tid}/parts/{pid}/return").status_code == 409
    assert tech_user.post(f"/api/v1/service-tickets/{tid}/parts",
                          json={"product_id": svc["id"], "quantity": "1"}).status_code == 422  # service, not part

    assert status(tech_user, tid, "completed").status_code == 409  # no work recorded
    tech_user.patch(f"/api/v1/service-tickets/{tid}", json={"work_performed": "Replaced SSD, installed OS"})
    done = status(tech_user, tid, "completed")
    assert done.status_code == 200 and done.json()["completed_at"]
    assert status(tech_user, tid, "closed").status_code == 403  # office closes tickets
    assert status(owner, tid, "closed").status_code == 409  # chargeable and not invoiced yet

    assert owner.post(f"/api/v1/service-tickets/{tid}/invoice", json={}).status_code == 422  # labour tax unknown
    inv = owner.post(f"/api/v1/service-tickets/{tid}/invoice", json={"labour_tax_rate": "18"})
    assert inv.status_code == 201, inv.text
    inv = inv.json()
    assert D(inv["taxable_total"]) == D("4000.00")  # 3200 part + 800 labour
    assert owner.post(f"/api/v1/service-tickets/{tid}/invoice", json={"labour_tax_rate": "18"}).status_code == 409
    issued = owner.post(f"/api/v1/invoices/{inv['id']}/issue").json()
    assert issued["number"].startswith("INV/")
    assert stock(owner, ssd["id"]) == 4  # NOT deducted a second time
    pl = {r["item"]: r for r in owner.get("/api/v1/reports/profit-loss")
          .json()["rows"]}
    assert D(pl["Less: cost of goods sold"]["amount"]) == D("-2500.00")  # part cost reaches COGS
    assert status(owner, tid, "closed").status_code == 200

    full = owner.get(f"/api/v1/service-tickets/{tid}").json()
    kinds = [e["kind"] for e in full["events"]]
    assert {"created", "assigned", "approval", "status", "part", "invoice"} <= set(kinds)
    assert full["invoice_number"] == issued["number"]
    pdf = owner.get(f"/api/v1/service-tickets/{tid}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_cancelled_ticket_invoice_can_be_reissued_without_restocking(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    stock_in(tenant, loc, cam["id"], "3", "1000")
    tk = ticket(tenant, cust)
    tenant.post(f"/api/v1/service-tickets/{tk['id']}/parts", json={"product_id": cam["id"], "quantity": "1"})
    tenant.patch(f"/api/v1/service-tickets/{tk['id']}", json={"work_performed": "Swapped camera"})
    status(tenant, tk["id"], "in_progress")
    status(tenant, tk["id"], "completed")
    inv = tenant.post(f"/api/v1/service-tickets/{tk['id']}/invoice", json={}).json()
    tenant.post(f"/api/v1/invoices/{inv['id']}/issue")
    assert stock(tenant, cam["id"]) == 2
    tenant.post(f"/api/v1/invoices/{inv['id']}/cancel", json={"reason": "wrong customer"})
    assert stock(tenant, cam["id"]) == 2  # the part was really used; cancelling the bill doesn't return it
    assert tenant.get(f"/api/v1/service-tickets/{tk['id']}").json()["sales_invoice_id"] is None
    assert tenant.post(f"/api/v1/service-tickets/{tk['id']}/invoice", json={}).status_code == 201


def test_warranty_job_and_cancel_rules(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    stock_in(tenant, loc, cam["id"], "2", "1000")
    tk = ticket(tenant, cust, is_warranty=True, estimate_amount="999")
    assert tk["customer_approval"] == "not_required"  # warranty: nothing to approve
    tenant.post(f"/api/v1/service-tickets/{tk['id']}/parts", json={"product_id": cam["id"], "quantity": "1"})
    assert status(tenant, tk["id"], "cancelled").status_code == 409  # parts still out
    tenant.patch(f"/api/v1/service-tickets/{tk['id']}", json={"work_performed": "Replaced under warranty"})
    status(tenant, tk["id"], "in_progress")
    status(tenant, tk["id"], "completed")
    assert tenant.post(f"/api/v1/service-tickets/{tk['id']}/invoice", json={}).status_code == 409
    assert status(tenant, tk["id"], "closed").status_code == 200  # no invoice needed
    assert status(tenant, tk["id"], "in_progress").status_code == 409  # closed is final
    other = ticket(tenant, cust)
    assert status(tenant, other["id"], "completed").status_code == 409  # can't skip in_progress
    assert status(tenant, other["id"], "cancelled", note="Customer withdrew").status_code == 200


def test_technician_can_only_touch_own_tickets(client):
    owner = register(client)
    loc, sup, cam, svc, cust = setup(owner)
    t1, t2 = add_member(owner, "technician"), add_member(owner, "technician")
    e1 = employee(owner, t1, "A")
    employee(owner, t2, "B")
    tk = ticket(owner, cust, assigned_to=e1["id"])
    assert t2.patch(f"/api/v1/service-tickets/{tk['id']}", json={"diagnosis": "x"}).status_code == 403
    assert t2.post(f"/api/v1/service-tickets/{tk['id']}/notes", json={"message": "hi"}).status_code == 403
    assert t1.post(f"/api/v1/service-tickets/{tk['id']}/notes", json={"message": "Called customer"}).status_code == 200
    assert t1.post("/api/v1/service-tickets", json={}).status_code == 403  # can't open tickets
    assert t1.post(f"/api/v1/service-tickets/{tk['id']}/assign", json={"employee_id": e1["id"]}).status_code == 403
    assert status(t1, tk["id"], "cancelled").status_code == 403
    mine = t1.get("/api/v1/service-tickets?mine=true").json()
    assert mine["total"] == 1 and t2.get("/api/v1/service-tickets?mine=true").json()["total"] == 0
    work = t1.get("/api/v1/my-work").json()
    assert work["employee"]["name"] == "A" and len(work["tickets"]) == 1
    receptionist = add_member(owner, "receptionist")
    assert receptionist.post("/api/v1/service-tickets", json={
        "ticket_type": "complaint", "customer_id": cust["id"], "reported_problem": "Camera 3 blurry"}).status_code == 201


# ---------------- installation, assets, maintenance ----------------
def test_installation_registers_assets_and_maintenance(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    tech = employee(tenant, name="Installer")
    tk = ticket(tenant, cust, ticket_type="installation", reported_problem="Install 4 cameras + DVR",
                assigned_to=tech["id"])
    body = {"installed_on": "2026-10-01", "maintenance": {"title": "Quarterly CCTV check", "interval_months": 3},
            "assets": [{"asset_type": "camera", "name": f"Camera {i}", "serial_number": f"CAM-{i}",
                        "site_location": f"Gate {i}", "ip_address": f"192.168.1.{10 + i}", "warranty_months": 12}
                       for i in range(1, 5)] + [{"asset_type": "dvr", "name": "DVR", "serial_number": "DVR-1",
                                                 "warranty_months": 24}]}
    r = tenant.post(f"/api/v1/service-tickets/{tk['id']}/assets", json=body)
    assert r.status_code == 201, r.text
    assets = r.json()
    assert len(assets) == 5 and assets[0]["warranty_until"] == "2027-10-01" and assets[-1]["warranty_until"] == "2028-10-01"
    assert tenant.post(f"/api/v1/service-tickets/{tk['id']}/assets", json={"assets": [
        {"asset_type": "camera", "name": "dup", "serial_number": "CAM-1"}]}).status_code == 409
    bad_ip = tenant.post(f"/api/v1/service-tickets/{tk['id']}/assets", json={"assets": [
        {"asset_type": "camera", "name": "x", "ip_address": "999.1.1.1"}]})
    assert bad_ip.status_code == 422
    assert tenant.get(f"/api/v1/assets?customer_id={cust['id']}").json()["total"] == 5

    sched = tenant.get("/api/v1/maintenance-schedules").json()
    assert len(sched) == 1 and sched[0]["next_due"] == "2027-01-01" and sched[0]["technician_name"] == "Installer"
    m = tenant.post(f"/api/v1/maintenance-schedules/{sched[0]['id']}/ticket")
    assert m.status_code == 201 and m.json()["ticket_type"] == "maintenance"
    assert tenant.post(f"/api/v1/maintenance-schedules/{sched[0]['id']}/ticket").status_code == 409
    mid = m.json()["id"]
    tenant.patch(f"/api/v1/service-tickets/{mid}", json={"work_performed": "Cleaned lenses, checked recording"})
    status(tenant, mid, "in_progress")
    status(tenant, mid, "completed")
    after = tenant.get("/api/v1/maintenance-schedules").json()[0]
    done = local_today()
    assert after["last_done"] == str(done) and after["next_due"] == str(add_months(done, 3))  # from completion

    # Service history and replacement
    cam1 = next(a for a in assets if a["serial_number"] == "CAM-1")
    rep = ticket(tenant, cust, asset_id=cam1["id"], equipment=None, serial_number=None,
                 reported_problem="Camera 1 no video")
    assert rep["serial_number"] == "CAM-1" and rep["asset_name"] == "Camera 1"
    assert len(tenant.get(f"/api/v1/assets/{cam1['id']}/history").json()) == 1
    new = tenant.post(f"/api/v1/assets/{cam1['id']}/replace", json={"reason": "Lightning damage", "new_asset": {
        "customer_id": cust["id"], "asset_type": "camera", "name": "Camera 1", "serial_number": "CAM-1B"}})
    assert new.status_code == 201
    old = tenant.get(f"/api/v1/assets/{cam1['id']}").json()
    assert old["status"] == "replaced"
    other = tenant.post("/api/v1/customers", json={"name": "Other"}).json()
    assert tenant.post("/api/v1/service-tickets", json={"ticket_type": "repair", "customer_id": other["id"],
                                                        "asset_id": cam1["id"], "reported_problem": "x y z"}
                       ).status_code == 422  # asset belongs to another customer


def test_warranty_filters_and_reports(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    mk = lambda name, until: tenant.post("/api/v1/assets", json={"customer_id": cust["id"], "asset_type": "nvr",
                                                                 "name": name, "warranty_until": until}).json()
    mk("Expiring", "2026-10-20")
    mk("Expired", "2026-09-01")
    mk("Fine", "2027-12-31")
    assert tenant.get("/api/v1/assets?warranty=expiring").json()["total"] == 1
    assert tenant.get("/api/v1/assets?warranty=expired").json()["total"] == 1
    w = tenant.get("/api/v1/reports/warranty-expiry?as_of=2026-10-02").json()
    assert [r["asset"] for r in w["rows"]] == ["Expiring"]  # expired 31+ days ago and far-future excluded
    for key in ("service-performance", "warranty-expiry", "maintenance-due", "task-completion", "attendance"):
        for fmt in ("json", "csv", "xlsx", "pdf"):
            assert tenant.get(f"/api/v1/reports/{key}?format={fmt}").status_code == 200, (key, fmt)
    d = tenant.get("/api/v1/dashboard/summary").json()
    assert d["service"]["warranty_expiring_30d"] == 1 and "service" not in d["not_yet_available"]


# ---------------- people ----------------
def test_employees_attendance_and_leave(client):
    owner = register(client)
    staff_user = add_member(owner, "salesperson")
    emp = employee(owner, staff_user, "Priya", technician=False)
    assert owner.post("/api/v1/employees", json={"name": "Dup", "user_id": emp["user_id"]}).status_code == 409
    stranger = register(client, "Elsewhere")
    stranger_uid = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {stranger.token}"}).json()["user"]["id"]
    assert owner.post("/api/v1/employees", json={"name": "X", "user_id": stranger_uid}).status_code == 422

    day = {"work_date": "2026-10-01", "entries": [{"employee_id": emp["id"], "status": "present",
                                                    "check_in": "09:30", "check_out": "18:00"}]}
    assert owner.put("/api/v1/attendance", json=day).status_code == 200
    day["entries"][0]["status"] = "half_day"
    owner.put("/api/v1/attendance", json=day)  # correction, not a duplicate
    rows = owner.get("/api/v1/attendance?date_from=2026-10-01").json()
    assert len(rows) == 1 and rows[0]["status"] == "half_day"
    assert owner.put("/api/v1/attendance", json={**day, "work_date": "2099-01-01"}).status_code == 422
    bad = {"work_date": "2026-10-01", "entries": [{"employee_id": emp["id"], "status": "present",
                                                    "check_in": "18:00", "check_out": "09:00"}]}
    assert owner.put("/api/v1/attendance", json=bad).status_code == 422
    assert staff_user.put("/api/v1/attendance", json=day).status_code == 403

    lr = staff_user.post("/api/v1/leave-requests", json={"start_date": "2026-10-05", "end_date": "2026-10-06",
                                                         "leave_type": "casual", "reason": "Family function"})
    assert lr.status_code == 201 and lr.json()["days"] == 2
    assert staff_user.post("/api/v1/leave-requests", json={"start_date": "2026-10-06", "end_date": "2026-10-07",
                                                           "leave_type": "sick"}).status_code == 409  # overlap
    assert staff_user.post(f"/api/v1/leave-requests/{lr.json()['id']}/decide",
                           json={"decision": "approved"}).status_code == 403
    assert len(staff_user.get("/api/v1/leave-requests").json()) == 1
    ok = owner.post(f"/api/v1/leave-requests/{lr.json()['id']}/decide", json={"decision": "approved"})
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    att = owner.get("/api/v1/attendance?date_from=2026-10-05&date_to=2026-10-06").json()
    assert [a["status"] for a in att] == ["leave", "leave"]
    summary = owner.get("/api/v1/reports/attendance?date_from=2026-10-01&date_to=2026-10-06").json()
    row = next(r for r in summary["rows"] if r["employee"] == "Priya")
    assert (row["half_day"], row["leave"], row["unrecorded"]) == (1, 2, 3)


def test_tasks(client):
    owner = register(client)
    u1, u2 = add_member(owner, "salesperson"), add_member(owner, "salesperson")
    e1 = employee(owner, u1, "One", technician=False)
    employee(owner, u2, "Two", technician=False)
    t = owner.post("/api/v1/tasks", json={"title": "Call St. Mary's about AMC renewal", "assigned_to": e1["id"],
                                          "priority": "high", "due_date": "2026-09-30"}).json()
    assert t["overdue"] is True and t["assignee_name"] == "One"
    assert u1.post("/api/v1/tasks", json={"title": "x"}).status_code == 403
    assert u2.post(f"/api/v1/tasks/{t['id']}/status", json={"status": "done"}).status_code == 403
    assert u1.post(f"/api/v1/tasks/{t['id']}/status", json={"status": "cancelled"}).status_code == 403
    done = u1.post(f"/api/v1/tasks/{t['id']}/status", json={"status": "done"}).json()
    assert done["status"] == "done" and done["completed_at"] and not done["overdue"]
    assert u1.get("/api/v1/tasks?mine=true").json()["total"] == 1
    tc = owner.get("/api/v1/reports/task-completion?date_from=2026-10-01").json()
    one = next(r for r in tc["rows"] if r["employee"] == "One")
    assert one["done"] == 1 and one["late"] == 1


def test_service_isolation(client):
    a, b = register(client, "A"), register(client, "B")
    loc, sup, cam, svc, cust = setup(a)
    emp = employee(a, name="A tech")
    tk = ticket(a, cust, assigned_to=emp["id"])
    asset = a.post("/api/v1/assets", json={"customer_id": cust["id"], "asset_type": "dvr", "name": "DVR"}).json()
    for url in (f"/api/v1/service-tickets/{tk['id']}", f"/api/v1/assets/{asset['id']}",
                f"/api/v1/service-tickets/{tk['id']}/pdf"):
        assert b.get(url).status_code == 404, url
    assert b.get("/api/v1/employees").json()["total"] == 0
    assert b.post(f"/api/v1/service-tickets/{tk['id']}/status", json={"status": "cancelled"}).status_code == 404
    b_loc, b_sup, b_cam, b_svc, b_cust = setup(b)
    assert b.post("/api/v1/service-tickets", json={"ticket_type": "repair", "customer_id": b_cust["id"],
                                                   "reported_problem": "abc", "assigned_to": emp["id"]}
                  ).status_code == 422  # A's employee
    assert b.post("/api/v1/tasks", json={"title": "x", "assigned_to": emp["id"]}).status_code == 422
    b_tk = ticket(b, b_cust)
    assert b.post(f"/api/v1/service-tickets/{b_tk['id']}/parts",
                  json={"product_id": cam["id"], "quantity": "1"}).status_code == 422  # A's product
    # Ticket numbers are per business
    assert b_tk["number"] == "SRV/2026-27/00001"


def test_add_months_clamps_month_end():
    from datetime import date
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2027, 12, 15), 3) == date(2028, 3, 15)
    assert add_months(date(2028, 2, 29), 12) == date(2029, 2, 28)
