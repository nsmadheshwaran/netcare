"""Database models for the foundation milestone.

Every business table carries organization_id; all queries must filter on it
(see deps.OrgContext). Money and quantities use Numeric, never float.
"""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, LargeBinary, Numeric, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from .db import Base

MONEY = Numeric(14, 2)
QTY = Numeric(14, 3)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend (SQLite drops tzinfo on read)."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc) if value is not None else None

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )


class Organization(TimestampMixin, Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    legal_name: Mapped[str | None] = mapped_column(String(200))
    gstin: Mapped[str | None] = mapped_column(String(15))
    state_code: Mapped[str | None] = mapped_column(String(2))
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    # Which sidebar modules the owner has enabled; None means defaults.
    enabled_modules: Mapped[list | None] = mapped_column(JSON)
    numbering_prefixes: Mapped[dict | None] = mapped_column(JSON)  # {"sales_invoice": "INV", ...}
    invoice_terms: Mapped[str | None] = mapped_column(Text)
    payment_instructions: Mapped[str | None] = mapped_column(Text)
    round_invoices_to_rupee: Mapped[bool] = mapped_column(Boolean, default=False)
    prices_include_tax_default: Mapped[bool] = mapped_column(Boolean, default=False)
    logo: Mapped[bytes | None] = mapped_column(LargeBinary)
    logo_mime: Mapped[str | None] = mapped_column(String(20))

    @property
    def has_logo(self) -> bool:
        return self.logo is not None
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False)
    phone: Mapped[str | None] = mapped_column(String(20))  # E.164, for text-message alerts the user opted into
    # Bumped on password change / logout-all to invalidate issued tokens.
    token_version: Mapped[int] = mapped_column(Integer, default=0)


class Membership(TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(30))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    organization: Mapped[Organization] = relationship()
    user: Mapped[User] = relationship()


class Location(TimestampMixin, Base):
    __tablename__ = "locations"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (Index("ix_customers_org_name", "organization_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    customer_type: Mapped[str] = mapped_column(String(20), default="individual")  # individual | business
    name: Mapped[str] = mapped_column(String(200))
    business_name: Mapped[str | None] = mapped_column(String(200))
    contact_person: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(30), index=True)
    email: Mapped[str | None] = mapped_column(String(200))
    gstin: Mapped[str | None] = mapped_column(String(15))
    billing_address: Mapped[str | None] = mapped_column(Text)
    shipping_address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    state_code: Mapped[str | None] = mapped_column(String(2))  # GST state code; drives place of supply
    pincode: Mapped[str | None] = mapped_column(String(10))
    category: Mapped[str | None] = mapped_column(String(60))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | inactive
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ProductCategory(TimestampMixin, Base):
    __tablename__ = "product_categories"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("organization_id", "sku"),
        CheckConstraint("purchase_price >= 0 AND selling_price >= 0", name="ck_products_prices_nonneg"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("product_categories.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200))
    sku: Mapped[str] = mapped_column(String(64))
    barcode: Mapped[str | None] = mapped_column(String(64), index=True)
    brand: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    hsn_sac: Mapped[str | None] = mapped_column(String(10))
    unit: Mapped[str] = mapped_column(String(20), default="pcs")
    purchase_price: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    selling_price: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    gst_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    min_stock: Mapped[Decimal] = mapped_column(QTY, default=Decimal("0"))
    # Moving-average cost across all locations, updated on purchase receipts. Used for COGS.
    avg_cost: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    track_serial: Mapped[bool] = mapped_column(Boolean, default=False)
    warranty_months: Mapped[int | None] = mapped_column(Integer)
    is_service: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    category: Mapped[ProductCategory | None] = relationship()


class StockLevel(Base):
    """Current on-hand quantity per product per location. Only changed via inventory service."""
    __tablename__ = "stock_levels"
    __table_args__ = (UniqueConstraint("product_id", "location_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"))
    quantity: Mapped[Decimal] = mapped_column(QTY, default=Decimal("0"))


class StockMovement(Base):
    """Append-only ledger. Corrections are new movements, never edits."""
    __tablename__ = "stock_movements"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key"),
        Index("ix_stock_mov_org_product", "organization_id", "product_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    movement_type: Mapped[str] = mapped_column(String(30))
    quantity_change: Mapped[Decimal] = mapped_column(QTY)
    balance_after: Mapped[Decimal] = mapped_column(QTY)
    unit_cost: Mapped[Decimal | None] = mapped_column(MONEY)
    reference: Mapped[str | None] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(60))
    details: Mapped[dict | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
