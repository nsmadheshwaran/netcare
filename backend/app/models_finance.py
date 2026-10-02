"""Phase 3: money accounts, expenses/other income/transfers, versioned tax rates.

This is operational accounting support, not double-entry bookkeeping.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import MONEY, Boolean, Numeric, TimestampMixin, UTCDateTime, utcnow


class MoneyAccount(TimestampMixin, Base):
    """Where money sits: cash drawer, bank account, UPI wallet."""
    __tablename__ = "money_accounts"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(10))  # cash | bank | other
    opening_balance: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    opening_date: Mapped[date | None] = mapped_column(Date)
    # Payments with no explicit account go to the default account of the matching kind.
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class FinanceCategory(TimestampMixin, Base):
    __tablename__ = "finance_categories"
    __table_args__ = (UniqueConstraint("organization_id", "kind", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # expense | income
    name: Mapped[str] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class FinanceEntry(TimestampMixin, Base):
    """An expense paid, other income received, or a transfer between accounts.
    Never edited after creation: mistakes are voided (kept with a reason) and re-entered."""
    __tablename__ = "finance_entries"
    __table_args__ = (
        UniqueConstraint("organization_id", "number"),
        UniqueConstraint("organization_id", "idempotency_key"),
        Index("ix_fin_org_date", "organization_id", "entry_date"),
        CheckConstraint("amount > 0", name="ck_fin_amount_pos"),
        CheckConstraint("tax_amount >= 0 AND tax_amount <= amount", name="ck_fin_tax"),
        CheckConstraint("(kind = 'transfer') = (to_account_id IS NOT NULL)", name="ck_fin_transfer"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    number: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(10))  # expense | income | transfer
    entry_date: Mapped[date] = mapped_column(Date)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("finance_categories.id"))
    amount: Mapped[Decimal] = mapped_column(MONEY)  # total paid/received, incl. any GST
    tax_amount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))  # GST shown on the bill, if any
    account_id: Mapped[int] = mapped_column(ForeignKey("money_accounts.id"))  # paid from / received into / from
    to_account_id: Mapped[int | None] = mapped_column(ForeignKey("money_accounts.id"))  # transfers only
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    method: Mapped[str] = mapped_column(String(20), default="cash")
    payee: Mapped[str | None] = mapped_column(String(200))  # free text when not a registered supplier
    reference: Mapped[str | None] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    voided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    void_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class TaxRate(Base):
    """Versioned GST rate master. Rows are never edited: a change retires the old row (effective_to)
    and adds a new one, so historic documents can be explained."""
    __tablename__ = "tax_rates"
    __table_args__ = (CheckConstraint("rate >= 0 AND rate <= 100", name="ck_tax_rate_range"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
