from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select

from ..deps import OrgContext, require
from ..models import Customer, Product, utcnow
from ..models_trade import (
    CreditNote, CreditNoteLine, Payment, Quotation, QuotationLine, SalesInvoice, SalesInvoiceLine,
)
from ..schemas import Page
from ..schemas_trade import (
    CancelIn, CreditNoteIn, CreditNoteOut, InvoiceIn, InvoiceOut, LineIn, QuotationIn, QuotationOut,
    QuotationStatusIn,
)
from ..services import billing, inventory
from ..services.timeutil import today
from ..services.trade import (
    active_customer, active_location, apply_totals, balance, build_lines, display_status, get_owned,
    interstate_for, refresh_sales_status,
)

router = APIRouter(tags=["sales"])
ZERO = Decimal("0")


def _inclusive(ctx: OrgContext, body) -> bool:
    return ctx.org.prices_include_tax_default if body.prices_include_tax is None else body.prices_include_tax


def _totals_for(ctx: OrgContext, customer: Customer, body):
    pos = body.place_of_supply or customer.state_code
    inter = interstate_for(ctx, pos)
    doc_date = getattr(body, "invoice_date", None) or getattr(body, "quote_date", None)
    totals = billing.compute(build_lines(ctx, body.lines, on=doc_date), interstate=inter,
                             document_discount=body.document_discount,
                             round_to_rupee=ctx.org.round_invoices_to_rupee, prices_include_tax=_inclusive(ctx, body))
    return totals, inter, pos


# ---------------- quotations ----------------
def _q_out(ctx: OrgContext, q: Quotation) -> QuotationOut:
    o = QuotationOut.model_validate(q)
    o.customer_name = ctx.db.get(Customer, q.customer_id).name
    o.converted_invoice_id = ctx.db.scalar(select(SalesInvoice.id).where(SalesInvoice.quotation_id == q.id)
                                           .where(SalesInvoice.status != "cancelled"))
    if q.status in ("draft", "sent") and q.valid_until and q.valid_until < today():
        o.status = "expired"
    return o


def _fill_quote(ctx: OrgContext, q: Quotation, body: QuotationIn):
    customer = active_customer(ctx, body.customer_id)
    totals, inter, pos = _totals_for(ctx, customer, body)
    for f in ("customer_id", "quote_date", "valid_until", "document_discount", "notes", "terms"):
        setattr(q, f, getattr(body, f))
    q.prices_include_tax = _inclusive(ctx, body)
    apply_totals(q, totals, QuotationLine, interstate=inter, place_of_supply=pos)


@router.get("/quotations", response_model=Page[QuotationOut])
def list_quotes(ctx: OrgContext = Depends(require("sales.view")), status: str | None = None,
                customer_id: int | None = None, q: str | None = None,
                page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=200)):
    base = select(Quotation).join(Customer).where(Quotation.organization_id == ctx.org_id)
    if status:
        base = base.where(Quotation.status == status)
    if customer_id:
        base = base.where(Quotation.customer_id == customer_id)
    if q:
        base = base.where(or_(Quotation.number.ilike(f"%{q}%"), Customer.name.ilike(f"%{q}%")))
    total = ctx.db.scalar(select(func.count()).select_from(base.subquery()))
    rows = ctx.db.scalars(base.order_by(Quotation.id.desc()).offset((page - 1) * size).limit(size)).all()
    return Page(items=[_q_out(ctx, x) for x in rows], total=total, page=page, size=size)


@router.post("/quotations", response_model=QuotationOut, status_code=201)
def create_quote(body: QuotationIn, ctx: OrgContext = Depends(require("sales.edit"))):
    q = Quotation(organization_id=ctx.org_id, status="draft", created_by=ctx.user.id,
                  number=billing.next_number(ctx.db, ctx.org_id, "quotation", body.quote_date))
    _fill_quote(ctx, q, body)
    ctx.db.add(q)
    ctx.db.flush()
    ctx.audit("create", "quotation", q.id, {"number": q.number, "total": str(q.total)})
    ctx.db.commit()
    return _q_out(ctx, q)


@router.get("/quotations/{qid}", response_model=QuotationOut)
def get_quote(qid: int, ctx: OrgContext = Depends(require("sales.view"))):
    return _q_out(ctx, get_owned(ctx, Quotation, qid, "Quotation"))


