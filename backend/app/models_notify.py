"""Phase 9: notifications (in-app), per-user preferences, and the email outbox."""
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import Boolean, UTCDateTime, utcnow


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("user_id", "organization_id", "dedupe_key"),
                      Index("ix_notif_user_unread", "user_id", "organization_id", "read_at"))
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(10), default="info")  # info | warning | critical | success
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(200))  # app path, e.g. /monitoring
    # Same key for the same user is stored once: daily digests and repeated events cannot spam.
    dedupe_key: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class NotificationPref(Base):
    """A user's choice for one kind in one business. No row means the kind's defaults."""
    __tablename__ = "notification_prefs"
    __table_args__ = (UniqueConstraint("user_id", "organization_id", "kind"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(30))
    in_app: Mapped[bool] = mapped_column(Boolean, default=True)
    email: Mapped[bool] = mapped_column(Boolean, default=False)


class EmailOutbox(Base):
    """Emails waiting to be sent. Delivered by the background worker with retries; kept for the record."""
    __tablename__ = "email_outbox"
    __table_args__ = (Index("ix_outbox_status", "status", "next_attempt_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    notification_id: Mapped[int | None] = mapped_column(ForeignKey("notifications.id", ondelete="SET NULL"))
    to_address: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | sent | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(300))
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
