"""Employees, attendance, leave and tasks. Not payroll."""
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from sqlalchemy import func, or_, select

from ..deps import OrgContext, require
from ..models import Customer, Membership, User, utcnow
from ..models_service import Attendance, Employee, LeaveRequest, ServiceTicket, Task
from ..permissions import has_permission
from ..schemas import Page
from ..services.timeutil import today
from ..services.trade import get_owned

router = APIRouter(tags=["employees"])


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def current_employee(ctx: OrgContext) -> Employee | None:
    return ctx.db.scalar(select(Employee).where(Employee.organization_id == ctx.org_id,
                                                Employee.user_id == ctx.user.id))


# ---------------- employees ----------------
class EmployeeIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    employee_code: str | None = Field(default=None, max_length=30)
    user_id: int | None = None
    phone: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = None
    job_role: str | None = Field(default=None, max_length=80)
    department: str | None = Field(default=None, max_length=80)
    joining_date: date | None = None
    status: Literal["active", "inactive", "left"] = "active"
    is_technician: bool = False
    notes: str | None = None

    @field_validator("email", "phone", "employee_code", mode="before")
    @classmethod
    def _blank(cls, v):
        return None if v == "" else v


class EmployeeOut(EmployeeIn, ORM):
    id: int
    email: str | None = None
    user_email: str | None = None


def _emp_out(ctx: OrgContext, e: Employee) -> EmployeeOut:
    o = EmployeeOut.model_validate(e)
    if e.user_id:
        u = ctx.db.get(User, e.user_id)
        o.user_email = u.email if u else None
    return o


def _check_employee_body(ctx: OrgContext, body: EmployeeIn, exclude_id: int | None = None):
    if body.user_id is not None:
        # Only link logins that belong to this organization.
        if not ctx.db.scalar(select(Membership.id).where(Membership.organization_id == ctx.org_id,
                                                         Membership.user_id == body.user_id)):
            raise HTTPException(422, "That user is not a member of this business")
        q = select(Employee.id).where(Employee.organization_id == ctx.org_id, Employee.user_id == body.user_id)
        if exclude_id:
            q = q.where(Employee.id != exclude_id)
        if ctx.db.scalar(q):
            raise HTTPException(409, "That login is already linked to another employee")
    if body.employee_code:
        q = select(Employee.id).where(Employee.organization_id == ctx.org_id,
                                      Employee.employee_code == body.employee_code)
        if exclude_id:
            q = q.where(Employee.id != exclude_id)
        if ctx.db.scalar(q):
            raise HTTPException(409, "Employee code already in use")


@router.get("/employees", response_model=Page[EmployeeOut])
def list_employees(ctx: OrgContext = Depends(require("tasks.view")), q: str | None = None,
                   status: str | None = "active", technicians: bool = False,
                   page: int = Query(1, ge=1), size: int = Query(100, ge=1, le=200)):
    """Readable by anyone who can see tasks, so tickets and tasks can show who is assigned.
    Sensitive fields are limited to contact details; there is no salary data in NetCare."""
    base = select(Employee).where(Employee.organization_id == ctx.org_id)
    if status:
        base = base.where(Employee.status == status)
    if technicians:
        base = base.where(Employee.is_technician.is_(True))
    if q:
        base = base.where(or_(Employee.name.ilike(f"%{q}%"), Employee.employee_code.ilike(f"%{q}%")))
    total = ctx.db.scalar(select(func.count()).select_from(base.subquery()))
    rows = ctx.db.scalars(base.order_by(Employee.name).offset((page - 1) * size).limit(size)).all()
    return Page(items=[_emp_out(ctx, e) for e in rows], total=total, page=page, size=size)


@router.post("/employees", response_model=EmployeeOut, status_code=201)
def create_employee(body: EmployeeIn, ctx: OrgContext = Depends(require("employees.manage"))):
    _check_employee_body(ctx, body)
    e = Employee(organization_id=ctx.org_id, **body.model_dump())
    ctx.db.add(e)
    ctx.db.flush()
    ctx.audit("create", "employee", e.id, {"name": e.name})
    ctx.db.commit()
    return _emp_out(ctx, e)


@router.get("/employees/me", response_model=EmployeeOut | None)
def my_employee(ctx: OrgContext = Depends(require("dashboard.view"))):
    e = current_employee(ctx)
    return _emp_out(ctx, e) if e else None


@router.put("/employees/{emp_id}", response_model=EmployeeOut)
def update_employee(emp_id: int, body: EmployeeIn, ctx: OrgContext = Depends(require("employees.manage"))):
    e = get_owned(ctx, Employee, emp_id, "Employee")
    _check_employee_body(ctx, body, exclude_id=e.id)
    changed = {k: v for k, v in body.model_dump().items() if getattr(e, k) != v}
    for k, v in changed.items():
        setattr(e, k, v)
    ctx.audit("update", "employee", e.id, {"fields": sorted(changed)})
    ctx.db.commit()
    return _emp_out(ctx, e)


