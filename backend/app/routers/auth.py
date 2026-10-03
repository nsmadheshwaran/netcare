from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import AuditLog, Location, Membership, Organization, User
from ..modules import effective_permissions, enabled
from ..schemas import ChangePasswordIn, LoginIn, MeOut, MembershipOut, RegisterIn, TokenOut, UserOut
from ..security import create_access_token, hash_password, login_limiter, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    """Self-service signup: creates the user, their business, an owner membership and a default location."""
    email = body.email.lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    user = User(email=email, full_name=body.full_name, password_hash=hash_password(body.password))
    org = Organization(name=body.organization_name)
    db.add_all([user, org])
    db.flush()
    db.add(Membership(organization_id=org.id, user_id=user.id, role="owner"))
    db.add(Location(organization_id=org.id, name="Main"))
    db.add(AuditLog(organization_id=org.id, user_id=user.id, action="register", entity_type="organization",
                    entity_id=str(org.id), ip_address=request.client.host if request.client else None))
    db.commit()
    return TokenOut(access_token=create_access_token(user.id, user.token_version))


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "?"
    key = f"{body.email.lower()}|{ip}"
    if login_limiter.blocked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts. Try again later.")
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if not user or not verify_password(body.password, user.password_hash) or not user.is_active:
        login_limiter.fail(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    login_limiter.reset(key)
    return TokenOut(access_token=create_access_token(user.id, user.token_version))


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Membership).where(Membership.user_id == user.id, Membership.is_active.is_(True))
                      .order_by(Membership.id)).all()
    return MeOut(user=UserOut.model_validate(user), memberships=[
        MembershipOut(organization_id=m.organization_id, organization_name=m.organization.name, role=m.role,
                      permissions=sorted(effective_permissions(m.role, m.organization)),
                      modules=sorted(enabled(m.organization)))
        for m in rows if m.organization.is_active])


@router.post("/change-password", status_code=204)
def change_password(body: ChangePasswordIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # revoke existing tokens
    db.commit()


@router.post("/logout-all", status_code=204)
def logout_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.token_version += 1
    db.commit()
