import re
from datetime import datetime
from decimal import Decimal
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

T = TypeVar("T")
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def _gstin(v: str | None) -> str | None:
    if v is None or v == "":
        return None
    v = v.strip().upper()
    if not GSTIN_RE.match(v):
        raise ValueError("Invalid GSTIN format")
    return v


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int


# --- auth ---
class RegisterIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=10, max_length=128)
    organization_name: str = Field(min_length=1, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)


class UserOut(ORM):
    id: int
    email: str
    full_name: str
    is_active: bool


class MembershipOut(ORM):
    organization_id: int
    organization_name: str
    role: str
    permissions: list[str]


class MeOut(BaseModel):
    user: UserOut
    memberships: list[MembershipOut]


# --- organizations ---
class OrgIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    legal_name: str | None = None
    gstin: str | None = None
    state_code: str | None = Field(default=None, pattern=r"^\d{2}$")
    phone: str | None = None
    email: EmailStr | None = None
    address: str | None = None
    enabled_modules: list[str] | None = None
    invoice_terms: str | None = None
    payment_instructions: str | None = None
    round_invoices_to_rupee: bool = False
    prices_include_tax_default: bool = False
    # Applies to sequences started after the change (i.e. doc types not yet used this financial year).
    numbering_prefixes: dict[str, str] | None = None
    _g = field_validator("gstin")(classmethod(lambda cls, v: _gstin(v)))

    @field_validator("numbering_prefixes")
    @classmethod
    def _prefixes(cls, v):
        from .services.billing import DEFAULT_PREFIX
        if v is None:
            return v
        for k, val in v.items():
            if k not in DEFAULT_PREFIX:
                raise ValueError(f"Unknown document type {k}")
            if not re.match(r"^[A-Za-z0-9-]{1,12}$", val):
                raise ValueError(f"Prefix for {k} must be 1-12 letters, digits or dashes")
        return v


class OrgOut(ORM):
    id: int
    name: str
    legal_name: str | None
    gstin: str | None
    state_code: str | None
    phone: str | None
    email: str | None
    address: str | None
    currency: str
    enabled_modules: list[str] | None
    invoice_terms: str | None
    payment_instructions: str | None
    round_invoices_to_rupee: bool
    prices_include_tax_default: bool
    has_logo: bool = False
    numbering_prefixes: dict[str, str] | None


class MemberIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    role: str
    # Initial password set by the owner; the invitee should change it on first login.
    # Replace with an emailed invite token once email delivery exists.
    temporary_password: str = Field(min_length=10, max_length=128)


class MemberUpdate(BaseModel):
    role: str | None = None
    is_active: bool | None = None


class MemberOut(BaseModel):
    id: int
    user_id: int
    email: str
    full_name: str
    role: str
    is_active: bool


class LocationIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    address: str | None = None


class LocationOut(ORM):
    id: int
    name: str
    address: str | None
    is_active: bool


# --- customers ---
class CustomerBase(BaseModel):
    customer_type: Literal["individual", "business"] = "individual"
    name: str = Field(min_length=1, max_length=200)
    business_name: str | None = None
    contact_person: str | None = None
    phone: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = None
    gstin: str | None = None
    billing_address: str | None = None
    shipping_address: str | None = None
    city: str | None = None
    state: str | None = None
    state_code: str | None = Field(default=None, pattern=r"^\d{2}$")
    pincode: str | None = Field(default=None, pattern=r"^\d{6}$")
    category: str | None = None
    notes: str | None = None
    status: Literal["active", "inactive"] = "active"
    _g = field_validator("gstin")(classmethod(lambda cls, v: _gstin(v)))

    @field_validator("email", "pincode", "phone", "state_code", mode="before")
    @classmethod
    def _blank_none(cls, v):
        return None if v == "" else v


class CustomerIn(CustomerBase):
    pass


class CustomerOut(CustomerBase, ORM):
    id: int
    email: str | None = None
    created_at: datetime
    archived_at: datetime | None


# --- products ---
class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class CategoryOut(ORM):
    id: int
    name: str


class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sku: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._\-/]+$")
    category_id: int | None = None
    barcode: str | None = None
    brand: str | None = None
    model: str | None = None
    hsn_sac: str | None = Field(default=None, pattern=r"^\d{4,8}$")
    unit: str = "pcs"
    purchase_price: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    selling_price: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    gst_rate: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    min_stock: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=3)
    track_serial: bool = False
    warranty_months: int | None = Field(default=None, ge=0, le=240)
    is_service: bool = False
    description: str | None = None
    status: Literal["active", "inactive"] = "active"

    @field_validator("hsn_sac", "barcode", mode="before")
    @classmethod
    def _blank_none(cls, v):
        return None if v == "" else v


class ProductOut(ProductIn, ORM):
    id: int
    category_name: str | None = None
    stock_on_hand: Decimal = Decimal("0")
    created_at: datetime
    archived_at: datetime | None


# --- inventory ---
MovementType = Literal["stock_in", "stock_out", "adjustment", "damaged", "customer_return", "supplier_return"]


class MovementIn(BaseModel):
    product_id: int
    location_id: int
    movement_type: MovementType
    # For stock_in/out/damaged/returns: positive quantity; sign is derived from type.
    # For adjustment: signed delta.
    quantity: Decimal = Field(max_digits=14, decimal_places=3)
    unit_cost: Decimal | None = Field(default=None, ge=0)
    reference: str | None = Field(default=None, max_length=120)
    note: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=80)


class TransferIn(BaseModel):
    product_id: int
    from_location_id: int
    to_location_id: int
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    note: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=80)


class MovementOut(ORM):
    id: int
    product_id: int
    location_id: int
    movement_type: str
    quantity_change: Decimal
    balance_after: Decimal
    unit_cost: Decimal | None
    reference: str | None
    note: str | None
    created_at: datetime
    product_name: str | None = None
    location_name: str | None = None


class StockLevelOut(BaseModel):
    product_id: int
    product_name: str
    sku: str
    location_id: int
    location_name: str
    quantity: Decimal
    min_stock: Decimal


class AuditOut(ORM):
    id: int
    user_id: int | None
    action: str
    entity_type: str
    entity_id: str | None
    details: dict | None
    created_at: datetime
