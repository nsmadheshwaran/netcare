from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select

from ..deps import OrgContext, require
from ..models import Product
from ..models_trade import (
    GoodsReceipt, GoodsReceiptLine, PurchaseInvoice, PurchaseInvoiceLine, PurchaseOrder, PurchaseOrderLine,
    PurchaseReturn, PurchaseReturnLine, Supplier,
)
from ..schemas import Page
from ..schemas_trade import (
    CancelIn, PurchaseInvoiceIn, PurchaseInvoiceOut, PurchaseOrderIn, PurchaseOrderOut, PurchaseReturnIn,
    PurchaseReturnOut, ReceiptIn, ReceiptOut,
)
from ..services import billing, inventory
from ..services.trade import (
    active_location, active_supplier, apply_totals, balance, build_lines, display_status, get_owned,
    interstate_for, refresh_purchase_status,
)

router = APIRouter(tags=["purchases"])


# ---------------- purchase orders ----------------
def _po_out(po: PurchaseOrder) -> PurchaseOrderOut:
    o = PurchaseOrderOut.model_validate(po)
    o.supplier_name = po.supplier.name
    return o


def _fill_po(ctx: OrgContext, po: PurchaseOrder, body: PurchaseOrderIn):
    supplier = active_supplier(ctx, body.supplier_id)
    active_location(ctx, body.location_id)
    lines = build_lines(ctx, body.lines, price_field="purchase_price")
    for li in lines:
        if ctx.db.get(Product, li.product_id).is_service:
            raise HTTPException(422, f"{li.description} is a service and cannot be purchased into stock")
    pos = supplier.state_code
    inter = interstate_for(ctx, pos)
    totals = billing.compute(lines, interstate=inter)
    po.supplier_id, po.location_id = body.supplier_id, body.location_id
    po.order_date, po.expected_date, po.notes = body.order_date, body.expected_date, body.notes
    apply_totals(po, totals, PurchaseOrderLine, interstate=inter, place_of_supply=pos, with_discount_pct=False)


@router.get("/purchase-orders", response_model=Page[PurchaseOrderOut])
def list_pos(ctx: OrgContext = Depends(require("purchases.view")), status: str | None = None,
             supplier_id: int | None = None, q: str | None = None,
             page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=200)):
    base = select(PurchaseOrder).join(Supplier).where(PurchaseOrder.organization_id == ctx.org_id)
    if status:
        base = base.where(PurchaseOrder.status == status)
    if supplier_id:
        base = base.where(PurchaseOrder.supplier_id == supplier_id)
    if q:
        base = base.where(or_(PurchaseOrder.number.ilike(f"%{q}%"), Supplier.name.ilike(f"%{q}%")))
    total = ctx.db.scalar(select(func.count()).select_from(base.subquery()))
    rows = ctx.db.scalars(base.order_by(PurchaseOrder.id.desc()).offset((page - 1) * size).limit(size)).all()
    return Page(items=[_po_out(p) for p in rows], total=total, page=page, size=size)


@router.post("/purchase-orders", response_model=PurchaseOrderOut, status_code=201)
def create_po(body: PurchaseOrderIn, ctx: OrgContext = Depends(require("purchases.edit"))):
    po = PurchaseOrder(organization_id=ctx.org_id, status="draft", created_by=ctx.user.id,
                       number=billing.next_number(ctx.db, ctx.org_id, "purchase_order", body.order_date))
    _fill_po(ctx, po, body)
    ctx.db.add(po)
    ctx.db.flush()
    ctx.audit("create", "purchase_order", po.id, {"number": po.number, "total": str(po.total)})
    ctx.db.commit()
    return _po_out(po)


@router.get("/purchase-orders/{po_id}", response_model=PurchaseOrderOut)
def get_po(po_id: int, ctx: OrgContext = Depends(require("purchases.view"))):
    return _po_out(get_owned(ctx, PurchaseOrder, po_id, "Purchase order"))


@router.put("/purchase-orders/{po_id}", response_model=PurchaseOrderOut)
def update_po(po_id: int, body: PurchaseOrderIn, ctx: OrgContext = Depends(require("purchases.edit"))):
    po = get_owned(ctx, PurchaseOrder, po_id, "Purchase order", lock=True)
    if po.status != "draft":
        raise HTTPException(409, "Only draft purchase orders can be edited")
    _fill_po(ctx, po, body)
    ctx.audit("update", "purchase_order", po.id, {"total": str(po.total)})
    ctx.db.commit()
    return _po_out(po)


