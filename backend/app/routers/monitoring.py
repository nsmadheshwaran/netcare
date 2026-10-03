"""Phase 6: network/CCTV monitoring. Admin API for agents and checks, and the agent API.

The agent API authenticates with a per-agent token (`Authorization: Bearer nca_...`), not a user login.
An agent can read only its own configuration and report results only for its own checks.
"""
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import OrgContext, require
from ..models import Customer, utcnow
from ..models_monitoring import MonitorAgent, MonitorCheck, MonitorIncident
from ..models_service import Asset
from ..services import monitoring as mon
from ..services.trade import get_owned

router = APIRouter(tags=["monitoring"])
AGENT_MAX_BATCH = 1000


# ---------------- schemas ----------------
class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    customer_id: int | None = None
    site_note: str | None = Field(default=None, max_length=200)
    collect_endpoint: bool = False


class AgentOut(BaseModel):
    id: int
    name: str
    customer_id: int | None
    customer_name: str | None
    site_note: str | None
    token_prefix: str
    status: str
    online: bool
    last_seen_at: datetime | None
    last_ip: str | None
    agent_version: str | None
    hostname: str | None
    checks: int
    collect_endpoint: bool


class AgentCreated(AgentOut):
    token: str  # shown once


class CheckIn(BaseModel):
    agent_id: int
    asset_id: int | None = None
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["icmp", "tcp"]
    host: str | None = Field(default=None, max_length=255)  # defaults to the asset's IP address
    port: int | None = Field(default=None, ge=1, le=65535)
    interval_seconds: int = Field(60, ge=30, le=3600)
    timeout_ms: int = Field(2000, ge=200, le=10000)
    failure_threshold: int = Field(3, ge=1, le=20)
    latency_warn_ms: int | None = Field(default=None, ge=1, le=60000)
    enabled: bool = True

    @field_validator("host")
    @classmethod
    def _host(cls, v):
        return None if v is None or not v.strip() else mon.validate_host(v)

    @model_validator(mode="after")
    def _port(self):
        if self.kind == "tcp" and self.port is None:
            raise ValueError("A TCP check needs a port")
        if self.kind == "icmp":
            self.port = None
        if self.timeout_ms >= self.interval_seconds * 1000:
            raise ValueError("The timeout must be shorter than the interval")
        return self


class CheckOut(BaseModel):
    id: int
    agent_id: int
    agent_name: str
    asset_id: int | None
    asset_name: str | None
    customer_name: str | None
    name: str
    kind: str
    host: str
    port: int | None
    interval_seconds: int
    timeout_ms: int
    failure_threshold: int
    latency_warn_ms: int | None
    enabled: bool
    status: str  # effective: unknown when the agent is offline or the data is stale
    stored_status: str
    status_since: datetime | None
    last_checked_at: datetime | None
    last_latency_ms: int | None
    last_error: str | None
    consecutive_failures: int