@router.put("/quotations/{qid}", response_model=QuotationOut)
def update_quote(qid: int, body: QuotationIn, ctx: OrgContext = Depends(require("sales.edit"))):
    q = get_owned(ctx, Quotation, qid, "Quotation", lock=True)
    if q.status not in ("draft", "sent"):
        raise HTTPException(409, f"A {q.status} quotation cannot be edited")
    _fill_quote(ctx, q, body)
    ctx.audit("update", "quotation", q.id, {"total": str(q.total)})
    ctx.db.commit()
    return _q_out(ctx, q)


@router.post("/quotations/{qid}/status", response_model=QuotationOut)
def set_quote_status(qid: int, body: QuotationStatusIn, ctx: OrgContext = Depends(require("sales.edit"))):
    q = get_owned(ctx, Quotation, qid, "Quotation", lock=True)
    allowed = {"sent": {"draft"}, "accepted": {"draft", "sent"}, "rejected": {"draft", "sent", "accepted"}}
    if q.status not in allowed[body.status]:
        raise HTTPException(409, f"Cannot mark a {q.status} quotation as {body.status}")
    q.status = body.status
    ctx.audit(body.status, "quotation", q.id)
    ctx.db.commit()
    return _q_out(ctx, q)


@router.post("/quotations/{qid}/convert", response_model=InvoiceOut, status_code=201)
def convert_quote(qid: int, location_id: int, ctx: OrgContext = Depends(require("sales.edit"))):
    """Create a draft invoice from an accepted (or sent) quotation, copying its lines and prices."""
    q = get_owned(ctx, Quotation, qid, "Quotation", lock=True)
    if q.status not in ("accepted", "sent", "draft"):
        raise HTTPException(409, f"A {q.status} quotation cannot be converted")
    lines = [LineIn(product_id=li.product_id, description=li.description, quantity=li.quantity,
                    unit_price=li.unit_price, tax_rate=li.tax_rate, line_discount_pct=li.line_discount_pct)
             for li in q.lines]
    body = InvoiceIn(customer_id=q.customer_id, location_id=location_id, invoice_date=today(),
                     place_of_supply=q.place_of_supply, document_discount=q.document_discount, notes=q.notes,
                     prices_include_tax=q.prices_include_tax,
                     terms=q.terms, lines=lines, idempotency_key=f"quotation:{q.id}")
    existing = ctx.db.scalar(select(SalesInvoice).where(SalesInvoice.organization_id == ctx.org_id,
                                                        SalesInvoice.idempotency_key == body.idempotency_key))
    if existing:
        return _inv_out(ctx, existing)
    inv = _new_invoice(ctx, body)
    inv.quotation_id = q.id
    q.status = "converted"
    ctx.audit("convert", "quotation", q.id, {"invoice_id": inv.id})
    ctx.db.commit()
    return _inv_out(ctx, inv)


# ---------------- invoices ----------------
def _inv_out(ctx: OrgContext, inv: SalesInvoice) -> InvoiceOut:
    o = InvoiceOut.model_validate(inv)
    o.customer_name = ctx.db.get(Customer, inv.customer_id).name
    o.balance_due = max(balance(inv), ZERO) if inv.status not in ("draft", "cancelled") else ZERO
    o.display_status = display_status(inv)
    return o


def _fill_invoice(ctx: OrgContext, inv: SalesInvoice, body: InvoiceIn):
    customer = active_customer(ctx, body.customer_id)
    active_location(ctx, body.location_id)
    totals, inter, pos = _totals_for(ctx, customer, body)
    for f in ("customer_id", "location_id", "invoice_date", "due_date", "document_discount", "notes", "terms"):
        setattr(inv, f, getattr(body, f))
    inv.prices_include_tax = _inclusive(ctx, body)
    inv.terms = inv.terms or ctx.org.invoice_terms
    apply_totals(inv, totals, SalesInvoiceLine, interstate=inter, place_of_supply=pos)


def _new_invoice(ctx: OrgContext, body: InvoiceIn) -> SalesInvoice:
    inv = SalesInvoice(organization_id=ctx.org_id, status="draft", created_by=ctx.user.id,
                       idempotency_key=body.idempotency_key)
    _fill_invoice(ctx, inv, body)
    ctx.db.add(inv)
    ctx.db.flush()
    ctx.audit("create", "sales_invoice", inv.id, {"total": str(inv.total), "draft": True})
    return inv


