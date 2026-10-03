"""Phase 4: employees, attendance, leave, tasks, customer assets, service tickets, maintenance schedules.

Payroll and statutory employment compliance are deliberately not modelled.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .models import MONEY, QTY, Boolean, TimestampMixin, UTCDateTime, utcnow


# ---------------- people ----------------
class Employee(TimestampMixin, Base):
    __tablename__ = "employees"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),
                      UniqueConstraint("organization_id", "employee_code"))
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # linked login, if any
    employee_code: Mapped[str | None] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(200))
    job_role: Mapped[str | None] = mapped_column(String(80))  # e.g. Technician, Sales executive
    department: Mapped[str | None] = mapped_column(String(80))
    joining_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | inactive | left
    is_technician: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)


class Attendance(Base):
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("employee_id", "work_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    work_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(15))  # present | absent | half_day | leave | holiday | week_off
    check_in: Mapped[str | None] = mapped_column(String(5))  # HH:MM local time
    check_out: Mapped[str | None] = mapped_column(String(5))
    note: Mapped[str | None] = mapped_column(String(200))
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class LeaveRequest(TimestampMixin, Base):
    __tablename__ = "leave_requests"
    __table_args__ = (CheckConstraint("end_date >= start_date", name="ck_leave_dates"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    leave_type: Mapped[str] = mapped_column(String(20))  # casual | sick | earned | unpaid | other
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | approved | rejected | cancelled
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    decision_note: Mapped[str | None] = mapped_column(Text)


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_org_status", "organization_id", "status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), index=True)
    priority: Mapped[str] = mapped_column(String(10), default="normal")  # low | normal | high | urgent
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(15), default="todo")  # todo | in_progress | done | cancelled
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("service_tickets.id"))
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


# ---------------- customer equipment ----------------
class Asset(TimestampMixin, Base):
    """Equipment at a customer site: cameras, DVRs, computers, routers... The base for service history,
    warranty tracking and (later) monitoring."""
    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("organization_id", "serial_number"),
                      UniqueConstraint("recorder_id", "channel", name="uq_assets_recorder_channel"),
                      Index("ix_assets_org_customer", "organization_id", "customer_id"))
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    asset_type: Mapped[str] = mapped_column(String(20))
    # camera | dvr | nvr | storage | computer | laptop | printer | router | switch | server | ups | other
    name: Mapped[str] = mapped_column(String(200))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    brand: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    serial_number: Mapped[str | None] = mapped_column(String(100))
    site_location: Mapped[str | None] = mapped_column(String(200))  # "Main gate, pole 2"
    ip_address: Mapped[str | None] = mapped_column(String(45))
    installed_on: Mapped[date | None] = mapped_column(Date)
    warranty_until: Mapped[date | None] = mapped_column(Date, index=True)
    sales_invoice_id: Mapped[int | None] = mapped_column(ForeignKey("sales_invoices.id"))
    # Plain id, no FK: tickets already reference assets, and a two-way FK cycle breaks table creation.
    installed_by_ticket_id: Mapped[int | None] = mapped_column(Integer)
    replaced_by_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"))
    status: Mapped[str] = mapped_column(String(15), default="active")  # active | replaced | retired
    notes: Mapped[str | None] = mapped_column(Text)
    # Phase 6: device and CCTV details
    mac_address: Mapped[str | None] = mapped_column(String(17))
    firmware: Mapped[str | None] = mapped_column(String(60))
    recorder_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", name="fk_assets_recorder_id"), index=True)  # camera -> DVR/NVR
    channel: Mapped[int | None] = mapped_column(Integer)  # recorder channel the camera is on
    resolution: Mapped[str | None] = mapped_column(String(20))  # "2MP", "4K"
    hdd_capacity_gb: Mapped[int | None] = mapped_column(Integer)  # recorders and storage
    retention_days: Mapped[int | None] = mapped_column(Integer)  # how many days the recorder keeps


# ---------------- service ----------------
class ServiceTicket(TimestampMixin, Base):
    __tablename__ = "service_tickets"
    __table_args__ = (UniqueConstraint("organization_id", "number"),
                      Index("ix_tickets_org_status", "organization_id", "status"),
                      CheckConstraint("labour_charge >= 0", name="ck_ticket_labour"))
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    number: Mapped[str] = mapped_column(String(40))
    ticket_type: Mapped[str] = mapped_column(String(15))  # repair | installation | maintenance | complaint
    priority: Mapped[str] = mapped_column(String(10), default="normal")
    status: Mapped[str] = mapped_column(String(20), default="new")
    # new | assigned | in_progress | waiting_parts | waiting_customer | completed | closed | cancelled
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    contact_name: Mapped[str | None] = mapped_column(String(200))
    contact_phone: Mapped[str | None] = mapped_column(String(30))
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"))
    equipment: Mapped[str | None] = mapped_column(String(200))  # walk-in item not registered as an asset
    serial_number: Mapped[str | None] = mapped_column(String(100))
    accessories_received: Mapped[str | None] = mapped_column(Text)  # "charger, bag" for bench repairs
    reported_problem: Mapped[str] = mapped_column(Text)
    diagnosis: Mapped[str | None] = mapped_column(Text)
    work_performed: Mapped[str | None] = mapped_column(Text)
    resolution: Mapped[str | None] = mapped_column(Text)
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), index=True)
    scheduled_visit: Mapped[datetime | None] = mapped_column(UTCDateTime())
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))  # parts are drawn from here
    estimate_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    labour_charge: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    customer_approval: Mapped[str] = mapped_column(String(15), default="not_required")
    # not_required | pending | approved | declined
    approval_note: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    is_warranty: Mapped[bool] = mapped_column(Boolean, default=False)  # no charge to customer
    maintenance_schedule_id: Mapped[int | None] = mapped_column(ForeignKey("maintenance_schedules.id"))
    sales_invoice_id: Mapped[int | None] = mapped_column(ForeignKey("sales_invoices.id"))
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    parts: Mapped[list["TicketPart"]] = relationship(order_by="TicketPart.id")
    events: Mapped[list["TicketEvent"]] = relationship(order_by="TicketEvent.id")


class TicketPart(Base):
    """A part used on a job. Stock is deducted when the part is recorded, whether or not it is billed."""
    __tablename__ = "ticket_parts"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_ticket_part_qty"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("service_tickets.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[Decimal] = mapped_column(QTY)
    unit_price: Mapped[Decimal] = mapped_column(MONEY)  # price to charge the customer
    unit_cost: Mapped[Decimal | None] = mapped_column(MONEY)  # average cost when used
    stock_movement_id: Mapped[int | None] = mapped_column(ForeignKey("stock_movements.id"))
    returned_movement_id: Mapped[int | None] = mapped_column(ForeignKey("stock_movements.id"))  # if removed
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class TicketEvent(Base):
    """Timeline / communication history of a ticket. Append-only."""
    __tablename__ = "ticket_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("service_tickets.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # created | status | assigned | note | part | approval | visit | invoice
    message: Mapped[str] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class MaintenanceSchedule(TimestampMixin, Base):
    __tablename__ = "maintenance_schedules"
    __table_args__ = (CheckConstraint("interval_months >= 1 AND interval_months <= 60", name="ck_maint_interval"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"))
    title: Mapped[str] = mapped_column(String(200))  # "Quarterly CCTV check, 16 cameras"
    interval_months: Mapped[int] = mapped_column(Integer)
    next_due: Mapped[date] = mapped_column(Date, index=True)
    last_done: Mapped[date | None] = mapped_column(Date)
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
