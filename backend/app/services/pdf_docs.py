"""Printable documents: A4 invoice/quotation, 80 mm thermal receipt, payment receipt."""
import io
from decimal import ROUND_HALF_UP, Decimal
from xml.sax.saxutils import escape as esc

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .export import inr

ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
        "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two(n: int) -> str:
    return ONES[n] if n < 20 else TENS[n // 10] + ("-" + ONES[n % 10] if n % 10 else "")


def _three(n: int) -> str:
    h, r = divmod(n, 100)
    return " ".join(p for p in ((ONES[h] + " Hundred") if h else "", _two(r) if r else "") if p)


def words_indian(n: int) -> str:
    """Integer to words with Indian grouping: 1,23,45,678 -> One Crore Twenty-Three Lakh ..."""
    if n == 0:
        return "Zero"
    parts = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    if crore:
        parts.append(words_indian(crore) + " Crore")  # recursion handles > 99 crore
    if lakh:
        parts.append(_two(lakh) + " Lakh")
    if thousand:
        parts.append(_two(thousand) + " Thousand")
    if n:
        parts.append(_three(n))
    return " ".join(parts)


def amount_in_words(v) -> str:
    d = Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rupees, paise = int(d), int((d - int(d)) * 100)
    s = f"Rupees {words_indian(rupees)}"
    if paise:
        s += f" and {_two(paise)} Paise"
    return s + " Only"


def _styles():
    ss = getSampleStyleSheet()
    base = ParagraphStyle("b", parent=ss["BodyText"], fontSize=8.5, leading=10.5)
    return {
        "base": base,
        "small": ParagraphStyle("s", parent=base, fontSize=7.5, leading=9),
        "right": ParagraphStyle("r", parent=base, alignment=2),
        "bold": ParagraphStyle("bb", parent=base, fontName="Helvetica-Bold"),
        "org": ParagraphStyle("o", parent=base, fontName="Helvetica-Bold", fontSize=14, leading=17),
        "title": ParagraphStyle("t", parent=base, fontName="Helvetica-Bold", fontSize=13, leading=16, alignment=2),
    }


def _p(text, style) -> Paragraph:
    return Paragraph(esc(str(text or "")).replace("\n", "<br/>"), style)


def _logo(org, max_w=35 * mm, max_h=18 * mm):
    if not org.logo:
        return None
    img = ImageReader(io.BytesIO(org.logo))
    w, h = img.getSize()
    scale = min(max_w / w, max_h / h)
    return Image(io.BytesIO(org.logo), width=w * scale, height=h * scale)


def _org_block(org, st):
    contact = " | ".join(x for x in (org.phone, org.email) if x)
    out = [Paragraph(esc(org.name), st["org"])]
    if org.legal_name and org.legal_name != org.name:
        out.append(_p(org.legal_name, st["base"]))
    if org.address:
        out.append(_p(org.address, st["base"]))
    if contact:
        out.append(_p(contact, st["base"]))
    if org.gstin:
        out.append(_p(f"GSTIN: {org.gstin}" + (f"   State code: {org.state_code}" if org.state_code else ""), st["bold"]))
    return out


def sales_document_pdf(org, doc, customer, *, kind: str) -> bytes:
    """kind: 'invoice' or 'quotation'. Drafts and cancelled invoices are stamped clearly."""
    st = _styles()
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=10 * mm,
                            bottomMargin=12 * mm, title=f"{kind.title()} {doc.number or ''}", author=org.name)
    if kind == "quotation":
        title, number, dt_label, dt = "QUOTATION", doc.number, "Date", doc.quote_date
        extra = [("Valid until", doc.valid_until)]
    else:
        title = "TAX INVOICE" if org.gstin else "INVOICE"
        if doc.status == "draft":
            title = "DRAFT INVOICE"
        number, dt_label, dt = doc.number or "(not issued)", "Invoice date", doc.invoice_date
        extra = [("Due date", doc.due_date)]
    meta = [(f"{'Quotation' if kind == 'quotation' else 'Invoice'} no.", number), (dt_label, dt.strftime("%d-%m-%Y"))]
    meta += [(k, v.strftime("%d-%m-%Y")) for k, v in extra if v]
    meta.append(("Place of supply", doc.place_of_supply or "Not specified"))
    if doc.prices_include_tax:
        meta.append(("Prices", "Inclusive of GST"))

    logo = _logo(org)
    left = ([logo] if logo else []) + _org_block(org, st)
    right = [Paragraph(title, st["title"])] + [
        Paragraph(f"{esc(k)}: <b>{esc(str(v))}</b>", st["right"]) for k, v in meta]
    story = [Table([[left, right]], colWidths=[110 * mm, 76 * mm],
                   style=[("VALIGN", (0, 0), (-1, -1), "TOP")])]
    if kind == "invoice" and doc.status == "cancelled":
        story.append(Paragraph(f"<font color='#b91c1c' size='14'><b>CANCELLED</b></font> "
                               f"{esc(doc.cancel_reason or '')}", st["base"]))
    if kind == "invoice" and doc.status == "draft":
        story.append(Paragraph("<font color='#b91c1c'><b>Draft. Not a valid tax invoice until issued.</b></font>",
                               st["base"]))
    story.append(Spacer(1, 4 * mm))

    bill_to = [Paragraph("<b>Bill to</b>", st["small"]), _p(customer.business_name or customer.name, st["bold"])]
    if customer.business_name and customer.name != customer.business_name:
        bill_to.append(_p(customer.name, st["base"]))
    for x in (customer.billing_address, ", ".join(p for p in (customer.city, customer.state, customer.pincode) if p),
              customer.phone):
        if x:
            bill_to.append(_p(x, st["base"]))
    if customer.gstin:
        bill_to.append(_p(f"GSTIN: {customer.gstin}", st["bold"]))
    ship = [Paragraph("<b>Ship / install at</b>", st["small"]), _p(customer.shipping_address or "Same as billing",
                                                                   st["base"])]
    story.append(Table([[bill_to, ship]], colWidths=[93 * mm, 93 * mm],
                       style=[("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#94a3b8")),
                              ("LINEAFTER", (0, 0), (0, 0), 0.4, colors.HexColor("#94a3b8")),
                              ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(Spacer(1, 4 * mm))

    inter = doc.is_interstate
    head = ["#", "Item", "HSN/SAC", "Qty", "Rate", "Disc.", "Taxable", "GST%"] + \
           (["IGST"] if inter else ["CGST", "SGST"]) + ["Amount"]
    rows = [[Paragraph(f"<b>{h}</b>", st["small"]) for h in head]]
    for n, li in enumerate(doc.lines, start=1):
        tax_cells = [inr(li.igst)] if inter else [inr(li.cgst), inr(li.sgst)]
        rows.append([str(n), _p(li.description, st["small"]), li.hsn_sac or "",
                     f"{Decimal(li.quantity).normalize():f}", inr(li.unit_price),
                     inr(li.discount_amount) if li.discount_amount else "", inr(li.taxable_value),
                     f"{Decimal(li.tax_rate).normalize():f}", *tax_cells, inr(li.line_total)])
    widths = [7, 46, 19, 11, 18, 15, 20, 12] + ([20] if inter else [17, 17]) + [20]
    scale = 186 / sum(widths)
    t = Table(rows, colWidths=[w * scale * mm for w in widths], repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e0e7ff")),
                           ("FONTSIZE", (0, 1), (-1, -1), 7.5), ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [t, Spacer(1, 3 * mm)]

    tot = [("Subtotal" + (" (incl. GST)" if doc.prices_include_tax else ""), doc.subtotal)]
    if doc.discount_total:
        tot.append(("Discount", -Decimal(doc.discount_total)))
    tot.append(("Taxable value", doc.taxable_total))
    tot += [("IGST", doc.igst_total)] if inter else [("CGST", doc.cgst_total), ("SGST", doc.sgst_total)]
    if doc.round_off:
        tot.append(("Round off", doc.round_off))
    tot.append(("Total", doc.total))
    if kind == "invoice" and doc.status not in ("draft", "cancelled"):
        tot.append(("Paid", doc.amount_paid))
        if doc.credited_amount:
            tot.append(("Credited (returns)", doc.credited_amount))
        tot.append(("Balance due", max(Decimal(doc.total) - doc.amount_paid - doc.credited_amount, Decimal("0"))))
    tot_rows = [[Paragraph(f"<b>{esc(k)}</b>" if k in ("Total", "Balance due") else esc(k), st["base"]),
                 Paragraph(f"<b>{inr(v)}</b>" if k in ("Total", "Balance due") else inr(v), st["right"])]
                for k, v in tot]
    totals = Table(tot_rows, colWidths=[38 * mm, 32 * mm],
                   style=[("LINEABOVE", (0, len(tot_rows) - 1), (-1, len(tot_rows) - 1), 0.4, colors.black)])
    words = [Paragraph("<b>Amount in words</b>", st["small"]), _p(amount_in_words(doc.total), st["base"])]
    if org.payment_instructions and kind == "invoice":
        words += [Spacer(1, 2 * mm), Paragraph("<b>Payment instructions</b>", st["small"]),
                  _p(org.payment_instructions, st["base"])]
    story.append(Table([[words, totals]], colWidths=[116 * mm, 70 * mm], style=[("VALIGN", (0, 0), (-1, -1), "TOP")]))

    if doc.notes:
        story += [Spacer(1, 3 * mm), Paragraph("<b>Notes</b>", st["small"]), _p(doc.notes, st["base"])]
    terms = doc.terms or org.invoice_terms
    if terms:
        story += [Spacer(1, 3 * mm), Paragraph("<b>Terms and conditions</b>", st["small"]), _p(terms, st["small"])]
    story += [Spacer(1, 10 * mm),
              Table([["", Paragraph(f"For <b>{esc(org.name)}</b><br/><br/><br/>Authorised signatory", st["right"])]],
                    colWidths=[116 * mm, 70 * mm]),
              Spacer(1, 4 * mm),
              Paragraph("This is a computer-generated document.", st["small"])]
    pdf.build(story)
    return buf.getvalue()


def thermal_receipt_pdf(org, inv, customer) -> bytes:
    """80 mm roll receipt. Height grows with the number of lines."""
    width = 80 * mm
    lines = inv.lines
    discounted = sum(1 for li in lines if li.discount_amount)
    height = (78 + 9 * len(lines) + 4.6 * discounted + (4 if org.gstin else 0)) * mm
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    c.setTitle(f"Receipt {inv.number or ''}")
    y = height - 8 * mm
    x0, x1 = 4 * mm, width - 4 * mm

    def text(s, size=8, bold=False, align="l"):
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        s = str(s)
        if align == "c":
            c.drawCentredString(width / 2, y, s)
        elif align == "r":
            c.drawRightString(x1, y, s)
        else:
            c.drawString(x0, y, s)
        y -= size * 0.45 * mm + 2.2 * mm

    def rule():
        nonlocal y
        c.setDash(1, 2)
        c.line(x0, y + 1.5 * mm, x1, y + 1.5 * mm)
        c.setDash()
        y -= 1.5 * mm

    text(org.name[:32], 11, True, "c")
    if org.address:
        text(org.address.replace("\n", ", ")[:46], 7, align="c")
    if org.phone:
        text(f"Ph: {org.phone}", 7, align="c")
    if org.gstin:
        text(f"GSTIN: {org.gstin}", 7, True, "c")
    rule()
    text(("TAX INVOICE" if org.gstin else "INVOICE") if inv.status != "draft" else "DRAFT - NOT VALID", 9, True, "c")
    text(f"No: {inv.number or '-'}   Date: {inv.invoice_date.strftime('%d-%m-%Y')}", 7.5)
    text(f"To: {(customer.business_name or customer.name)[:38]}", 7.5)
    rule()
    for li in lines:
        text(li.description[:40], 7.5)
        qty = f"{Decimal(li.quantity).normalize():f}"
        c.setFont("Helvetica", 7.5)
        c.drawString(x0 + 3 * mm, y, f"{qty} x {inr(li.unit_price)}  GST {Decimal(li.tax_rate).normalize():f}%")
        c.drawRightString(x1, y, inr(li.line_total))
        y -= 4.6 * mm
        if li.discount_amount:
            c.drawString(x0 + 3 * mm, y, f"incl. discount -{inr(li.discount_amount)}")
            y -= 4.6 * mm
    rule()
    for label, val in (("Taxable", inv.taxable_total),
                       *((("IGST", inv.igst_total),) if inv.is_interstate else
                         (("CGST", inv.cgst_total), ("SGST", inv.sgst_total))),
                       *((("Round off", inv.round_off),) if inv.round_off else ())):
        c.setFont("Helvetica", 8)
        c.drawString(x0, y, label)
        c.drawRightString(x1, y, inr(val))
        y -= 4.2 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x0, y, "TOTAL")
    c.drawRightString(x1, y, f"Rs {inr(inv.total)}")
    y -= 5 * mm
    if inv.status not in ("draft", "cancelled"):
        c.setFont("Helvetica", 8)
        c.drawString(x0, y, "Paid")
        c.drawRightString(x1, y, inr(inv.amount_paid))
        y -= 4.2 * mm
    rule()
    text("Thank you!", 9, True, "c")
    c.showPage()
    c.save()
    return buf.getvalue()


def payment_receipt_pdf(org, payment, party_name: str, allocations: list[tuple[str, Decimal]],
                        account_name: str | None) -> bytes:
    st = _styles()
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=A5, leftMargin=10 * mm, rightMargin=10 * mm, topMargin=10 * mm,
                            bottomMargin=10 * mm, title=f"Receipt {payment.number}", author=org.name)
    incoming = payment.direction == "in"
    title = "PAYMENT RECEIPT" if incoming else "PAYMENT VOUCHER"
    logo = _logo(org, 28 * mm, 14 * mm)
    story = [Table([[([logo] if logo else []) + _org_block(org, st), Paragraph(title, st["title"])]],
                   colWidths=[80 * mm, 48 * mm], style=[("VALIGN", (0, 0), (-1, -1), "TOP")])]
    if payment.voided_at:
        story.append(Paragraph(f"<font color='#b91c1c' size='13'><b>VOID</b></font> {esc(payment.void_reason or '')}",
                               st["base"]))
    rows = [("Number", payment.number), ("Date", payment.payment_date.strftime("%d-%m-%Y")),
            ("Received from" if incoming else "Paid to", party_name),
            ("Amount", f"Rs {inr(payment.amount)}"), ("In words", amount_in_words(payment.amount)),
            ("Method", payment.method.replace("_", " ").title())]
    if payment.reference:
        rows.append(("Reference", payment.reference))
    if account_name:
        rows.append(("Account", account_name))
    story += [Spacer(1, 5 * mm), Table([[_p(k, st["bold"]), _p(v, st["base"])] for k, v in rows],
                                       colWidths=[32 * mm, 96 * mm],
                                       style=[("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0"))])]
    if allocations:
        story += [Spacer(1, 4 * mm), Paragraph("<b>Applied to</b>", st["small"]),
                  Table([[_p(n, st["base"]), Paragraph(inr(a), st["right"])] for n, a in allocations],
                        colWidths=[96 * mm, 32 * mm])]
    unalloc = Decimal(payment.amount) - sum((a for _, a in allocations), Decimal("0"))
    if unalloc > 0 and not payment.voided_at:
        story.append(_p(f"Advance kept on account: Rs {inr(unalloc)}", st["base"]))
    story += [Spacer(1, 12 * mm), Paragraph(f"For <b>{esc(org.name)}</b><br/><br/>Authorised signatory", st["right"]),
              Spacer(1, 3 * mm), Paragraph("This is a computer-generated document.", st["small"])]
    pdf.build(story)
    return buf.getvalue()
