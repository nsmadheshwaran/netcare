"""Phase 7: endpoint security visibility. Agents report Defender status; staff see it and acknowledge threats."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import OrgContext, require
from ..models import Customer, User, utcnow
from ..models_monitoring import MonitorAgent
from ..models_security import Endpoint, EndpointThreat
from ..models_service import Asset
from ..services import endpoint_security as es
from ..services.trade import get_owned
from .monitoring import current_agent

router = APIRouter(tags=["endpoint security"])
THREAT_DAYS = 30


def _utc(v: datetime | None) -> datetime | None:
    return None if v is None else v if v.tzinfo else v.replace(tzinfo=timezone.utc)


class DefenderIn(BaseModel):
    av_enabled: bool | None = None
    realtime_enabled: bool | None = None
    antispyware_enabled: bool | None = None
    behavior_monitor_enabled: bool | None = None
    tamper_protected: bool | None = None
    running_mode: str | None = Field(None, max_length=30)
    signature_version: str | None = Field(None, max_length=40)
    signature_updated_at: datetime | None = None
    engine_version: str | None = Field(None, max_length=40)
    product_version: str | None = Field(None, max_length=40)
    quick_scan_at: datetime | None = None
    full_scan_at: datetime | None = None

    @field_validator("signature_updated_at", "quick_scan_at", "full_scan_at")
    @classmethod
    def _tz(cls, v):
        return _utc(v)


class ThreatIn(BaseModel):
    detection_id: str = Field(min_length=1, max_length=64)
    threat_name: str = Field(min_length=1, max_length=200)
    severity_id: int | None = None
    category: str | None = Field(None, max_length=40)
    status_id: int | None = None
    action_success: bool | None = None
    detected_at: datetime
    resources: str | None = Field(None, max_length=4000)

    @field_validator("detected_at")
    @classmethod
    def _tz(cls, v):
        return _utc(v)


class EndpointReport(BaseModel):
    hostname: str = Field(min_length=1, max_length=100)
    os_name: str | None = Field(None, max_length=120)
    os_version: str | None = Field(None, max_length=40)
    defender: DefenderIn | None = None  # None: Defender cmdlets not available on this PC
    threats: list[ThreatIn] = Field(default_factory=list, max_length=500)


class LinkIn(BaseModel):
    asset_id: int | None = None


class AckIn(BaseModel):
    note: str = Field(min_length=3, max_length=1000)


def _threats(ctx_db, endpoint_id: int) -> list[EndpointThreat]:
    since = utcnow() - timedelta(days=THREAT_DAYS)
    return ctx_db.scalars(select(EndpointThreat).where(EndpointThreat.endpoint_id == endpoint_id,
                                                       EndpointThreat.detected_at >= since)
                          .order_by(EndpointThreat.detected_at.desc())).all()


def _threat_out(ctx: OrgContext, t: EndpointThreat) -> dict:
    by = ctx.db.get(User, t.acknowledged_by) if t.acknowledged_by else None
    return {"id": t.id, "threat_name": t.threat_name, "severity": t.severity, "category": t.category,
            "status": t.status, "action_success": t.action_success, "detected_at": t.detected_at,
            "resources": t.resources, "acknowledged_at": t.acknowledged_at,
            "acknowledged_by": by.full_name if by else None, "acknowledge_note": t.acknowledge_note,
            "active": t.status in es.ACTIVE}


def _endpoint_out(ctx: OrgContext, e: Endpoint, detail: bool = False, now: datetime | None = None) -> dict:
    threats = _threats(ctx.db, e.id)
    rating, reasons = es.evaluate(e, threats, now)
    agent = ctx.db.get(MonitorAgent, e.agent_id)
    asset = ctx.db.get(Asset, e.asset_id) if e.asset_id else None
    cust_id = asset.customer_id if asset else agent.customer_id
    out = {"id": e.id, "hostname": e.hostname, "agent_id": e.agent_id, "agent_name": agent.name,
           "asset_id": e.asset_id, "asset_name": asset.name if asset else None,
           "customer_name": ctx.db.get(Customer, cust_id).name if cust_id else None,
           "os_name": e.os_name, "os_version": e.os_version, "last_report_at": e.last_report_at,
           "rating": rating, "reasons": reasons, "defender_available": e.defender_available,
           "realtime_enabled": e.realtime_enabled, "signature_updated_at": e.signature_updated_at,
           "active_threats": sum(1 for t in threats if t.status in es.ACTIVE), "threats_30d": len(threats)}
    if detail:
        out |= {k: getattr(e, k) for k in ("av_enabled", "antispyware_enabled", "behavior_monitor_enabled",
                                           "tamper_protected", "running_mode", "signature_version",
                                           "engine_version", "product_version", "quick_scan_at", "full_scan_at")}
        out["threats"] = [_threat_out(ctx, t) for t in threats]
    return out


# ---------------- agent ----------------
@router.post("/agent/endpoint")
def agent_endpoint_report(body: EndpointReport, agent: MonitorAgent = Depends(current_agent),
                          db: Session = Depends(get_db)):
    if not agent.collect_endpoint:
        db.commit()  # keep last_seen
        raise HTTPException(403, "Endpoint reporting is not enabled for this agent")
    now = utcnow()
    if any(t.detected_at > now + timedelta(minutes=5) for t in body.threats):
        raise HTTPException(422, "A detection is timestamped in the future; check the PC's clock")
    e = es.ingest_report(db, agent, body.model_dump())
    db.commit()
    return {"endpoint_id": e.id}


# ---------------- staff ----------------
@router.get("/endpoints")
def list_endpoints(ctx: OrgContext = Depends(require("security.view")), rating: str | None = None):
    now = utcnow()
    rows = [_endpoint_out(ctx, e, now=now) for e in ctx.db.scalars(
        select(Endpoint).where(Endpoint.organization_id == ctx.org_id).order_by(Endpoint.hostname))]
    if rating:
        rows = [r for r in rows if r["rating"] == rating]
    return sorted(rows, key=lambda r: (-es.RANK[r["rating"]], r["customer_name"] or "", r["hostname"]))


@router.get("/endpoints/summary")
def endpoints_summary(ctx: OrgContext = Depends(require("security.view"))):
    rows = list_endpoints(ctx)
    counts = {k: 0 for k in ("critical", "warning", "ok", "unknown")}
    for r in rows:
        counts[r["rating"]] += 1
    return {"endpoints": len(rows), **counts, "active_threats": sum(r["active_threats"] for r in rows)}


@router.get("/endpoints/{endpoint_id}")
def get_endpoint(endpoint_id: int, ctx: OrgContext = Depends(require("security.view"))):
    return _endpoint_out(ctx, get_owned(ctx, Endpoint, endpoint_id, "Endpoint"), detail=True)


@router.put("/endpoints/{endpoint_id}/asset")
def link_asset(endpoint_id: int, body: LinkIn, ctx: OrgContext = Depends(require("security.manage"))):
    e = get_owned(ctx, Endpoint, endpoint_id, "Endpoint")
    if body.asset_id is not None:
        a = get_owned(ctx, Asset, body.asset_id, "Equipment", status_code=422)
        if a.asset_type not in ("computer", "laptop", "server"):
            raise HTTPException(422, "Link a computer, laptop or server")
        if ctx.db.scalar(select(Endpoint.id).where(Endpoint.asset_id == a.id, Endpoint.id != e.id)):
            raise HTTPException(409, "That equipment is already linked to another endpoint")
    e.asset_id = body.asset_id
    ctx.audit("link_asset", "endpoint", e.id, {"asset_id": body.asset_id})
    ctx.db.commit()
    return _endpoint_out(ctx, e, detail=True)


@router.post("/endpoints/{endpoint_id}/threats/{threat_id}/acknowledge")
def acknowledge(endpoint_id: int, threat_id: int, body: AckIn, ctx: OrgContext = Depends(require("security.manage"))):
    """Record that someone reviewed a detection. It does not change anything on the PC."""
    e = get_owned(ctx, Endpoint, endpoint_id, "Endpoint")
    t = ctx.db.get(EndpointThreat, threat_id)
    if t is None or t.endpoint_id != e.id:
        raise HTTPException(404, "Threat not found")
    if t.status in es.ACTIVE:
        raise HTTPException(409, "This threat is still active on the PC. Remove it there (Windows Security), "
                                 "then wait for the next report")
    t.acknowledged_at, t.acknowledged_by, t.acknowledge_note = utcnow(), ctx.user.id, body.note
    ctx.audit("acknowledge_threat", "endpoint", e.id, {"threat": t.threat_name, "note": body.note})
    ctx.db.commit()
    return _threat_out(ctx, t)
