from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user
from ..models import AuditLog, Location, Membership, Organization, User
from ..modules import effective_permissions, enabled
from ..schemas import (
    ChangePasswordIn, ForgotIn, LoginIn, MeOut, MembershipOut, RefreshIn, RegisterIn, SetPasswordIn, TokenOut,
    UserOut,
)
from ..security import hash_password, login_limiter, verify_password
from ..services import accounts

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
    tokens = accounts.issue_tokens(db, user, request)
    db.commit()
    return tokens


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
    tokens = accounts.issue_tokens(db, user, request)
    db.commit()
    return tokens


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, request: Request, db: Session = Depends(get_db)):
    tokens = accounts.refresh(db, body.refresh_token, request)
    db.commit()
    return tokens


@router.post("/logout", status_code=204)
def logout(body: RefreshIn, db: Session = Depends(get_db)):
    """End this sign-in (its refresh token family). The short-lived access token simply expires."""
    accounts.logout(db, body.refresh_token)
    db.commit()


@router.get("/config")
def config():
    """Public: what the sign-in pages can offer."""
    return {"email_enabled": accounts.email_enabled()}


@router.post("/forgot-password", status_code=202)
def forgot_password(body: ForgotIn, request: Request, db: Session = Depends(get_db)):
    """Same answer whether or not the account exists, so this cannot be used to find accounts."""
    answer = {"detail": "If an account exists for that email, a reset link has been sent."}
    key = f"forgot|{body.email.lower()}"
    if login_limiter.blocked(key):
        return answer  # quietly: no more emails for a while
    login_limiter.fail(key)
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if user and user.is_active and accounts.email_enabled():
        raw = accounts.create_link(db, user, "reset")
        accounts.queue_email(db, user.email, "Reset your password",
                             f"Hello {user.full_name},\n\nSomeone (hopefully you) asked to reset your NetCare "
                             f"password. Open this link within {get_settings().reset_minutes} minutes:\n\n"
                             f"{accounts.link_url(raw)}\n\nIf it was not you, ignore this email; your password "
                             "stays the same.")
        db.commit()
    return answer


@router.post("/set-password", response_model=TokenOut)
def set_password(body: SetPasswordIn, request: Request, db: Session = Depends(get_db)):
    """Use an invite or reset link: sets the password, ends other sessions and signs this one in."""
    user, purpose = accounts.consume_link(db, body.token)
    accounts.set_password(db, user, body.password)
    db.add(AuditLog(organization_id=None, user_id=user.id, action=f"password_{purpose}", entity_type="user",
                    entity_id=str(user.id), ip_address=request.client.host if request.client else None))
    db.flush()
    tokens = accounts.issue_tokens(db, user, request)
    db.commit()
    return tokens


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
    accounts.set_password(db, user, body.new_password)  # also ends every session
    db.commit()


@router.post("/logout-all", status_code=204)
def logout_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.token_version += 1
    accounts.revoke_all(db, user.id)
    db.commit()
