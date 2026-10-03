import io
import re
import zipfile
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from ..deps import OrgContext, require
from ..modules import REPORT_MODULE, enabled
from ..services import export
from ..services.reports import CATALOG, REPORT_PERMS
from ..services.timeutil import today

router = APIRouter(prefix="/reports", tags=["reports"])

MEDIA = {"csv": ("text/csv; charset=utf-8", "csv"),
         "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
         "pdf": ("application/pdf", "pdf")}


def _allowed(ctx: OrgContext, key: str) -> bool:
    perm = REPORT_PERMS.get(key)
    mod = REPORT_MODULE.get(key)
    return (perm is None or ctx.can(perm)) and (mod is None or mod in enabled(ctx.org))


def _period(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    t = today()
    d0, d1 = date_from or t.replace(day=1), date_to or t
    if d1 < d0:
        raise HTTPException(422, "date_to is before date_from")
    if (d1 - d0).days > 3 * 366:
        raise HTTPException(422, "Choose a period of at most three years")
    return d0, d1


def _render(report: export.Report, format: str, org_name: str) -> bytes:
    if format == "pdf":
        return export.to_pdf(report, org_name)
    return {"csv": export.to_csv, "xlsx": export.to_xlsx}[format](report)


def _filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


@router.get("")
def catalog(ctx: OrgContext = Depends(require("reports.view"))):
    return [{"key": k, "title": t, "params": p} for k, (t, p, _) in CATALOG.items() if _allowed(ctx, k)]


@router.get("/pack")
def report_pack(ctx: OrgContext = Depends(require("reports.view")), date_from: date | None = None,
                date_to: date | None = None, format: str = Query("xlsx", pattern="^(csv|xlsx|pdf)$"),
                keys: str | None = Query(None, description="Comma-separated report keys; default all")):
    """Every report for one period in a single ZIP, e.g. the month-end handover to the accountant.
    Period reports cover the period; as-of and stock reports are taken at its last day; the daily closing
    is left out (it is one day)."""
    d0, d1 = _period(date_from, date_to)
    wanted = [k.strip() for k in keys.split(",")] if keys else [k for k in CATALOG if k != "daily-closing"]
    unknown = [k for k in wanted if k not in CATALOG]
    if unknown:
        raise HTTPException(422, f"Unknown report(s): {', '.join(unknown)}")
    wanted = [k for k in wanted if _allowed(ctx, k)]
    if not wanted:
        raise HTTPException(422, "No reports selected")
    _, ext = MEDIA[format]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, key in enumerate(wanted, 1):
            _, kind, fn = CATALOG[key]
            report = (fn(ctx, d0, d1) if kind == "period" else fn(ctx, d1) if kind in ("day", "as_of")
                      else fn(ctx, None))
            z.writestr(f"{i:02d}_{key}.{ext}", _render(report, format, ctx.org.name))
        z.writestr("README.txt", f"{ctx.org.name}: reports for {d0} to {d1}, generated {today()}.\n"
                   "Period reports cover the whole period. Dues, warranty, maintenance and document reports are\n"
                   "as of the last day; stock valuation is the current stock. The GST summary is a draft for\n"
                   "your accountant, not a return.\n")
    ctx.audit("export_pack", "report", None, {"format": format, "from": str(d0), "to": str(d1), "keys": wanted})
    ctx.db.commit()
    return Response(buf.getvalue(), media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{_filename(f"reports_{d0}_{d1}_{format}.zip")}"'})


@router.get("/{key}")
def run_report(key: str, ctx: OrgContext = Depends(require("reports.view")),
               date_from: date | None = None, date_to: date | None = None, day: date | None = None,
               as_of: date | None = None, location_id: int | None = None,
               format: str = Query("json", pattern="^(json|csv|xlsx|pdf)$")):
    if key not in CATALOG:
        raise HTTPException(404, "Unknown report")
    if not _allowed(ctx, key):
        raise HTTPException(403, f"Missing permission: {REPORT_PERMS[key]}" if key in REPORT_PERMS
                            and not ctx.can(REPORT_PERMS[key]) else "This module is switched off for this business")
    title, kind, fn = CATALOG[key]
    t = today()
    if kind == "period":
        d0, d1 = _period(date_from, date_to)
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
    return Response(_render(report, format, ctx.org.name), media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{_filename(f"{key}_{suffix}.{ext}")}"'})
