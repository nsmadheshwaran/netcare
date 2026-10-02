import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from ..deps import OrgContext, require
from ..services import export
from ..services.reports import CATALOG
from ..services.timeutil import today

router = APIRouter(prefix="/reports", tags=["reports"])

MEDIA = {"csv": ("text/csv; charset=utf-8", "csv"),
         "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
         "pdf": ("application/pdf", "pdf")}


@router.get("")
def catalog(ctx: OrgContext = Depends(require("reports.view"))):
    return [{"key": k, "title": t, "params": p} for k, (t, p, _) in CATALOG.items()]


@router.get("/{key}")
def run_report(key: str, ctx: OrgContext = Depends(require("reports.view")),
               date_from: date | None = None, date_to: date | None = None, day: date | None = None,
               as_of: date | None = None, location_id: int | None = None,
               format: str = Query("json", pattern="^(json|csv|xlsx|pdf)$")):
    if key not in CATALOG:
        raise HTTPException(404, "Unknown report")
    title, kind, fn = CATALOG[key]
    t = today()
    if kind == "period":
        d0 = date_from or t.replace(day=1)
        d1 = date_to or t
        if d1 < d0:
            raise HTTPException(422, "date_to is before date_from")
        if (d1 - d0).days > 3 * 366:
            raise HTTPException(422, "Choose a period of at most three years")
        report = fn(ctx, d0, d1)
        suffix = f"{d0}_{d1}"
    elif kind == "day":
        report = fn(ctx, day or t)
        suffix = str(day or t)
    elif kind == "as_of":
        report = fn(ctx, as_of or t)
        suffix = str(as_of or t)
    else:
        report = fn(ctx, location_id)
        suffix = str(t)
    ctx.audit("run_report", "report", key, {"format": format, "suffix": suffix})
    ctx.db.commit()
    if format == "json":
        return report.to_json()
    media, ext = MEDIA[format]
    body = {"csv": export.to_csv, "xlsx": export.to_xlsx}[format](report) if format != "pdf" \
        else export.to_pdf(report, ctx.org.name)
    filename = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{key}_{suffix}.{ext}")
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
