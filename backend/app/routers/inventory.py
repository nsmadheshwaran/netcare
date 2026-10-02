from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from ..deps import OrgContext, require
from ..models import Location, Product, StockLevel, StockMovement
from ..schemas import MovementIn, MovementOut, Page, StockLevelOut, TransferIn
from ..services import inventory as svc

router = APIRouter(prefix="/inventory", tags=["inventory"])


def _mov_out(m: StockMovement, pname: str | None, lname: str | None) -> MovementOut:
    out = MovementOut.model_validate(m)
    out.product_name, out.location_name = pname, lname
    return out


@router.get("/levels", response_model=list[StockLevelOut])
def stock_levels(ctx: OrgContext = Depends(require("inventory.view")),
                 product_id: int | None = None, location_id: int | None = None):
    q = (select(StockLevel, Product, Location)
         .join(Product, Product.id == StockLevel.product_id).join(Location, Location.id == StockLevel.location_id)
         .where(StockLevel.organization_id == ctx.org_id, Product.archived_at.is_(None)))
    if product_id:
        q = q.where(StockLevel.product_id == product_id)
    if location_id:
        q = q.where(StockLevel.location_id == location_id)
    return [StockLevelOut(product_id=p.id, product_name=p.name, sku=p.sku, location_id=loc.id,
                          location_name=loc.name, quantity=s.quantity, min_stock=p.min_stock)
            for s, p, loc in ctx.db.execute(q.order_by(Product.name, Location.name))]


@router.get("/movements", response_model=Page[MovementOut])
def movements(ctx: OrgContext = Depends(require("inventory.view")),
              product_id: int | None = None, location_id: int | None = None, movement_type: str | None = None,
              page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200)):
    q = (select(StockMovement, Product.name, Location.name)
         .join(Product, Product.id == StockMovement.product_id)
         .join(Location, Location.id == StockMovement.location_id)
         .where(StockMovement.organization_id == ctx.org_id))
    if product_id:
        q = q.where(StockMovement.product_id == product_id)
    if location_id:
        q = q.where(StockMovement.location_id == location_id)
    if movement_type:
        q = q.where(StockMovement.movement_type == movement_type)
    total = ctx.db.scalar(select(func.count()).select_from(q.subquery()))
    rows = ctx.db.execute(q.order_by(StockMovement.id.desc()).offset((page - 1) * size).limit(size)).all()
    return Page(items=[_mov_out(*r) for r in rows], total=total, page=page, size=size)


@router.post("/movements", response_model=MovementOut, status_code=201)
def create_movement(body: MovementIn, ctx: OrgContext = Depends(require("inventory.adjust"))):
    m = svc.apply_movement(ctx.db, org_id=ctx.org_id, user_id=ctx.user.id, **body.model_dump())
    ctx.audit(body.movement_type, "stock_movement", m.id,
              {"product_id": m.product_id, "location_id": m.location_id, "change": str(m.quantity_change)})
    ctx.db.commit()
    return _mov_out(m, None, None)


@router.post("/transfers", response_model=list[MovementOut], status_code=201)
def create_transfer(body: TransferIn, ctx: OrgContext = Depends(require("inventory.adjust"))):
    out, inn = svc.transfer(ctx.db, org_id=ctx.org_id, user_id=ctx.user.id, **body.model_dump())
    ctx.audit("transfer", "stock_movement", out.id, {"product_id": body.product_id, "qty": str(body.quantity),
                                                     "from": body.from_location_id, "to": body.to_location_id})
    ctx.db.commit()
    return [_mov_out(out, None, None), _mov_out(inn, None, None)]
