"""Builds a one-page leave-behind flyer PDF for in-person pitches.

Run from the repository root:  python scripts/make_flyer.py
Needs reportlab and qrcode (pip install qrcode[pil] if not already present).
"""
import io
from pathlib import Path

import qrcode
from reportlab.lib import colors
from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent.parent
INK = colors.HexColor("#0f172a")
BRAND = colors.HexColor("#4f46e5")
MUTE = colors.HexColor("#64748b")
LINE = colors.HexColor("#e2e8f0")

# ---- fill in your own details here ----
NAME = "Madheshwaran"
PHONE = "90433 53383"
WHATSAPP_NUMBER = "919043353383"  # country code + number, no spaces or +, for the wa.me link
EMAIL = "nsmadheshwaran@gmail.com"
CITY = "Tirupur"

FEATURES = [
    "GST billing, quotations and credit notes",
    "Multi-location stock and purchase tracking",
    "Service job tickets with on-screen customer sign-off",
    "AMC maintenance schedules and reminders",
    "Optional CCTV and network device monitoring",
    "Runs on your own PC — no monthly fee, your data stays with you",
]


def qr_png_bytes(url: str) -> bytes:
    img = qrcode.make(url, border=2)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def build(out_path: Path):
    title = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=25, textColor=INK, leading=29)
    sub = ParagraphStyle("sub", fontName="Helvetica", fontSize=11, textColor=MUTE, leading=15)
    pitch = ParagraphStyle("pitch", fontName="Helvetica-Bold", fontSize=13, textColor=BRAND, leading=18,
                           spaceBefore=10, spaceAfter=8)
    feat = ParagraphStyle("feat", fontName="Helvetica", fontSize=10.5, textColor=INK, leading=16, leftIndent=10)
    contactName = ParagraphStyle("cn", fontName="Helvetica-Bold", fontSize=13, textColor=INK)
    contactLine = ParagraphStyle("cl", fontName="Helvetica", fontSize=10.5, textColor=INK, leading=15)
    qrCaption = ParagraphStyle("qc", fontName="Helvetica", fontSize=8.5, textColor=MUTE, alignment=1)

    doc = SimpleDocTemplate(str(out_path), pagesize=A5, leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            title="NetCare - Business & Service Management", author=NAME)
    story = [
        Paragraph("NetCare", title),
        Paragraph("Business &amp; service management for computer, CCTV and IT shops", sub),
        Spacer(1, 3 * mm), HRFlowable(width="100%", thickness=1, color=LINE), Spacer(1, 2 * mm),
        Paragraph("Run billing, stock and service jobs from one simple app — built for shops like yours.",
                  pitch),
    ]
    for f in FEATURES:
        story.append(Paragraph(f"&bull;&nbsp;&nbsp;{f}", feat))

    qr_path = ROOT / "scripts" / "_flyer_qr.png"
    qr_path.write_bytes(qr_png_bytes(f"https://wa.me/{WHATSAPP_NUMBER}"))
    qr_img = Image(str(qr_path), width=28 * mm, height=28 * mm)

    contact = [Paragraph(NAME, contactName), Paragraph(f"Phone: {PHONE}", contactLine),
               Paragraph(f"Email: {EMAIL}", contactLine), Paragraph(CITY, contactLine)]
    qr_block = [qr_img, Spacer(1, 1 * mm), Paragraph("Scan to WhatsApp me", qrCaption)]
    row = Table([[contact, qr_block]], colWidths=[76 * mm, 32 * mm])
    row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (1, 0), (1, 0), "CENTER")]))
    story += [Spacer(1, 6 * mm), HRFlowable(width="100%", thickness=1, color=LINE), Spacer(1, 4 * mm), row]
    doc.build(story)
    qr_path.unlink(missing_ok=True)


if __name__ == "__main__":
    out = ROOT / "release" / "NetCare_Flyer.pdf"
    out.parent.mkdir(exist_ok=True)
    build(out)
    print(f"Wrote {out} ({out.stat().st_size / 1024:.0f} KB)")
