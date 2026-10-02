from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from ..deps import OrgContext, get_org_context, require
from ..models import Location, Membership, User
from ..permissions import ROLES
from ..schemas import LocationIn, LocationOut, MemberIn, MemberOut, MemberUpdate, OrgIn, OrgOut
from ..security import hash_password

router = APIRouter(prefix="/organization", tags=["organizations"])


@router.get("", response_model=OrgOut)
def get_org(ctx: OrgContext = Depends(get_org_context)):
    return ctx.org


@router.put("", response_model=OrgOut)
def update_org(body: OrgIn, ctx: OrgContext = Depends(require("org.manage"))):
    changes = body.model_dump()
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
