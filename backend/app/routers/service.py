"""Service and repair: tickets, parts used, customer approval, billing, assets, maintenance, technician workspace."""
import calendar
import ipaddress
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import func, or_, select

from ..deps import OrgContext, require
from ..models import Customer, Location, Product, User, utcnow
from ..models_service import Asset, Employee, MaintenanceSchedule, ServiceTicket, Task, TicketEvent, TicketPart
from ..models_trade import SalesInvoice
from ..permissions import has_permission
from ..schemas import Page
from ..schemas_trade import InvoiceIn, InvoiceOut, LineIn
from ..services import billing, inventory
from ..services.pdf_docs import service_report_pdf
from ..services.timeutil import BUSINESS_TZ, today
from ..services.trade import active_customer, active_location, get_owned
from .employees import _task_out, current_employee
from .sales import _inv_out, _new_invoice

router = APIRouter(tags=["service"])
ZERO = Decimal("0")
OPEN = ("new", "assigned", "in_progress", "waiting_parts", "waiting_customer")
TRANSITIONS = {
    "new": {"assigned", "in_progress", "waiting_customer", "cancelled"},
    "assigned": {"in_progress", "waiting_parts", "waiting_customer", "cancelled"},
    "in_progress": {"waiting_parts", "waiting_customer", "completed", "cancelled"},
    "waiting_parts": {"in_progress", "cancelled"},
    "waiting_customer": {"in_progress", "assigned", "cancelled"},
    "completed": {"closed", "in_progress"},  # in_progress = reopen
    "closed": set(),
    "cancelled": set(),
}
MANAGER_ONLY = {"cancelled", "closed"}


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _event(ctx: OrgContext, t: ServiceTicket, kind: str, message: str):
    # Through the relationship, so the in-memory ticket shows the new entry in this response.
    t.events.append(TicketEvent(kind=kind, message=message, user_id=ctx.user.id))


def _notify_assigned(ctx: OrgContext, t: ServiceTicket) -> None:
    from ..services.notify import notify_employee
    cust = ctx.db.get(Customer, t.customer_id)
    visit = f" Visit: {t.scheduled_visit.astimezone(BUSINESS_TZ):%d %b %H:%M}." if t.scheduled_visit else ""
    notify_employee(ctx.db, ctx.org_id, t.assigned_to, "ticket_assigned", f"Job {t.number} assigned to you",
                    f"{cust.name}: {t.reported_problem[:200]}.{visit}", "/my-work", ctx.user.id)


def _can_work(ctx: OrgContext, t: ServiceTicket) -> None:
    """service.edit may touch any ticket; service.work only tickets assigned to the caller."""
    role = ctx.membership.role
    if has_permission(role, "service.edit"):
        return
    if has_permission(role, "service.work"):
        me = current_employee(ctx)
        if me and t.assigned_to == me.id:
            return
        raise HTTPException(403, "This ticket is not assigned to you")
    raise HTTPException(403, "Missing permission: service.work")


# ---------------- schemas ----------------
TicketType = Literal["repair", "installation", "maintenance", "complaint"]
Priority = Literal["low", "normal", "high", "urgent"]


class TicketIn(BaseModel):
    ticket_type: TicketType
    customer_id: int
    priority: Priority = "normal"
    contact_name: str | None = Field(default=None, max_length=200)
    contact_phone: str | None = Field(default=None, max_length=30)
    asset_id: int | None = None
    equipment: str | None = Field(default=None, max_length=200)
    serial_number: str | None = Field(default=None, max_length=100)
    accessories_received: str | None = None
    reported_problem: str = Field(min_length=3)
    location_id: int | None = None
    assigned_to: int | None = None
    scheduled_visit: datetime | None = None
    estimate_amount: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    labour_charge: Decimal = Field(default=ZERO, ge=0, max_digits=14, decimal_places=2)
    is_warranty: bool = False


class TicketUpdate(BaseModel):
    """Fields a technician fills in while working. All optional; only sent fields change."""
    priority: Priority | None = None
    diagnosis: str | None = None
    work_performed: str | None = None
    resolution: str | None = None
    estimate_amount: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    labour_charge: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    is_warranty: bool | None = None
    scheduled_visit: datetime | None = None
    contact_name: str | None = None
    contact_phone: str | None = None


class PartOut(ORM):
    id: int
    product_id: int
    product_name: str | None = None
    sku: str | None = None
    quantity: Decimal
    unit_price: Decimal
    unit_cost: Decimal | None
    returned: bool = False
    created_at: datetime


class EventOut(ORM):
    id: int
    kind: str
    message: str
    user_id: int | None
    user_name: str | None = None
    created_at: datetime


class TicketOut(ORM):
    id: int
    number: str
    ticket_type: str
    priority: str
    status: str
    customer_id: int
    customer_name: str | None = None
    contact_name: str | None
    contact_phone: str | None
    asset_id: int | None
    asset_name: str | None = None
    equipment: str | None
    serial_number: str | None
    accessories_received: str | None
    reported_problem: str
    diagnosis: str | None
    work_performed: str | None
    resolution: str | None
    assigned_to: int | None
    technician_name: str | None = None
    scheduled_visit: datetime | None
    location_id: int
    estimate_amount: Decimal | None
    labour_charge: Decimal
    customer_approval: str
    approval_note: str | None
    approved_at: datetime | None
    is_warranty: bool
    maintenance_schedule_id: int | None
    sales_invoice_id: int | None
    invoice_number: str | None = None
    parts_total: Decimal = ZERO
    charges_total: Decimal = ZERO
    completed_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    parts: list[PartOut] = []
    events: list[EventOut] = []


