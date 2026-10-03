from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException

from ..deps import OrgContext, require
from ..services.analytics import overview
from ..services.timeutil import today

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview")
def analytics_overview(ctx: OrgContext = Depends(require("analytics.view")),
                       date_from: date | None = None, date_to: date | None = None):
    d1 = date_to or today()
    d0 = date_from or (d1.replace(day=1) - timedelta(days=150)).replace(day=1)  # this month and the 5 before
    if d1 < d0:
        raise HTTPException(422, "date_to is before date_from")
    if (d1 - d0).days > 2 * 366:
        raise HTTPException(422, "Choose a period of at most two years")
    return overview(ctx, d0, d1)
