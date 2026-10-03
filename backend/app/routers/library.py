"""Phase 5: document library. Secure upload, attach to records, download, delete/restore/purge.

Access is checked twice: the documents.* permission, and view permission on the record the file is attached
to (a salesperson cannot see an expense receipt by guessing its id). Sensitive documents need
documents.sensitive. Every download is audited.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from ..config import get_settings
from ..deps import OrgContext, require
from ..models import Customer, Product, User, utcnow
from ..models_docs import StoredDocument
from ..models_finance import FinanceEntry
from ..models_service import Asset, Employee, ServiceTicket
from ..models_trade import PurchaseInvoice, PurchaseOrder, SalesInvoice, Supplier
from ..permissions import has_permission
from ..schemas import Page
from ..services import storage
from ..services.timeutil import today
from ..services.trade import get_owned
from .service import _can_work

router = APIRouter(prefix="/documents", tags=["documents"])

CATEGORIES = ["invoice", "bill", "receipt", "quotation", "warranty", "contract", "photo", "id_proof", "manual",
              "licence", "report", "other"]

# entity_type -> (model, permission needed to see the record, label for display)
ENTITIES = {
    "customer": (Customer, "customers.view", lambda o: o.name),
    "supplier": (Supplier, "suppliers.view", lambda o: o.name),
    "product": (Product, "products.view", lambda o: o.name),
    "sales_invoice": (SalesInvoice, "sales.view", lambda o: o.number or f"Draft #{o.id}"),
    "purchase_invoice": (PurchaseInvoice, "purchases.view", lambda o: f"{o.number} ({o.supplier_invoice_number})"),
    "purchase_order": (PurchaseOrder, "purchases.view", lambda o: o.number),
    "expense": (FinanceEntry, "expenses.view", lambda o: o.number),
    "service_ticket": (ServiceTicket, "service.view", lambda o: o.number),
    "asset": (Asset, "assets.view", lambda o: o.name),
    "employee": (Employee, "employees.view", lambda o: o.name),
}
ENTITY_TYPES = ["general", *ENTITIES]


class DocOut(BaseModel):
    id: int
    entity_type: str
    entity_id: int | None
    entity_label: str | None
    title: str
    category: str
    tags: str | None
    notes: str | None
    expires_on: date | None
    is_sensitive: bool
    original_name: str
    content_type: str
    extension: str
    size_bytes: int
    sha256: str
    uploaded_by_name: str | None
    created_at: str
    deleted_at: str | None
    delete_reason: str | None


class DocUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    category: str | None = None
    tags: str | None = Field(None, max_length=200)
    notes: str | None = Field(None, max_length=2000)
    expires_on: date | None = None
    is_sensitive: bool | None = None


class Reason(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


def _can(ctx: OrgContext, perm: str) -> bool:
    return has_permission(ctx.membership.role, perm)


def visible_types(ctx: OrgContext) -> list[str]:
    return ["general"] + [t for t, (_, perm, _) in ENTITIES.items() if _can(ctx, perm)]


def visible_query(ctx: OrgContext):
    """Documents this caller may see, not purged. Deleted ones are filtered separately."""
    q = select(StoredDocument).where(StoredDocument.organization_id == ctx.org_id,
                                     StoredDocument.purged_at.is_(None),
                                     StoredDocument.entity_type.in_(visible_types(ctx)))
    if not _can(ctx, "documents.sensitive"):
        q = q.where(StoredDocument.is_sensitive.is_(False))
    return q


def _target(ctx: OrgContext, entity_type: str, entity_id: int | None):
    """Validate the record a document is attached to; returns it (None for general)."""
    if entity_type not in ENTITY_TYPES:
        raise HTTPException(422, f"entity_type must be one of {ENTITY_TYPES}")
    if entity_type == "general":
        if entity_id is not None:
            raise HTTPException(422, "General documents are not attached to a record")
        return None
    model, perm, _ = ENTITIES[entity_type]
    if not _can(ctx, perm):
        raise HTTPException(403, f"Missing permission: {perm}")
    return get_owned(ctx, model, entity_id, entity_type.replace("_", " ").capitalize(), status_code=422)


def _check_edit_target(ctx: OrgContext, entity_type: str, obj) -> None:
    # Technicians (service.work) may add photos and reports only to their own jobs.
    if entity_type == "service_ticket":
        _can_work(ctx, obj)


def _get(ctx: OrgContext, doc_id: int, *, include_deleted: bool = False) -> StoredDocument:
    d = ctx.db.scalar(visible_query(ctx).where(StoredDocument.id == doc_id))
    if d is None or (d.deleted_at is not None and not include_deleted):
        raise HTTPException(404, "Document not found")
    return d


def _out(ctx: OrgContext, d: StoredDocument) -> DocOut:
    label = None
    if d.entity_type != "general":
        model, _, fn = ENTITIES[d.entity_type]
        obj = ctx.db.get(model, d.entity_id)
        label = fn(obj) if obj else None
    user = ctx.db.get(User, d.uploaded_by) if d.uploaded_by else None
    return DocOut(id=d.id, entity_type=d.entity_type, entity_id=d.entity_id, entity_label=label, title=d.title,
                  category=d.category, tags=d.tags, notes=d.notes, expires_on=d.expires_on,
                  is_sensitive=d.is_sensitive, original_name=d.original_name, content_type=d.content_type,
                  extension=d.extension, size_bytes=d.size_bytes, sha256=d.sha256,
                  uploaded_by_name=user.full_name if user else None, created_at=d.created_at.isoformat(),
                  deleted_at=d.deleted_at.isoformat() if d.deleted_at else None, delete_reason=d.delete_reason)


def _used_bytes(ctx: OrgContext) -> int:
    return ctx.db.scalar(select(func.coalesce(func.sum(StoredDocument.size_bytes), 0)).where(
        StoredDocument.organization_id == ctx.org_id, StoredDocument.purged_at.is_(None))) or 0


@router.get("/meta")
def meta(ctx: OrgContext = Depends(require("documents.view"))):
    s = get_settings()
    return {"categories": CATEGORIES, "entity_types": visible_types(ctx), "max_upload_bytes": s.max_upload_mb << 20,
            "quota_bytes": s.org_storage_quota_mb << 20, "used_bytes": _used_bytes(ctx),
            "can_see_sensitive": _can(ctx, "documents.sensitive"), "can_purge": _can(ctx, "documents.purge")}


@router.get("", response_model=Page[DocOut])
def list_documents(ctx: OrgContext = Depends(require("documents.view")), q: str | None = None,
                   entity_type: str | None = None, entity_id: int | None = None, category: str | None = None,
                   expiring_days: int | None = Query(None, ge=0, le=3650), deleted: bool = False,
                   page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200)):
    if deleted and not _can(ctx, "documents.sensitive"):
        raise HTTPException(403, "Only owners and managers can see deleted documents")
    base = visible_query(ctx).where(StoredDocument.deleted_at.is_not(None) if deleted
                                    else StoredDocument.deleted_at.is_(None))
    if entity_type:
        base = base.where(StoredDocument.entity_type == entity_type)
    if entity_id is not None:
        base = base.where(StoredDocument.entity_id == entity_id)
    if category:
        base = base.where(StoredDocument.category == category)
    if expiring_days is not None:
        base = base.where(StoredDocument.expires_on.is_not(None),
                          StoredDocument.expires_on <= today() + timedelta(days=expiring_days))
    if q:
        like = f"%{q}%"
        base = base.where(or_(StoredDocument.title.ilike(like), StoredDocument.original_name.ilike(like),
                              StoredDocument.tags.ilike(like), StoredDocument.notes.ilike(like)))
    total = ctx.db.scalar(select(func.count()).select_from(base.subquery()))
    order = StoredDocument.expires_on if expiring_days is not None else StoredDocument.id.desc()
    rows = ctx.db.scalars(base.order_by(order).offset((page - 1) * size).limit(size)).all()
    return Page(items=[_out(ctx, d) for d in rows], total=total, page=page, size=size)


@router.post("", response_model=DocOut, status_code=201)
async def upload(file: UploadFile = File(...), entity_type: str = Form("general"),
                 entity_id: int | None = Form(None), title: str | None = Form(None, max_length=200),
                 category: str = Form("other"), tags: str | None = Form(None, max_length=200),
                 notes: str | None = Form(None, max_length=2000), expires_on: date | None = Form(None),
                 is_sensitive: bool = Form(False), ctx: OrgContext = Depends(require("documents.edit"))):
    if category not in CATEGORIES:
        raise HTTPException(422, f"category must be one of {CATEGORIES}")
    if is_sensitive and not _can(ctx, "documents.sensitive"):
        raise HTTPException(403, "Only owners and managers can file sensitive documents")
    obj = _target(ctx, entity_type, entity_id)
    _check_edit_target(ctx, entity_type, obj)

    s = get_settings()
    limit = s.max_upload_mb << 20
    data = await file.read(limit + 1)
    if not data:
        raise HTTPException(422, "The file is empty")
    if len(data) > limit:
        raise HTTPException(413, f"Files must be {s.max_upload_mb} MB or smaller")
    if _used_bytes(ctx) + len(data) > s.org_storage_quota_mb << 20:
        raise HTTPException(507, "Document storage for this business is full. Purge deleted documents or "
                                 "ask your administrator to raise the limit")
    try:
        kind = storage.detect(data, file.filename or "")
    except storage.Rejected as e:
        raise HTTPException(422, str(e))

    name = storage.safe_name(file.filename or "document", kind.extension)
    key, sha = storage.save(ctx.org_id, data)
    dup = ctx.db.scalar(select(StoredDocument.id).where(
        StoredDocument.organization_id == ctx.org_id, StoredDocument.sha256 == sha,
        StoredDocument.entity_type == entity_type,
        StoredDocument.entity_id.is_(None) if entity_id is None else StoredDocument.entity_id == entity_id,
        StoredDocument.deleted_at.is_(None), StoredDocument.purged_at.is_(None)))
    if dup:
        storage.remove(key)
        raise HTTPException(409, f"This file is already attached here (document #{dup})")
    d = StoredDocument(organization_id=ctx.org_id, entity_type=entity_type, entity_id=entity_id,
                       title=(title or "").strip() or name.rsplit(".", 1)[0], category=category,
                       tags=tags or None, notes=notes or None, expires_on=expires_on,
                       is_sensitive=is_sensitive, original_name=name, content_type=kind.content_type,
                       extension=kind.extension, size_bytes=len(data), sha256=sha, storage_key=key,
                       uploaded_by=ctx.user.id)
    ctx.db.add(d)
    try:
        ctx.db.flush()
        ctx.audit("upload", "document", d.id, {"name": name, "bytes": len(data), "type": kind.content_type,
                                               "entity": entity_type, "entity_id": entity_id})
        ctx.db.commit()
    except Exception:
        ctx.db.rollback()
        storage.remove(key)  # no orphan files when the row could not be saved
        raise
    return _out(ctx, d)


@router.get("/{doc_id}", response_model=DocOut)
def get_document(doc_id: int, ctx: OrgContext = Depends(require("documents.view"))):
    return _out(ctx, _get(ctx, doc_id, include_deleted=_can(ctx, "documents.sensitive")))


@router.patch("/{doc_id}", response_model=DocOut)
def update_document(doc_id: int, body: DocUpdate, ctx: OrgContext = Depends(require("documents.edit"))):
    d = _get(ctx, doc_id)
    _check_edit_target(ctx, d.entity_type, _target(ctx, d.entity_type, d.entity_id))
    changes = body.model_dump(exclude_unset=True)
    if "category" in changes and changes["category"] not in CATEGORIES:
        raise HTTPException(422, f"category must be one of {CATEGORIES}")
    if "is_sensitive" in changes and changes["is_sensitive"] != d.is_sensitive \
            and not _can(ctx, "documents.sensitive"):
        raise HTTPException(403, "Only owners and managers can change the sensitive flag")
    if changes.get("title") is None:
        changes.pop("title", None)
    for k, v in changes.items():
        setattr(d, k, v)
    ctx.audit("update", "document", d.id, {"fields": list(changes)})
    ctx.db.commit()
    return _out(ctx, d)


@router.get("/{doc_id}/download")
def download(doc_id: int, inline: bool = False, ctx: OrgContext = Depends(require("documents.view"))):
    d = _get(ctx, doc_id)
    try:
        body = storage.read(d.storage_key)
    except FileNotFoundError:
        raise HTTPException(410, "The stored file is missing. Restore it from backup")
    disp = "inline" if inline and d.content_type in storage.INLINE_OK else "attachment"
    ctx.audit("download", "document", d.id, {"inline": disp == "inline"})
    ctx.db.commit()
    ascii_name = d.original_name.encode("ascii", "replace").decode().replace("?", "_")
    return Response(body, media_type=d.content_type, headers={
        "Content-Disposition": f'{disp}; filename="{ascii_name}"',
        # Even if a file slipped through, it cannot run script on our origin.
        "Content-Security-Policy": "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox",
        "Cache-Control": "private, no-store",
    })


@router.post("/{doc_id}/delete", response_model=DocOut)
def delete_document(doc_id: int, body: Reason, ctx: OrgContext = Depends(require("documents.edit"))):
    d = _get(ctx, doc_id)
    _check_edit_target(ctx, d.entity_type, _target(ctx, d.entity_type, d.entity_id))
    d.deleted_at, d.deleted_by, d.delete_reason = utcnow(), ctx.user.id, body.reason
    ctx.audit("delete", "document", d.id, {"reason": body.reason})
    ctx.db.commit()
    return _out(ctx, d)


@router.post("/{doc_id}/restore", response_model=DocOut)
def restore_document(doc_id: int, ctx: OrgContext = Depends(require("documents.sensitive"))):
    d = _get(ctx, doc_id, include_deleted=True)
    if d.deleted_at is None:
        raise HTTPException(409, "Document is not deleted")
    d.deleted_at = d.deleted_by = d.delete_reason = None
    ctx.audit("restore", "document", d.id)
    ctx.db.commit()
    return _out(ctx, d)


@router.post("/{doc_id}/purge", status_code=204)
def purge_document(doc_id: int, ctx: OrgContext = Depends(require("documents.purge"))):
    """Permanently remove the file of a deleted document. The row stays as an audit tombstone."""
    d = _get(ctx, doc_id, include_deleted=True)
    if d.deleted_at is None:
        raise HTTPException(409, "Delete the document before purging it")
    d.purged_at = utcnow()
    ctx.audit("purge", "document", d.id, {"name": d.original_name, "sha256": d.sha256})
    ctx.db.commit()
    storage.remove(d.storage_key)  # after commit: a failed commit must not lose the file
