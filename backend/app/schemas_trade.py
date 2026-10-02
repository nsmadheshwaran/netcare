from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from .schemas import _gstin

Money = Decimal
PaymentMethod = Literal["cash", "upi", "bank_transfer", "card", "cheque", "other"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _blank(v):
    return None if v == "" else v


# ---------- suppliers ----------
class SupplierIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    contact_person: str | None = None
    phone: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = None
    gstin: str | None = None
    state_code: str | None = Field(default=None, pattern=r"^\d{2}$")
    address: str | None = None
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    notes: str | None = None
    _g = field_validator("gstin")(classmethod(lambda cls, v: _gstin(v)))
    _b = field_validator("email", "phone", "state_code", mode="before")(classmethod(lambda cls, v: _blank(v)))


class SupplierOut(SupplierIn, ORM):
    id: int
    email: str | None = None
    created_at: datetime
    archived_at: datetime | None
    balance_due: Decimal = Decimal("0")


# ---------- lines ----------
class LineIn(BaseModel):
    product_id: int | None = None
    description: str | None = Field(default=None, max_length=300)
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    tax_rate: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    line_discount_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100, decimal_places=2)

    @model_validator(mode="after")
    def _need_desc(self):
        if self.product_id is None and not self.description:
            raise ValueError("Free-text lines need a description")
        if self.product_id is None and self.unit_price is None:
            raise ValueError("Free-text lines need a unit price")
        return self


class LineOut(ORM):
    id: int
    product_id: int | None
    description: str
    hsn_sac: str | None
    quantity: Decimal
    unit_price: Decimal
    line_discount_pct: Decimal = Decimal("0")
    discount_amount: Decimal
    taxable_value: Decimal
    tax_rate: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    line_total: Decimal
    received_quantity: Decimal | None = None
    returned_quantity: Decimal | None = None


class TotalsOut(ORM):
    subtotal: Decimal
    discount_total: Decimal
    taxable_total: Decimal
    cgst_total: Decimal
    sgst_total: Decimal
    igst_total: Decimal
    round_off: Decimal
    total: Decimal
    is_interstate: bool
    place_of_supply: str | None


# ---------- purchasing ----------
class PurchaseOrderIn(BaseModel):
    supplier_id: int
    location_id: int
    order_date: date
    expected_date: date | None = None
    notes: str | None = None
    lines: list[LineIn] = Field(min_length=1)

    @model_validator(mode="after")
    def _products_only(self):
        if any(li.product_id is None for li in self.lines):
            raise ValueError("Purchase order lines must reference products")
        return self


class PurchaseOrderOut(TotalsOut):
    id: int
    number: str
    supplier_id: int
    supplier_name: str | None = None
    location_id: int
    status: str
    order_date: date
    expected_date: date | None
    notes: str | None
    lines: list[LineOut] = []
    created_at: datetime


class ReceiptLineIn(BaseModel):
    purchase_order_line_id: int
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)


class ReceiptIn(BaseModel):
    received_date: date
    supplier_reference: str | None = Field(default=None, max_length=80)
    notes: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=80)
    lines: list[ReceiptLineIn] = Field(min_length=1)


class ReceiptOut(ORM):
    id: int
    number: str
    purchase_order_id: int
    location_id: int
    received_date: date
    supplier_reference: str | None
    created_at: datetime


class PurchaseInvoiceIn(BaseModel):
    supplier_id: int
    supplier_invoice_number: str = Field(min_length=1, max_length=60)
    purchase_order_id: int | None = None
    invoice_date: date
    due_date: date | None = None
    place_of_supply: str | None = Field(default=None, pattern=r"^\d{2}$")
    notes: str | None = None
    lines: list[LineIn] = Field(min_length=1)


class PurchaseInvoiceOut(TotalsOut):
    id: int
    number: str
    supplier_invoice_number: str
    supplier_id: int
    supplier_name: str | None = None
    purchase_order_id: int | None
    invoice_date: date
    due_date: date | None
    status: str
    display_status: str = ""
    amount_paid: Decimal
    credited_amount: Decimal
    balance_due: Decimal = Decimal("0")
    notes: str | None
    lines: list[LineOut] = []


class PurchaseReturnLineIn(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    unit_cost: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100)