class ResultIn(BaseModel):
    check_id: int
    observed_at: datetime
    ok: bool
    latency_ms: int | None = Field(default=None, ge=0, le=600000)
    error: str | None = Field(default=None, max_length=500)

    @field_validator("observed_at")
    @classmethod
    def _aware(cls, v: datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


class ResultsIn(BaseModel):
    results: list[ResultIn] = Field(max_length=AGENT_MAX_BATCH)


# ---------------- helpers ----------------
def _agent_out(ctx: OrgContext, a: MonitorAgent) -> AgentOut:
    cust = ctx.db.get(Customer, a.customer_id) if a.customer_id else None
    n = ctx.db.scalar(select(func.count()).select_from(MonitorCheck).where(MonitorCheck.agent_id == a.id))
    return AgentOut(id=a.id, name=a.name, customer_id=a.customer_id, customer_name=cust.name if cust else None,
                    site_note=a.site_note, token_prefix=a.token_prefix, status=a.status, online=mon.agent_online(a),
                    last_seen_at=a.last_seen_at, last_ip=a.last_ip, agent_version=a.agent_version,
                    hostname=a.hostname, checks=n, collect_endpoint=a.collect_endpoint)


def _check_out(ctx: OrgContext, c: MonitorCheck, now: datetime | None = None) -> CheckOut:
    agent = ctx.db.get(MonitorAgent, c.agent_id)
    asset = ctx.db.get(Asset, c.asset_id) if c.asset_id else None
    cust_id = asset.customer_id if asset else agent.customer_id
    cust = ctx.db.get(Customer, cust_id) if cust_id else None
    return CheckOut(id=c.id, agent_id=c.agent_id, agent_name=agent.name, asset_id=c.asset_id,
                    asset_name=asset.name if asset else None, customer_name=cust.name if cust else None,
                    name=c.name, kind=c.kind, host=c.host, port=c.port, interval_seconds=c.interval_seconds,
                    timeout_ms=c.timeout_ms, failure_threshold=c.failure_threshold,
                    latency_warn_ms=c.latency_warn_ms, enabled=c.enabled,
                    status=mon.effective_status(c, agent, now), stored_status=c.status, status_since=c.status_since,
                    last_checked_at=c.last_checked_at, last_latency_ms=c.last_latency_ms, last_error=c.last_error,
                    consecutive_failures=c.consecutive_failures)


def asset_monitor_status(ctx: OrgContext, asset_id: int) -> str | None:
    """Worst effective status of the asset's enabled checks; None if it is not monitored."""
    checks = ctx.db.scalars(select(MonitorCheck).where(MonitorCheck.asset_id == asset_id,
                                                       MonitorCheck.enabled.is_(True))).all()
    if not checks:
        return None
    now = utcnow()
    return max((mon.effective_status(c, ctx.db.get(MonitorAgent, c.agent_id), now) for c in checks),
               key=lambda s: mon.SEVERITY[s])


def _close_incidents(ctx: OrgContext, check_ids: list[int], why: str) -> None:
    """End open outages when monitoring stops, so downtime does not keep growing for a check nobody runs."""
    if not check_ids:
        return
    for inc in ctx.db.scalars(select(MonitorIncident).where(MonitorIncident.check_id.in_(check_ids),
                                                            MonitorIncident.ended_at.is_(None))):
        inc.ended_at, inc.reason = utcnow(), f"{inc.reason or ''} ({why})".strip()


def _validate_check(ctx: OrgContext, body: CheckIn, exclude_id: int | None = None,
                    current_agent_id: int | None = None) -> str:
    agent = get_owned(ctx, MonitorAgent, body.agent_id, "Agent", status_code=422)
    # A revoked agent gets no new checks, but its existing checks can still be edited (e.g. disabled).
    if agent.status != "active" and agent.id != current_agent_id:
        raise HTTPException(422, "The agent's token is revoked")
    host = body.host
    if body.asset_id is not None:
        asset = get_owned(ctx, Asset, body.asset_id, "Equipment", status_code=422)
        if agent.customer_id and asset.customer_id != agent.customer_id:
            raise HTTPException(422, "The equipment is at another site than the agent")
        host = host or asset.ip_address
    if not host:
        raise HTTPException(422, "Enter the host, or link equipment that has an IP address")
    q = select(func.count()).select_from(MonitorCheck).where(MonitorCheck.agent_id == agent.id)
    if exclude_id:
        q = q.where(MonitorCheck.id != exclude_id)
    if ctx.db.scalar(q) >= mon.MAX_CHECKS_PER_AGENT:
        raise HTTPException(409, f"An agent can run at most {mon.MAX_CHECKS_PER_AGENT} checks")
    return host


# ---------------- agents (admin) ----------------
@router.get("/monitoring/agents", response_model=list[AgentOut])
def list_agents(ctx: OrgContext = Depends(require("monitoring.view"))):
    rows = ctx.db.scalars(select(MonitorAgent).where(MonitorAgent.organization_id == ctx.org_id)
                          .order_by(MonitorAgent.name)).all()
    return [_agent_out(ctx, a) for a in rows]


@router.post("/monitoring/agents", response_model=AgentCreated, status_code=201)
def create_agent(body: AgentIn, ctx: OrgContext = Depends(require("monitoring.manage"))):
    if body.customer_id is not None:
        get_owned(ctx, Customer, body.customer_id, "Customer", status_code=422)
    if ctx.db.scalar(select(MonitorAgent.id).where(MonitorAgent.organization_id == ctx.org_id,
                                                   MonitorAgent.name == body.name)):
        raise HTTPException(409, "An agent with this name exists")
    raw, digest, prefix = mon.new_token()
    a = MonitorAgent(organization_id=ctx.org_id, token_hash=digest, token_prefix=prefix, created_by=ctx.user.id,
                     **body.model_dump())
    ctx.db.add(a)
    ctx.db.flush()
    ctx.audit("create", "monitor_agent", a.id, {"name": a.name, "token_prefix": prefix})
    ctx.db.commit()
    return AgentCreated(**_agent_out(ctx, a).model_dump(), token=raw)


@router.put("/monitoring/agents/{agent_id}", response_model=AgentOut)
def update_agent(agent_id: int, body: AgentIn, ctx: OrgContext = Depends(require("monitoring.manage"))):
    a = get_owned(ctx, MonitorAgent, agent_id, "Agent")
    if body.customer_id is not None:
        get_owned(ctx, Customer, body.customer_id, "Customer", status_code=422)
    for k, v in body.model_dump().items():
        setattr(a, k, v)
    ctx.audit("update", "monitor_agent", a.id, body.model_dump())
    ctx.db.commit()
    return _agent_out(ctx, a)


@router.post("/monitoring/agents/{agent_id}/rotate-token", response_model=AgentCreated)
def rotate_token(agent_id: int, ctx: OrgContext = Depends(require("monitoring.manage"))):
    """Issue a new token; the old one stops working at once. Also re-activates a revoked agent."""
    a = get_owned(ctx, MonitorAgent, agent_id, "Agent")
    raw, a.token_hash, a.token_prefix = mon.new_token()
    a.status, a.revoked_at = "active", None
    ctx.audit("rotate_token", "monitor_agent", a.id, {"token_prefix": a.token_prefix})
    ctx.db.commit()
    return AgentCreated(**_agent_out(ctx, a).model_dump(), token=raw)


@router.post("/monitoring/agents/{agent_id}/revoke", response_model=AgentOut)
def revoke_agent(agent_id: int, ctx: OrgContext = Depends(require("monitoring.manage"))):
    a = get_owned(ctx, MonitorAgent, agent_id, "Agent")
    if a.status == "revoked":
        raise HTTPException(409, "Already revoked")
    a.status, a.revoked_at = "revoked", utcnow()
    _close_incidents(ctx, list(ctx.db.scalars(select(MonitorCheck.id).where(MonitorCheck.agent_id == a.id))),
                     "agent revoked")
    ctx.audit("revoke", "monitor_agent", a.id, {"token_prefix": a.token_prefix})
    ctx.db.commit()
    return _agent_out(ctx, a)


# ---------------- checks (admin) ----------------
@router.get("/monitoring/checks", response_model=list[CheckOut])
def list_checks(ctx: OrgContext = Depends(require("monitoring.view")), agent_id: int | None = None,
                asset_id: int | None = None, status: str | None = None):
    q = select(MonitorCheck).where(MonitorCheck.organization_id == ctx.org_id)
    if agent_id:
        q = q.where(MonitorCheck.agent_id == agent_id)
    if asset_id:
        q = q.where(MonitorCheck.asset_id == asset_id)
    now = utcnow()
    out = [_check_out(ctx, c, now) for c in ctx.db.scalars(q.order_by(MonitorCheck.name))]
    if status:
        out = [c for c in out if c.status == status]
    return sorted(out, key=lambda c: (-mon.SEVERITY[c.status], c.customer_name or "", c.name))


@router.post("/monitoring/checks", response_model=CheckOut, status_code=201)
def create_check(body: CheckIn, ctx: OrgContext = Depends(require("monitoring.manage"))):
    host = _validate_check(ctx, body)
    c = MonitorCheck(organization_id=ctx.org_id, **{**body.model_dump(), "host": host})
    ctx.db.add(c)
    ctx.db.flush()
    ctx.audit("create", "monitor_check", c.id, {"kind": c.kind, "host": c.host, "port": c.port})
    ctx.db.commit()
    return _check_out(ctx, c)


@router.get("/monitoring/checks/{check_id}", response_model=CheckOut)
def get_check(check_id: int, ctx: OrgContext = Depends(require("monitoring.view"))):
    return _check_out(ctx, get_owned(ctx, MonitorCheck, check_id, "Check"))


@router.put("/monitoring/checks/{check_id}", response_model=CheckOut)
def update_check(check_id: int, body: CheckIn, ctx: OrgContext = Depends(require("monitoring.manage"))):
    c = get_owned(ctx, MonitorCheck, check_id, "Check")
    host = _validate_check(ctx, body, exclude_id=c.id, current_agent_id=c.agent_id)
    new = {**body.model_dump(), "host": host}
    target_changed = any(getattr(c, k) != new[k] for k in ("agent_id", "kind", "host", "port"))
    for k, v in new.items():
        setattr(c, k, v)
    if target_changed:  # old state described another target
        c.status, c.status_since, c.consecutive_failures, c.failing_since = "unknown", None, 0, None
        c.last_checked_at = c.last_latency_ms = c.last_error = None
        _close_incidents(ctx, [c.id], "check target changed")
    elif not c.enabled:
        _close_incidents(ctx, [c.id], "check disabled")
    ctx.audit("update", "monitor_check", c.id, {"target_changed": target_changed})
    ctx.db.commit()
    return _check_out(ctx, c)


@router.delete("/monitoring/checks/{check_id}", status_code=204)
def delete_check(check_id: int, ctx: OrgContext = Depends(require("monitoring.manage"))):
    c = get_owned(ctx, MonitorCheck, check_id, "Check")
    ctx.audit("delete", "monitor_check", c.id, {"name": c.name, "host": c.host})
    ctx.db.delete(c)
    ctx.db.commit()


@router.get("/monitoring/checks/{check_id}/stats")
def check_stats(check_id: int, ctx: OrgContext = Depends(require("monitoring.view")),
                range: Literal["24h", "7d", "30d"] = "24h"):
    c = get_owned(ctx, MonitorCheck, check_id, "Check")
    now = utcnow()
    span = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}[range]
    incidents = ctx.db.scalars(select(MonitorIncident).where(MonitorIncident.check_id == c.id)
                               .order_by(MonitorIncident.started_at.desc()).limit(20)).all()
    return {
        "windows": {k: mon.window_stats(ctx.db, c.id, now - d, now) for k, d in
                    (("24h", timedelta(hours=24)), ("7d", timedelta(days=7)), ("30d", timedelta(days=30)))},
        "series": mon.series(ctx.db, c.id, now - span, now),
        "incidents": [{"id": i.id, "started_at": i.started_at, "ended_at": i.ended_at, "reason": i.reason,
                       "minutes": round(((i.ended_at or now) - i.started_at).total_seconds() / 60)}
                      for i in incidents],
    }