def _ticket_out(ctx: OrgContext, t: ServiceTicket, detail: bool = False) -> TicketOut:
    o = TicketOut.model_validate({**{c: getattr(t, c) for c in TicketOut.model_fields
                                     if hasattr(t, c) and c not in ("parts", "events")}})
    o.customer_name = ctx.db.get(Customer, t.customer_id).name
    if t.asset_id:
        o.asset_name = ctx.db.get(Asset, t.asset_id).name
    if t.assigned_to:
        o.technician_name = ctx.db.get(Employee, t.assigned_to).name
    if t.sales_invoice_id:
        inv = ctx.db.get(SalesInvoice, t.sales_invoice_id)
        o.invoice_number = inv.number or f"draft #{inv.id}"
    live = [p for p in t.parts if p.returned_movement_id is None]
    o.parts_total = sum((Decimal(p.quantity) * Decimal(p.unit_price) for p in live), ZERO)
    o.charges_total = ZERO if t.is_warranty else o.parts_total + Decimal(t.labour_charge)
    if detail:
        parts = []
        for p in t.parts:
            po = PartOut.model_validate(p)
            prod = ctx.db.get(Product, p.product_id)
            po.product_name, po.sku, po.returned = prod.name, prod.sku, p.returned_movement_id is not None
            parts.append(po)
        o.parts = parts
        evs = []
        for e in t.events:
            eo = EventOut.model_validate(e)
            u = ctx.db.get(User, e.user_id) if e.user_id else None
            eo.user_name = u.full_name if u else None
            evs.append(eo)
        o.events = evs
    return o


def _check_assignee(ctx: OrgContext, emp_id: int | None) -> Employee | None:
    if emp_id is None:
        return None
    emp = get_owned(ctx, Employee, emp_id, "Employee", status_code=422)
    if emp.status != "active":
        raise HTTPException(422, f"{emp.name} is not an active employee")
    return emp


def _check_asset(ctx: OrgContext, asset_id: int | None, customer_id: int) -> Asset | None:
    if asset_id is None:
        return None
    a = get_owned(ctx, Asset, asset_id, "Asset", status_code=422)
    if a.customer_id != customer_id:
        raise HTTPException(422, "That equipment belongs to a different customer")
    return a


def _default_location(ctx: OrgContext) -> int:
    loc = ctx.db.scalar(select(Location.id).where(Location.organization_id == ctx.org_id,
                                                  Location.is_active.is_(True)).order_by(Location.id))
    if loc is None:
        raise HTTPException(422, "Create a location first")
    return loc


# ---------------- tickets ----------------
@router.get("/service-tickets", response_model=Page[TicketOut])
def list_tickets(ctx: OrgContext = Depends(require("service.view")), status: str | None = None,
                 ticket_type: str | None = None, assigned_to: int | None = None, customer_id: int | None = None,
                 mine: bool = False, q: str | None = None, page: int = Query(1, ge=1),
                 size: int = Query(25, ge=1, le=200)):
    base = select(ServiceTicket).join(Customer, Customer.id == ServiceTicket.customer_id).where(
        ServiceTicket.organization_id == ctx.org_id)
    if status == "open":
        base = base.where(ServiceTicket.status.in_(OPEN))
    elif status:
        base = base.where(ServiceTicket.status == status)
    if ticket_type:
        base = base.where(ServiceTicket.ticket_type == ticket_type)
    if mine:
        me = current_employee(ctx)
        base = base.where(ServiceTicket.assigned_to == (me.id if me else -1))
    elif assigned_to:
        base = base.where(ServiceTicket.assigned_to == assigned_to)
    if customer_id:
        base = base.where(ServiceTicket.customer_id == customer_id)
    if q:
        base = base.where(or_(ServiceTicket.number.ilike(f"%{q}%"), Customer.name.ilike(f"%{q}%"),
                              ServiceTicket.serial_number.ilike(f"%{q}%"), ServiceTicket.equipment.ilike(f"%{q}%"),
                              ServiceTicket.contact_phone.ilike(f"%{q}%")))
    total = ctx.db.scalar(select(func.count()).select_from(base.subquery()))
    prio = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    rows = ctx.db.scalars(base.order_by(ServiceTicket.id.desc()).offset((page - 1) * size).limit(size)).all()
    items = [_ticket_out(ctx, t) for t in rows]
    items.sort(key=lambda t: (t.status not in OPEN, prio.get(t.priority, 9)))  # open + urgent first within page
    return Page(items=items, total=total, page=page, size=size)


@router.post("/service-tickets", response_model=TicketOut, status_code=201)
def create_ticket(body: TicketIn, ctx: OrgContext = Depends(require("service.edit"))):
    customer = active_customer(ctx, body.customer_id)
    asset = _check_asset(ctx, body.asset_id, customer.id)
    emp = _check_assignee(ctx, body.assigned_to)
    loc_id = body.location_id or _default_location(ctx)
    active_location(ctx, loc_id)
    data = body.model_dump(exclude={"location_id"})
    if asset and not data.get("serial_number"):
        data["serial_number"] = asset.serial_number
    t = ServiceTicket(organization_id=ctx.org_id, location_id=loc_id, created_by=ctx.user.id,
                      status="assigned" if emp else "new",
                      customer_approval="pending" if body.estimate_amount and not body.is_warranty else "not_required",
                      contact_name=body.contact_name or customer.contact_person or customer.name,
                      contact_phone=body.contact_phone or customer.phone,
                      number=billing.next_number(ctx.db, ctx.org_id, "service_ticket", today()),
                      **{k: v for k, v in data.items() if k not in ("contact_name", "contact_phone")})
    ctx.db.add(t)
    ctx.db.flush()
    _event(ctx, t, "created", f"{body.ticket_type.title()} ticket opened: {body.reported_problem[:200]}")
    if emp:
        _event(ctx, t, "assigned", f"Assigned to {emp.name}")
        _notify_assigned(ctx, t)
    ctx.audit("create", "service_ticket", t.id, {"number": t.number})
    ctx.db.commit()
    return _ticket_out(ctx, t, detail=True)


