"""Customer signature drawn on a tablet: stored, validated, served and printed."""
import base64
import io

from PIL import Image

from conftest import register
from test_service import ticket
from test_trade import setup

A = "/api/v1/service-tickets"


def png_bytes(size=(400, 150), fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, fmt)
    return buf.getvalue()


def data_url(raw: bytes, mime="image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def pending_ticket(t):
    _loc, _sup, _cam, _svc, cust = setup(t)
    return ticket(t, cust, estimate_amount="4500")


def test_signature_is_stored_served_and_printed(tenant):
    tk = pending_ticket(tenant)
    raw = png_bytes()
    r = tenant.post(f"{A}/{tk['id']}/approval", json={"decision": "approved", "signed_by": "Ramesh Kumar",
                                                       "signature_png": data_url(raw)})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["customer_approval"] == "approved" and out["has_signature"] is True
    assert out["approval_signed_by"] == "Ramesh Kumar"
    assert "signature_png" not in out and "approval_signature" not in out  # the image never rides along in JSON
    assert any("signed on screen by Ramesh Kumar" in e["message"] for e in out["events"])
    img = tenant.get(f"{A}/{tk['id']}/signature")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert img.content == raw and img.headers["cache-control"] == "private, no-store"
    pdf = tenant.get(f"{A}/{tk['id']}/pdf")
    assert pdf.status_code == 200 and b"/Subtype /Image" in pdf.content
    plain = pending_ticket_pdf_without_signature(tenant)
    assert b"/Subtype /Image" not in plain


def pending_ticket_pdf_without_signature(t):
    cust = t.post("/api/v1/customers", json={"name": "Other", "state_code": "33"}).json()
    tk = ticket(t, cust, estimate_amount="100")
    t.post(f"{A}/{tk['id']}/approval", json={"decision": "approved", "note": "by phone"})
    return t.get(f"{A}/{tk['id']}/pdf").content


def test_bad_signatures_are_refused_and_nothing_is_saved(tenant):
    tk = pending_ticket(tenant)
    url = f"{A}/{tk['id']}/approval"
    good = png_bytes()
    cases = {
        "no name": {"signature_png": data_url(good)},
        "blank name": {"signature_png": data_url(good), "signed_by": "   "},
        "jpeg": {"signature_png": data_url(png_bytes(fmt="JPEG"), "image/jpeg"), "signed_by": "X"},
        "jpeg labelled png": {"signature_png": data_url(png_bytes(fmt="JPEG")), "signed_by": "X"},
        "not base64": {"signature_png": "!!!not-base64!!!", "signed_by": "X"},
        "text": {"signature_png": base64.b64encode(b"<script>alert(1)</script>").decode(), "signed_by": "X"},
        "truncated png": {"signature_png": base64.b64encode(good[:60]).decode(), "signed_by": "X"},
        "too large in pixels": {"signature_png": data_url(png_bytes((2500, 100))), "signed_by": "X"},
        "too many bytes": {"signature_png": base64.b64encode(good + b"0" * (151 * 1024)).decode(), "signed_by": "X"},
    }
    for name, extra in cases.items():
        r = tenant.post(url, json={"decision": "approved", **extra})
        assert r.status_code == 422, (name, r.status_code, r.text[:200])
    after = tenant.get(f"{A}/{tk['id']}").json()
    assert after["customer_approval"] == "pending" and after["has_signature"] is False
    assert tenant.get(f"{A}/{tk['id']}/signature").status_code == 404


def test_signature_is_private_to_the_business(client):
    a, b = register(client, "A Shop"), register(client, "B Shop")
    tk = pending_ticket(a)
    a.post(f"{A}/{tk['id']}/approval", json={"decision": "approved", "signed_by": "Cust",
                                              "signature_png": data_url(png_bytes())})
    assert a.get(f"{A}/{tk['id']}/signature").status_code == 200
    assert b.get(f"{A}/{tk['id']}/signature").status_code == 404


def test_plain_approval_still_works(tenant):
    tk = pending_ticket(tenant)
    r = tenant.post(f"{A}/{tk['id']}/approval", json={"decision": "approved", "note": "Approved by phone"})
    assert r.status_code == 200 and r.json()["has_signature"] is False
    assert tenant.get(f"{A}/{tk['id']}/signature").status_code == 404


def test_transparent_signature_is_flattened_onto_white(tenant):
    tk = pending_ticket(tenant)
    img = Image.new("RGBA", (400, 150), (0, 0, 0, 0))  # what a tablet canvas exports: transparent background
    for x in range(50, 150):
        img.putpixel((x, 75), (15, 23, 42, 255))  # one dark stroke
    buf = io.BytesIO()
    img.save(buf, "PNG")
    r = tenant.post(f"{A}/{tk['id']}/approval", json={"decision": "approved", "signed_by": "Cust",
                                                       "signature_png": data_url(buf.getvalue())})
    assert r.status_code == 200, r.text
    stored = Image.open(io.BytesIO(tenant.get(f"{A}/{tk['id']}/signature").content))
    assert stored.mode == "RGB"
    assert stored.getpixel((10, 10)) == (255, 255, 255)  # was transparent, now white
    assert stored.getpixel((100, 75)) == (15, 23, 42)  # the stroke survives
    assert tenant.get(f"{A}/{tk['id']}/pdf").status_code == 200
