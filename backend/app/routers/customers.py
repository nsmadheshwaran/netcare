import csv
import io
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy import func, or_, select

from ..deps import OrgContext, require
from ..models import Customer, utcnow
from ..schemas import CustomerIn, CustomerOut, Page

router = APIRouter(prefix="/customers", tags=["customers"])

SORTABLE = {"name": Customer.name, "created_at": Customer.created_at, "city": Customer.city}
CSV_FIELDS = list(CustomerIn.model_fields)
MAX_IMPORT_BYTES = 2 * 1024 * 1024


def _get(ctx: OrgContext, customer_id: int) -> Customer:
    c = ctx.db.get(Customer, customer_id)
    if not c or c.organization_id != ctx.org_id:
        raise HTTPException(404, "Customer not found")
    return c


def _find_duplicate(ctx: OrgContext, data: dict, exclude_id: int | None = None) -> Customer | None:
    conds = []
    if data.get("phone"):
        conds.append(Customer.phone == data["phone"])
    if data.get("email"):
        conds.append(func.lower(Customer.email) == data["email"].lower())
    if data.get("gstin"):
        conds.append(Customer.gstin == data["gstin"])
    if not conds:
        return None
    q = select(Customer).where(Customer.organization_id == ctx.org_id, Customer.archived_at.is_(None), or_(*conds))
    if exclude_id:
        q = q.where(Customer.id != exclude_id)
    return ctx.db.scalars(q).first()


@router.get("", response_model=Page[CustomerOut])
def list_customers(ctx: OrgContext = Depends(require("customers.view")),
                   q: str | None = None, status: str | None = None, category: str | None = None,
                   archived: bool = False, sort: str = "name", order: str = Query("asc", pattern="^(asc|desc)$"),
                   page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=200)):
    base = select(Customer).where(Customer.organization_id == ctx.org_id)
    base = base.where(Customer.archived_at.is_not(None) if archived else Customer.archived_at.is_(None))
    if q:
        like = f"%{q.lower()}%"
        base = base.where(or_(func.lower(Customer.name).like(like), func.lower(Customer.business_name).like(like),
                              Customer.phone.like(f"%{q}%"), func.lower(Customer.email).like(like),
                              func.upper(Customer.gstin).like(f"%{q.upper()}%")))
    if status:
        base = base.where(Customer.status == status)
    if category:
        base = base.where(Customer.category == category)
    total = ctx.db.scalar(select(func.count()).select_from(base.subquery()))
    col = SORTABLE.get(sort, Customer.name)
    rows = ctx.db.scalars(base.order_by(col.desc() if order == "desc" else col.asc(), Customer.id)
                          .offset((page - 1) * size).limit(size)).all()
    return Page(items=rows, total=total, page=page, size=size)


@router.post("", response_model=CustomerOut, status_code=201)
def create_customer(body: CustomerIn, ctx: OrgContext = Depends(require("customers.edit")),
                    allow_duplicate: bool = False):
    data = body.model_dump()
    if not allow_duplicate and (dup := _find_duplicate(ctx, data)):
        raise HTTPException(409, f"Possible duplicate of customer #{dup.id} ({dup.name}). "
                                 "Pass allow_duplicate=true to create anyway.")
    c = Customer(organization_id=ctx.org_id, **data)
    ctx.db.add(c)
    ctx.db.flush()
    ctx.audit("create", "customer", c.id, {"name": c.name})
    ctx.db.commit()
    return c


@router.get("/export.csv")
def export_customers(ctx: OrgContext = Depends(require("customers.view")), archived: bool = False):
    q = select(Customer).where(Customer.organization_id == ctx.org_id)
    q = q.where(Customer.archived_at.is_not(None) if archived else Customer.archived_at.is_(None))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", *CSV_FIELDS, "created_at"])
    for c in ctx.db.scalars(q.order_by(Customer.id)):
        # Prefix formula-like cells to avoid CSV injection when opened in Excel.
        vals = [getattr(c, f) for f in CSV_FIELDS]
        vals = ["'" + v if isinstance(v, str) and v[:1] in "=+-@" else v for v in vals]
        w.writerow([c.id, *vals, c.created_at.isoformat()])
    ctx.audit("export", "customer", None, {"format": "csv"})
    ctx.db.commit()
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="customers.csv"'})