@router.get("/invoices", response_model=Page[InvoiceOut])
def list_invoices(ctx: OrgContext = Depends(require("sales.view")), status: str | None = None,
                  customer_id: int | None = None, q: str | None = None, unpaid: bool = False,
                  overdue: bool = False, date_from: date | None = None, date_to: date | None = None,
                  page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=200)):
    base = select(SalesInvoice).join(Customer).where(SalesInvoice.organization_id == ctx.org_id)
    if status:
        base = base.where(SalesInvoice.status == status)
    if unpaid or overdue:
        base = base.where(SalesInvoice.status.in_(["issued", "partially_paid"]))
    if overdue:
        base = base.where(SalesInvoice.due_date < today())
    if customer_id:
        base = base.where(SalesInvoice.customer_id == customer_id)
    if date_from:
        base = base.where(SalesInvoice.invoice_date >= date_from)
    if date_to:
        base = base.where(SalesInvoice.invoice_date <= date_to)
    if q:
        base = base.where(or_(SalesInvoice.number.ilike(f"%{q}%"), Customer.name.ilike(f"%{q}%")))
    total = ctx.db.scalar(select(func.count()).select_from(base.subquery()))
    rows = ctx.db.scalars(base.order_by(SalesInvoice.id.desc()).offset((page - 1) * size).limit(size)).all()
    return Page(items=[_inv_out(ctx, i) for i in rows], total=total, page=page, size=size)


@router.post("/invoices", response_model=InvoiceOut, status_code=201)
def create_invoice(body: InvoiceIn, ctx: OrgContext = Depends(require("sales.edit"))):
    if body.idempotency_key:
        prior = ctx.db.scalar(select(SalesInvoice).where(SalesInvoice.organization_id == ctx.org_id,
                                                         SalesInvoice.idempotency_key == body.idempotency_key))
        if prior:
            return _inv_out(ctx, prior)
    inv = _new_invoice(ctx, body)
    ctx.db.commit()
    return _inv_out(ctx, inv)


@router.get("/invoices/{inv_id}", response_model=InvoiceOut)
def get_invoice(inv_id: int, ctx: OrgContext = Depends(require("sales.view"))):
    return _inv_out(ctx, get_owned(ctx, SalesInvoice, inv_id, "Invoice"))


@router.put("/invoices/{inv_id}", response_model=InvoiceOut)
def update_invoice(inv_id: int, body: InvoiceIn, ctx: OrgContext = Depends(require("sales.edit"))):
    inv = get_owned(ctx, SalesInvoice, inv_id, "Invoice", lock=True)
    if inv.status != "draft":
        raise HTTPException(409, "Issued invoices cannot be edited; cancel it or issue a credit note")
    _fill_invoice(ctx, inv, body)
    ctx.audit("update", "sales_invoice", inv.id, {"total": str(inv.total)})
    ctx.db.commit()
    return _inv_out(ctx, inv)


@router.post("/invoices/{inv_id}/issue", response_model=InvoiceOut)
def issue_invoice(inv_id: int, ctx: OrgContext = Depends(require("sales.edit"))):
    """Assign the invoice number, deduct stock and create the receivable, all in one transaction."""
    inv = get_owned(ctx, SalesInvoice, inv_id, "Invoice", lock=True)
    if inv.status != "draft":
        raise HTTPException(409, f"Invoice is already {inv.status}")
    customer = active_customer(ctx, inv.customer_id)
    if inv.due_date is None:
        inv.due_date = inv.invoice_date
    inv.number = billing.next_number(ctx.db, ctx.org_id, "sales_invoice", inv.invoice_date)
    for li in inv.lines:
        if li.product_id and not ctx.db.get(Product, li.product_id).is_service:
            mv = inventory.apply_movement(ctx.db, org_id=ctx.org_id, user_id=ctx.user.id,
                                          product_id=li.product_id, location_id=inv.location_id,
                                          movement_type="sale", quantity=li.quantity, reference=inv.number,
                                          idempotency_key=f"inv{inv.id}:l{li.id}:sale")
            li.unit_cost = mv.unit_cost
    inv.status = "issued"
    inv.issued_at = utcnow()
    refresh_sales_status(inv)  # zero-value invoices are immediately paid
    ctx.audit("issue", "sales_invoice", inv.id, {"number": inv.number, "total": str(inv.total),
                                                 "customer": customer.name})
    ctx.db.commit()
    return _inv_out(ctx, inv)


