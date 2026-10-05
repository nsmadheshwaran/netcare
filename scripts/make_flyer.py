"""Builds a one-page, full-colour A4 leave-behind flyer PDF for in-person pitches.

Run from the repository root:  python scripts/make_flyer.py
Needs reportlab and qrcode (pip install qrcode[pil] if not already present).
"""
import io
from pathlib import Path

import qrcode
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent.parent
INK = colors.HexColor("#0f172a")
BRAND = colors.HexColor("#4f46e5")
BRAND_DARK = colors.HexColor("#3730a3")
TINT = colors.HexColor("#eef2ff")
AMBER = colors.HexColor("#f59e0b")
WHITE = colors.white

# ---- fill in your own details here ----
NAME = "Madheshwaran"
PHONE = "90433 53383"
WHATSAPP_NUMBER = "919043353383"  # country code + number, no spaces or +, for the wa.me link
EMAIL = "nsmadheshwaran@gmail.com"
CITY = "Tirupur"
PRICE_LINE = "One-time price from Rs 14,999 — no monthly fee"

FEATURE_GROUPS = [
    ("Billing & GST", ["GST tax invoices, quotations & credit notes", "Thermal receipts & email invoices"]),
    ("Stock & purchases", ["Multi-location stock tracking", "Purchase orders & supplier bills"]),
    ("Service jobs", ["Repair/installation/AMC job tickets", "On-screen customer signature"]),
    ("Monitoring (optional)", ["CCTV & network device status", "Switch off if you don't need it"]),
]

WHY = [
    ("Runs on your PC", "No cloud fee. Your data never leaves your shop."),
    ("One-time purchase", "Pay once. No subscription to keep using it."),
    ("Simple install", "Double-click setup, done in minutes."),
]


def qr_png_bytes(url: str) -> bytes:
    img = qrcode.make(url, border=2)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def band(story, text, style, bg, pad=6, space_after=6):
    t = Table([[Paragraph(text, style)]], colWidths=[182 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("LEFTPADDING", (0, 0), (-1, -1), 10 * mm),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 10 * mm), ("TOPPADDING", (0, 0), (-1, -1), pad * mm),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), pad * mm)]))
    story += [t, Spacer(1, space_after * mm)]


