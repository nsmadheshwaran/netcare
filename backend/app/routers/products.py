from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select

from ..deps import OrgContext, require
from ..models import Product, ProductCategory, StockLevel, StockMovement, utcnow
from ..schemas import CategoryIn, CategoryOut, Page, ProductIn, ProductOut

router = APIRouter(tags=["products"])

SORTABLE = {"name": Product.name, "sku": Product.sku, "created_at": Product.created_at,
            "selling_price": Product.selling_price}


def _stock_subq(org_id: int):
    return (select(StockLevel.product_id, func.coalesce(func.sum(StockLevel.quantity), 0).label("qty"))
            .where(StockLevel.organization_id == org_id).group_by(StockLevel.product_id).subquery())


def _out(p: Product, qty) -> ProductOut:
    out = ProductOut.model_validate(p)
    out.category_name = p.category.name if p.category else None
    out.stock_on_hand = Decimal(qty or 0)
    return out


def _get(ctx: OrgContext, product_id: int) -> Product:
    p = ctx.db.get(Product, product_id)
    if not p or p.organization_id != ctx.org_id:
        raise HTTPException(404, "Product not found")
    return p


def _check_category(ctx: OrgContext, category_id: int | None):
    if category_id is not None:
        c = ctx.db.get(ProductCategory, category_id)
        if not c or c.organization_id != ctx.org_id:
            raise HTTPException(422, "Category not found")


def _check_sku(ctx: OrgContext, sku: str, exclude_id: int | None = None):
    q = select(Product.id).where(Product.organization_id == ctx.org_id, func.lower(Product.sku) == sku.lower())
    if exclude_id:
        q = q.where(Product.id != exclude_id)
    if ctx.db.scalar(q):
        raise HTTPException(409, f"SKU {sku} already exists")


# --- categories ---
@router.get("/product-categories", response_model=list[CategoryOut])
def list_categories(ctx: OrgContext = Depends(require("products.view"))):
    return ctx.db.scalars(select(ProductCategory).where(ProductCategory.organization_id == ctx.org_id)
                          .order_by(ProductCategory.name)).all()


@router.post("/product-categories", response_model=CategoryOut, status_code=201)
def create_category(body: CategoryIn, ctx: OrgContext = Depends(require("products.edit"))):
    if ctx.db.scalar(select(ProductCategory).where(ProductCategory.organization_id == ctx.org_id,
                                                   func.lower(ProductCategory.name) == body.name.lower())):
        raise HTTPException(409, "Category exists")
    c = ProductCategory(organization_id=ctx.org_id, name=body.name)
    ctx.db.add(c)
    ctx.db.flush()
    ctx.audit("create", "product_category", c.id, {"name": c.name})
    ctx.db.commit()
    return c


# --- products ---
@router.get("/products", response_model=Page[ProductOut])
def list_products(ctx: OrgContext = Depends(require("products.view")),
                  q: str | None = None, category_id: int | None = None, low_stock: bool = False,
                  archived: bool = False, sort: str = "name", order: str = Query("asc", pattern="^(asc|desc)$"),
                  page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=200)):
    stock = _stock_subq(ctx.org_id)
    qty = func.coalesce(stock.c.qty, 0)
    base = (select(Product, qty.label("qty")).outerjoin(stock, stock.c.product_id == Product.id)
            .where(Product.organization_id == ctx.org_id))
    base = base.where(Product.archived_at.is_not(None) if archived else Product.archived_at.is_(None))
    if q:
        like = f"%{q.lower()}%"
        base = base.where(or_(func.lower(Product.name).like(like), func.lower(Product.sku).like(like),
                              Product.barcode == q, func.lower(Product.brand).like(like),
                              func.lower(Product.model).like(like)))
    if category_id:
        base = base.where(Product.category_id == category_id)
    if low_stock:
        base = base.where(Product.is_service.is_(False), qty <= Product.min_stock)
    total = ctx.db.scalar(select(func.count()).select_from(base.subquery()))
    col = SORTABLE.get(sort, Product.name)
    rows = ctx.db.execute(base.order_by(col.desc() if order == "desc" else col.asc(), Product.id)
                          .offset((page - 1) * size).limit(size)).all()
    return Page(items=[_out(p, qtyv) for p, qtyv in rows], total=total, page=page, size=size)


@router.post("/products", response_model=ProductOut, status_code=201)
def create_product(body: ProductIn, ctx: OrgContext = Depends(require("products.edit"))):
    _check_category(ctx, body.category_id)
    _check_sku(ctx, body.sku)
    # Until goods are received at a real cost, value stock at the stated purchase price.
    p = Product(organization_id=ctx.org_id, avg_cost=body.purchase_price, **body.model_dump())
    ctx.db.add(p)
    ctx.db.flush()
    ctx.audit("create", "product", p.id, {"sku": p.sku, "name": p.name})
    ctx.db.commit()
    return _out(p, 0)


def _qty(ctx: OrgContext, product_id: int):
    return ctx.db.scalar(select(func.coalesce(func.sum(StockLevel.quantity), 0))
                         .where(StockLevel.product_id == product_id))


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: int, ctx: OrgContext = Depends(require("products.view"))):
    p = _get(ctx, product_id)
    return _out(p, _qty(ctx, p.id))


@router.put("/products/{product_id}", response_model=ProductOut)
def update_product(product_id: int, body: ProductIn, ctx: OrgContext = Depends(require("products.edit"))):
    p = _get(ctx, product_id)
    _check_category(ctx, body.category_id)
    _check_sku(ctx, body.sku, exclude_id=p.id)
    data = body.model_dump()
    if data["is_service"] and not p.is_service:
        has_moves = ctx.db.scalar(select(StockMovement.id).where(StockMovement.product_id == p.id).limit(1))
        if has_moves:
            raise HTTPException(409, "Product has stock history and cannot become a service")
    changed = {k: v for k, v in data.items() if getattr(p, k) != v}
    # Price changes are audited with old/new values.
    price_diff = {k: [str(getattr(p, k)), str(v)] for k, v in changed.items() if k.endswith("price")}
    for k, v in changed.items():
        setattr(p, k, v)
    ctx.audit("update", "product", p.id, {"fields": sorted(changed), "prices": price_diff or None})
    ctx.db.commit()
    return _out(p, _qty(ctx, p.id))


@router.post("/products/{product_id}/archive", response_model=ProductOut)
def archive_product(product_id: int, ctx: OrgContext = Depends(require("products.edit"))):
    p = _get(ctx, product_id)
    p.archived_at = p.archived_at or utcnow()
    ctx.audit("archive", "product", p.id)
    ctx.db.commit()
    return _out(p, _qty(ctx, p.id))


@router.post("/products/{product_id}/restore", response_model=ProductOut)
def restore_product(product_id: int, ctx: OrgContext = Depends(require("products.edit"))):
    p = _get(ctx, product_id)
    p.archived_at = None
    ctx.audit("restore", "product", p.id)
    ctx.db.commit()
    return _out(p, _qty(ctx, p.id))
