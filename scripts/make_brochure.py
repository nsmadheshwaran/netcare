"""Builds a customer-facing feature brochure PDF for NetCare Business Suite.

Plain-language, no engineering jargon (customers don't care about "RBAC" or "row locking").
Run from the repository root:  python scripts/make_brochure.py
Needs reportlab (already a backend dependency).
"""
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, HRFlowable

ROOT = Path(__file__).resolve().parent.parent
INK = colors.HexColor("#0f172a")
BRAND = colors.HexColor("#4f46e5")
MUTE = colors.HexColor("#64748b")
LINE = colors.HexColor("#e2e8f0")

VERSION = re.search(r'version="([\d.]+)"', (ROOT / "backend/app/main.py").read_text(encoding="utf-8")).group(1)

SECTIONS = [
    ("Customers and sales", [
        "Keep every customer's details, GST number and full order history in one place.",
        "Create quotations and turn an accepted one into an invoice in a click.",
        "GST-correct tax invoices (CGST/SGST/IGST worked out automatically), a compact thermal receipt "
        "for the counter, and credit notes for returns — all as ready-to-print PDFs.",
        "Invoices get a proper financial-year number automatically (e.g. INV/2026-27/00001), with no gaps "
        "and no duplicates.",
        "Email an invoice to the customer straight from the app.",
    ]),
    ("Stock and purchasing", [
        "Track stock across more than one shop or warehouse, with a full movement history for every item.",
        "Record purchase orders, goods received and supplier bills, and returns to suppliers.",
        "The app stops you selling what isn't in stock, and works out each product's average cost "
        "automatically as stock comes in.",
    ]),
    ("Payments and accounts", [
        "Record cash, UPI, bank transfer, card and cheque payments, applied automatically against open bills.",
        "Track advance payments received before an invoice exists.",
        "Reports for profit and loss, cash flow, sales and purchase registers, who owes you and who you owe, "
        "stock value, and a draft GST summary for your accountant — exportable to PDF, Excel or CSV.",
    ]),
    ("Service jobs and repairs", [
        "Log repair, installation, maintenance and complaint jobs, and assign them to a technician.",
        "Capture the customer's approval of a repair estimate right on a tablet, with their signature — no "
        "paper form needed.",
        "Parts used on a job come out of stock automatically.",
        "Print a job sheet when equipment comes in and a completion report when the job is done.",
        "Keep a record of each customer's equipment (recorders, cameras, routers, PCs) with its serial "
        "number and warranty, and set up annual maintenance visits that create the job automatically when due.",
    ]),
    ("Staff and tasks", [
        "A staff directory with daily attendance and leave requests and approvals.",
        "Assign tasks to technicians with due dates, linked to the relevant job.",
    ]),
    ("Monitoring (for IT and CCTV service businesses)", [
        "A small, free monitoring agent installed at a customer's site reports whether their routers, "
        "servers, recorders and other devices are up or down — and can be switched off entirely for "
        "customers who don't need it.",
        "See the security status of Windows PCs you manage — protection switched on or off, how current "
        "their virus definitions are, and any threats found.",
        "Keep a record of CCTV recorders, their channels and how long footage is kept.",
    ]),
    ("Staying informed and secure", [
        "A notification bell for what needs your attention, with optional email, SMS and WhatsApp alerts.",
        "Every important action is logged, so you can see who did what and when.",
        "Give each staff member their own login with only the access they need — an owner sees everything, "
        "a technician sees their own jobs, and so on.",
    ]),
]

OPERATIONAL = [
    ("Runs on your own computer", "Your data stays on your PC or server. No monthly cloud fee, no "
     "internet dependency to keep working, and nobody else can see your business data."),
    ("One-time purchase", "No subscription to use the software. You buy it once; it keeps working."),
    ("Simple to install", "A guided, double-click installer sets it up, including daily automatic backups."),
    ("Switch off what you don't need", "Every business sees a different set of features — a shop that "
     "doesn't do CCTV work can hide that section entirely, in two clicks."),
]


def styles():
    return {
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=22, textColor=INK, leading=26),
        "subtitle": ParagraphStyle("subtitle", fontName="Helvetica", fontSize=11.5, textColor=MUTE, leading=15),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13, textColor=BRAND, spaceBefore=12,
                             spaceAfter=4),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.7, textColor=INK, leading=13.5,
                               leftIndent=10, bulletIndent=0, spaceAfter=3),
        "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8.5, textColor=MUTE, leading=12),
        "opTitle": ParagraphStyle("opTitle", fontName="Helvetica-Bold", fontSize=10, textColor=INK, leading=13),
        "opBody": ParagraphStyle("opBody", fontName="Helvetica", fontSize=9, textColor=MUTE, leading=12.5),
        "foot": ParagraphStyle("foot", fontName="Helvetica", fontSize=8, textColor=MUTE),
    }


def bullets(items, st):
    return [Paragraph(f'<bullet color="#4f46e5">&bull;</bullet>{t}', st["body"]) for t in items]


def build(out_path: Path):
    st = styles()
    doc = SimpleDocTemplate(str(out_path), pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            title="NetCare Business Suite - Features", author="NetCare")
    story = [
        Paragraph("NetCare Business Suite", st["title"]),
        Paragraph("A complete business management system for IT, computer and CCTV service businesses "
                  f"&mdash; sales, stock, service jobs, staff and monitoring in one place.  (v{VERSION})",
                  st["subtitle"]),
        Spacer(1, 3 * mm), HRFlowable(width="100%", thickness=1, color=LINE), Spacer(1, 2 * mm),
    ]
    for title, items in SECTIONS:
        story += [Paragraph(title, st["h2"]), *bullets(items, st)]

    story += [Spacer(1, 4 * mm), HRFlowable(width="100%", thickness=1, color=LINE), Spacer(1, 3 * mm),
              Paragraph("Why businesses choose it", st["h2"])]
    rows = [[Paragraph(f"<b>{t}</b>", st["opTitle"]), Paragraph(d, st["opBody"])] for t, d in OPERATIONAL]
    table = Table(rows, colWidths=[42 * mm, 132 * mm])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                               ("TOPPADDING", (0, 0), (-1, -1), 2)]))
    story.append(table)

    story += [Spacer(1, 6 * mm), HRFlowable(width="100%", thickness=1, color=LINE), Spacer(1, 3 * mm),
              Paragraph("NetCare is a business management tool, not accounting or GST-filing software &mdash; "
                        "its GST figures are a draft for your accountant to confirm. It does not file GST "
                        "e-invoices or e-way bills.", st["foot"])]
    doc.build(story)


if __name__ == "__main__":
    out = ROOT / "release" / "NetCare_Features.pdf"
    out.parent.mkdir(exist_ok=True)
    build(out)
    print(f"Wrote {out} ({out.stat().st_size / 1024:.0f} KB)")
