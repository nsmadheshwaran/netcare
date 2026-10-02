from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select

from ..deps import OrgContext, require
from ..models import utcnow
from ..models_trade import PurchaseInvoice, Supplier
from ..schemas import Page
from ..schemas_trade import SupplierIn, SupplierOut
from ..services.trade import get_owned

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


def _balances(ctx: OrgContext, ids: list[int]) -> dict[int, Decimal]:
    if not ids:
        return {}
    q = (select(PurchaseInvoice.supplier_id,
                func.sum(PurchaseInvoice.total - PurchaseInvoice.amount_paid - PurchaseInvoice.credited_amount))
         .where(PurchaseInvoice.organization_id == ctx.org_id, PurchaseInvoice.supplier_id.in_(ids),
                PurchaseInvoice.status.in_(["open", "partially_paid"]))
         .group_by(PurchaseInvoice.supplier_id))
    return {sid: Decimal(b or 0) for sid, b in ctx.db.execute(q)}


def _out(s: Supplier, bal: Decimal) -> SupplierOut:
    o = SupplierOut.model_validate(s)
    o.balance_due = bal
    return o


@router.get("", response_model=Page[SupplierOut])
def list_suppliers(ctx: OrgContext = Depends(require("suppliers.view")), q: str | None = None,
                   archived: bool = False, page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=200)):
    base = select(Supplier).where(Supplier.organization_id == ctx.org_id)
    base = base.where(Supplier.archived_at.is_not(None) if archived else Supplier.archived_at.is_(None))
    if q:
        like = f"%{q.lower()}%"
        base = base.where(or_(func.lower(Supplier.name).like(like), Supplier.phone.like(f"%{q}%"),
                              func.upper(Supplier.gstin).like(f"%{q.upper()}%")))
    total = ctx.db.scalar(select(func.count()).select_from(base.subquery()))
    rows = ctx.db.scalars(base.order_by(Supplier.name, Supplier.id).offset((page - 1) * size).limit(size)).all()
    bals = _balances(ctx, [s.id for s in rows])
    return Page(items=[_out(s, bals.get(s.id, Decimal("0"))) for s in rows], total=total, page=page, size=size)


@router.post("", response_model=SupplierOut, status_code=201)
def create_supplier(body: SupplierIn, ctx: OrgContext = Depends(require("suppliers.edit"))):
    if body.gstin and ctx.db.scalar(select(Supplier.id).where(Supplier.organization_id == ctx.org_id,
                                                              Supplier.gstin == body.gstin,
                                                              Supplier.archived_at.is_(None))):
        raise HTTPException(409, "A supplier with this GSTIN already exists")
    s = Supplier(organization_id=ctx.org_id, **body.model_dump())
    ctx.db.add(s)
    ctx.db.flush()
    ctx.audit("create", "supplier", s.id, {"name": s.name})
    ctx.db.commit()
    return _out(s, Decimal("0"))


@router.get("/{supplier_id}", response_model=SupplierOut)
def get_supplier(supplier_id: int, ctx: OrgContext = Depends(require("suppliers.view"))):
    s = get_owned(ctx, Supplier, supplier_id, "Supplier")
    return _out(s, _balances(ctx, [s.id]).get(s.id, Decimal("0")))


@router.put("/{supplier_id}", response_model=SupplierOut)
def update_supplier(supplier_id: int, body: SupplierIn, ctx: OrgContext = Depends(require("suppliers.edit"))):
    s = get_owned(ctx, Supplier, supplier_id, "Supplier")
    changed = {k: v for k, v in body.model_dump().items() if getattr(s, k) != v}
    for k, v in changed.items():
        setattr(s, k, v)
    ctx.audit("update", "supplier", s.id, {"fields": sorted(changed)})
    ctx.db.commit()
    return _out(s, _balances(ctx, [s.id]).get(s.id, Decimal("0")))


@router.post("/{supplier_id}/archive", response_model=SupplierOut)
def archive_supplier(supplier_id: int, ctx: OrgContext = Depends(require("suppliers.edit"))):
    s = get_owned(ctx, Supplier, supplier_id, "Supplier")
    s.archived_at = s.archived_at or utcnow()
    ctx.audit("archive", "supplier", s.id)
    ctx.db.commit()
    return _out(s, Decimal("0"))


@router.post("/{supplier_id}/restore", response_model=SupplierOut)
def restore_supplier(supplier_id: int, ctx: OrgContext = Depends(require("suppliers.edit"))):
    s = get_owned(ctx, Supplier, supplier_id, "Supplier")
    s.archived_at = None
    ctx.audit("restore", "supplier", s.id)
    ctx.db.commit()
    return _out(s, Decimal("0"))