@router.get("/service-tickets/{tid}", response_model=TicketOut)
def get_ticket(tid: int, ctx: OrgContext = Depends(require("service.view"))):
    return _ticket_out(ctx, get_owned(ctx, ServiceTicket, tid, "Ticket"), detail=True)


@router.patch("/service-tickets/{tid}", response_model=TicketOut)
def update_ticket(tid: int, body: TicketUpdate, ctx: OrgContext = Depends(require("service.view"))):
    t = get_owned(ctx, ServiceTicket, tid, "Ticket", lock=True)
    _can_work(ctx, t)
    if t.status in ("closed", "cancelled"):
        raise HTTPException(409, f"Ticket is {t.status}")
    changes = body.model_dump(exclude_unset=True)
    if t.sales_invoice_id and ({"labour_charge", "is_warranty"} & changes.keys()):
        raise HTTPException(409, "Charges are locked once the ticket has been invoiced")
    for k, v in changes.items():
        setattr(t, k, v)
    if "estimate_amount" in changes and not t.is_warranty:
        if changes["estimate_amount"] and t.customer_approval in ("not_required", "declined"):
            t.customer_approval = "pending"
            _event(ctx, t, "approval", f"Estimate of Rs {changes['estimate_amount']} awaiting customer approval")
    if "scheduled_visit" in changes and changes["scheduled_visit"]:
        _event(ctx, t, "visit", f"Visit scheduled for {changes['scheduled_visit'].astimezone(BUSINESS_TZ):%d %b %Y %H:%M}")
    for k in ("diagnosis", "work_performed", "resolution"):
        if changes.get(k):
            _event(ctx, t, "note", f"{k.replace('_', ' ').capitalize()}: {changes[k][:300]}")
    ctx.audit("update", "service_ticket", t.id, {"fields": sorted(changes)})
    ctx.db.commit()
    return _ticket_out(ctx, t, detail=True)


class AssignIn(BaseModel):
    employee_id: int | None
    scheduled_visit: datetime | None = None


@router.post("/service-tickets/{tid}/assign", response_model=TicketOut)
def assign_ticket(tid: int, body: AssignIn, ctx: OrgContext = Depends(require("service.edit"))):
    t = get_owned(ctx, ServiceTicket, tid, "Ticket", lock=True)
    if t.status not in OPEN:
        raise HTTPException(409, f"Ticket is {t.status}")
    emp = _check_assignee(ctx, body.employee_id)
    changed = t.assigned_to != (emp.id if emp else None)
    t.assigned_to = emp.id if emp else None
    if body.scheduled_visit:
        t.scheduled_visit = body.scheduled_visit
    if emp and t.status == "new":
        t.status = "assigned"
    _event(ctx, t, "assigned", f"Assigned to {emp.name}" if emp else "Unassigned")
    if emp and changed:
        _notify_assigned(ctx, t)
    ctx.audit("assign", "service_ticket", t.id, {"employee": body.employee_id})
    ctx.db.commit()
    return _ticket_out(ctx, t, detail=True)


class StatusIn(BaseModel):
    status: Literal["new", "assigned", "in_progress", "waiting_parts", "waiting_customer", "completed", "closed",
                    "cancelled"]
    note: str | None = Field(default=None, max_length=1000)


@router.post("/service-tickets/{tid}/status", response_model=TicketOut)
def change_status(tid: int, body: StatusIn, ctx: OrgContext = Depends(require("service.view"))):
    t = get_owned(ctx, ServiceTicket, tid, "Ticket", lock=True)
    _can_work(ctx, t)
    new = body.status
    if new in MANAGER_ONLY and not has_permission(ctx.membership.role, "service.edit"):
        raise HTTPException(403, f"Only the office can mark a ticket {new}")
    if new not in TRANSITIONS[t.status]:
        raise HTTPException(409, f"Cannot move a {t.status.replace('_', ' ')} ticket to {new.replace('_', ' ')}")
    if new == "in_progress" and t.customer_approval in ("pending", "declined"):
        raise HTTPException(409, "The customer has not approved the estimate yet")
    if new == "assigned" and not t.assigned_to:
        raise HTTPException(409, "Assign a technician first")
    if new == "completed" and not (t.work_performed or "").strip():
        raise HTTPException(409, "Record the work performed before completing")
    live_parts = [p for p in t.parts if p.returned_movement_id is None]
    if new == "cancelled" and live_parts:
        raise HTTPException(409, "Return the parts used to stock (or keep the ticket) before cancelling")
    if new == "cancelled" and t.sales_invoice_id:
        raise HTTPException(409, "Ticket has an invoice; cancel the invoice first")
    if new == "closed":
        chargeable = (not t.is_warranty) and (live_parts or Decimal(t.labour_charge) > 0)
        if chargeable and not t.sales_invoice_id:
            raise HTTPException(409, "Create the invoice for this job first, or mark it as warranty / no charge")
    old = t.status
    t.status = new
    now = utcnow()
    if new == "completed":
        t.completed_at = now
        if t.maintenance_schedule_id:
            s = ctx.db.get(MaintenanceSchedule, t.maintenance_schedule_id)
            done = today()
            s.last_done, s.next_due = done, add_months(done, s.interval_months)
            _event(ctx, t, "note", f"Maintenance schedule advanced; next due {s.next_due:%d %b %Y}")
    elif new == "in_progress" and old == "completed":
        t.completed_at = None
    elif new == "closed":
        t.closed_at = now
    _event(ctx, t, "status", f"{old.replace('_', ' ').title()} -> {new.replace('_', ' ').title()}"
                             + (f": {body.note}" if body.note else ""))
    ctx.audit("status", "service_ticket", t.id, {"from": old, "to": new})
    ctx.db.commit()
    return _ticket_out(ctx, t, detail=True)


class NoteIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@router.post("/service-tickets/{tid}/notes", response_model=TicketOut)
def add_note(tid: int, body: NoteIn, ctx: OrgContext = Depends(require("service.view"))):
    """Record communication: calls, customer messages, internal notes."""
    t = get_owned(ctx, ServiceTicket, tid, "Ticket")
    if not (has_permission(ctx.membership.role, "service.edit") or has_permission(ctx.membership.role, "service.work")):
        raise HTTPException(403, "Missing permission: service.work")
    if not has_permission(ctx.membership.role, "service.edit"):
        _can_work(ctx, t)
    _event(ctx, t, "note", body.message)
    ctx.db.commit()
    return _ticket_out(ctx, t, detail=True)


class ApprovalIn(BaseModel):
    decision: Literal["approved", "declined"]
    note: str | None = Field(default=None, max_length=1000)  # e.g. "Approved by phone, spoke to Mr. Ravi"


@router.post("/service-tickets/{tid}/approval", response_model=TicketOut)
def record_approval(tid: int, body: ApprovalIn, ctx: OrgContext = Depends(require("service.view"))):
    t = get_owned(ctx, ServiceTicket, tid, "Ticket", lock=True)
    _can_work(ctx, t)
    if t.customer_approval != "pending":
        raise HTTPException(409, "No estimate is awaiting approval")
    t.customer_approval, t.approval_note, t.approved_at = body.decision, body.note, utcnow()
    _event(ctx, t, "approval", f"Customer {body.decision} the estimate of Rs {t.estimate_amount}"
                               + (f": {body.note}" if body.note else ""))
    ctx.audit(body.decision, "service_estimate", t.id, {"amount": str(t.estimate_amount), "note": body.note})
    ctx.db.commit()
    return _ticket_out(ctx, t, detail=True)


