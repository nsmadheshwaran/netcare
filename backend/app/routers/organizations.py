from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from ..deps import OrgContext, get_org_context, require
from ..models import Location, Membership, User
from ..modules import MODULES, enabled, validate
from ..permissions import ROLES
from ..schemas import LocationIn, LocationOut, MemberIn, MemberOut, MemberUpdate, OrgIn, OrgOut
from ..security import hash_password

router = APIRouter(prefix="/organization", tags=["organizations"])


@router.get("", response_model=OrgOut)
def get_org(ctx: OrgContext = Depends(get_org_context)):
    return ctx.org


@router.get("/modules")
def list_modules(ctx: OrgContext = Depends(get_org_context)):
    on = enabled(ctx.org)
    return [{"key": k, "label": m["label"], "detail": m["detail"], "requires": m.get("requires"), "enabled": k in on}
            for k, m in MODULES.items()]


class ModulesIn(BaseModel):
    enabled: list[str]

    @field_validator("enabled")
    @classmethod
    def _v(cls, v):
        return validate(v)


@router.put("/modules")
def set_modules(body: ModulesIn, ctx: OrgContext = Depends(require("org.manage"))):
    """Switching a module off hides it and blocks its API for everyone; its data is kept and returns when it is
    switched back on."""
    before = sorted(enabled(ctx.org))
    ctx.org.enabled_modules = body.enabled
    ctx.audit("set_modules", "organization", ctx.org_id, {"before": before, "after": body.enabled})
    ctx.db.commit()
    return list_modules(ctx)


@router.put("", response_model=OrgOut)
def update_org(body: OrgIn, ctx: OrgContext = Depends(require("org.manage"))):
    changes = body.model_dump()
    if "enabled_modules" not in body.model_fields_set:
        changes.pop("enabled_modules")  # omitted is not "switch everything on"
    for k, v in changes.items():
        setattr(ctx.org, k, v)
    ctx.audit("update", "organization", ctx.org_id, {"fields": list(changes)})
    ctx.db.commit()
    return ctx.org


def _member_out(m: Membership) -> MemberOut:
    return MemberOut(id=m.id, user_id=m.user_id, email=m.user.email, full_name=m.user.full_name,
                     role=m.role, is_active=m.is_active)


@router.get("/members", response_model=list[MemberOut])
def list_members(ctx: OrgContext = Depends(require("users.manage"))):
    rows = ctx.db.scalars(select(Membership).where(Membership.organization_id == ctx.org_id)
                          .order_by(Membership.id)).all()
    return [_member_out(m) for m in rows]


@router.post("/members", response_model=MemberOut, status_code=201)
def add_member(body: MemberIn, ctx: OrgContext = Depends(require("users.manage"))):
    if body.role not in ROLES:
        raise HTTPException(422, f"Role must be one of {ROLES}")
    if body.role == "owner" and ctx.membership.role != "owner":
        raise HTTPException(403, "Only owners can add owners")
    db = ctx.db
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if user is None:
        user = User(email=body.email.lower(), full_name=body.full_name,
                    password_hash=hash_password(body.temporary_password))
        db.add(user)
        db.flush()
    elif db.scalar(select(Membership).where(Membership.organization_id == ctx.org_id,
                                            Membership.user_id == user.id)):
        raise HTTPException(409, "User is already a member")
    # For an existing account the temporary password is ignored; we never overwrite an existing password.
    m = Membership(organization_id=ctx.org_id, user_id=user.id, role=body.role)
    db.add(m)
    db.flush()
    ctx.audit("add_member", "membership", m.id, {"email": user.email, "role": body.role})
    db.commit()
    return _member_out(m)


@router.patch("/members/{member_id}", response_model=MemberOut)
def update_member(member_id: int, body: MemberUpdate, ctx: OrgContext = Depends(require("users.manage"))):
    m = ctx.db.get(Membership, member_id)
    if not m or m.organization_id != ctx.org_id:
        raise HTTPException(404, "Member not found")
    if body.role is not None and body.role not in ROLES:
        raise HTTPException(422, f"Role must be one of {ROLES}")
    if (m.role == "owner" or body.role == "owner") and ctx.membership.role != "owner":
        raise HTTPException(403, "Only owners can change owner memberships")
    if m.role == "owner" and (body.role not in (None, "owner") or body.is_active is False):
        owners = ctx.db.scalar(select(func.count()).select_from(Membership).where(
            Membership.organization_id == ctx.org_id, Membership.role == "owner", Membership.is_active.is_(True)))
        if owners <= 1:
            raise HTTPException(409, "Organization must keep at least one active owner")
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(m, k, v)
    ctx.audit("update_member", "membership", m.id, changes)
    ctx.db.commit()
    return _member_out(m)


