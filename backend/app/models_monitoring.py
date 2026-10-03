"""Phase 6: monitoring agents, checks, results and incidents.

An agent runs on a customer's network and reports results over outbound HTTPS. It only ever runs the checks
configured here (ICMP ping or a TCP connect to one host and port). There are no ranges or discovery: each check
names exactly one host. The server stores a SHA-256 hash of the agent token, never the token.
"""
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import Boolean, TimestampMixin, UTCDateTime


class MonitorAgent(TimestampMixin, Base):
    __tablename__ = "monitor_agents"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))  # the site it runs at
    name: Mapped[str] = mapped_column(String(100))
    site_note: Mapped[str | None] = mapped_column(String(200))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_prefix: Mapped[str] = mapped_column(String(12))  # shown in the UI to tell tokens apart
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | revoked
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_ip: Mapped[str | None] = mapped_column(String(45))
    agent_version: Mapped[str | None] = mapped_column(String(20))
    hostname: Mapped[str | None] = mapped_column(String(100))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class MonitorCheck(TimestampMixin, Base):
    __tablename__ = "monitor_checks"
    __table_args__ = (
        Index("ix_checks_org_agent", "organization_id", "agent_id"),
        CheckConstraint("interval_seconds >= 30", name="ck_check_interval"),
        CheckConstraint("(kind = 'tcp') = (port IS NOT NULL)", name="ck_check_port"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("monitor_agents.id", ondelete="CASCADE"))
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(5))  # icmp | tcp
    host: Mapped[str] = mapped_column(String(255))  # one IP address or host name; never a range
    port: Mapped[int | None] = mapped_column(Integer)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=60)
    timeout_ms: Mapped[int] = mapped_column(Integer, default=2000)
    failure_threshold: Mapped[int] = mapped_column(Integer, default=3)  # consecutive failures before "down"
    latency_warn_ms: Mapped[int | None] = mapped_column(Integer)  # slower than this is "degraded"
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Current state, maintained from results in observed order
    status: Mapped[str] = mapped_column(String(10), default="unknown")  # unknown | up | degraded | down
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    failing_since: Mapped[datetime | None] = mapped_column(UTCDateTime())  # first failure of the current run
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_latency_ms: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(String(200))
    status_since: Mapped[datetime | None] = mapped_column(UTCDateTime())


class CheckResult(Base):
    """Raw results, kept for RESULT_RETENTION_DAYS. Incidents are kept forever."""
    __tablename__ = "check_results"
    __table_args__ = (UniqueConstraint("check_id", "observed_at"),
                      Index("ix_results_check_time", "check_id", "observed_at"))
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    check_id: Mapped[int] = mapped_column(ForeignKey("monitor_checks.id", ondelete="CASCADE"))
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    ok: Mapped[bool] = mapped_column(Boolean)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(200))


class MonitorIncident(Base):
    """A period during which a check was down. Open while ended_at is null."""
    __tablename__ = "monitor_incidents"
    __table_args__ = (Index("ix_incidents_check", "check_id", "started_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    check_id: Mapped[int] = mapped_column(ForeignKey("monitor_checks.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())  # first failed result of the run
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime())  # first successful result after it
    reason: Mapped[str | None] = mapped_column(Text)