@router.get("/monitoring/overview")
def overview(ctx: OrgContext = Depends(require("monitoring.view"))):
    now = utcnow()
    checks = [_check_out(ctx, c, now) for c in ctx.db.scalars(
        select(MonitorCheck).where(MonitorCheck.organization_id == ctx.org_id))]
    agents = ctx.db.scalars(select(MonitorAgent).where(MonitorAgent.organization_id == ctx.org_id,
                                                       MonitorAgent.status == "active")).all()
    counts = {s: 0 for s in ("up", "degraded", "down", "unknown")}
    for c in checks:
        counts[c.status] += 1
    open_incidents = ctx.db.scalar(select(func.count()).select_from(MonitorIncident).where(
        MonitorIncident.organization_id == ctx.org_id, MonitorIncident.ended_at.is_(None)))
    return {"checks": counts, "agents_total": len(agents),
            "agents_online": sum(1 for a in agents if mon.agent_online(a, now)), "open_incidents": open_incidents}


# ---------------- agent API ----------------
def current_agent(request: Request, authorization: str | None = Header(None),
                  x_agent_version: str | None = Header(None), x_agent_hostname: str | None = Header(None),
                  db: Session = Depends(get_db)) -> MonitorAgent:
    unauthorized = HTTPException(401, "Invalid or revoked agent token", headers={"WWW-Authenticate": "Bearer"})
    if not authorization or not authorization.startswith("Bearer " + mon.TOKEN_PREFIX):
        raise unauthorized
    a = db.scalar(select(MonitorAgent).where(MonitorAgent.token_hash == mon.hash_token(authorization[7:].strip())))
    if a is None or a.status != "active":
        raise unauthorized
    a.last_seen_at = utcnow()
    a.last_ip = request.client.host if request.client else None
    a.agent_version = (x_agent_version or "")[:20] or a.agent_version
    a.hostname = (x_agent_hostname or "")[:100] or a.hostname
    return a


