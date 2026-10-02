from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import AuditLog, Membership, Organization, User
from .permissions import has_permission
from .security import decode_access_token

bearer = HTTPBearer(auto_error=False)


def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                     db: Session = Depends(get_db)) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated",
                                 headers={"WWW-Authenticate": "Bearer"})
    if not creds:
        raise unauthorized
    payload = decode_access_token(creds.credentials)
    if not payload:
        raise unauthorized
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active or user.token_version != payload.get("tv"):
        raise unauthorized
    return user


@dataclass
class OrgContext:
    user: User
    org: Organization
    membership: Membership
    db: Session
    ip: str | None

    @property
    def org_id(self) -> int:
        return self.org.id

    def audit(self, action: str, entity_type: str, entity_id=None, details: dict | None = None) -> None:
        self.db.add(AuditLog(organization_id=self.org.id, user_id=self.user.id, action=action,
                             entity_type=entity_type, entity_id=None if entity_id is None else str(entity_id),
                             details=details, ip_address=self.ip))


def get_org_context(request: Request,
                    x_organization_id: int = Header(..., alias="X-Organization-ID"),
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)) -> OrgContext:
    m = db.scalar(select(Membership).where(Membership.organization_id == x_organization_id,
                                           Membership.user_id == user.id, Membership.is_active.is_(True)))
    # Same 404 whether the org doesn't exist or the user isn't a member: don't leak existence.
    if not m or not m.organization.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    return OrgContext(user=user, org=m.organization, membership=m, db=db,
                      ip=request.client.host if request.client else None)


def require(perm: str):
    def checker(ctx: OrgContext = Depends(get_org_context)) -> OrgContext:
        if not has_permission(ctx.membership.role, perm):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {perm}")
        return ctx
    return checker