# ---------------- parts ----------------
class PartIn(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    idempotency_key: str | None = Field(default=None, max_length=60)


@router.post("/service-tickets/{tid}/parts", response_model=TicketOut, status_code=201)
def add_part(tid: int, body: PartIn, ctx: OrgContext = Depends(require("service.view"))):
    t = get_owned(ctx, ServiceTicket, tid, "Ticket", lock=True)
    _can_work(ctx, t)
    if t.status not in OPEN and t.status != "completed":
        raise HTTPException(409, f"Ticket is {t.status}")
    if t.sales_invoice_id:
        raise HTTPException(409, "Ticket is already invoiced; add further parts on a new ticket or invoice")
    product = get_owned(ctx, Product, body.product_id, "Product", status_code=422)
    if product.is_service:
        raise HTTPException(422, "Services are charged as labour, not as parts")
    key = f"tkt{t.id}:{body.idempotency_key}" if body.idempotency_key else None
    mv = inventory.apply_movement(ctx.db, org_id=ctx.org_id, user_id=ctx.user.id, product_id=product.id,
                                  location_id=t.location_id, movement_type="service_part", quantity=body.quantity,
                                  reference=t.number, idempotency_key=key)
    if key and ctx.db.scalar(select(TicketPart.id).where(TicketPart.stock_movement_id == mv.id)):
        return _ticket_out(ctx, t, detail=True)  # replayed request
    price = body.unit_price if body.unit_price is not None else product.selling_price
    t.parts.append(TicketPart(product_id=product.id, quantity=body.quantity, unit_price=price,
                              unit_cost=mv.unit_cost, stock_movement_id=mv.id, added_by=ctx.user.id))
    _event(ctx, t, "part", f"Used {body.quantity.normalize():f} x {product.name} (from stock)")
    ctx.audit("part_used", "service_ticket", t.id, {"product": product.id, "qty": str(body.quantity)})
    ctx.db.commit()
    return _ticket_out(ctx, t, detail=True)


@router.post("/service-tickets/{tid}/parts/{part_id}/return", response_model=TicketOut)
def return_part(tid: int, part_id: int, ctx: OrgContext = Depends(require("service.view"))):
    """Part was not used after all: put it back in stock at the cost it left at."""
    t = get_owned(ctx, ServiceTicket, tid, "Ticket", lock=True)
    _can_work(ctx, t)
    p = ctx.db.get(TicketPart, part_id)
    if p is None or p.ticket_id != t.id:
        raise HTTPException(404, "Part not found on this ticket")
    if p.returned_movement_id:
        raise HTTPException(409, "Part already returned")
    if t.sales_invoice_id:
        raise HTTPException(409, "Ticket is invoiced; use a credit note on the invoice instead")
    mv = inventory.apply_movement(ctx.db, org_id=ctx.org_id, user_id=ctx.user.id, product_id=p.product_id,
                                  location_id=t.location_id, movement_type="service_part_return",
                                  quantity=p.quantity, unit_cost=p.unit_cost, reference=f"Return {t.number}")
    p.returned_movement_id = mv.id
    _event(ctx, t, "part", f"Returned {Decimal(p.quantity).normalize():f} x {ctx.db.get(Product, p.product_id).name} to stock")
    ctx.audit("part_returned", "service_ticket", t.id, {"part": p.id})
    ctx.db.commit()
    return _ticket_out(ctx, t, detail=True)


# ---------------- billing ----------------
class TicketInvoiceIn(BaseModel):
    location_id: int | None = None
    labour_product_id: int | None = None  # a service product carrying the labour HSN/SAC and GST rate
    labour_tax_rate: Decimal | None = Field(default=None, ge=0, le=100)
    prices_include_tax: bool | None = None


@router.post("/service-tickets/{tid}/invoice", response_model=InvoiceOut, status_code=201)
def invoice_ticket(tid: int, body: TicketInvoiceIn, ctx: OrgContext = Depends(require("service.edit"))):
    """Draft invoice for the parts and labour on a completed job. Parts are already out of stock,
    so issuing this invoice will not deduct them again."""
    if not has_permission(ctx.membership.role, "sales.edit"):
        raise HTTPException(403, "Missing permission: sales.edit")
    t = get_owned(ctx, ServiceTicket, tid, "Ticket", lock=True)
    if t.status not in ("completed", "closed"):
        raise HTTPException(409, "Complete the job before invoicing")
    if t.is_warranty:
        raise HTTPException(409, "Warranty jobs are not charged")
    if t.sales_invoice_id:
        existing = ctx.db.get(SalesInvoice, t.sales_invoice_id)
        if existing.status != "cancelled":
            raise HTTPException(409, f"Already invoiced ({existing.number or 'draft'})")
    parts = [p for p in t.parts if p.returned_movement_id is None]
    lines: list[LineIn] = [LineIn(product_id=p.product_id, quantity=p.quantity, unit_price=p.unit_price)
                           for p in parts]
    if Decimal(t.labour_charge) > 0:
        if body.labour_product_id:
            lp = get_owned(ctx, Product, body.labour_product_id, "Labour product", status_code=422)
            if not lp.is_service:
                raise HTTPException(422, "Labour must be billed with a service product")
            lines.append(LineIn(product_id=lp.id, description=f"Labour: {t.number}", quantity=Decimal("1"),
                                unit_price=t.labour_charge))
        elif body.labour_tax_rate is not None:
            lines.append(LineIn(description=f"Service charges ({t.number})", quantity=Decimal("1"),
                                unit_price=t.labour_charge, tax_rate=body.labour_tax_rate))
        else:
            raise HTTPException(422, "Choose a labour service product or give the GST rate for labour")
    if not lines:
        raise HTTPException(409, "Nothing to invoice: no parts or labour recorded")
    inv = _new_invoice(ctx, InvoiceIn(customer_id=t.customer_id, location_id=body.location_id or t.location_id,
                                      invoice_date=today(), lines=lines, prices_include_tax=body.prices_include_tax,
                                      notes=f"Service job {t.number}"))
    for line, part in zip(inv.lines, parts):
        line.ticket_part_id = part.id
    t.sales_invoice_id = inv.id
    _event(ctx, t, "invoice", f"Draft invoice created for Rs {inv.total}")
    ctx.audit("invoice", "service_ticket", t.id, {"invoice_id": inv.id})
    ctx.db.commit()
    return _inv_out(ctx, inv)


# ---------------- assets ----------------
AssetType = Literal["camera", "dvr", "nvr", "storage", "computer", "laptop", "printer", "router", "switch",
                    "server", "ups", "access_point", "other"]


class AssetIn(BaseModel):
    customer_id: int
    asset_type: AssetType
    name: str = Field(min_length=1, max_length=200)
    product_id: int | None = None
    brand: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    serial_number: str | None = Field(default=None, max_length=100)
    site_location: str | None = Field(default=None, max_length=200)
    ip_address: str | None = Field(default=None, max_length=45)
    installed_on: date | None = None
    warranty_until: date | None = None
    sales_invoice_id: int | None = None
    status: Literal["active", "replaced", "retired"] = "active"
    notes: str | None = None
    mac_address: str | None = Field(default=None, max_length=17)
    firmware: str | None = Field(default=None, max_length=60)
    recorder_id: int | None = None
    channel: int | None = Field(default=None, ge=1, le=256)
    resolution: str | None = Field(default=None, max_length=20)
    hdd_capacity_gb: int | None = Field(default=None, ge=0, le=1_000_000)
    retention_days: int | None = Field(default=None, ge=0, le=3650)

    @model_validator(mode="after")
    def _clean(self):
        if self.serial_number == "":
            self.serial_number = None
        if self.mac_address:
            mac = re.sub(r"[^0-9A-Fa-f]", "", self.mac_address)
            if len(mac) != 12:
                raise ValueError("Invalid MAC address")
            self.mac_address = ":".join(mac[i:i + 2] for i in range(0, 12, 2)).upper()
        else:
            self.mac_address = None
        if self.channel is not None and self.recorder_id is None:
            raise ValueError("A channel needs a recorder")
        if self.ip_address:
            try:
                ipaddress.ip_address(self.ip_address)
            except ValueError:
                raise ValueError("Invalid IP address")
        else:
            self.ip_address = None
        return self


class AssetOut(AssetIn, ORM):
    id: int
    customer_name: str | None = None
    recorder_name: str | None = None
    monitor_status: str | None = None  # worst status of its enabled monitoring checks, if any
    warranty_status: str = "unknown"  # in_warranty | expiring | expired | unknown
    open_tickets: int = 0
    installed_by_ticket_id: int | None = None


def _asset_out(ctx: OrgContext, a: Asset) -> AssetOut:
    o = AssetOut.model_validate(a)
    o.customer_name = ctx.db.get(Customer, a.customer_id).name
    t = today()
    if a.warranty_until:
        o.warranty_status = "expired" if a.warranty_until < t else \
            "expiring" if a.warranty_until <= t + timedelta(days=30) else "in_warranty"
    o.open_tickets = ctx.db.scalar(select(func.count()).select_from(ServiceTicket).where(
        ServiceTicket.asset_id == a.id, ServiceTicket.status.in_(OPEN)))
    if a.recorder_id:
        o.recorder_name = ctx.db.get(Asset, a.recorder_id).name
    from .monitoring import asset_monitor_status  # local import: monitoring imports this module's models
    o.monitor_status = asset_monitor_status(ctx, a.id)
    return o


def _validate_asset(ctx: OrgContext, body: AssetIn, exclude_id: int | None = None):
    active_customer(ctx, body.customer_id)
    if body.product_id is not None:
        get_owned(ctx, Product, body.product_id, "Product", status_code=422)
    if body.sales_invoice_id is not None:
        inv = get_owned(ctx, SalesInvoice, body.sales_invoice_id, "Invoice", status_code=422)
        if inv.customer_id != body.customer_id:
            raise HTTPException(422, "Invoice belongs to another customer")
    if body.recorder_id is not None:
        rec = get_owned(ctx, Asset, body.recorder_id, "Recorder", status_code=422)
        if rec.asset_type not in ("dvr", "nvr") or rec.id == exclude_id:
            raise HTTPException(422, "The recorder must be a DVR or NVR")
        if rec.customer_id != body.customer_id:
            raise HTTPException(422, "The recorder is at another customer's site")
        if body.channel is not None:
            q = select(Asset.id).where(Asset.recorder_id == rec.id, Asset.channel == body.channel)
            if exclude_id:
                q = q.where(Asset.id != exclude_id)
            if ctx.db.scalar(q):
                raise HTTPException(409, f"Channel {body.channel} of {rec.name} is already used")
    if body.serial_number:
        q = select(Asset.id).where(Asset.organization_id == ctx.org_id, Asset.serial_number == body.serial_number)
        if exclude_id:
            q = q.where(Asset.id != exclude_id)
        if ctx.db.scalar(q):
            raise HTTPException(409, f"Serial number {body.serial_number} is already registered")


@router.get("/assets", response_model=Page[AssetOut])
def list_assets(ctx: OrgContext = Depends(require("assets.view")), customer_id: int | None = None,
                asset_type: str | None = None, q: str | None = None, warranty: str | None = None,
                status: str | None = "active", page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200)):
    base = select(Asset).join(Customer, Customer.id == Asset.customer_id).where(Asset.organization_id == ctx.org_id)
    if customer_id:
        base = base.where(Asset.customer_id == customer_id)
    if asset_type:
        base = base.where(Asset.asset_type == asset_type)
    if status:
        base = base.where(Asset.status == status)
    t = today()
    if warranty == "expiring":
        base = base.where(Asset.warranty_until >= t, Asset.warranty_until <= t + timedelta(days=30))
    elif warranty == "expired":
        base = base.where(Asset.warranty_until < t)
    elif warranty == "in_warranty":
        base = base.where(Asset.warranty_until >= t)
    if q:
        base = base.where(or_(Asset.name.ilike(f"%{q}%"), Asset.serial_number.ilike(f"%{q}%"),
                              Asset.ip_address.ilike(f"%{q}%"), Customer.name.ilike(f"%{q}%"),
                              Asset.site_location.ilike(f"%{q}%")))
    total = ctx.db.scalar(select(func.count()).select_from(base.subquery()))
    rows = ctx.db.scalars(base.order_by(Customer.name, Asset.asset_type, Asset.name)
                          .offset((page - 1) * size).limit(size)).all()
    return Page(items=[_asset_out(ctx, a) for a in rows], total=total, page=page, size=size)