@router.get("/agent/config")
def agent_config(agent: MonitorAgent = Depends(current_agent), db: Session = Depends(get_db)):
    checks = db.scalars(select(MonitorCheck).where(MonitorCheck.agent_id == agent.id,
                                                   MonitorCheck.enabled.is_(True)).order_by(MonitorCheck.id)).all()
    db.commit()
    return {"agent_id": agent.id, "server_time": utcnow().isoformat(), "config_refresh_seconds": 300,
            "collect_endpoint": agent.collect_endpoint, "endpoint_report_seconds": 900,
            "checks": [{"id": c.id, "kind": c.kind, "host": c.host, "port": c.port,
                        "interval_seconds": c.interval_seconds, "timeout_ms": c.timeout_ms} for c in checks]}


@router.post("/agent/results")
def agent_results(body: ResultsIn, agent: MonitorAgent = Depends(current_agent), db: Session = Depends(get_db)):
    now = utcnow()
    for r in body.results:
        if r.observed_at > now + timedelta(minutes=5):
            raise HTTPException(422, "A result is timestamped in the future; check the agent's clock")
    # Queued results older than the retention window would be pruned at once; drop them here.
    fresh = [r.model_dump() for r in body.results if r.observed_at >= now - timedelta(days=mon.RESULT_RETENTION_DAYS)]
    out = mon.ingest(db, agent, fresh)
    db.commit()
    return {**out, "too_old": len(body.results) - len(fresh)}


@router.get("/monitoring/assets/{asset_id}/checks", response_model=list[CheckOut])
def asset_checks(asset_id: int, ctx: OrgContext = Depends(require("monitoring.view"))):
    get_owned(ctx, Asset, asset_id, "Equipment")
    return [_check_out(ctx, c) for c in ctx.db.scalars(select(MonitorCheck).where(MonitorCheck.asset_id == asset_id))]
