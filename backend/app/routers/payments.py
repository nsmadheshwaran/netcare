from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..deps import OrgContext, require
from ..models import Customer, utcnow
from ..models_trade import Payment, PaymentAllocation, PurchaseInvoice, SalesInvoice, Supplier
from ..schemas import Page
from ..schemas_trade import AllocationIn, AllocationOut, CancelIn, PaymentIn, PaymentOut
from ..models_finance import MoneyAccount
from ..services import billing
from ..services.finance import resolve_account
from ..services.trade import (
    active_customer, active_supplier, balance, get_owned, refresh_purchase_status, refresh_sales_status,
)

router = APIRouter(prefix="/payments", tags=["payments"])
ZERO = Decimal("0")


def payment_out(ctx: OrgContext, p: Payment) -> PaymentOut:
    o = PaymentOut.model_validate(p)
    party = ctx.db.get(Customer, p.customer_id) if p.customer_id else ctx.db.get(Supplier, p.supplier_id)
    o.party_name = party.name if party else None
    o.account_name = ctx.db.get(MoneyAccount, p.account_id).name if p.account_id else None
    o.unallocated = ZERO if p.voided_at else Decimal(p.amount) - sum((Decimal(a.amount) for a in p.allocations), ZERO)
    allocs = []
    for a in p.allocations:
        ao = AllocationOut.model_validate(a)
        doc = ctx.db.get(SalesInvoice, a.sales_invoice_id) if a.sales_invoice_id \
            else ctx.db.get(PurchaseInvoice, a.purchase_invoice_id)
        ao.invoice_number = doc.number if doc else None
        allocs.append(ao)
    o.allocations = allocs
    return o


def _allocate(ctx: OrgContext, p: Payment, allocations: list[AllocationIn]) -> None:
    already = sum((Decimal(a.amount) for a in p.allocations), ZERO)
    if already + sum((a.amount for a in allocations), ZERO) > Decimal(p.amount):
        raise HTTPException(422, "Allocations exceed the payment amount")
    for a in allocations:
        if p.direction == "in":
            doc = get_owned(ctx, SalesInvoice, a.invoice_id, f"Invoice {a.invoice_id}", lock=True, status_code=422)
            if doc.customer_id != p.customer_id:
                raise HTTPException(422, f"Invoice {doc.number or doc.id} belongs to another customer")
            if doc.status not in ("issued", "partially_paid"):
                raise HTTPException(409, f"Invoice {doc.number or doc.id} is {doc.status} and cannot take payments")
        else:
            doc = get_owned(ctx, PurchaseInvoice, a.invoice_id, f"Bill {a.invoice_id}", lock=True, status_code=422)
            if doc.supplier_id != p.supplier_id:
                raise HTTPException(422, f"Bill {doc.number} belongs to another supplier")
            if doc.status not in ("open", "partially_paid"):
                raise HTTPException(409, f"Bill {doc.number} is {doc.status} and cannot take payments")
        if a.amount > balance(doc):
            raise HTTPException(409, f"{doc.number}: allocating {a.amount} but only {balance(doc)} is due")
        doc.amount_paid = Decimal(doc.amount_paid) + a.amount
        if p.direction == "in":
            p.allocations.append(PaymentAllocation(sales_invoice_id=doc.id, amount=a.amount))
            refresh_sales_status(doc)
        else:
            p.allocations.append(PaymentAllocation(purchase_invoice_id=doc.id, amount=a.amount))
            refresh_purchase_status(doc)


@router.get("", response_model=Page[PaymentOut])
def list_payments(ctx: OrgContext = Depends(require("payments.view")), direction: str | None = None,
                  customer_id: int | None = None, supplier_id: int | None = None, method: str | None = None,
                  date_from: date | None = None, date_to: date | None = None, include_voided: bool = True,
                  page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=200)):
    base = select(Payment).where(Payment.organization_id == ctx.org_id)
    if direction:
        base = base.where(Payment.direction == direction)
    if customer_id:
        base = base.where(Payment.customer_id == customer_id)
    if supplier_id:
        base = base.where(Payment.supplier_id == supplier_id)
    if method:
        base = base.where(Payment.method == method)
    if date_from:
        base = base.where(Payment.payment_date >= date_from)
    if date_to:
        base = base.where(Payment.payment_date <= date_to)
    if not include_voided:
        base = base.where(Payment.voided_at.is_(None))
    total = ctx.db.scalar(select(func.count()).select_from(base.subquery()))
    rows = ctx.db.scalars(base.order_by(Payment.id.desc()).offset((page - 1) * size).limit(size)).all()
    return Page(items=[payment_out(ctx, p) for p in rows], total=total, page=page, size=size)