# ---------------- attendance ----------------
ATT_STATUS = Literal["present", "absent", "half_day", "leave", "holiday", "week_off"]
TIME_RE = r"^([01]\d|2[0-3]):[0-5]\d$"


class AttendanceIn(BaseModel):
    employee_id: int
    status: ATT_STATUS
    check_in: str | None = Field(default=None, pattern=TIME_RE)
    check_out: str | None = Field(default=None, pattern=TIME_RE)
    note: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _times(self):
        if self.check_in and self.check_out and self.check_out < self.check_in:
            raise ValueError("Check-out is before check-in")
        return self


class AttendanceDayIn(BaseModel):
    work_date: date
    entries: list[AttendanceIn] = Field(min_length=1, max_length=500)


class AttendanceOut(ORM):
    employee_id: int
    work_date: date
    status: str
    check_in: str | None
    check_out: str | None
    note: str | None


@router.get("/attendance", response_model=list[AttendanceOut])
def get_attendance(ctx: OrgContext = Depends(require("employees.view")), date_from: date | None = None,
                   date_to: date | None = None, employee_id: int | None = None):
    d0, d1 = date_from or today(), date_to or date_from or today()
    if (d1 - d0).days > 62:
        raise HTTPException(422, "Choose at most two months")
    q = select(Attendance).where(Attendance.organization_id == ctx.org_id, Attendance.work_date >= d0,
                                 Attendance.work_date <= d1)
    if employee_id:
        q = q.where(Attendance.employee_id == employee_id)
    return ctx.db.scalars(q.order_by(Attendance.work_date, Attendance.employee_id)).all()


@router.put("/attendance", response_model=list[AttendanceOut])
def save_attendance(body: AttendanceDayIn, ctx: OrgContext = Depends(require("attendance.manage"))):
    """Record or correct a day's attendance for several employees at once (upsert per employee)."""
    if body.work_date > today():
        raise HTTPException(422, "Attendance cannot be recorded for a future date")
    out = []
    for e in body.entries:
        emp = get_owned(ctx, Employee, e.employee_id, f"Employee {e.employee_id}", status_code=422)
        row = ctx.db.scalar(select(Attendance).where(Attendance.employee_id == emp.id,
                                                     Attendance.work_date == body.work_date))
        before = None
        if row is None:
            row = Attendance(organization_id=ctx.org_id, employee_id=emp.id, work_date=body.work_date)
            ctx.db.add(row)
        else:
            before = row.status
        row.status, row.check_in, row.check_out, row.note = e.status, e.check_in, e.check_out, e.note
        row.recorded_by = ctx.user.id
        out.append(row)
        if before is not None and before != e.status:
            ctx.audit("correct", "attendance", row.id, {"employee": emp.id, "date": str(body.work_date),
                                                        "from": before, "to": e.status})
    ctx.audit("record", "attendance", None, {"date": str(body.work_date), "count": len(body.entries)})
    ctx.db.commit()
    return out


# ---------------- leave ----------------
class LeaveIn(BaseModel):
    employee_id: int | None = None  # default: the caller's own employee record
    start_date: date
    end_date: date
    leave_type: Literal["casual", "sick", "earned", "unpaid", "other"]
    reason: str | None = None

    @model_validator(mode="after")
    def _dates(self):
        if self.end_date < self.start_date:
            raise ValueError("End date is before start date")
        if (self.end_date - self.start_date).days > 90:
            raise ValueError("A single request can cover at most 90 days")
        return self


class LeaveOut(ORM):
    id: int
    employee_id: int
    employee_name: str | None = None
    start_date: date
    end_date: date
    days: int = 0
    leave_type: str
    reason: str | None
    status: str
    decision_note: str | None


def _leave_out(ctx: OrgContext, lr: LeaveRequest) -> LeaveOut:
    o = LeaveOut.model_validate(lr)
    o.employee_name = ctx.db.get(Employee, lr.employee_id).name
    o.days = (lr.end_date - lr.start_date).days + 1
    return o


@router.get("/leave-requests", response_model=list[LeaveOut])
def list_leave(ctx: OrgContext = Depends(require("tasks.view")), status: str | None = None):
    """Managers (employees.view) see everyone's requests; others see only their own."""
    q = select(LeaveRequest).where(LeaveRequest.organization_id == ctx.org_id)
    if not has_permission(ctx.membership.role, "employees.view"):
        me = current_employee(ctx)
        q = q.where(LeaveRequest.employee_id == (me.id if me else -1))
    if status:
        q = q.where(LeaveRequest.status == status)
    return [_leave_out(ctx, lr) for lr in ctx.db.scalars(q.order_by(LeaveRequest.start_date.desc()).limit(200))]


