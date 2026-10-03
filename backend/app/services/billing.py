"""Line/total calculations and document numbering.

Calculation order per line (all Decimal, ROUND_HALF_UP to paise at each stored amount):
  gross        = qty * unit_price
  line_disc    = gross * line_discount_pct / 100
  doc_disc     = share of document-level discount, allocated by net value (last line takes remainder)
  taxable      = gross - line_disc - doc_disc
  tax          = taxable * rate / 100, split CGST/SGST (half each, SGST takes the odd paisa) or IGST
Prices are tax-exclusive. Tax-inclusive pricing and versioned tax rules are Phase 3.
Tax figures are computed for record-keeping and are NOT a GST compliance determination.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models_trade import DocumentSequence

PAISA = Decimal("0.01")
ZERO = Decimal("0")


def money(v) -> Decimal:
    return Decimal(v).quantize(PAISA, rounding=ROUND_HALF_UP)


@dataclass
class LineInput:
    description: str
    quantity: Decimal
    unit_price: Decimal
    tax_rate: Decimal = ZERO
    line_discount_pct: Decimal = ZERO
    product_id: int | None = None
    hsn_sac: str | None = None


@dataclass
class LineResult:
    inp: LineInput
    gross: Decimal
    discount_amount: Decimal
    taxable_value: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    line_total: Decimal


@dataclass
class Totals:
    lines: list[LineResult] = field(default_factory=list)
    subtotal: Decimal = ZERO
    discount_total: Decimal = ZERO
    taxable_total: Decimal = ZERO
    cgst_total: Decimal = ZERO
    sgst_total: Decimal = ZERO
    igst_total: Decimal = ZERO
    round_off: Decimal = ZERO
    total: Decimal = ZERO

    @property
    def tax_total(self) -> Decimal:
        return self.cgst_total + self.sgst_total + self.igst_total


def compute(lines: list[LineInput], *, interstate: bool, document_discount: Decimal = ZERO,
            round_to_rupee: bool = False, prices_include_tax: bool = False) -> Totals:
    """With prices_include_tax, unit prices and discounts are GST-inclusive: the discounted inclusive amount
    is the line total, taxable = amount * 100 / (100 + rate), and tax is the exact remainder.
    In that mode subtotal and discount_total are inclusive figures too."""
    if not lines:
        raise HTTPException(422, "At least one line is required")
    gross = [money(li.quantity * li.unit_price) for li in lines]
    line_disc = [money(g * li.line_discount_pct / 100) for g, li in zip(gross, lines)]
    net = [g - d for g, d in zip(gross, line_disc)]
    net_sum = sum(net, ZERO)
    document_discount = money(document_discount)
    if document_discount < 0 or document_discount > net_sum:
        raise HTTPException(422, "Document discount must be between 0 and the discounted subtotal")

    shares, allocated = [], ZERO
    for i, n in enumerate(net):
        if i == len(net) - 1:
            share = document_discount - allocated
        else:
            share = money(document_discount * n / net_sum) if net_sum else ZERO
            allocated += share
        shares.append(share)

    t = Totals()
    for li, g, ld, n, s in zip(lines, gross, line_disc, net, shares):
        if prices_include_tax:
            inclusive = n - s
            taxable = money(inclusive * 100 / (100 + li.tax_rate))
            tax = inclusive - taxable
        else:
            taxable = n - s
            tax = money(taxable * li.tax_rate / 100)
        if interstate:
            cgst = sgst = ZERO
            igst = tax
        else:
            # Avoid half-paisa drift: SGST is whatever remains so cgst + sgst == tax exactly.
            cgst = (tax / 2).quantize(PAISA, rounding="ROUND_DOWN")
            sgst = tax - cgst
            igst = ZERO
        r = LineResult(li, g, ld + s, taxable, cgst, sgst, igst, taxable + tax)
        t.lines.append(r)
        t.subtotal += g
        t.discount_total += ld + s
        t.taxable_total += taxable
        t.cgst_total += cgst
        t.sgst_total += sgst
        t.igst_total += igst
    exact = t.taxable_total + t.tax_total
    t.total = exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP) if round_to_rupee else exact
    t.round_off = t.total - exact
    return t


def is_interstate(org_state: str | None, place_of_supply: str | None) -> bool:
    """Inter-state only when both state codes are known and differ. Unknown -> intra-state (flagged in UI)."""
    return bool(org_state and place_of_supply and org_state != place_of_supply)


def fiscal_year(d: date) -> str:
    """Indian financial year label, e.g. 2026-10-02 -> '2026-27'."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{str(start + 1)[2:]}"


DEFAULT_PREFIX = {"sales_invoice": "INV", "quotation": "QT", "purchase_order": "PO", "goods_receipt": "GRN",
                  "purchase_invoice": "PB", "credit_note": "CN", "purchase_return": "PR",
                  "receipt": "RCPT", "supplier_payment": "PAY", "expense": "EXP", "income": "INC",
                  "transfer": "TRF", "service_ticket": "SRV"}


def next_number(db: Session, org_id: int, doc_type: str, on: date) -> str:
    """Allocate the next gap-free number. Row-locked so concurrent requests can't share a number;
    the unique (organization_id, number) constraints on documents are the backstop."""
    fy = fiscal_year(on)
    q = select(DocumentSequence).where(DocumentSequence.organization_id == org_id,
                                       DocumentSequence.doc_type == doc_type,
                                       DocumentSequence.fiscal_year == fy).with_for_update()
    seq = db.scalar(q)
    if seq is None:
        prefix = _configured_prefix(db, org_id, doc_type)
        try:
            # Savepoint: if a concurrent request created the row first, fall back to locking theirs.
            with db.begin_nested():
                db.add(DocumentSequence(organization_id=org_id, doc_type=doc_type, fiscal_year=fy,
                                        prefix=prefix, next_number=1))
        except IntegrityError:
            pass
        seq = db.scalar(q)
    n = seq.next_number
    seq.next_number = n + 1
    db.flush()
    return f"{seq.prefix}/{fy}/{n:05d}"


def _configured_prefix(db: Session, org_id: int, doc_type: str) -> str:
    from ..models import Organization
    org = db.get(Organization, org_id)
    custom = (org.numbering_prefixes or {}) if org else {}
    return custom.get(doc_type) or DEFAULT_PREFIX[doc_type]