def _po_transition(ctx: OrgContext, po_id: int, allowed: set[str], new: str, action: str) -> PurchaseOrder:
    po = get_owned(ctx, PurchaseOrder, po_id, "Purchase order", lock=True)
    if po.status not in allowed:
        raise HTTPException(409, f"Cannot {action} a purchase order that is {po.status}")
    po.status = new
    return po


@router.post("/purchase-orders/{po_id}/approve", response_model=PurchaseOrderOut)
def approve_po(po_id: int, ctx: OrgContext = Depends(require("purchases.approve"))):
    po = _po_transition(ctx, po_id, {"draft"}, "approved", "approve")
    po.approved_by = ctx.user.id
    ctx.audit("approve", "purchase_order", po.id)
    ctx.db.commit()
    return _po_out(po)


@router.post("/purchase-orders/{po_id}/cancel", response_model=PurchaseOrderOut)
def cancel_po(po_id: int, body: CancelIn, ctx: OrgContext = Depends(require("purchases.edit"))):
    po = _po_transition(ctx, po_id, {"draft", "approved"}, "cancelled", "cancel")
    ctx.audit("cancel", "purchase_order", po.id, {"reason": body.reason})
    ctx.db.commit()
    return _po_out(po)


@router.post("/purchase-orders/{po_id}/close", response_model=PurchaseOrderOut)
def close_po(po_id: int, ctx: OrgContext = Depends(require("purchases.edit"))):
    """Stop expecting the remaining quantity of a partially received order."""
    po = _po_transition(ctx, po_id, {"partially_received"}, "closed", "close")
    ctx.audit("close", "purchase_order", po.id)
    ctx.db.commit()
    return _po_out(po)


# ---------------- goods receipts ----------------
@router.post("/purchase-orders/{po_id}/receipts", response_model=ReceiptOut, status_code=201)
def receive(po_id: int, body: ReceiptIn, ctx: OrgContext = Depends(require("purchases.edit"))):
    if body.idempotency_key:
        prior = ctx.db.scalar(select(GoodsReceipt).where(GoodsReceipt.organization_id == ctx.org_id,
                                                         GoodsReceipt.idempotency_key == body.idempotency_key))
        if prior:
            return prior
    po = get_owned(ctx, PurchaseOrder, po_id, "Purchase order", lock=True)
    if po.status not in ("approved", "partially_received"):
        raise HTTPException(409, f"Cannot receive against a purchase order that is {po.status}")
    by_id = {li.id: li for li in po.lines}
    grn = GoodsReceipt(organization_id=ctx.org_id, purchase_order_id=po.id, location_id=po.location_id,
                       received_date=body.received_date, supplier_reference=body.supplier_reference,
                       notes=body.notes, idempotency_key=body.idempotency_key, created_by=ctx.user.id,
                       number=billing.next_number(ctx.db, ctx.org_id, "goods_receipt", body.received_date))
    ctx.db.add(grn)
    ctx.db.flush()
    seen = set()
    for r in body.lines:
        line = by_id.get(r.purchase_order_line_id)
        if line is None or r.purchase_order_line_id in seen:
            raise HTTPException(422, f"Line {r.purchase_order_line_id} is not on this order (or repeated)")
        seen.add(line.id)
        remaining = Decimal(line.quantity) - Decimal(line.received_quantity)
        if r.quantity > remaining:
            raise HTTPException(409, f"{line.description}: receiving {r.quantity} but only {remaining} outstanding")
        unit_cost = billing.money(Decimal(line.taxable_value) / Decimal(line.quantity))
        mv = inventory.apply_movement(ctx.db, org_id=ctx.org_id, user_id=ctx.user.id, product_id=line.product_id,
                                      location_id=po.location_id, movement_type="purchase_receipt",
                                      quantity=r.quantity, unit_cost=unit_cost, reference=grn.number)
        line.received_quantity = Decimal(line.received_quantity) + r.quantity
        grn.lines.append(GoodsReceiptLine(purchase_order_line_id=line.id, product_id=line.product_id,
                                          quantity=r.quantity, stock_movement_id=mv.id))
    fully = all(Decimal(li.received_quantity) >= Decimal(li.quantity) for li in po.lines)
    po.status = "received" if fully else "partially_received"
    ctx.audit("receive", "goods_receipt", grn.id, {"number": grn.number, "po": po.number})
    ctx.db.commit()
    return grn