def build(out_path: Path):
    title = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=34, textColor=WHITE, leading=38)
    sub = ParagraphStyle("sub", fontName="Helvetica", fontSize=13, textColor=colors.HexColor("#e0e7ff"), leading=17)
    pitch = ParagraphStyle("pitch", fontName="Helvetica-Bold", fontSize=16, textColor=INK, leading=21, alignment=1)
    groupTitle = ParagraphStyle("gt", fontName="Helvetica-Bold", fontSize=12, textColor=BRAND_DARK, leading=15)
    groupItem = ParagraphStyle("gi", fontName="Helvetica", fontSize=10, textColor=INK, leading=14)
    priceText = ParagraphStyle("price", fontName="Helvetica-Bold", fontSize=14, textColor=WHITE, alignment=1)
    whyTitle = ParagraphStyle("wt", fontName="Helvetica-Bold", fontSize=10.5, textColor=INK, leading=13)
    whyBody = ParagraphStyle("wb", fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#475569"),
                             leading=12)
    contactName = ParagraphStyle("cn", fontName="Helvetica-Bold", fontSize=14, textColor=WHITE)
    contactLine = ParagraphStyle("cl", fontName="Helvetica", fontSize=10.5, textColor=colors.HexColor("#cbd5e1"),
                                 leading=15)
    qrCaption = ParagraphStyle("qc", fontName="Helvetica-Bold", fontSize=8.5, textColor=INK, alignment=1)

    doc = SimpleDocTemplate(str(out_path), pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=0, bottomMargin=0,
                            title="NetCare - Business & Service Management", author=NAME)
    story = []

    # Header band
    header = Table([[Paragraph("NetCare", title)],
                    [Paragraph("Business &amp; service management for computer, CCTV &amp; IT shops", sub)]],
                   colWidths=[210 * mm])
    header.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), BRAND),
                                ("LEFTPADDING", (0, 0), (-1, -1), 20 * mm),
                                ("TOPPADDING", (0, 0), (0, 0), 16 * mm), ("BOTTOMPADDING", (0, 0), (0, 0), 1 * mm),
                                ("TOPPADDING", (0, 1), (0, 1), 1 * mm), ("BOTTOMPADDING", (0, 1), (0, 1), 14 * mm)]))
    story.append(header)

    # Body (margins applied manually since topMargin/bottomMargin are 0 for full-bleed bands)
    story.append(Spacer(1, 10 * mm))
    body_wrap = []
    body_wrap.append(Paragraph("Run billing, stock and service jobs from one simple app — "
                               "built for shops like yours.", pitch))
    body_wrap.append(Spacer(1, 8 * mm))

    cells = []
    for gtitle, items in FEATURE_GROUPS:
        lines = [Paragraph(gtitle, groupTitle), Spacer(1, 2 * mm)]
        for it in items:
            lines.append(Paragraph(f"&bull;&nbsp;{it}", groupItem))
            lines.append(Spacer(1, 1.5 * mm))
        cells.append(lines)
    grid = Table([[cells[0], cells[1]], [cells[2], cells[3]]], colWidths=[85 * mm, 85 * mm])
    grid.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), TINT), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 6 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 5 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 5 * mm),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#c7d2fe")),
        ("INNERGRID", (0, 0), (-1, -1), 0.75, colors.HexColor("#c7d2fe")),
    ]))
    body_wrap += [grid, Spacer(1, 7 * mm)]

    price = Table([[Paragraph(PRICE_LINE, priceText)]], colWidths=[170 * mm])
    price.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), AMBER),
                               ("TOPPADDING", (0, 0), (-1, -1), 4 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm)]))
    body_wrap += [price, Spacer(1, 7 * mm)]

    why_cells = [[Paragraph(t, whyTitle), Paragraph(d, whyBody)] for t, d in WHY]
    why_table = Table([[c[0] for c in why_cells], [c[1] for c in why_cells]], colWidths=[56.6 * mm] * 3)
    why_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
                                   ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
                                   ("BOTTOMPADDING", (0, 0), (0, -1), 1.5 * mm)]))
    body_wrap.append(why_table)

    body_table = Table([[body_wrap]], colWidths=[182 * mm])
    body_table.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(Table([[body_table]], colWidths=[182 * mm],
                       style=[("LEFTPADDING", (0, 0), (-1, -1), 14 * mm),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 14 * mm)]))

    story.append(Spacer(1, 16 * mm))

    # Footer band: contact + QR
    qr_path = ROOT / "scripts" / "_flyer_qr.png"
    qr_path.write_bytes(qr_png_bytes(f"https://wa.me/{WHATSAPP_NUMBER}"))
    qr_white_box = Table([[Image(str(qr_path), width=26 * mm, height=26 * mm)],
                          [Paragraph("Scan to WhatsApp", qrCaption)]], colWidths=[32 * mm])
    qr_white_box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), WHITE),
                                      ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                                      ("TOPPADDING", (0, 0), (0, 0), 3 * mm), ("BOTTOMPADDING", (0, 0), (0, 0), 1 * mm),
                                      ("BOTTOMPADDING", (0, 1), (0, 1), 3 * mm)]))

    contact = [Paragraph(NAME, contactName), Spacer(1, 2 * mm), Paragraph(f"Phone / WhatsApp: {PHONE}", contactLine),
               Paragraph(f"Email: {EMAIL}", contactLine), Paragraph(CITY, contactLine)]
    footer = Table([[contact, qr_white_box]], colWidths=[150 * mm, 32 * mm])
    footer.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), INK), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                ("ALIGN", (1, 0), (1, 0), "CENTER"),
                                ("LEFTPADDING", (0, 0), (0, 0), 20 * mm), ("RIGHTPADDING", (1, 0), (1, 0), 20 * mm),
                                ("TOPPADDING", (0, 0), (-1, -1), 8 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 8 * mm)]))
    story.append(footer)

    doc.build(story)
    qr_path.unlink(missing_ok=True)


if __name__ == "__main__":
    out = ROOT / "release" / "NetCare_Flyer.pdf"
    out.parent.mkdir(exist_ok=True)
    build(out)
    print(f"Wrote {out} ({out.stat().st_size / 1024:.0f} KB)")