@router.post("/leave-requests", response_model=LeaveOut, status_code=201)
def request_leave(body: LeaveIn, ctx: OrgContext = Depends(require("tasks.view"))):
    me = current_employee(ctx)
    if body.employee_id is None or (me and body.employee_id == me.id):
        if me is None:
            raise HTTPException(422, "Your login is not linked to an employee record")
        emp = me
    else:
        if not has_permission(ctx.membership.role, "attendance.manage"):
            raise HTTPException(403, "You can only request leave for yourself")
        emp = get_owned(ctx, Employee, body.employee_id, "Employee", status_code=422)
    overlap = ctx.db.scalar(select(LeaveRequest.id).where(
        LeaveRequest.employee_id == emp.id, LeaveRequest.status.in_(["pending", "approved"]),
        LeaveRequest.start_date <= body.end_date, LeaveRequest.end_date >= body.start_date))
    if overlap:
        raise HTTPException(409, "Overlaps an existing pending or approved request")
    lr = LeaveRequest(organization_id=ctx.org_id, employee_id=emp.id,
                      **body.model_dump(exclude={"employee_id"}))
    ctx.db.add(lr)
    ctx.db.flush()
    from ..services.notify import KINDS, members_with, notify
    approvers = [u.id for _m, u in members_with(ctx.db, ctx.org_id, KINDS["leave_request"][1])
                 if u.id != ctx.user.id and u.id != emp.user_id]
    notify(ctx.db, ctx.org_id, "leave_request", f"Leave request: {emp.name}",
           f"{lr.leave_type.title()} leave {lr.start_date:%d %b} to {lr.end_date:%d %b %Y}.", "/employees",
           users=approvers)
    ctx.audit("request", "leave", lr.id, {"employee": emp.id, "from": str(lr.start_date), "to": str(lr.end_date)})
    ctx.db.commit()
    return _leave_out(ctx, lr)


class LeaveDecisionIn(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=500)


@router.post("/leave-requests/{lr_id}/decide", response_model=LeaveOut)
def decide_leave(lr_id: int, body: LeaveDecisionIn, ctx: OrgContext = Depends(require("attendance.manage"))):
    lr = get_owned(ctx, LeaveRequest, lr_id, "Leave request", lock=True)
    if lr.status != "pending":
        raise HTTPException(409, f"Request is already {lr.status}")
    me = current_employee(ctx)
    if me and me.id == lr.employee_id and ctx.membership.role != "owner":
        raise HTTPException(403, "You cannot approve your own leave")
    lr.status, lr.decision_note = body.decision, body.note
    lr.decided_by, lr.decided_at = ctx.user.id, utcnow()
    if body.decision == "approved":
        # Mark attendance as leave for each day not already recorded.
        d = lr.start_date
        while d <= lr.end_date:
            if not ctx.db.scalar(select(Attendance.id).where(Attendance.employee_id == lr.employee_id,
                                                             Attendance.work_date == d)):
                ctx.db.add(Attendance(organization_id=ctx.org_id, employee_id=lr.employee_id, work_date=d,
                                      status="leave", note=f"{lr.leave_type} leave", recorded_by=ctx.user.id))
            d += timedelta(days=1)
    from ..services.notify import notify_employee
    notify_employee(ctx.db, ctx.org_id, lr.employee_id, "leave_decided", f"Leave {body.decision}",
                    f"{lr.start_date:%d %b} to {lr.end_date:%d %b %Y}" + (f": {body.note}" if body.note else ""),
                    "/my-work", ctx.user.id)
    ctx.audit(body.decision, "leave", lr.id, {"note": body.note})
    ctx.db.commit()
    return _leave_out(ctx, lr)


@router.post("/leave-requests/{lr_id}/cancel", response_model=LeaveOut)
def cancel_leave(lr_id: int, ctx: OrgContext = Depends(require("tasks.view"))):
    lr = get_owned(ctx, LeaveRequest, lr_id, "Leave request", lock=True)
    me = current_employee(ctx)
    if not (me and me.id == lr.employee_id) and not has_permission(ctx.membership.role, "attendance.manage"):
        raise HTTPException(403, "Not your request")
    if lr.status != "pending":
        raise HTTPException(409, "Only pending requests can be cancelled")
    lr.status = "cancelled"
    ctx.audit("cancel", "leave", lr.id)
    ctx.db.commit()
    return _leave_out(ctx, lr)


