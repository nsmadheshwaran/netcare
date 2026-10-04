"""Monitoring: agent tokens, target validation, result ingestion (state machine) and uptime statistics.

Status rules:
- A successful result makes a check "up", or "degraded" if slower than its latency warning.
- A failure counts towards `failure_threshold`; reaching it makes the check "down" and opens an incident that
  starts at the first failure of the run. The next success closes it.
- Results are applied in observed order. A late result (older than the last applied one) is stored for the
  statistics but does not change the current state.
- What the server cannot see, it does not guess: when the agent stops reporting, checks show "unknown"
  (computed at read time) and no incident is opened.
"""
import hashlib
import ipaddress
import re
import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, select

from ..models import utcnow
from ..models_monitoring import CheckResult, MonitorAgent, MonitorCheck, MonitorIncident
from .timeutil import BUSINESS_TZ

TOKEN_PREFIX = "nca_"
RESULT_RETENTION_DAYS = 30
MAX_CHECKS_PER_AGENT = 200
AGENT_OFFLINE_AFTER = timedelta(minutes=5)
HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
                         r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
SEVERITY = {"down": 3, "degraded": 2, "unknown": 1, "up": 0}


# ---------------- tokens ----------------
def new_token() -> tuple[str, str, str]:
    """Returns (token shown once, its hash to store, a short prefix for display)."""
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return raw, hash_token(raw), raw[len(TOKEN_PREFIX):len(TOKEN_PREFIX) + 8]


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------- targets ----------------
def validate_host(host: str) -> str:
    """Exactly one host: an IP address or a DNS name. No ranges, CIDR blocks, wildcards or URLs."""
    host = host.strip()
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # A real host name ends in a label with a letter: "10.0.0.1-50" or "1.2.3" are not host names.
        if not HOSTNAME_RE.match(host) or not re.search(r"[A-Za-z]", host.rsplit(".", 1)[-1]):
            raise ValueError("Enter one IP address or host name (no ranges, CIDR blocks or URLs)")
        return host.lower()
    if ip.is_unspecified or ip.is_multicast or (ip.version == 4 and ip == ipaddress.ip_address("255.255.255.255")):
        raise ValueError("Broadcast, multicast and unspecified addresses cannot be monitored")
    return str(ip)


# ---------------- state ----------------
def agent_online(agent: MonitorAgent, now: datetime | None = None) -> bool:
    now = now or utcnow()
    return (agent.status == "active" and agent.last_seen_at is not None
            and now - agent.last_seen_at <= AGENT_OFFLINE_AFTER)


def effective_status(check: MonitorCheck, agent: MonitorAgent, now: datetime | None = None) -> str:
    """The status to show now: the stored state, unless the data is too old to trust."""
    now = now or utcnow()
    if not check.enabled or not agent_online(agent, now) or check.last_checked_at is None:
        return "unknown"
    if now - check.last_checked_at > timedelta(seconds=3 * check.interval_seconds + 60):
        return "unknown"
    return check.status


def _target(c: MonitorCheck) -> str:
    return f"{c.host}:{c.port}" if c.port else c.host


def _notify(db, c: MonitorCheck, severity: str, title: str, body: str, key: str) -> None:
    from .notify import notify  # local import: notify imports models that import this module's peers
    notify(db, c.organization_id, "monitor_down", title, body, "/monitoring", severity, dedupe=key)


def _set_status(c: MonitorCheck, status: str, at: datetime) -> None:
    if c.status != status:
        c.status, c.status_since = status, at


def apply_result(db, c: MonitorCheck, at: datetime, ok: bool, latency_ms: int | None, error: str | None,
                 values: dict | None = None) -> None:
    """Advance the check's state machine with one result newer than the last applied one."""
    c.last_checked_at, c.last_latency_ms = at, latency_ms if ok else None
    if values is not None:
        c.last_values = values
    open_inc = db.scalar(select(MonitorIncident).where(MonitorIncident.check_id == c.id,
                                                       MonitorIncident.ended_at.is_(None)))
    if ok:
        c.consecutive_failures, c.failing_since, c.last_error = 0, None, None
        if open_inc:
            open_inc.ended_at = at
            mins = round((at - open_inc.started_at).total_seconds() / 60)
            _notify(db, c, "success", f"Back up: {c.name}", f"{_target(c)} is reachable again after {mins} min.",
                    f"up:{open_inc.id}")
        slow = c.latency_warn_ms is not None and latency_ms is not None and latency_ms > c.latency_warn_ms
        _set_status(c, "degraded" if slow else "up", at)
        return
    c.consecutive_failures += 1
    c.last_error = error
    if c.failing_since is None:
        c.failing_since = at
    if c.consecutive_failures >= c.failure_threshold:
        if open_inc is None:
            inc = MonitorIncident(organization_id=c.organization_id, check_id=c.id, started_at=c.failing_since,
                                  reason=error)
            db.add(inc)
            db.flush()
            _notify(db, c, "critical", f"Down: {c.name}",
                    f"{_target(c)} has failed {c.consecutive_failures} checks in a row since "
                    f"{c.failing_since.astimezone(BUSINESS_TZ):%d %b %H:%M}. Last error: {error or 'none'}.",
                    f"down:{inc.id}")
        _set_status(c, "down", c.failing_since if c.status != "down" else at)


