"""Phase 2: suppliers, purchasing, sales documents, payments, returns, document numbering.

Rules:
- Stock moves only through services.inventory (receipts, invoice issue, credit-note restock, purchase returns).
- Invoices are not cash: balances change only when a Payment is allocated or a credit note is issued.
- Issued documents are never edited; they are cancelled or corrected with credit notes / returns.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .models import MONEY, QTY, Numeric, TimestampMixin, UTCDateTime

RATE = Numeric(5, 2)


class Supplier(TimestampMixin, Base):
    __tablename__ = "suppliers"
    __table_args__ = (Index("ix_suppliers_org_name", "organization_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    contact_person: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(200))
    gstin: Mapped[str | None] = mapped_column(String(15))
    state_code: Mapped[str | None] = mapped_column(String(2))
    address: Mapped[str | None] = mapped_column(Text)
    payment_terms_days: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class DocumentSequence(Base):
    """One row per (org, doc type, financial year); locked FOR UPDATE when a number is taken."""
    __tablename__ = "document_sequences"
    __table_args__ = (UniqueConstraint("organization_id", "doc_type", "fiscal_year"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    doc_type: Mapped[str] = mapped_column(String(20))
    fiscal_year: Mapped[str] = mapped_column(String(7))  # e.g. 2026-27
    prefix: Mapped[str] = mapped_column(String(20))
    next_number: Mapped[int] = mapped_column(Integer, default=1)


class _LineMixin:
    """Monetary breakdown shared by every priced line. All amounts are computed server-side."""
    description: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[Decimal] = mapped_column(QTY)
    unit_price: Mapped[Decimal] = mapped_column(MONEY)
    discount_amount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))  # line + share of doc discount
    taxable_value: Mapped[Decimal] = mapped_column(MONEY)
    tax_rate: Mapped[Decimal] = mapped_column(RATE, default=Decimal("0"))
    cgst: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    sgst: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    igst: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    line_total: Mapped[Decimal] = mapped_column(MONEY)
    hsn_sac: Mapped[str | None] = mapped_column(String(10))


class _TotalsMixin:
    subtotal: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))       # sum qty*price
    discount_total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    taxable_total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    cgst_total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    sgst_total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    igst_total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    round_off: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    is_interstate: Mapped[bool] = mapped_column(Boolean, default=False)
    place_of_supply: Mapped[str | None] = mapped_column(String(2))


# ---------------- purchasing ----------------
class PurchaseOrder(TimestampMixin, _TotalsMixin, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("organization_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    number: Mapped[str] = mapped_column(String(40))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    # draft | approved | partially_received | received | cancelled | closed
    order_date: Mapped[date] = mapped_column(Date)
    expected_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    supplier: Mapped[Supplier] = relationship()
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(cascade="all, delete-orphan",
                                                            order_by="PurchaseOrderLine.id")


class PurchaseOrderLine(_LineMixin, Base):
    __tablename__ = "purchase_order_lines"
    __table_args__ = (CheckConstraint("quantity > 0 AND received_quantity >= 0", name="ck_pol_qty"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    received_quantity: Mapped[Decimal] = mapped_column(QTY, default=Decimal("0"))


class GoodsReceipt(Base):
    __tablename__ = "goods_receipts"
    __table_args__ = (UniqueConstraint("organization_id", "number"),
                      UniqueConstraint("organization_id", "idempotency_key"))
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    number: Mapped[str] = mapped_column(String(40))
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    received_date: Mapped[date] = mapped_column(Date)
    supplier_reference: Mapped[str | None] = mapped_column(String(80))  # delivery challan no.
    notes: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=lambda: _now())

    lines: Mapped[list["GoodsReceiptLine"]] = relationship(cascade="all, delete-orphan")


class GoodsReceiptLine(Base):
    __tablename__ = "goods_receipt_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    goods_receipt_id: Mapped[int] = mapped_column(ForeignKey("goods_receipts.id", ondelete="CASCADE"), index=True)
    purchase_order_line_id: Mapped[int] = mapped_column(ForeignKey("purchase_order_lines.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[Decimal] = mapped_column(QTY)
    stock_movement_id: Mapped[int | None] = mapped_column(ForeignKey("stock_movements.id"))


class PurchaseInvoice(TimestampMixin, _TotalsMixin, Base):
    """Supplier bill. Creates a payable; stock comes from goods receipts, not from the bill."""
    __tablename__ = "purchase_invoices"
    __table_args__ = (UniqueConstraint("organization_id", "number"),
                      UniqueConstraint("organization_id", "supplier_id", "supplier_invoice_number"))
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    number: Mapped[str] = mapped_column(String(40))
    supplier_invoice_number: Mapped[str] = mapped_column(String(60))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    purchase_order_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"))
    invoice_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | partially_paid | paid | cancelled
    amount_paid: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    credited_amount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    supplier: Mapped[Supplier] = relationship()
    lines: Mapped[list["PurchaseInvoiceLine"]] = relationship(cascade="all, delete-orphan",
                                                              order_by="PurchaseInvoiceLine.id")


class PurchaseInvoiceLine(_LineMixin, Base):
    __tablename__ = "purchase_invoice_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_invoice_id: Mapped[int] = mapped_column(ForeignKey("purchase_invoices.id", ondelete="CASCADE"),
                                                     index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))


class PurchaseReturn(Base):
    __tablename__ = "purchase_returns"
    __table_args__ = (UniqueConstraint("organization_id", "number"),
                      UniqueConstraint("organization_id", "idempotency_key"))
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    number: Mapped[str] = mapped_column(String(40))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    purchase_invoice_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_invoices.id"))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    return_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(Text)
    total: Mapped[Decimal] = mapped_column(MONEY)
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=lambda: _now())

    lines: Mapped[list["PurchaseReturnLine"]] = relationship(cascade="all, delete-orphan")


class PurchaseReturnLine(Base):
    __tablename__ = "purchase_return_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_return_id: Mapped[int] = mapped_column(ForeignKey("purchase_returns.id", ondelete="CASCADE"),
                                                    index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[Decimal] = mapped_column(QTY)
    unit_cost: Mapped[Decimal] = mapped_column(MONEY)
    amount: Mapped[Decimal] = mapped_column(MONEY)  # incl. tax at the bill's rate, as entered
    stock_movement_id: Mapped[int | None] = mapped_column(ForeignKey("stock_movements.id"))


# ---------------- sales ----------------
class Quotation(TimestampMixin, _TotalsMixin, Base):
    __tablename__ = "quotations"
    __table_args__ = (UniqueConstraint("organization_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    number: Mapped[str] = mapped_column(String(40))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    quote_date: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    # draft | sent | accepted | rejected | converted | expired
    document_discount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    prices_include_tax: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    terms: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    lines: Mapped[list["QuotationLine"]] = relationship(cascade="all, delete-orphan", order_by="QuotationLine.id")


class QuotationLine(_LineMixin, Base):
    __tablename__ = "quotation_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_id: Mapped[int] = mapped_column(ForeignKey("quotations.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    line_discount_pct: Mapped[Decimal] = mapped_column(RATE, default=Decimal("0"))


class SalesInvoice(TimestampMixin, _TotalsMixin, Base):
    __tablename__ = "sales_invoices"
    __table_args__ = (UniqueConstraint("organization_id", "number"),
                      UniqueConstraint("organization_id", "idempotency_key"),
                      Index("ix_sales_inv_org_date", "organization_id", "invoice_date"))
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    number: Mapped[str | None] = mapped_column(String(40))  # assigned when issued; drafts have none
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    quotation_id: Mapped[int | None] = mapped_column(ForeignKey("quotations.id"))
    invoice_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    # draft | issued | partially_paid | paid | cancelled   ("overdue" is derived from due_date)
    document_discount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    prices_include_tax: Mapped[bool] = mapped_column(Boolean, default=False)
    amount_paid: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    credited_amount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    notes: Mapped[str | None] = mapped_column(Text)
    terms: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    issued_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    lines: Mapped[list["SalesInvoiceLine"]] = relationship(cascade="all, delete-orphan",
                                                           order_by="SalesInvoiceLine.id")


class SalesInvoiceLine(_LineMixin, Base):
    __tablename__ = "sales_invoice_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    sales_invoice_id: Mapped[int] = mapped_column(ForeignKey("sales_invoices.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    line_discount_pct: Mapped[Decimal] = mapped_column(RATE, default=Decimal("0"))
    returned_quantity: Mapped[Decimal] = mapped_column(QTY, default=Decimal("0"))
    # Moving-average unit cost captured when the invoice was issued (None for services / free text).
    unit_cost: Mapped[Decimal | None] = mapped_column(MONEY)


class CreditNote(Base):
    __tablename__ = "credit_notes"
    __table_args__ = (UniqueConstraint("organization_id", "number"),
                      UniqueConstraint("organization_id", "idempotency_key"))
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    number: Mapped[str] = mapped_column(String(40))
    sales_invoice_id: Mapped[int] = mapped_column(ForeignKey("sales_invoices.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    note_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text)
    restock: Mapped[bool] = mapped_column(Boolean, default=True)
    taxable_total: Mapped[Decimal] = mapped_column(MONEY)
    tax_total: Mapped[Decimal] = mapped_column(MONEY)
    total: Mapped[Decimal] = mapped_column(MONEY)
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=lambda: _now())

    lines: Mapped[list["CreditNoteLine"]] = relationship(cascade="all, delete-orphan")


class CreditNoteLine(Base):
    __tablename__ = "credit_note_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    credit_note_id: Mapped[int] = mapped_column(ForeignKey("credit_notes.id", ondelete="CASCADE"), index=True)
    sales_invoice_line_id: Mapped[int] = mapped_column(ForeignKey("sales_invoice_lines.id"))
    quantity: Mapped[Decimal] = mapped_column(QTY)
    taxable_value: Mapped[Decimal] = mapped_column(MONEY)
    tax_amount: Mapped[Decimal] = mapped_column(MONEY)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    stock_movement_id: Mapped[int | None] = mapped_column(ForeignKey("stock_movements.id"))


# ---------------- payments ----------------
class Payment(TimestampMixin, Base):
    """Money actually received from a customer (direction=in) or paid to a supplier (direction=out)."""
    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("organization_id", "number"),
                      UniqueConstraint("organization_id", "idempotency_key"),
                      CheckConstraint("amount > 0", name="ck_payments_amount_pos"),
                      CheckConstraint("(customer_id IS NULL) <> (supplier_id IS NULL)", name="ck_payments_party"))
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    number: Mapped[str] = mapped_column(String(40))
    direction: Mapped[str] = mapped_column(String(3))  # in | out
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), index=True)
    payment_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    method: Mapped[str] = mapped_column(String(20))  # cash | upi | bank_transfer | card | cheque | other
    account_id: Mapped[int | None] = mapped_column(ForeignKey("money_accounts.id"))
    reference: Mapped[str | None] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    voided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    void_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    allocations: Mapped[list["PaymentAllocation"]] = relationship(cascade="all, delete-orphan")


class PaymentAllocation(Base):
    __tablename__ = "payment_allocations"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_alloc_amount_pos"),
                      CheckConstraint("(sales_invoice_id IS NULL) <> (purchase_invoice_id IS NULL)",
                                      name="ck_alloc_target"))
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id", ondelete="CASCADE"), index=True)
    sales_invoice_id: Mapped[int | None] = mapped_column(ForeignKey("sales_invoices.id"), index=True)
    purchase_invoice_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_invoices.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)


def _now():
    from .models import utcnow
    return utcnow()