@router.get("/purchase-orders/{po_id}/receipts", response_model=list[ReceiptOut])
def list_receipts(po_id: int, ctx: OrgContext = Depends(require("purchases.view"))):
    get_owned(ctx, PurchaseOrder, po_id, "Purchase order")
    return ctx.db.scalars(select(GoodsReceipt).where(GoodsReceipt.purchase_order_id == po_id)
                          .order_by(GoodsReceipt.id)).all()


# ---------------- supplier bills ----------------
def _bill_out(b: PurchaseInvoice) -> PurchaseInvoiceOut:
    o = PurchaseInvoiceOut.model_validate(b)
    o.supplier_name = b.supplier.name
    o.balance_due = max(balance(b), Decimal("0")) if b.status != "cancelled" else Decimal("0")
    o.display_status = display_status(b)
    return o


@router.get("/purchase-invoices", response_model=Page[PurchaseInvoiceOut])
def list_bills(ctx: OrgContext = Depends(require("purchases.view")), status: str | None = None,
               supplier_id: int | None = None, q: str | None = None, unpaid: bool = False,
               page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=200)):
    base = select(PurchaseInvoice).join(Supplier).where(PurchaseInvoice.organization_id == ctx.org_id)
    if status:
        base = base.where(PurchaseInvoice.status == status)
    if unpaid:
        base = base.where(PurchaseInvoice.status.in_(["open", "partially_paid"]))
    if supplier_id:
        base = base.where(PurchaseInvoice.supplier_id == supplier_id)
    if q:
        base = base.where(or_(PurchaseInvoice.number.ilike(f"%{q}%"),
                              PurchaseInvoice.supplier_invoice_number.ilike(f"%{q}%"),
                              Supplier.name.ilike(f"%{q}%")))
    total = ctx.db.scalar(select(func.count()).select_from(base.subquery()))
    rows = ctx.db.scalars(base.order_by(PurchaseInvoice.id.desc()).offset((page - 1) * size).limit(size)).all()
    return Page(items=[_bill_out(b) for b in rows], total=total, page=page, size=size)


@router.post("/purchase-invoices", response_model=PurchaseInvoiceOut, status_code=201)
def create_bill(body: PurchaseInvoiceIn, ctx: OrgContext = Depends(require("purchases.edit"))):
    supplier = active_supplier(ctx, body.supplier_id)
    if body.purchase_order_id:
        po = get_owned(ctx, PurchaseOrder, body.purchase_order_id, "Purchase order", status_code=422)
        if po.supplier_id != supplier.id:
            raise HTTPException(422, "Purchase order belongs to a different supplier")
    if ctx.db.scalar(select(PurchaseInvoice.id).where(
            PurchaseInvoice.organization_id == ctx.org_id, PurchaseInvoice.supplier_id == supplier.id,
            PurchaseInvoice.supplier_invoice_number == body.supplier_invoice_number)):
        raise HTTPException(409, f"Bill {body.supplier_invoice_number} from this supplier is already recorded")
    pos = body.place_of_supply or supplier.state_code
    inter = interstate_for(ctx, pos)
    totals = billing.compute(build_lines(ctx, body.lines, price_field="purchase_price"), interstate=inter)
    due = body.due_date
    if due is None and supplier.payment_terms_days is not None:
        from datetime import timedelta
        due = body.invoice_date + timedelta(days=supplier.payment_terms_days)
    bill = PurchaseInvoice(organization_id=ctx.org_id, supplier_id=supplier.id,
                           supplier_invoice_number=body.supplier_invoice_number,
                           purchase_order_id=body.purchase_order_id, invoice_date=body.invoice_date, due_date=due,
                           notes=body.notes, status="open", created_by=ctx.user.id,
                           number=billing.next_number(ctx.db, ctx.org_id, "purchase_invoice", body.invoice_date))
    apply_totals(bill, totals, PurchaseInvoiceLine, interstate=inter, place_of_supply=pos, with_discount_pct=False)
    ctx.db.add(bill)
    ctx.db.flush()
    ctx.audit("create", "purchase_invoice", bill.id, {"number": bill.number, "total": str(bill.total)})
    ctx.db.commit()
    return _bill_out(bill)