@router.post("/invoices/{inv_id}/cancel", response_model=InvoiceOut)
def cancel_invoice(inv_id: int, body: CancelIn, ctx: OrgContext = Depends(require("sales.edit"))):
    inv = get_owned(ctx, SalesInvoice, inv_id, "Invoice", lock=True)
    if inv.status == "cancelled":
        raise HTTPException(409, "Invoice is already cancelled")
    if inv.amount_paid > 0 or inv.credited_amount > 0:
        raise HTTPException(409, "Invoice has payments or credit notes. Void the payments or issue a credit note.")
    if inv.status != "draft":
        for li in inv.lines:
            if li.product_id and not ctx.db.get(Product, li.product_id).is_service:
                inventory.apply_movement(ctx.db, org_id=ctx.org_id, user_id=ctx.user.id, product_id=li.product_id,
                                         location_id=inv.location_id, movement_type="sale_cancel",
                                         quantity=li.quantity, reference=f"Cancel {inv.number}",
                                         unit_cost=inventory.sale_cost(ctx.db, ctx.org_id,
                                                                       f"inv{inv.id}:l{li.id}:sale"),
                                         idempotency_key=f"inv{inv.id}:l{li.id}:cancel")
    inv.status = "cancelled"
    inv.cancelled_at = utcnow()
    inv.cancel_reason = body.reason
    ctx.audit("cancel", "sales_invoice", inv.id, {"number": inv.number, "reason": body.reason})
    ctx.db.commit()
    return _inv_out(ctx, inv)


# ---------------- credit notes ----------------
@router.post("/invoices/{inv_id}/credit-notes", response_model=CreditNoteOut, status_code=201)
def create_credit_note(inv_id: int, body: CreditNoteIn, ctx: OrgContext = Depends(require("sales.edit"))):
    if body.idempotency_key:
        prior = ctx.db.scalar(select(CreditNote).where(CreditNote.organization_id == ctx.org_id,
                                                       CreditNote.idempotency_key == body.idempotency_key))
        if prior:
            return prior
    inv = get_owned(ctx, SalesInvoice, inv_id, "Invoice", lock=True)
    if inv.status not in ("issued", "partially_paid", "paid"):
        raise HTTPException(409, f"Cannot credit a {inv.status} invoice")
    by_id = {li.id: li for li in inv.lines}
    cn = CreditNote(organization_id=ctx.org_id, sales_invoice_id=inv.id, customer_id=inv.customer_id,
                    note_date=body.note_date, reason=body.reason, restock=body.restock,
                    idempotency_key=body.idempotency_key, created_by=ctx.user.id,
                    taxable_total=ZERO, tax_total=ZERO, total=ZERO,
                    number=billing.next_number(ctx.db, ctx.org_id, "credit_note", body.note_date))
    ctx.db.add(cn)
    ctx.db.flush()
    seen = set()
    for r in body.lines:
        li = by_id.get(r.sales_invoice_line_id)
        if li is None or li.id in seen:
            raise HTTPException(422, f"Line {r.sales_invoice_line_id} is not on this invoice (or repeated)")
        seen.add(li.id)
        qty, returned = Decimal(li.quantity), Decimal(li.returned_quantity)
        if r.quantity > qty - returned:
            raise HTTPException(409, f"{li.description}: only {qty - returned} can still be credited")
        line_tax = Decimal(li.cgst) + Decimal(li.sgst) + Decimal(li.igst)
        if r.quantity == qty - returned:
            # Final portion takes the exact remainder so the line is credited to the paisa.
            prev = ctx.db.execute(select(func.coalesce(func.sum(CreditNoteLine.taxable_value), 0),
                                         func.coalesce(func.sum(CreditNoteLine.tax_amount), 0))
                                  .where(CreditNoteLine.sales_invoice_line_id == li.id)).one()
            taxable = Decimal(li.taxable_value) - Decimal(prev[0])
            tax = line_tax - Decimal(prev[1])
        else:
            taxable = billing.money(Decimal(li.taxable_value) * r.quantity / qty)
            tax = billing.money(line_tax * r.quantity / qty)
        mv_id = None
        if body.restock and li.product_id and not ctx.db.get(Product, li.product_id).is_service:
            mv_id = inventory.apply_movement(ctx.db, org_id=ctx.org_id, user_id=ctx.user.id,
                                             product_id=li.product_id, location_id=inv.location_id,
                                             movement_type="customer_return", quantity=r.quantity,
                                             reference=cn.number,
                                             unit_cost=inventory.sale_cost(ctx.db, ctx.org_id,
                                                                           f"inv{inv.id}:l{li.id}:sale")).id
        li.returned_quantity = returned + r.quantity
        cn.lines.append(CreditNoteLine(sales_invoice_line_id=li.id, quantity=r.quantity, taxable_value=taxable,
                                       tax_amount=tax, amount=taxable + tax, stock_movement_id=mv_id))
        cn.taxable_total += taxable
        cn.tax_total += tax
    cn.total = cn.taxable_total + cn.tax_total
    inv.credited_amount = Decimal(inv.credited_amount) + cn.total
    refresh_sales_status(inv)
    ctx.audit("create", "credit_note", cn.id, {"number": cn.number, "invoice": inv.number, "total": str(cn.total)})
    ctx.db.commit()
    return cn