@router.post("", response_model=PaymentOut, status_code=201)
def record_payment(body: PaymentIn, ctx: OrgContext = Depends(require("payments.edit"))):
    """Record money received (customer_id) or paid (supplier_id), optionally allocated to invoices.
    Any unallocated remainder stays on the party's account as an advance."""
    if body.idempotency_key:
        prior = ctx.db.scalar(select(Payment).where(Payment.organization_id == ctx.org_id,
                                                    Payment.idempotency_key == body.idempotency_key))
        if prior:
            return payment_out(ctx, prior)
    incoming = body.customer_id is not None
    if incoming:
        active_customer(ctx, body.customer_id)
    else:
        active_supplier(ctx, body.supplier_id)
    account = resolve_account(ctx, body.account_id, body.method)
    p = Payment(organization_id=ctx.org_id, direction="in" if incoming else "out", account_id=account.id,
                customer_id=body.customer_id, supplier_id=body.supplier_id, payment_date=body.payment_date,
                amount=body.amount, method=body.method, reference=body.reference, notes=body.notes,
                idempotency_key=body.idempotency_key, created_by=ctx.user.id,
                number=billing.next_number(ctx.db, ctx.org_id, "receipt" if incoming else "supplier_payment",
                                           body.payment_date))
    ctx.db.add(p)
    ctx.db.flush()
    _allocate(ctx, p, body.allocations)
    ctx.audit("create", "payment", p.id, {"number": p.number, "amount": str(p.amount), "method": p.method,
                                          "allocations": [[a.invoice_id, str(a.amount)] for a in body.allocations]})
    ctx.db.commit()
    return payment_out(ctx, p)


@router.get("/{payment_id}", response_model=PaymentOut)
def get_payment(payment_id: int, ctx: OrgContext = Depends(require("payments.view"))):
    return payment_out(ctx, get_owned(ctx, Payment, payment_id, "Payment"))


class AllocateIn(BaseModel):
    allocations: list[AllocationIn] = Field(min_length=1)


@router.post("/{payment_id}/allocate", response_model=PaymentOut)
def allocate_payment(payment_id: int, body: AllocateIn, ctx: OrgContext = Depends(require("payments.edit"))):
    """Apply an advance (unallocated amount) to invoices later."""
    p = get_owned(ctx, Payment, payment_id, "Payment", lock=True)
    if p.voided_at:
        raise HTTPException(409, "Payment is voided")
    _allocate(ctx, p, body.allocations)
    ctx.audit("allocate", "payment", p.id, {"allocations": [[a.invoice_id, str(a.amount)] for a in body.allocations]})
    ctx.db.commit()
    return payment_out(ctx, p)


@router.post("/{payment_id}/void", response_model=PaymentOut)
def void_payment(payment_id: int, body: CancelIn, ctx: OrgContext = Depends(require("payments.edit"))):
    """Reverse a payment recorded in error (e.g. bounced cheque). The record is kept, marked void."""
    p = get_owned(ctx, Payment, payment_id, "Payment", lock=True)
    if p.voided_at:
        raise HTTPException(409, "Payment is already voided")
    for a in p.allocations:
        if a.sales_invoice_id:
            doc = get_owned(ctx, SalesInvoice, a.sales_invoice_id, "Invoice", lock=True)
            doc.amount_paid = Decimal(doc.amount_paid) - Decimal(a.amount)
            refresh_sales_status(doc)
        else:
            doc = get_owned(ctx, PurchaseInvoice, a.purchase_invoice_id, "Bill", lock=True)
            doc.amount_paid = Decimal(doc.amount_paid) - Decimal(a.amount)
            refresh_purchase_status(doc)
    p.voided_at = utcnow()
    p.void_reason = body.reason
    ctx.audit("void", "payment", p.id, {"number": p.number, "reason": body.reason})
    ctx.db.commit()
    return payment_out(ctx, p)
