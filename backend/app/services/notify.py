"""Notifications: who gets what, in-app and by email.

- Events (device down, job assigned...) call `notify()` inside the same transaction as the change.
- Daily digests (overdue invoices, low stock...) are built by `run_digests()`, at most once per user, kind and
  business-local day (the dedupe key makes repeats harmless, even with several workers).
- Emails go through `email_outbox` and are sent by `deliver_emails()` with retries. Nothing is emailed unless
  SMTP is configured; the in-app bell always works.
- SMS/WhatsApp are not sent: they need a paid provider account. See docs/NOTIFICATIONS.md.
"""
import logging
import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage
from types import SimpleNamespace

from sqlalchemy import func, select

from ..config import get_settings
from ..models import Membership, Organization, Product, StockLevel, User, utcnow
from ..models_notify import EmailOutbox, Notification, NotificationPref
from ..permissions import has_permission
from .timeutil import today

log = logging.getLogger("netcare.notify")
MAX_ATTEMPTS = 5

# kind -> (label shown in preferences, permission the recipient needs or None for direct, email by default)
KINDS: dict[str, tuple[str, str | None, bool]] = {
    "monitor_down": ("A monitored device goes down or comes back", "monitoring.view", True),
    "agent_offline": ("A monitoring agent stops reporting (daily)", "monitoring.manage", False),
    "endpoint_critical": ("A PC's security becomes critical", "security.view", True),
    "ticket_assigned": ("A service job is assigned to you", None, True),
    "task_assigned": ("A task is assigned to you", None, False),
    "leave_request": ("A leave request needs a decision", "attendance.manage", False),
    "leave_decided": ("Your leave request is decided", None, False),
    "invoice_overdue": ("Customer invoices are overdue (daily)", "payments.view", False),
    "low_stock": ("Products below minimum stock (daily)", "inventory.view", False),
    "maintenance_due": ("Maintenance visits due (daily)", "service.edit", False),
    "documents_expiring": ("Documents expiring within 30 days (daily)", "documents.view", False),
}


def email_configured() -> bool:
    s = get_settings()
    return bool(s.smtp_host and s.smtp_from)


def members_with(db, org_id: int, perm: str | None) -> list[tuple[Membership, User]]:
    rows = db.execute(select(Membership, User).join(User, User.id == Membership.user_id).where(
        Membership.organization_id == org_id, Membership.is_active.is_(True), User.is_active.is_(True))).all()
    return [(m, u) for m, u in rows if perm is None or has_permission(m.role, perm)]


def _prefs(db, org_id: int, user_id: int, kind: str) -> tuple[bool, bool]:
    p = db.scalar(select(NotificationPref).where(NotificationPref.organization_id == org_id,
                                                 NotificationPref.user_id == user_id, NotificationPref.kind == kind))
    return (p.in_app, p.email) if p else (True, KINDS[kind][2])


def notify(db, org_id: int, kind: str, title: str, body: str | None = None, link: str | None = None,
           severity: str = "info", users: list[int] | None = None, dedupe: str | None = None) -> int:
    """Create notifications for the recipients (given user ids, else members with the kind's permission).
    Returns how many were created. Respects preferences; skips duplicates of `dedupe` per user."""
    perm = KINDS[kind][1]
    recipients = members_with(db, org_id, perm if users is None else None)
    if users is not None:
        wanted = set(users)
        recipients = [(m, u) for m, u in recipients if u.id in wanted]
    created = 0
    for _m, u in recipients:
        in_app, email = _prefs(db, org_id, u.id, kind)
        if not in_app and not (email and email_configured()):
            continue
        if dedupe and db.scalar(select(Notification.id).where(
                Notification.user_id == u.id, Notification.organization_id == org_id,
                Notification.dedupe_key == dedupe)):
            continue
        n = Notification(organization_id=org_id, user_id=u.id, kind=kind, severity=severity, title=title[:200],
                         body=body, link=link, dedupe_key=dedupe,
                         read_at=None if in_app else utcnow())  # email-only: nothing to show as unread
        db.add(n)
        db.flush()
        if email and email_configured() and u.email:
            url = get_settings().app_url.rstrip("/")
            text = "\n\n".join(x for x in (body, f"Open NetCare: {url}{link}" if url and link else None,
                                          "You can change which emails you get under Alerts > Preferences.") if x)
            db.add(EmailOutbox(organization_id=org_id, notification_id=n.id, to_address=u.email,
                               subject=f"[NetCare] {title}"[:200], body=text))
        created += 1
    return created


def notify_employee(db, org_id: int, employee_id: int | None, kind: str, title: str, body: str | None, link: str,
                    actor_id: int | None, dedupe: str | None = None) -> int:
    """Notify the login linked to an employee record, unless they did it themselves."""
    from ..models_service import Employee
    emp = db.get(Employee, employee_id) if employee_id else None
    if emp is None or emp.user_id is None or emp.user_id == actor_id:
        return 0
    return notify(db, org_id, kind, title, body, link, users=[emp.user_id], dedupe=dedupe)


# ---------------- daily digests ----------------
def _digest(db, org_id: int, kind: str, title: str, body: str, link: str, severity="warning",
            users: list[int] | None = None) -> int:
    return notify(db, org_id, kind, title, body, link, severity, users=users, dedupe=f"{kind}:{today()}")