class PasswordResetIn(BaseModel):
    temporary_password: str = Field(min_length=10, max_length=128)


@router.post("/members/{member_id}/reset-password", status_code=204)
def reset_member_password(member_id: int, body: PasswordResetIn, ctx: OrgContext = Depends(require("users.manage"))):
    """Set a temporary password for a staff member who forgot theirs, and sign them out everywhere.
    Refused for accounts that also belong to another business: one business must not be able to take over
    a login that has access elsewhere."""
    m = ctx.db.get(Membership, member_id)
    if not m or m.organization_id != ctx.org_id:
        raise HTTPException(404, "Member not found")
    if m.user_id == ctx.user.id:
        raise HTTPException(409, "Change your own password under Settings")
    if m.role == "owner" and ctx.membership.role != "owner":
        raise HTTPException(403, "Only owners can reset an owner's password")
    elsewhere = ctx.db.scalar(select(func.count()).select_from(Membership).where(
        Membership.user_id == m.user_id, Membership.organization_id != ctx.org_id))
    if elsewhere:
        raise HTTPException(409, "This login also belongs to another business, so it cannot be reset from here. "
                                 "The person can change their password while signed in")
    user = ctx.db.get(User, m.user_id)
    user.password_hash = hash_password(body.temporary_password)
    user.token_version += 1  # signs out every existing session
    ctx.audit("reset_password", "membership", m.id, {"email": user.email})
    ctx.db.commit()


@router.get("/locations", response_model=list[LocationOut])
def list_locations(ctx: OrgContext = Depends(get_org_context)):
    return ctx.db.scalars(select(Location).where(Location.organization_id == ctx.org_id).order_by(Location.id)).all()


@router.post("/locations", response_model=LocationOut, status_code=201)
def add_location(body: LocationIn, ctx: OrgContext = Depends(require("locations.manage"))):
    if ctx.db.scalar(select(Location).where(Location.organization_id == ctx.org_id, Location.name == body.name)):
        raise HTTPException(409, "A location with this name exists")
    loc = Location(organization_id=ctx.org_id, **body.model_dump())
    ctx.db.add(loc)
    ctx.db.flush()
    ctx.audit("create", "location", loc.id, body.model_dump())
    ctx.db.commit()
    return loc


@router.get("/onboarding")
def onboarding(ctx: OrgContext = Depends(get_org_context)):
    """First-run checklist, computed from real data (nothing to tick by hand)."""
    from ..models import Customer, Product
    from ..models_monitoring import MonitorAgent
    from ..models_trade import SalesInvoice

    def count(model, *where):
        return ctx.db.scalar(select(func.count()).select_from(model).where(model.organization_id == ctx.org_id,
                                                                           *where))

    org, on = ctx.org, enabled(ctx.org)
    steps = [
        ("profile", "Complete your business details", "State and address are needed for correct GST on invoices",
         bool(org.state_code and org.address), "/settings"),
        ("modules", "Choose the modules you use", "Switch off what you do not need to keep the menu simple",
         org.enabled_modules is not None, "/settings"),
        ("products", "Add your products and services", "Or import them later; prices and GST rates are used on bills",
         count(Product) > 0, "/products"),
        ("customers", "Add or import customers", "CSV import is under Customers", count(Customer) > 0, "/customers"),
        ("team", "Invite your staff", "Give each person their own login and role",
         count(Membership, Membership.is_active.is_(True)) > 1, "/users"),
    ]
    if "trade" in on:
        steps.append(("invoice", "Issue your first invoice", "Check the printout before sending it to customers",
                      count(SalesInvoice, SalesInvoice.number.is_not(None)) > 0, "/sales"))
    if "monitoring" in on:
        steps.append(("monitoring", "Install a monitoring agent", "Watch routers, recorders and cameras at a site",
                      count(MonitorAgent) > 0, "/monitoring"))
    items = [{"key": k, "title": t, "hint": h, "done": d, "link": link} for k, t, h, d, link in steps]
    return {"steps": items, "done": sum(i["done"] for i in items), "total": len(items),
            "complete": all(i["done"] for i in items)}