def ingest(db, agent: MonitorAgent, results: list[dict]) -> dict:
    """Store a batch from an agent. Idempotent: a (check, observed_at) already stored is skipped."""
    checks = {c.id: c for c in db.scalars(select(MonitorCheck).where(MonitorCheck.agent_id == agent.id))}
    accepted = duplicates = 0
    rejected: list[int] = []
    seen: set = set()
    for r in sorted(results, key=lambda r: r["observed_at"]):
        c = checks.get(r["check_id"])
        if c is None:
            rejected.append(r["check_id"])
            continue
        at = r["observed_at"]
        if (c.id, at) in seen or db.scalar(select(CheckResult.id).where(CheckResult.check_id == c.id, CheckResult.observed_at == at)):
            duplicates += 1
            continue
        error = (r.get("error") or None) and r["error"][:200]
        values = r.get("values") if c.kind == "snmp" else None
        db.add(CheckResult(organization_id=agent.organization_id, check_id=c.id, observed_at=at, ok=r["ok"],
                           latency_ms=r.get("latency_ms"), error=error, values=values))
        seen.add((c.id, at))
        accepted += 1
        if c.last_checked_at is None or at > c.last_checked_at:
            apply_result(db, c, at, r["ok"], r.get("latency_ms"), error, values)
    if checks:
        db.execute(delete(CheckResult).where(
            CheckResult.check_id.in_(list(checks)),
            CheckResult.observed_at < utcnow() - timedelta(days=RESULT_RETENTION_DAYS)))
    return {"accepted": accepted, "duplicates": duplicates, "rejected_check_ids": sorted(set(rejected))}


# ---------------- statistics ----------------
def _p95(values: list[int]) -> int | None:
    if not values:
        return None
    v = sorted(values)
    return v[min(len(v) - 1, int(round(0.95 * (len(v) - 1))))]


def window_stats(db, check_id: int, start: datetime, end: datetime) -> dict:
    rows = db.execute(select(CheckResult.ok, CheckResult.latency_ms).where(
        CheckResult.check_id == check_id, CheckResult.observed_at >= start, CheckResult.observed_at < end)).all()
    ok_lat = [lat for ok, lat in rows if ok and lat is not None]
    incidents = db.scalars(select(MonitorIncident).where(
        MonitorIncident.check_id == check_id, MonitorIncident.started_at < end,
        (MonitorIncident.ended_at.is_(None)) | (MonitorIncident.ended_at > start))).all()
    down = sum(((min(i.ended_at or end, end) - max(i.started_at, start)).total_seconds() for i in incidents), 0.0)
    return {
        "samples": len(rows),
        # Share of results that succeeded. None when nothing was measured: no data is not 100 %.
        "uptime_pct": round(100 * sum(1 for ok, _ in rows if ok) / len(rows), 2) if rows else None,
        "avg_latency_ms": round(sum(ok_lat) / len(ok_lat)) if ok_lat else None,
        "p95_latency_ms": _p95(ok_lat),
        "incidents": len(incidents),
        "downtime_minutes": round(down / 60),
    }


def series(db, check_id: int, start: datetime, end: datetime, buckets: int = 48) -> list[dict]:
    step = (end - start) / buckets
    out = [{"t": (start + step * i).isoformat(), "lat": [], "fail": 0, "n": 0} for i in range(buckets)]
    for at, ok, lat in db.execute(select(CheckResult.observed_at, CheckResult.ok, CheckResult.latency_ms).where(
            CheckResult.check_id == check_id, CheckResult.observed_at >= start, CheckResult.observed_at < end)):
        b = out[min(buckets - 1, int((at - start) / step))]
        b["n"] += 1
        if ok and lat is not None:
            b["lat"].append(lat)
        if not ok:
            b["fail"] += 1
    return [{"t": b["t"], "samples": b["n"], "failures": b["fail"],
             "avg_latency_ms": round(sum(b["lat"]) / len(b["lat"])) if b["lat"] else None} for b in out]