def run_digests(db, org: Organization) -> int:
    from ..models_docs import StoredDocument
    from ..models_monitoring import MonitorAgent
    from ..models_service import MaintenanceSchedule
    from ..models_trade import SalesInvoice
    from ..routers.library import visible_query
    t, n = today(), 0

    overdue = db.scalars(select(SalesInvoice).where(
        SalesInvoice.organization_id == org.id, SalesInvoice.status.in_(("issued", "partially_paid")),
        SalesInvoice.due_date < t)).all()
    overdue = [i for i in overdue if i.total - i.amount_paid - i.credited_amount > 0]
    if overdue:
        due = sum(i.total - i.amount_paid - i.credited_amount for i in overdue)
        n += _digest(db, org.id, "invoice_overdue", f"{len(overdue)} invoice(s) overdue",
                     f"Rs {due:,.2f} is overdue. Oldest due date: {min(i.due_date for i in overdue):%d %b %Y}.",
                     "/sales")

    qty = dict(db.execute(select(StockLevel.product_id, func.sum(StockLevel.quantity)).where(
        StockLevel.organization_id == org.id).group_by(StockLevel.product_id)).all())
    low = [p for p in db.scalars(select(Product).where(
        Product.organization_id == org.id, Product.is_service.is_(False), Product.archived_at.is_(None),
        Product.min_stock > 0)) if (qty.get(p.id) or 0) < p.min_stock]
    if low:
        names = ", ".join(p.name for p in low[:5]) + (" and more" if len(low) > 5 else "")
        n += _digest(db, org.id, "low_stock", f"{len(low)} product(s) below minimum stock", names, "/products")

    maint = db.scalars(select(MaintenanceSchedule).where(
        MaintenanceSchedule.organization_id == org.id, MaintenanceSchedule.is_active.is_(True),
        MaintenanceSchedule.next_due <= t + timedelta(days=3))).all()
    if maint:
        late = sum(1 for m in maint if m.next_due < t)
        n += _digest(db, org.id, "maintenance_due", f"{len(maint)} maintenance visit(s) due",
                     f"{late} overdue, {len(maint) - late} due within 3 days.", "/service")

    stale = [a for a in db.scalars(select(MonitorAgent).where(
        MonitorAgent.organization_id == org.id, MonitorAgent.status == "active",
        MonitorAgent.last_seen_at.is_not(None))) if utcnow() - a.last_seen_at > timedelta(minutes=30)]
    if stale:
        n += _digest(db, org.id, "agent_offline", f"{len(stale)} monitoring agent(s) not reporting",
                     ", ".join(a.name for a in stale), "/monitoring")

    # Documents: each recipient sees only what they may see, so count per person.
    for m, u in members_with(db, org.id, KINDS["documents_expiring"][1]):
        ctx = SimpleNamespace(org_id=org.id, membership=m, db=db)
        count = db.scalar(select(func.count()).select_from(visible_query(ctx).where(
            StoredDocument.deleted_at.is_(None), StoredDocument.expires_on.is_not(None),
            StoredDocument.expires_on <= t + timedelta(days=30)).subquery()))
        if count:
            n += _digest(db, org.id, "documents_expiring", f"{count} document(s) expired or expiring soon",
                         "Contracts, warranty cards or licences need renewing.", "/documents", users=[u.id])
    return n


# ---------------- email ----------------
def _send(msg: EmailMessage) -> None:
    s = get_settings()
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
        if s.smtp_starttls:
            smtp.starttls(context=ssl.create_default_context())
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)


def deliver_emails(db, sender=None, limit: int = 50) -> dict:
    """Send due emails. Failures back off 2, 4, 8, 16 minutes and give up after MAX_ATTEMPTS."""
    if not email_configured():
        return {"sent": 0, "failed": 0}
    sender = sender or _send
    now, sent, failed = utcnow(), 0, 0
    rows = db.scalars(select(EmailOutbox).where(EmailOutbox.status == "pending", EmailOutbox.next_attempt_at <= now)
                      .order_by(EmailOutbox.id).limit(limit)).all()
    for e in rows:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = get_settings().smtp_from, e.to_address, e.subject
        msg.set_content(e.body)
        e.attempts += 1
        try:
            sender(msg)
            e.status, e.sent_at, e.last_error = "sent", utcnow(), None
            sent += 1
        except Exception as ex:  # any SMTP/network error: retry later, never crash the worker
            e.last_error = f"{type(ex).__name__}: {ex}"[:300]
            if e.attempts >= MAX_ATTEMPTS:
                e.status = "failed"
                failed += 1
            else:
                e.next_attempt_at = now + timedelta(minutes=2 ** e.attempts)
        db.commit()
    return {"sent": sent, "failed": failed}


def sweep(db) -> None:
    """One pass of the background worker: digests for every active business, then email delivery."""
    for org in db.scalars(select(Organization).where(Organization.is_active.is_(True))):
        try:
            run_digests(db, org)
            db.commit()
        except Exception:
            db.rollback()
            log.exception('"digest failed for organization %s"', org.id)
    deliver_emails(db)
