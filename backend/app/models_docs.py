"""Phase 5: uploaded documents.

File bytes live on disk under settings.storage_dir; this table holds the metadata, the SHA-256 checksum and
who did what. Rows are never deleted: a deleted document keeps its row (and file, so it can be restored) until
an owner purges it, which removes the file and leaves the row as a tombstone for the audit trail.
"""
from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import Boolean, TimestampMixin, UTCDateTime


class StoredDocument(TimestampMixin, Base):
    __tablename__ = "stored_documents"
    __table_args__ = (
        Index("ix_docs_org_entity", "organization_id", "entity_type", "entity_id"),
        Index("ix_docs_org_sha", "organization_id", "sha256"),
        CheckConstraint("size_bytes > 0", name="ck_docs_size_pos"),
        CheckConstraint("(entity_type = 'general') = (entity_id IS NULL)", name="ck_docs_entity"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    # What the file belongs to: general | customer | supplier | product | sales_invoice | purchase_invoice |
    # purchase_order | expense | service_ticket | asset | employee. Checked against the organization on upload.
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[int | None] = mapped_column()
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(20), default="other")
    tags: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    expires_on: Mapped[date | None] = mapped_column(Date, index=True)  # warranty card, contract, licence
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    original_name: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(100))  # detected from the bytes, not the browser
    extension: Mapped[str] = mapped_column(String(10))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(80), unique=True)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    delete_reason: Mapped[str | None] = mapped_column(Text)
    purged_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
