"""Helpers shared by purchase/sales/payment routers. Every lookup is organization-scoped."""
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select

from ..deps import OrgContext
from ..models import Customer, Location, Product
from ..models_trade import PurchaseInvoice, SalesInvoice, Supplier
from . import billing

ZERO = Decimal("0")


def get_owned(ctx: OrgContext, model, obj_id: int | None, label: str, *, lock: bool = False,
              status_code: int = 404):
    if obj_id is None:
        raise HTTPException(status_code, f"{label} not found")
    if lock:
        obj = ctx.db.scalar(select(model).where(model.id == obj_id).with_for_update())
    else:
        obj = ctx.db.get(model, obj_id)
    if obj is None or obj.organization_id != ctx.org_id:
        raise HTTPException(status_code, f"{label} not found")
    return obj


def active_customer(ctx: OrgContext, customer_id: int) -> Customer:
    c = get_owned(ctx, Customer, customer_id, "Customer", status_code=422)
    if c.archived_at:
        raise HTTPException(422, "Customer is archived")
    return c


def active_supplier(ctx: OrgContext, supplier_id: int) -> Supplier:
    s = get_owned(ctx, Supplier, supplier_id, "Supplier", status_code=422)
    if s.archived_at:
        raise HTTPException(422, "Supplier is archived")
    return s


def active_location(ctx: OrgContext, location_id: int) -> Location:
    loc = get_owned(ctx, Location, location_id, "Location", status_code=422)
    if not loc.is_active:
        raise HTTPException(422, "Location is inactive")
    return loc


def build_lines(ctx: OrgContext, lines, *, price_field: str = "selling_price") -> list[billing.LineInput]:
    """Resolve product defaults (description, price, GST rate, HSN) and validate ownership."""
    out = []
    for li in lines:
        product = None
        if li.product_id is not None:
            product = get_owned(ctx, Product, li.product_id, f"Product {li.product_id}", status_code=422)
            if product.archived_at:
                raise HTTPException(422, f"Product {product.sku} is archived")
        price = li.unit_price if li.unit_price is not None else getattr(product, price_field)
        rate = li.tax_rate if li.tax_rate is not None else (product.gst_rate if product and product.gst_rate else ZERO)
        out.append(billing.LineInput(
            description=li.description or product.name, quantity=li.quantity, unit_price=Decimal(price),
            tax_rate=Decimal(rate), line_discount_pct=getattr(li, "line_discount_pct", ZERO) or ZERO,
            product_id=li.product_id, hsn_sac=product.hsn_sac if product else None))
    return out


def apply_totals(doc, totals: billing.Totals, line_model, *, interstate: bool, place_of_supply: str | None,
                 with_discount_pct: bool = True):
    for f in ("subtotal", "discount_total", "taxable_total", "cgst_total", "sgst_total", "igst_total",
              "round_off", "total"):
        setattr(doc, f, getattr(totals, f))
    doc.is_interstate = interstate
    doc.place_of_supply = place_of_supply
    doc.lines.clear()
    for r in totals.lines:
        kw = dict(product_id=r.inp.product_id, description=r.inp.description, hsn_sac=r.inp.hsn_sac,
                  quantity=r.inp.quantity, unit_price=r.inp.unit_price, discount_amount=r.discount_amount,
                  taxable_value=r.taxable_value, tax_rate=r.inp.tax_rate, cgst=r.cgst, sgst=r.sgst, igst=r.igst,
                  line_total=r.line_total)
        if with_discount_pct:
            kw["line_discount_pct"] = r.inp.line_discount_pct
        doc.lines.append(line_model(**kw))


def balance(doc) -> Decimal:
    return Decimal(doc.total) - Decimal(doc.amount_paid) - Decimal(doc.credited_amount)


def refresh_sales_status(inv: SalesInvoice) -> None:
    if inv.status in ("draft", "cancelled"):
        return
    b = balance(inv)
    if b <= 0:
        inv.status = "paid"
    elif inv.amount_paid > 0 or inv.credited_amount > 0:
        inv.status = "partially_paid"
    else:
        inv.status = "issued"


def refresh_purchase_status(bill: PurchaseInvoice) -> None:
    if bill.status == "cancelled":
        return
    b = balance(bill)
    bill.status = "paid" if b <= 0 else "partially_paid" if (bill.amount_paid > 0 or bill.credited_amount > 0) \
        else "open"


def display_status(doc, today: date | None = None) -> str:
    today = today or date.today()
    if doc.status in ("issued", "partially_paid", "open") and doc.due_date and doc.due_date < today \
            and balance(doc) > 0:
        return "overdue"
    return doc.status


def interstate_for(ctx: OrgContext, place_of_supply: str | None) -> bool:
    return billing.is_interstate(ctx.org.state_code, place_of_supply)