@router.post("/assets", response_model=AssetOut, status_code=201)
def create_asset(body: AssetIn, ctx: OrgContext = Depends(require("assets.edit"))):
    _validate_asset(ctx, body)
    a = Asset(organization_id=ctx.org_id, **body.model_dump())
    ctx.db.add(a)
    ctx.db.flush()
    ctx.audit("create", "asset", a.id, {"name": a.name, "serial": a.serial_number})
    ctx.db.commit()
    return _asset_out(ctx, a)


@router.get("/assets/{asset_id}", response_model=AssetOut)
def get_asset(asset_id: int, ctx: OrgContext = Depends(require("assets.view"))):
    return _asset_out(ctx, get_owned(ctx, Asset, asset_id, "Asset"))


@router.put("/assets/{asset_id}", response_model=AssetOut)
def update_asset(asset_id: int, body: AssetIn, ctx: OrgContext = Depends(require("assets.edit"))):
    a = get_owned(ctx, Asset, asset_id, "Asset")
    _validate_asset(ctx, body, exclude_id=a.id)
    changed = {k: v for k, v in body.model_dump().items() if getattr(a, k) != v}
    for k, v in changed.items():
        setattr(a, k, v)
    ctx.audit("update", "asset", a.id, {"fields": sorted(changed)})
    ctx.db.commit()
    return _asset_out(ctx, a)