@router.get("/credit-notes", response_model=Page[CreditNoteOut])
def list_credit_notes(ctx: OrgContext = Depends(require("sales.view")), customer_id: int | None = None,
                      invoice_id: int | None = None, page: int = Query(1, ge=1),
                      size: int = Query(25, ge=1, le=200)):
    base = select(CreditNote).where(CreditNote.organization_id == ctx.org_id)
    if customer_id:
        base = base.where(CreditNote.customer_id == customer_id)
    if invoice_id:
        base = base.where(CreditNote.sales_invoice_id == invoice_id)
    total = ctx.db.scalar(select(func.count()).select_from(base.subquery()))
    rows = ctx.db.scalars(base.order_by(CreditNote.id.desc()).offset((page - 1) * size).limit(size)).all()
    return Page(items=rows, total=total, page=page, size=size)


# ---------------- customer account ----------------
@router.get("/customers/{customer_id}/account")
def customer_account(customer_id: int, ctx: OrgContext = Depends(require("sales.view"))):
    """Everything about a customer's trading in one response: totals, open invoices, recent documents."""
    c = get_owned(ctx, Customer, customer_id, "Customer")
    inv_q = select(SalesInvoice).where(SalesInvoice.organization_id == ctx.org_id,
                                       SalesInvoice.customer_id == c.id)
    invoices = ctx.db.scalars(inv_q.order_by(SalesInvoice.id.desc())).all()
    live = [i for i in invoices if i.status not in ("draft", "cancelled")]
    payments = ctx.db.scalars(select(Payment).where(Payment.organization_id == ctx.org_id,
                                                    Payment.customer_id == c.id)
                              .order_by(Payment.id.desc())).all()
    allocated = {p.id: sum((Decimal(a.amount) for a in p.allocations), ZERO) for p in payments}
    unallocated = sum((Decimal(p.amount) - allocated[p.id] for p in payments if not p.voided_at), ZERO)
    from .payments import payment_out
    return {
        "customer_id": c.id,
        "total_invoiced": str(sum((Decimal(i.total) for i in live), ZERO)),
        "total_paid": str(sum((Decimal(p.amount) for p in payments if not p.voided_at), ZERO)),
        "total_credited": str(sum((Decimal(i.credited_amount) for i in live), ZERO)),
        "outstanding": str(sum((max(balance(i), ZERO) for i in live), ZERO)),
        "overdue": str(sum((max(balance(i), ZERO) for i in live if display_status(i) == "overdue"), ZERO)),
        "unallocated_payments": str(unallocated),
        "invoices": [_inv_out(ctx, i).model_dump(mode="json", exclude={"lines"}) for i in invoices[:50]],
        "quotations": [_q_out(ctx, q).model_dump(mode="json", exclude={"lines"}) for q in ctx.db.scalars(
            select(Quotation).where(Quotation.organization_id == ctx.org_id, Quotation.customer_id == c.id)
            .order_by(Quotation.id.desc()).limit(50))],
        "payments": [payment_out(ctx, p).model_dump(mode="json") for p in payments[:50]],
        "credit_notes": [CreditNoteOut.model_validate(n).model_dump(mode="json") for n in ctx.db.scalars(
            select(CreditNote).where(CreditNote.organization_id == ctx.org_id, CreditNote.customer_id == c.id)
            .order_by(CreditNote.id.desc()).limit(50))],
    }

