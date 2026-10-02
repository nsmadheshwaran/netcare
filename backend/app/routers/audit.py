from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from ..deps import OrgContext, require
from ..models import AuditLog
from ..schemas import AuditOut, Page

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("", response_model=Page[AuditOut])
def list_audit(ctx: OrgContext = Depends(require("audit.view")), entity_type: str | None = None,
               page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200)):
    q = select(AuditLog).where(AuditLog.organization_id == ctx.org_id)
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    total = ctx.db.scalar(select(func.count()).select_from(q.subquery()))
    rows = ctx.db.scalars(q.order_by(AuditLog.id.desc()).offset((page - 1) * size).limit(size)).all()
    return Page(items=rows, total=total, page=page, size=size)
