"""Endpoint security: store Defender reports and rate each PC.

Rating (worst wins), each with a plain reason the technician can act on:
- critical: antivirus or real-time protection off; an active (unresolved) threat; Defender not available.
- warning: signatures older than 3 days; no quick or full scan in 14 days; tamper protection off; Defender in
  passive mode (another antivirus should be protecting the PC); a threat the user allowed; a resolved threat
  in the last 7 days that nobody has acknowledged.
- unknown: no report for 24 hours (the PC may just be switched off; nothing is guessed).
"""
from datetime import datetime, timedelta

from sqlalchemy import select

from ..models import utcnow
from ..models_security import Endpoint, EndpointThreat

STALE_AFTER = timedelta(hours=24)
SIGNATURE_MAX_AGE = timedelta(days=3)
SCAN_MAX_AGE = timedelta(days=14)
RECENT_THREAT = timedelta(days=7)

# Defender ThreatStatusID -> our status
THREAT_STATUS = {0: "unknown", 1: "detected", 2: "cleaned", 3: "quarantined", 4: "removed", 5: "allowed",
                 6: "blocked", 102: "quarantine_failed", 103: "remove_failed", 104: "allow_failed",
                 105: "abandoned", 107: "block_failed"}
RESOLVED = {"cleaned", "quarantined", "removed", "blocked"}
ACTIVE = {"detected", "quarantine_failed", "remove_failed", "abandoned", "block_failed", "unknown"}
SEVERITY = {0: "unknown", 1: "low", 2: "moderate", 4: "high", 5: "severe"}
RANK = {"critical": 3, "warning": 2, "unknown": 1, "ok": 0}


def evaluate(e: Endpoint, threats: list[EndpointThreat], now: datetime | None = None) -> tuple[str, list[str]]:
    now = now or utcnow()
    if e.last_report_at is None:
        return "unknown", ["Has not reported yet"]
    issues: list[tuple[str, str]] = []
    if now - e.last_report_at > STALE_AFTER:
        return "unknown", [f"No report since {e.last_report_at:%d %b %Y %H:%M} UTC (PC off or agent stopped)"]
    if not e.defender_available:
        issues.append(("critical", "Microsoft Defender status is not available on this PC"))
    else:
        passive = (e.running_mode or "").lower().startswith("passive")
        if e.av_enabled is False and not passive:
            issues.append(("critical", "Antivirus is turned off"))
        if e.realtime_enabled is False and not passive:
            issues.append(("critical", "Real-time protection is turned off"))
        if passive:
            issues.append(("warning", "Defender is in passive mode: confirm another antivirus is active"))
        if e.tamper_protected is False:
            issues.append(("warning", "Tamper protection is off"))
        if e.signature_updated_at is None or now - e.signature_updated_at > SIGNATURE_MAX_AGE:
            age = "never" if e.signature_updated_at is None else f"{(now - e.signature_updated_at).days} days ago"
            issues.append(("warning", f"Virus definitions are out of date (updated {age})"))
        last_scan = max((d for d in (e.quick_scan_at, e.full_scan_at) if d), default=None)
        if last_scan is None or now - last_scan > SCAN_MAX_AGE:
            issues.append(("warning", "No scan in the last 14 days"))
    for t in threats:
        if t.status in ACTIVE:
            issues.append(("critical", f"Active threat: {t.threat_name} ({t.status.replace('_', ' ')})"))
        elif t.status == "allowed" and t.acknowledged_at is None:
            issues.append(("warning", f"Threat allowed by a user: {t.threat_name}"))
        elif t.status in RESOLVED and t.acknowledged_at is None and now - t.detected_at <= RECENT_THREAT:
            issues.append(("warning", f"Recent threat {t.status}: {t.threat_name} (review and acknowledge)"))
    if not issues:
        return "ok", []
    level = max((lvl for lvl, _ in issues), key=RANK.__getitem__)
    return level, [msg for lvl, msg in sorted(issues, key=lambda i: -RANK[i[0]])]


def ingest_report(db, agent, report: dict) -> Endpoint:
    """Upsert the endpoint for (agent, hostname) and its detections."""
    now = utcnow()
    e = db.scalar(select(Endpoint).where(Endpoint.agent_id == agent.id, Endpoint.hostname == report["hostname"]))
    if e is None:
        e = Endpoint(organization_id=agent.organization_id, agent_id=agent.id, hostname=report["hostname"])
        db.add(e)
    e.os_name, e.os_version, e.last_report_at = report.get("os_name"), report.get("os_version"), now
    d = report.get("defender")
    e.defender_available = d is not None
    fields = ("av_enabled", "realtime_enabled", "antispyware_enabled", "behavior_monitor_enabled",
              "tamper_protected", "running_mode", "signature_version", "signature_updated_at", "engine_version",
              "product_version", "quick_scan_at", "full_scan_at")
    for f in fields:
        setattr(e, f, (d or {}).get(f))
    db.flush()
    for t in report.get("threats", []):
        row = db.scalar(select(EndpointThreat).where(EndpointThreat.endpoint_id == e.id,
                                                     EndpointThreat.detection_id == t["detection_id"]))
        status = THREAT_STATUS.get(t.get("status_id"), "unknown")
        if row is None:
            db.add(EndpointThreat(
                organization_id=e.organization_id, endpoint_id=e.id, detection_id=t["detection_id"],
                threat_name=t["threat_name"], severity=SEVERITY.get(t.get("severity_id"), "unknown"),
                category=t.get("category"), status=status, action_success=t.get("action_success"),
                detected_at=t["detected_at"], resources=t.get("resources"), first_reported_at=now))
            continue
        if row.status != status and status in ACTIVE | {"allowed"}:
            row.acknowledged_at = row.acknowledged_by = row.acknowledge_note = None  # got worse: review again
        row.status, row.action_success = status, t.get("action_success")
        row.times_reported += 1
    return e