@router.get("/assets/{asset_id}/history", response_model=list[TicketOut])
def asset_history(asset_id: int, ctx: OrgContext = Depends(require("service.view"))):
    a = get_owned(ctx, Asset, asset_id, "Asset")
    return [_ticket_out(ctx, t) for t in ctx.db.scalars(
        select(ServiceTicket).where(ServiceTicket.asset_id == a.id).order_by(ServiceTicket.id.desc()))]


class ReplaceIn(BaseModel):
    new_asset: AssetIn
    reason: str = Field(min_length=3, max_length=500)


@router.post("/assets/{asset_id}/replace", response_model=AssetOut, status_code=201)
def replace_asset(asset_id: int, body: ReplaceIn, ctx: OrgContext = Depends(require("assets.edit"))):
    """Record a replacement: the old unit is kept as history and points at its successor."""
    old = get_owned(ctx, Asset, asset_id, "Asset", lock=True)
    if old.status != "active":
        raise HTTPException(409, "Only an active asset can be replaced")
    if body.new_asset.customer_id != old.customer_id:
        raise HTTPException(422, "Replacement must be at the same customer")
    _validate_asset(ctx, body.new_asset)
    new = Asset(organization_id=ctx.org_id, **body.new_asset.model_dump())
    ctx.db.add(new)
    ctx.db.flush()
    old.status, old.replaced_by_id = "replaced", new.id
    old.notes = ((old.notes or "") + f"\nReplaced on {today()}: {body.reason}").strip()
    ctx.audit("replace", "asset", old.id, {"new": new.id, "reason": body.reason})
    ctx.db.commit()
    return _asset_out(ctx, new)


class InstallAssetIn(BaseModel):
    asset_type: AssetType
    name: str = Field(min_length=1, max_length=200)
    product_id: int | None = None
    brand: str | None = None
    model: str | None = None
    serial_number: str | None = None
    site_location: str | None = None
    ip_address: str | None = None
    warranty_months: int | None = Field(default=None, ge=0, le=120)


class InstallMaintenanceIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    interval_months: int = Field(ge=1, le=60)


class RegisterAssetsIn(BaseModel):
    assets: list[InstallAssetIn] = Field(min_length=1, max_length=200)
    installed_on: date | None = None
    maintenance: InstallMaintenanceIn | None = None


@router.post("/service-tickets/{tid}/assets", response_model=list[AssetOut], status_code=201)
def register_installed_assets(tid: int, body: RegisterAssetsIn, ctx: OrgContext = Depends(require("assets.edit"))):
    """After an installation: register the equipment at the customer, with warranty dates, and optionally
    start a maintenance schedule. All or nothing."""
    t = get_owned(ctx, ServiceTicket, tid, "Ticket", lock=True)
    if t.status in ("cancelled",):
        raise HTTPException(409, "Ticket is cancelled")
    installed = body.installed_on or today()
    serials = [a.serial_number for a in body.assets if a.serial_number]
    if len(serials) != len(set(serials)):
        raise HTTPException(422, "Duplicate serial numbers in the list")
    out = []
    for a in body.assets:
        data = a.model_dump(exclude={"warranty_months"})
        try:
            ai = AssetIn(customer_id=t.customer_id, installed_on=installed,
                         warranty_until=add_months(installed, a.warranty_months) if a.warranty_months else None,
                         sales_invoice_id=t.sales_invoice_id, **data)
        except ValidationError as e:  # raised inside the handler, so FastAPI would otherwise answer 500
            raise HTTPException(422, f"{a.name}: " + "; ".join(err["msg"] for err in e.errors()))
        _validate_asset(ctx, ai)
        asset = Asset(organization_id=ctx.org_id, installed_by_ticket_id=t.id, **ai.model_dump())
        ctx.db.add(asset)
        ctx.db.flush()
        out.append(asset)
    if body.maintenance:
        s = MaintenanceSchedule(organization_id=ctx.org_id, customer_id=t.customer_id, title=body.maintenance.title,
                                interval_months=body.maintenance.interval_months, assigned_to=t.assigned_to,
                                next_due=add_months(installed, body.maintenance.interval_months))
        ctx.db.add(s)
        _event(ctx, t, "note", f"Maintenance every {s.interval_months} month(s) scheduled from {installed:%d %b %Y}")
    _event(ctx, t, "note", f"Registered {len(out)} item(s) at the customer site")
    ctx.audit("register_assets", "service_ticket", t.id, {"count": len(out)})
    ctx.db.commit()
    return [_asset_out(ctx, a) for a in out]


# ---------------- maintenance ----------------
class ScheduleIn(BaseModel):
    customer_id: int
    asset_id: int | None = None
    title: str = Field(min_length=3, max_length=200)
    interval_months: int = Field(ge=1, le=60)
    next_due: date
    assigned_to: int | None = None
    is_active: bool = True
    notes: str | None = None


class ScheduleOut(ScheduleIn, ORM):
    id: int
    last_done: date | None
    customer_name: str | None = None
    technician_name: str | None = None
    overdue: bool = False
    open_ticket_id: int | None = None


def _sched_out(ctx: OrgContext, s: MaintenanceSchedule) -> ScheduleOut:
    o = ScheduleOut.model_validate(s)
    o.customer_name = ctx.db.get(Customer, s.customer_id).name
    o.technician_name = ctx.db.get(Employee, s.assigned_to).name if s.assigned_to else None
    o.overdue = s.is_active and s.next_due < today()
    o.open_ticket_id = ctx.db.scalar(select(ServiceTicket.id).where(
        ServiceTicket.maintenance_schedule_id == s.id, ServiceTicket.status.in_(OPEN)))
    return o