@router.post("/import")
async def import_customers(ctx: OrgContext = Depends(require("customers.edit")),
                           file: UploadFile = File(...),
                           mapping: str = Form("{}", description='JSON {"csv column": "customer field"}'),
                           commit: bool = Form(False), skip_duplicates: bool = Form(True)):
    """Preview (commit=false, default) or import customers from CSV.

    Unmapped columns whose header matches a field name are mapped automatically.
    Nothing is written unless commit=true, and then only rows that validated.
    """
    raw = await file.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        raise HTTPException(413, "CSV larger than 2 MB")
    try:
        text = raw.decode("utf-8-sig")
        col_map = json.loads(mapping)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(422, "File must be UTF-8 CSV and mapping must be valid JSON")
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    for h in headers:
        if h not in col_map and h.strip().lower() in CSV_FIELDS:
            col_map[h] = h.strip().lower()
    bad = [f for f in col_map.values() if f not in CSV_FIELDS]
    if bad:
        raise HTTPException(422, f"Unknown target fields: {bad}")

    results, valid, seen = [], [], set()
    for i, row in enumerate(reader, start=2):
        data = {field: (row.get(col) or "").strip() for col, field in col_map.items()}
        data = {k: v for k, v in data.items() if v != ""}
        try:
            parsed = CustomerIn(**data).model_dump()
        except ValidationError as e:
            results.append({"row": i, "status": "error",
                            "errors": [f"{'.'.join(map(str, er['loc']))}: {er['msg']}" for er in e.errors()]})
            continue
        keys = {(f, str(parsed[f]).lower()) for f in ("phone", "email", "gstin") if parsed.get(f)}
        dup = _find_duplicate(ctx, parsed)
        in_file_dup = bool(keys & seen)
        seen |= keys
        if dup or in_file_dup:
            results.append({"row": i, "status": "duplicate", "name": parsed["name"],
                            "duplicate_of": dup.id if dup else "earlier row in file"})
            if skip_duplicates:
                continue
        else:
            results.append({"row": i, "status": "ok", "name": parsed["name"]})
        valid.append(parsed)

    created = 0
    if commit and valid:
        for d in valid:
            ctx.db.add(Customer(organization_id=ctx.org_id, **d))
        created = len(valid)
        ctx.audit("import", "customer", None, {"created": created, "file": file.filename})
        ctx.db.commit()
    return {"headers": headers, "mapping": col_map, "committed": commit, "created": created,
            "summary": {s: sum(1 for r in results if r["status"] == s) for s in ("ok", "duplicate", "error")},
            "rows": results[:500]}


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: int, ctx: OrgContext = Depends(require("customers.view"))):
    return _get(ctx, customer_id)


@router.put("/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: int, body: CustomerIn, ctx: OrgContext = Depends(require("customers.edit"))):
    c = _get(ctx, customer_id)
    data = body.model_dump()
    changed = {k: v for k, v in data.items() if getattr(c, k) != v}
    for k, v in changed.items():
        setattr(c, k, v)
    ctx.audit("update", "customer", c.id, {"fields": sorted(changed)})
    ctx.db.commit()
    return c


@router.post("/{customer_id}/archive", response_model=CustomerOut)
def archive_customer(customer_id: int, ctx: OrgContext = Depends(require("customers.edit"))):
    c = _get(ctx, customer_id)
    c.archived_at = c.archived_at or utcnow()
    ctx.audit("archive", "customer", c.id)
    ctx.db.commit()
    return c


@router.post("/{customer_id}/restore", response_model=CustomerOut)
def restore_customer(customer_id: int, ctx: OrgContext = Depends(require("customers.edit"))):
    c = _get(ctx, customer_id)
    c.archived_at = None
    ctx.audit("restore", "customer", c.id)
    ctx.db.commit()
    return c
