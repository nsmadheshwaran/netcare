"""Fills a NEW NetCare install with a fictional business so you can demo it to customers.

Everything goes through the app's own API, so invoices, GST, stock and balances are calculated by NetCare itself.
Run only against a demo copy (it registers a new business), for example:
    python scripts/seed_demo.py --url http://localhost:8090
Uses only the Python standard library.
"""
import argparse
import base64
import json
import math
import struct
import sys
import urllib.error
import urllib.request
import zlib
from datetime import date, timedelta


class Api:
    def __init__(self, base: str):
        self.base, self.token, self.org = base.rstrip("/") + "/api/v1", None, None

    def call(self, method: str, path: str, body=None):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.org:
            headers["X-Organization-ID"] = str(self.org)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            sys.exit(f"{method} {path} failed with {e.code}: {e.read().decode()[:300]}")


def signature_png(w=400, h=150) -> str:
    """A hand-drawn-looking squiggle as a data URL, built without any imaging library."""
    px = [[255] * w for _ in range(h)]
    pts = [(40 + i * 3.2, 80 + 35 * math.sin(i / 7.0) * math.cos(i / 23.0)) for i in range(100)]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        for t in range(20):
            x, y = x0 + (x1 - x0) * t / 20, y0 + (y1 - y0) * t / 20
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if 0 <= int(y) + dy < h and 0 <= int(x) + dx < w:
                        px[int(y) + dy][int(x) + dx] = 20
    raw = b"".join(b"\x00" + bytes(row) for row in px)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8090")
    ap.add_argument("--email", default="demo@example.com")
    ap.add_argument("--password", default="Demo-Pass-2026")
    a = ap.parse_args()
    api = Api(a.url)
    today = date.today()
    d = lambda n: (today - timedelta(days=n)).isoformat()

    r = api.call("POST", "/auth/register", {"email": a.email, "full_name": "Demo Owner", "password": a.password,
                                            "organization_name": "Sunrise Security & IT Solutions (DEMO)"})
    api.token = r["access_token"]
    api.org = api.call("GET", "/auth/me")["memberships"][0]["organization_id"]
    api.call("PUT", "/organization", {
        "name": "Sunrise Security & IT Solutions (DEMO)", "state_code": "33", "phone": "+91 98400 00000",
        "email": "demo-business@example.com", "address": "12, Sample Street, Chennai - 600001 (demo data)",
        "invoice_terms": "Goods once sold are not returnable. Warranty as per manufacturer. Demo data only.",
        "payment_instructions": "Pay by UPI or bank transfer (demo details)."})
    loc = api.call("GET", "/organization/locations")[0]["id"]

    customers = {}
    for key, body in {
        "school": {"name": "Govt Higher Secondary School, Tambaram", "customer_type": "business", "state_code": "33",
                   "phone": "+91 98400 11111", "city": "Chennai"},
        "medical": {"name": "Anand Medicals", "customer_type": "business", "state_code": "33",
                    "phone": "+91 98400 22222", "email": "anand.medicals@example.com", "city": "Chennai"},
        "person": {"name": "Ravi Kumar", "customer_type": "individual", "state_code": "33",
                   "phone": "+91 98400 33333", "city": "Chennai"}}.items():
        customers[key] = api.call("POST", "/customers", body)["id"]
    api.call("POST", "/suppliers", {"name": "Sample Security Distributors", "state_code": "33", "payment_terms_days": 30})

    catalogue = {
        "cam": ("CCTV Camera 2MP Dome", "CAM-2MP", "8525", "1300", "1850", False, 20),
        "nvr": ("4-Channel NVR", "NVR-4CH", "8521", "4200", "5800", False, 6),
        "hdd": ("1TB Surveillance HDD", "HDD-1TB", "8471", "3000", "3800", False, 6),
        "cable": ("Cat6 Cable, 305 m box", "CAB-CAT6", "8544", "5200", "6500", False, 5),
        "router": ("Dual-band WiFi Router", "RTR-DB", "8517", "1500", "2100", False, 8),
        "install": ("Installation and configuration", "SVC-INST", "9987", None, "1500", True, 0),
        "amc": ("Annual maintenance contract (per site)", "SVC-AMC", "9987", None, "6000", True, 0)}
    prod = {}
    for key, (name, sku, hsn, cost, price, service, qty) in catalogue.items():
        body = {"name": name, "sku": sku, "hsn_sac": hsn, "selling_price": price, "gst_rate": "18",
                "is_service": service, "min_stock": "3" if not service else "0"}
        if cost:
            body["purchase_price"] = cost
        prod[key] = api.call("POST", "/products", body)["id"]
        if qty:
            api.call("POST", "/inventory/movements", {"product_id": prod[key], "location_id": loc,
                                                       "movement_type": "stock_in", "quantity": str(qty),
                                                       "unit_cost": cost, "reference": "Opening stock (demo)"})

    def invoice(cust, days_ago, due_in, lines, issue=True):
        inv = api.call("POST", "/invoices", {
            "customer_id": customers[cust], "location_id": loc, "invoice_date": d(days_ago),
            "due_date": d(days_ago - due_in), "lines": [{"product_id": prod[p], "quantity": str(q)} for p, q in lines]})
        return api.call("POST", f"/invoices/{inv['id']}/issue") if issue else inv

    def pay(inv, cust, amount, method):
        api.call("POST", "/payments", {"customer_id": customers[cust], "payment_date": today.isoformat(),
                                       "amount": str(amount), "method": method,
                                       "allocations": [{"invoice_id": inv["id"], "amount": str(amount)}]})

    school = invoice("school", 20, 14, [("cam", 8), ("nvr", 1), ("hdd", 1), ("cable", 1), ("install", 1)])
    pay(school, "school", 25000, "bank_transfer")  # partly paid and overdue
    shop = invoice("medical", 5, 7, [("router", 2), ("install", 1)])
    pay(shop, "medical", shop["total"], "upi")  # fully paid
    invoice("person", 0, 7, [("cam", 2), ("install", 1)])  # issued today, unpaid
    invoice("medical", 0, 7, [("amc", 1)], issue=False)  # a draft

    api.call("POST", "/quotations", {"customer_id": customers["medical"], "quote_date": today.isoformat(),
                                     "valid_until": (today + timedelta(days=15)).isoformat(),
                                     "lines": [{"product_id": prod["cam"], "quantity": "4"},
                                               {"product_id": prod["nvr"], "quantity": "1"},
                                               {"product_id": prod["install"], "quantity": "1"}]})

    tech = api.call("POST", "/employees", {"name": "Arun (technician)", "is_technician": True,
                                           "job_role": "Technician"})
    t1 = api.call("POST", "/service-tickets", {
        "ticket_type": "repair", "customer_id": customers["medical"], "assigned_to": tech["id"],
        "reported_problem": "Two cameras showing no picture", "equipment": "CCTV system, 4 cameras",
        "estimate_amount": "1500"})
    api.call("POST", f"/service-tickets/{t1['id']}/approval", {"decision": "approved", "signed_by": "Anand",
                                                               "signature_png": signature_png()})
    api.call("POST", "/service-tickets", {
        "ticket_type": "installation", "customer_id": customers["person"], "assigned_to": tech["id"],
        "reported_problem": "Install 2 cameras at the shop entrance and rear", "equipment": "2 x 2MP dome cameras"})

    print(f"Demo ready at {a.url}\n  sign in: {a.email} / {a.password}\n  business: Sunrise Security & IT Solutions (DEMO)")


if __name__ == "__main__":
    main()
