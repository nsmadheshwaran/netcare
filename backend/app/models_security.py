"""Phase 7: endpoint security visibility (Microsoft Defender).

Read-only: NetCare shows what Defender reports on a PC. It never changes Defender settings, starts scans or
removes threats; those stay with the technician at the PC (or in Microsoft's own tools).
"""
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import Boolean, TimestampMixin, UTCDateTime


class Endpoint(TimestampMixin, Base):
    """A PC that reports its Defender status through an agent running on it."""
    __tablename__ = "endpoints"
    __table_args__ = (UniqueConstraint("agent_id", "hostname"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("monitor_agents.id", ondelete="CASCADE"))
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), index=True)  # the computer, if registered
    hostname: Mapped[str] = mapped_column(String(100))
    os_name: Mapped[str | None] = mapped_column(String(120))
    os_version: Mapped[str | None] = mapped_column(String(40))
    last_report_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    defender_available: Mapped[bool] = mapped_column(Boolean, default=False)
    # Defender status, as last reported (None = not reported)
    av_enabled: Mapped[bool | None] = mapped_column(Boolean)
    realtime_enabled: Mapped[bool | None] = mapped_column(Boolean)
    antispyware_enabled: Mapped[bool | None] = mapped_column(Boolean)
    behavior_monitor_enabled: Mapped[bool | None] = mapped_column(Boolean)
    tamper_protected: Mapped[bool | None] = mapped_column(Boolean)
    running_mode: Mapped[str | None] = mapped_column(String(30))  # Normal | Passive | EDR Block Mode ...
    signature_version: Mapped[str | None] = mapped_column(String(40))
    signature_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    engine_version: Mapped[str | None] = mapped_column(String(40))
    product_version: Mapped[str | None] = mapped_column(String(40))
    quick_scan_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    full_scan_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class EndpointThreat(Base):
    """One Defender detection. Upserted by Defender's DetectionID, so repeated reports update the status."""
    __tablename__ = "endpoint_threats"
    __table_args__ = (UniqueConstraint("endpoint_id", "detection_id"),
                      Index("ix_threats_org_detected", "organization_id", "detected_at"))
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    endpoint_id: Mapped[int] = mapped_column(ForeignKey("endpoints.id", ondelete="CASCADE"))
    detection_id: Mapped[str] = mapped_column(String(64))
    threat_name: Mapped[str] = mapped_column(String(200))
    severity: Mapped[str] = mapped_column(String(10))  # unknown | low | moderate | high | severe
    category: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))  # see services.endpoint_security.THREAT_STATUS
    action_success: Mapped[bool | None] = mapped_column(Boolean)
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime())
    resources: Mapped[str | None] = mapped_column(Text)  # affected file paths/URLs as Defender lists them
    first_reported_at: Mapped[datetime] = mapped_column(UTCDateTime())
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    acknowledged_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    acknowledge_note: Mapped[str | None] = mapped_column(Text)
    times_reported: Mapped[int] = mapped_column(Integer, default=1)