class PurchaseReturnIn(BaseModel):
    supplier_id: int
    purchase_invoice_id: int | None = None
    location_id: int
    return_date: date
    reason: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=80)
    lines: list[PurchaseReturnLineIn] = Field(min_length=1)


class PurchaseReturnOut(ORM):
    id: int
    number: str
    supplier_id: int
    purchase_invoice_id: int | None
    location_id: int
    return_date: date
    reason: str | None
    total: Decimal
    created_at: datetime


# ---------- sales ----------
class QuotationIn(BaseModel):
    customer_id: int
    quote_date: date
    valid_until: date | None = None
    place_of_supply: str | None = Field(default=None, pattern=r"^\d{2}$")
    document_discount: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    notes: str | None = None
    terms: str | None = None
    lines: list[LineIn] = Field(min_length=1)


class QuotationOut(TotalsOut):
    id: int
    number: str
    customer_id: int
    customer_name: str | None = None
    quote_date: date
    valid_until: date | None
    status: str
    document_discount: Decimal
    notes: str | None
    terms: str | None
    converted_invoice_id: int | None = None
    lines: list[LineOut] = []


class QuotationStatusIn(BaseModel):
    status: Literal["sent", "accepted", "rejected"]


class InvoiceIn(BaseModel):
    customer_id: int
    location_id: int
    invoice_date: date
    due_date: date | None = None
    place_of_supply: str | None = Field(default=None, pattern=r"^\d{2}$")
    document_discount: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    notes: str | None = None
    terms: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=80)
    lines: list[LineIn] = Field(min_length=1)

    @model_validator(mode="after")
    def _dates(self):
        if self.due_date and self.due_date < self.invoice_date:
            raise ValueError("Due date cannot be before invoice date")
        return self


class InvoiceOut(TotalsOut):
    id: int
    number: str | None
    customer_id: int
    customer_name: str | None = None
    location_id: int
    quotation_id: int | None
    invoice_date: date
    due_date: date | None
    status: str
    display_status: str = ""
    document_discount: Decimal
    amount_paid: Decimal
    credited_amount: Decimal
    balance_due: Decimal = Decimal("0")
    notes: str | None
    terms: str | None
    issued_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    lines: list[LineOut] = []


class CancelIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class CreditNoteLineIn(BaseModel):
    sales_invoice_line_id: int
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)


class CreditNoteIn(BaseModel):
    note_date: date
    reason: str = Field(min_length=3, max_length=500)
    restock: bool = True
    idempotency_key: str | None = Field(default=None, max_length=80)
    lines: list[CreditNoteLineIn] = Field(min_length=1)


class CreditNoteOut(ORM):
    id: int
    number: str
    sales_invoice_id: int
    customer_id: int
    note_date: date
    reason: str
    restock: bool
    taxable_total: Decimal
    tax_total: Decimal
    total: Decimal
    created_at: datetime


# ---------- payments ----------
class AllocationIn(BaseModel):
    invoice_id: int
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)


class PaymentIn(BaseModel):
    customer_id: int | None = None
    supplier_id: int | None = None
    payment_date: date
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    method: PaymentMethod
    reference: str | None = Field(default=None, max_length=80)
    notes: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=80)
    allocations: list[AllocationIn] = []

    @model_validator(mode="after")
    def _party(self):
        if (self.customer_id is None) == (self.supplier_id is None):
            raise ValueError("Provide exactly one of customer_id or supplier_id")
        if sum((a.amount for a in self.allocations), Decimal("0")) > self.amount:
            raise ValueError("Allocations exceed payment amount")
        if len({a.invoice_id for a in self.allocations}) != len(self.allocations):
            raise ValueError("Each invoice may appear once per payment")
        return self


class AllocationOut(ORM):
    id: int
    sales_invoice_id: int | None
    purchase_invoice_id: int | None
    amount: Decimal
    invoice_number: str | None = None


class PaymentOut(ORM):
    id: int
    number: str
    direction: str
    customer_id: int | None
    supplier_id: int | None
    party_name: str | None = None
    payment_date: date
    amount: Decimal
    unallocated: Decimal = Decimal("0")
    method: str
    reference: str | None
    notes: str | None
    voided_at: datetime | None
    void_reason: str | None
    allocations: list[AllocationOut] = []
    created_at: datetime