# ---------------- tasks ----------------
def _notify_task(ctx: OrgContext, t: Task) -> None:
    from ..services.notify import notify_employee
    due = f" Due {t.due_date:%d %b %Y}." if t.due_date else ""
    notify_employee(ctx.db, ctx.org_id, t.assigned_to, "task_assigned", f"Task for you: {t.title}",
                    f"{(t.description or '')[:200]}{due}".strip() or None, "/my-work", ctx.user.id)


PRIORITY = Literal["low", "normal", "high", "urgent"]


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    assigned_to: int | None = None
    priority: PRIORITY = "normal"
    due_date: date | None = None
    customer_id: int | None = None
    ticket_id: int | None = None


class TaskOut(TaskIn, ORM):
    id: int
    status: str
    assignee_name: str | None = None
    overdue: bool = False
    completed_at: datetime | None
    created_at: datetime


def _task_out(ctx: OrgContext, t: Task) -> TaskOut:
    o = TaskOut.model_validate(t)
    o.assignee_name = ctx.db.get(Employee, t.assigned_to).name if t.assigned_to else None
    o.overdue = bool(t.due_date and t.due_date < today() and t.status in ("todo", "in_progress"))
    return o


def _check_task_refs(ctx: OrgContext, body: TaskIn):
    if body.assigned_to is not None:
        emp = get_owned(ctx, Employee, body.assigned_to, "Employee", status_code=422)
        if emp.status != "active":
            raise HTTPException(422, f"{emp.name} is not an active employee")
    if body.customer_id is not None:
        get_owned(ctx, Customer, body.customer_id, "Customer", status_code=422)
    if body.ticket_id is not None:
        get_owned(ctx, ServiceTicket, body.ticket_id, "Ticket", status_code=422)


@router.get("/tasks", response_model=Page[TaskOut])
def list_tasks(ctx: OrgContext = Depends(require("tasks.view")), mine: bool = False, status: str | None = None,
               assigned_to: int | None = None, overdue: bool = False,
               page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200)):
    base = select(Task).where(Task.organization_id == ctx.org_id)
    if mine:
        me = current_employee(ctx)
        base = base.where(Task.assigned_to == (me.id if me else -1))
    if assigned_to:
        base = base.where(Task.assigned_to == assigned_to)
    if status == "open":
        base = base.where(Task.status.in_(["todo", "in_progress"]))
    elif status:
        base = base.where(Task.status == status)
    if overdue:
        base = base.where(Task.due_date < today(), Task.status.in_(["todo", "in_progress"]))
    total = ctx.db.scalar(select(func.count()).select_from(base.subquery()))
    order = (Task.status.in_(["done", "cancelled"]), Task.due_date.is_(None), Task.due_date, Task.id.desc())
    rows = ctx.db.scalars(base.order_by(*order).offset((page - 1) * size).limit(size)).all()
    return Page(items=[_task_out(ctx, t) for t in rows], total=total, page=page, size=size)


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(body: TaskIn, ctx: OrgContext = Depends(require("tasks.edit"))):
    _check_task_refs(ctx, body)
    t = Task(organization_id=ctx.org_id, created_by=ctx.user.id, **body.model_dump())
    ctx.db.add(t)
    ctx.db.flush()
    _notify_task(ctx, t)
    ctx.audit("create", "task", t.id, {"title": t.title, "assigned_to": t.assigned_to})
    ctx.db.commit()
    return _task_out(ctx, t)


@router.put("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, body: TaskIn, ctx: OrgContext = Depends(require("tasks.edit"))):
    t = get_owned(ctx, Task, task_id, "Task")
    _check_task_refs(ctx, body)
    reassigned = body.assigned_to != t.assigned_to
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    if reassigned:
        _notify_task(ctx, t)
    ctx.audit("update", "task", t.id)
    ctx.db.commit()
    return _task_out(ctx, t)


class TaskStatusIn(BaseModel):
    status: Literal["todo", "in_progress", "done", "cancelled"]


@router.post("/tasks/{task_id}/status", response_model=TaskOut)
def set_task_status(task_id: int, body: TaskStatusIn, ctx: OrgContext = Depends(require("tasks.view"))):
    """Assignees can move their own tasks; managers (tasks.edit) can move any."""
    t = get_owned(ctx, Task, task_id, "Task", lock=True)
    if not has_permission(ctx.membership.role, "tasks.edit"):
        me = current_employee(ctx)
        if not me or t.assigned_to != me.id:
            raise HTTPException(403, "You can only update tasks assigned to you")
        if body.status == "cancelled":
            raise HTTPException(403, "Only a manager can cancel a task")
    t.status = body.status
    t.completed_at = utcnow() if body.status == "done" else None
    ctx.audit("status", "task", t.id, {"status": body.status})
    ctx.db.commit()
    return _task_out(ctx, t)