@router.get("/purchase-invoices/{bill_id}", response_model=PurchaseInvoiceOut)
def get_bill(bill_id: int, ctx: OrgContext = Depends(require("purchases.view"))):
    return _bill_out(get_owned(ctx, PurchaseInvoice, bill_id, "Purchase invoice"))


@router.post("/purchase-invoices/{bill_id}/cancel", response_model=PurchaseInvoiceOut)
def cancel_bill(bill_id: int, body: CancelIn, ctx: OrgContext = Depends(require("purchases.edit"))):
    bill = get_owned(ctx, PurchaseInvoice, bill_id, "Purchase invoice", lock=True)
    if bill.status == "cancelled":
        raise HTTPException(409, "Already cancelled")
    if bill.amount_paid > 0 or bill.credited_amount > 0:
        raise HTTPException(409, "Void the payments and returns against this bill first")
    bill.status = "cancelled"
    ctx.audit("cancel", "purchase_invoice", bill.id, {"reason": body.reason})
    ctx.db.commit()
    return _bill_out(bill)


# ---------------- purchase returns ----------------
@router.get("/purchase-returns", response_model=Page[PurchaseReturnOut])
def list_returns(ctx: OrgContext = Depends(require("purchases.view")), supplier_id: int | None = None,
                 page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=200)):
    base = select(PurchaseReturn).where(PurchaseReturn.organization_id == ctx.org_id)
    if supplier_id:
        base = base.where(PurchaseReturn.supplier_id == supplier_id)
    total = ctx.db.scalar(select(func.count()).select_from(base.subquery()))
    rows = ctx.db.scalars(base.order_by(PurchaseReturn.id.desc()).offset((page - 1) * size).limit(size)).all()
    return Page(items=rows, total=total, page=page, size=size)


@router.post("/purchase-returns", response_model=PurchaseReturnOut, status_code=201)
def create_return(body: PurchaseReturnIn, ctx: OrgContext = Depends(require("purchases.edit"))):
    if body.idempotency_key:
        prior = ctx.db.scalar(select(PurchaseReturn).where(PurchaseReturn.organization_id == ctx.org_id,
                                                           PurchaseReturn.idempotency_key == body.idempotency_key))
        if prior:
            return prior
    supplier = active_supplier(ctx, body.supplier_id)
    active_location(ctx, body.location_id)
    bill = None
    if body.purchase_invoice_id:
        bill = get_owned(ctx, PurchaseInvoice, body.purchase_invoice_id, "Purchase invoice", lock=True,
                         status_code=422)
        if bill.supplier_id != supplier.id or bill.status == "cancelled":
            raise HTTPException(422, "Bill is cancelled or belongs to another supplier")
    ret = PurchaseReturn(organization_id=ctx.org_id, supplier_id=supplier.id, purchase_invoice_id=bill and bill.id,
                         location_id=body.location_id, return_date=body.return_date, reason=body.reason,
                         idempotency_key=body.idempotency_key, created_by=ctx.user.id, total=Decimal("0"),
                         number=billing.next_number(ctx.db, ctx.org_id, "purchase_return", body.return_date))
    ctx.db.add(ret)
    ctx.db.flush()
    total = Decimal("0")
    for li in body.lines:
        get_owned(ctx, Product, li.product_id, f"Product {li.product_id}", status_code=422)
        mv = inventory.apply_movement(ctx.db, org_id=ctx.org_id, user_id=ctx.user.id, product_id=li.product_id,
                                      location_id=body.location_id, movement_type="supplier_return",
                                      quantity=li.quantity, unit_cost=li.unit_cost, reference=ret.number)
        amount = billing.money(li.quantity * li.unit_cost * (1 + li.tax_rate / 100))
        total += amount
        ret.lines.append(PurchaseReturnLine(product_id=li.product_id, quantity=li.quantity, unit_cost=li.unit_cost,
                                            amount=amount, stock_movement_id=mv.id))
    ret.total = total
    if bill is not None:
        if total > balance(bill) + Decimal(bill.amount_paid):
            raise HTTPException(409, "Return value exceeds the bill amount")
        bill.credited_amount = Decimal(bill.credited_amount) + total
        refresh_purchase_status(bill)
    ctx.audit("create", "purchase_return", ret.id, {"number": ret.number, "total": str(total)})
    ctx.db.commit()
    return ret
