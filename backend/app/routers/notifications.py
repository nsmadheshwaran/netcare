"""Phase 9: the signed-in user's notifications and preferences; email outbox status for administrators."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, update

from ..deps import OrgContext, get_org_context, require
from ..models import utcnow
from ..models_notify import EmailOutbox, Notification, NotificationPref
from ..services import notify as nt

router = APIRouter(prefix="/notifications", tags=["notifications"])


class PrefIn(BaseModel):
    kind: str
    in_app: bool
    email: bool


def _mine(ctx: OrgContext):
    return select(Notification).where(Notification.user_id == ctx.user.id,
                                      Notification.organization_id == ctx.org_id)


def _out(n: Notification) -> dict:
    return {"id": n.id, "kind": n.kind, "severity": n.severity, "title": n.title, "body": n.body, "link": n.link,
            "created_at": n.created_at, "read_at": n.read_at}


@router.get("")
def list_notifications(ctx: OrgContext = Depends(get_org_context), unread: bool = False,
                       page: int = Query(1, ge=1), size: int = Query(30, ge=1, le=100)):
    q = _mine(ctx)
    if unread:
        q = q.where(Notification.read_at.is_(None))
    total = ctx.db.scalar(select(func.count()).select_from(q.subquery()))
    rows = ctx.db.scalars(q.order_by(Notification.id.desc()).offset((page - 1) * size).limit(size)).all()
    return {"items": [_out(n) for n in rows], "total": total, "page": page, "size": size}


@router.get("/unread-count")
def unread_count(ctx: OrgContext = Depends(get_org_context)):
    return {"unread": ctx.db.scalar(select(func.count()).select_from(
        _mine(ctx).where(Notification.read_at.is_(None)).subquery()))}


@router.post("/{nid}/read")
def mark_read(nid: int, ctx: OrgContext = Depends(get_org_context)):
    n = ctx.db.scalar(_mine(ctx).where(Notification.id == nid))
    if n is None:
        raise HTTPException(404, "Notification not found")
    n.read_at = n.read_at or utcnow()
    ctx.db.commit()
    return _out(n)


@router.post("/read-all")
def mark_all_read(ctx: OrgContext = Depends(get_org_context)):
    r = ctx.db.execute(update(Notification).where(
        Notification.user_id == ctx.user.id, Notification.organization_id == ctx.org_id,
        Notification.read_at.is_(None)).values(read_at=utcnow()))
    ctx.db.commit()
    return {"marked": r.rowcount}


@router.get("/preferences")
def get_preferences(ctx: OrgContext = Depends(get_org_context)):
    """Only kinds this user can receive are listed."""
    saved = {p.kind: p for p in ctx.db.scalars(select(NotificationPref).where(
        NotificationPref.user_id == ctx.user.id, NotificationPref.organization_id == ctx.org_id))}
    out = []
    for kind, (label, perm, email_default) in nt.KINDS.items():
        if perm and not ctx.can(perm):
            continue
        p = saved.get(kind)
        out.append({"kind": kind, "label": label, "in_app": p.in_app if p else True,
                    "email": p.email if p else email_default})
    return {"email_configured": nt.email_configured(), "email_address": ctx.user.email, "kinds": out}


@router.put("/preferences")
def set_preferences(body: list[PrefIn], ctx: OrgContext = Depends(get_org_context)):
    for b in body:
        if b.kind not in nt.KINDS:
            raise HTTPException(422, f"Unknown notification kind: {b.kind}")
        p = ctx.db.scalar(select(NotificationPref).where(
            NotificationPref.user_id == ctx.user.id, NotificationPref.organization_id == ctx.org_id,
            NotificationPref.kind == b.kind))
        if p is None:
            p = NotificationPref(user_id=ctx.user.id, organization_id=ctx.org_id, kind=b.kind)
            ctx.db.add(p)
        p.in_app, p.email = b.in_app, b.email
    ctx.db.commit()
    return get_preferences(ctx)


@router.post("/test-email")
def test_email(ctx: OrgContext = Depends(get_org_context)):
    """Queue a test email to yourself; it is sent within a minute by the worker."""
    if not nt.email_configured():
        raise HTTPException(409, "Email is not configured on this server (NETCARE_SMTP_HOST and NETCARE_SMTP_FROM)")
    ctx.db.add(EmailOutbox(organization_id=ctx.org_id, to_address=ctx.user.email,
                           subject="[NetCare] Test email", body="Email notifications from NetCare are working."))
    ctx.db.commit()
    return {"queued_to": ctx.user.email}


@router.get("/outbox")
def outbox(ctx: OrgContext = Depends(require("org.manage")), status: str | None = None):
    q = select(EmailOutbox).where(EmailOutbox.organization_id == ctx.org_id)
    if status:
        q = q.where(EmailOutbox.status == status)
    rows = ctx.db.scalars(q.order_by(EmailOutbox.id.desc()).limit(100)).all()
    return {"email_configured": nt.email_configured(),
            "items": [{"id": e.id, "to": e.to_address, "subject": e.subject, "status": e.status,
                       "attempts": e.attempts, "last_error": e.last_error, "created_at": e.created_at,
                       "sent_at": e.sent_at} for e in rows]}


@router.post("/run-digests")
def run_digests_now(ctx: OrgContext = Depends(require("org.manage"))):
    """Build today's digests now instead of waiting for the worker (already-sent ones are not repeated)."""
    n = nt.run_digests(ctx.db, ctx.org)
    ctx.db.commit()
    return {"created": n}