@router.get("/maintenance-schedules", response_model=list[ScheduleOut])
def list_schedules(ctx: OrgContext = Depends(require("service.view")), due_within_days: int | None = None,
                   customer_id: int | None = None, include_inactive: bool = False):
    q = select(MaintenanceSchedule).where(MaintenanceSchedule.organization_id == ctx.org_id)
    if not include_inactive:
        q = q.where(MaintenanceSchedule.is_active.is_(True))
    if customer_id:
        q = q.where(MaintenanceSchedule.customer_id == customer_id)
    if due_within_days is not None:
        q = q.where(MaintenanceSchedule.next_due <= today() + timedelta(days=due_within_days))
    return [_sched_out(ctx, s) for s in ctx.db.scalars(q.order_by(MaintenanceSchedule.next_due))]


def _check_schedule(ctx: OrgContext, body: ScheduleIn):
    active_customer(ctx, body.customer_id)
    _check_asset(ctx, body.asset_id, body.customer_id)
    _check_assignee(ctx, body.assigned_to)


@router.post("/maintenance-schedules", response_model=ScheduleOut, status_code=201)
def create_schedule(body: ScheduleIn, ctx: OrgContext = Depends(require("service.edit"))):
    _check_schedule(ctx, body)
    s = MaintenanceSchedule(organization_id=ctx.org_id, **body.model_dump())
    ctx.db.add(s)
    ctx.db.flush()
    ctx.audit("create", "maintenance_schedule", s.id, {"title": s.title})
    ctx.db.commit()
    return _sched_out(ctx, s)


@router.put("/maintenance-schedules/{sid}", response_model=ScheduleOut)
def update_schedule(sid: int, body: ScheduleIn, ctx: OrgContext = Depends(require("service.edit"))):
    s = get_owned(ctx, MaintenanceSchedule, sid, "Schedule")
    _check_schedule(ctx, body)
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    ctx.audit("update", "maintenance_schedule", s.id)
    ctx.db.commit()
    return _sched_out(ctx, s)


@router.post("/maintenance-schedules/{sid}/ticket", response_model=TicketOut, status_code=201)
def ticket_from_schedule(sid: int, ctx: OrgContext = Depends(require("service.edit"))):
    s = get_owned(ctx, MaintenanceSchedule, sid, "Schedule", lock=True)
    if not s.is_active:
        raise HTTPException(409, "Schedule is inactive")
    if ctx.db.scalar(select(ServiceTicket.id).where(ServiceTicket.maintenance_schedule_id == s.id,
                                                    ServiceTicket.status.in_(OPEN))):
        raise HTTPException(409, "A maintenance ticket for this schedule is already open")
    t = create_ticket(TicketIn(ticket_type="maintenance", customer_id=s.customer_id, asset_id=s.asset_id,
                               reported_problem=f"Scheduled maintenance: {s.title}", assigned_to=s.assigned_to),
                      ctx)
    ticket = ctx.db.get(ServiceTicket, t.id)
    ticket.maintenance_schedule_id = s.id
    ctx.db.commit()
    return _ticket_out(ctx, ticket, detail=True)


# ---------------- technician workspace ----------------
@router.get("/my-work")
def my_work(ctx: OrgContext = Depends(require("tasks.view"))):
    me = current_employee(ctx)
    if me is None:
        return {"employee": None, "tickets": [], "visits_today": [], "tasks": [], "completed_this_month": 0}
    t0 = today()
    start = datetime.combine(t0, time.min, BUSINESS_TZ)
    tickets = ctx.db.scalars(select(ServiceTicket).where(ServiceTicket.organization_id == ctx.org_id,
                                                         ServiceTicket.assigned_to == me.id,
                                                         ServiceTicket.status.in_(OPEN))
                             .order_by(ServiceTicket.scheduled_visit.is_(None), ServiceTicket.scheduled_visit)).all()
    visits = [t for t in tickets if t.scheduled_visit and start <= t.scheduled_visit < start + timedelta(days=1)]
    month_start = datetime.combine(t0.replace(day=1), time.min, BUSINESS_TZ)
    done = ctx.db.scalar(select(func.count()).select_from(ServiceTicket).where(
        ServiceTicket.assigned_to == me.id, ServiceTicket.completed_at >= month_start))
    tasks = ctx.db.scalars(select(Task).where(Task.organization_id == ctx.org_id, Task.assigned_to == me.id,
                                              Task.status.in_(["todo", "in_progress"]))
                           .order_by(Task.due_date.is_(None), Task.due_date)).all()
    return {"employee": {"id": me.id, "name": me.name},
            "tickets": [_ticket_out(ctx, t).model_dump(mode="json", exclude={"parts", "events"}) for t in tickets],
            "visits_today": [t.id for t in visits],
            "tasks": [_task_out(ctx, x).model_dump(mode="json") for x in tasks],
            "completed_this_month": done}


# ---------------- job sheet PDF ----------------
@router.get("/service-tickets/{tid}/pdf")
def ticket_pdf(tid: int, ctx: OrgContext = Depends(require("service.view")), download: bool = False):
    t = get_owned(ctx, ServiceTicket, tid, "Ticket")
    out = _ticket_out(ctx, t, detail=True)
    installed = ctx.db.scalars(select(Asset).where(Asset.organization_id == ctx.org_id,
                                                   Asset.installed_by_ticket_id == t.id).order_by(Asset.id)).all()
    body = service_report_pdf(ctx.org, out, ctx.db.get(Customer, t.customer_id), installed)
    disp = "attachment" if download else "inline"
    return Response(body, media_type="application/pdf",
                    headers={"Content-Disposition": f'{disp}; filename="{t.number.replace("/", "-")}.pdf"'})
