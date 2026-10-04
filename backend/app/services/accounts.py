"""Sign-in sessions (access + refresh tokens) and emailed single-use links (invites, password resets)."""
import hashlib
import secrets
from datetime import timedelta

from fastapi import HTTPException, Request
from sqlalchemy import select, update

from ..config import get_settings
from ..models import User, utcnow
from ..models_auth import RefreshToken, UserToken
from ..models_notify import EmailOutbox
from ..schemas import TokenOut
from ..security import create_access_token, hash_password


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------- sessions ----------------
def issue_tokens(db, user: User, request: Request | None = None, family: str | None = None) -> TokenOut:
    s = get_settings()
    raw = secrets.token_urlsafe(32)
    db.add(RefreshToken(user_id=user.id, token_hash=_hash(raw), family=family or secrets.token_hex(16),
                        token_version=user.token_version, expires_at=utcnow() + timedelta(days=s.refresh_token_days),
                        ip_address=request.client.host if request and request.client else None,
                        user_agent=(request.headers.get("user-agent") or "")[:200] if request else None))
    return TokenOut(access_token=create_access_token(user.id, user.token_version), refresh_token=raw,
                    expires_in=s.access_token_minutes * 60)


def refresh(db, raw: str, request: Request | None = None) -> TokenOut:
    """Rotate a refresh token. Reusing an already-rotated token revokes the whole family (it was copied)."""
    invalid = HTTPException(401, "Session expired. Please sign in again.")
    rt = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash(raw)))
    if rt is None or rt.revoked_at is not None:
        raise invalid
    now = utcnow()
    if rt.used_at is not None:
        revoke_family(db, rt.family)
        db.commit()
        raise invalid
    user = db.get(User, rt.user_id)
    if rt.expires_at < now or user is None or not user.is_active or user.token_version != rt.token_version:
        raise invalid
    rt.used_at = now
    return issue_tokens(db, user, request, family=rt.family)


def revoke_family(db, family: str) -> None:
    db.execute(update(RefreshToken).where(RefreshToken.family == family, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=utcnow()))


def revoke_all(db, user_id: int) -> None:
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=utcnow()))


def logout(db, raw: str) -> None:
    rt = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash(raw)))
    if rt is not None:
        revoke_family(db, rt.family)


# ---------------- emailed links ----------------
def email_enabled() -> bool:
    s = get_settings()
    return bool(s.smtp_host and s.smtp_from)


def create_link(db, user: User, purpose: str) -> str:
    """New single-use token; older unused tokens for the same purpose stop working."""
    s = get_settings()
    ttl = timedelta(days=s.invite_days) if purpose == "invite" else timedelta(minutes=s.reset_minutes)
    db.execute(update(UserToken).where(UserToken.user_id == user.id, UserToken.purpose == purpose,
                                       UserToken.used_at.is_(None)).values(used_at=utcnow()))
    raw = secrets.token_urlsafe(32)
    db.add(UserToken(user_id=user.id, purpose=purpose, token_hash=_hash(raw), expires_at=utcnow() + ttl))
    return raw


def link_url(raw: str) -> str:
    # Fragment, not query string: the token is never sent to a server or leaked in a Referer header.
    return f"{get_settings().app_url.rstrip('/')}/set-password#token={raw}"


def consume_link(db, raw: str) -> tuple[User, str]:
    t = db.scalar(select(UserToken).where(UserToken.token_hash == _hash(raw)))
    if t is None or t.used_at is not None or t.expires_at < utcnow():
        raise HTTPException(400, "This link has expired or was already used. Ask for a new one.")
    user = db.get(User, t.user_id)
    if user is None or not user.is_active:
        raise HTTPException(400, "This account is not active")
    t.used_at = utcnow()
    return user, t.purpose


def set_password(db, user: User, password: str) -> None:
    user.password_hash = hash_password(password)
    user.token_version += 1  # every other session ends
    revoke_all(db, user.id)


def unusable_password() -> str:
    return hash_password(secrets.token_urlsafe(48))  # nobody knows it; the user sets one from the invite


def queue_email(db, to: str, subject: str, body: str, org_id: int | None = None) -> None:
    db.add(EmailOutbox(organization_id=org_id, to_address=to, subject=f"[NetCare] {subject}"[:200], body=body))
