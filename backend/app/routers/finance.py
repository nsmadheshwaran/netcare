from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, or_, select

from ..deps import OrgContext, require
from ..models import Location, utcnow
from ..models_finance import FinanceCategory, FinanceEntry, MoneyAccount, TaxRate
from ..models_trade import Supplier
from ..schemas import Page
from ..schemas_trade import CancelIn, PaymentMethod
from ..services import billing
from ..services.finance import resolve_account
from ..services.timeutil import today as local_today
from ..services.trade import get_owned

router = APIRouter(tags=["finance"])


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------- accounts ----------------
class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["cash", "bank", "other"]
    opening_balance: Decimal = Field(default=Decimal("0"), max_digits=14, decimal_places=2)
    opening_date: date | None = None
    is_default: bool = False


class AccountOut(ORM):
    id: int
    name: str
    kind: str
    opening_balance: Decimal
    opening_date: date | None
    is_default: bool
    is_active: bool


def _set_default(ctx: OrgContext, acc: MoneyAccount):
    if acc.is_default:
        for other in ctx.db.scalars(select(MoneyAccount).where(MoneyAccount.organization_id == ctx.org_id,
                                                               MoneyAccount.kind == acc.kind,
                                                               MoneyAccount.id != acc.id)):
            other.is_default = False


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(ctx: OrgContext = Depends(require("finance.view"))):
    return ctx.db.scalars(select(MoneyAccount).where(MoneyAccount.organization_id == ctx.org_id)
                          .order_by(MoneyAccount.kind, MoneyAccount.name)).all()


@router.post("/accounts", response_model=AccountOut, status_code=201)
def create_account(body: AccountIn, ctx: OrgContext = Depends(require("finance.manage"))):
    if ctx.db.scalar(select(MoneyAccount.id).where(MoneyAccount.organization_id == ctx.org_id,
                                                   MoneyAccount.name == body.name)):
        raise HTTPException(409, "An account with this name exists")
    acc = MoneyAccount(organization_id=ctx.org_id, **body.model_dump())
    ctx.db.add(acc)
    ctx.db.flush()
    _set_default(ctx, acc)
    ctx.audit("create", "money_account", acc.id, {"name": acc.name, "opening": str(acc.opening_balance)})
    ctx.db.commit()
    return acc


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    is_default: bool | None = None
    is_active: bool | None = None


@router.patch("/accounts/{acc_id}", response_model=AccountOut)
def update_account(acc_id: int, body: AccountUpdate, ctx: OrgContext = Depends(require("finance.manage"))):
    """Opening balances are fixed after creation; correct them with an income/expense entry instead."""
    acc = get_owned(ctx, MoneyAccount, acc_id, "Account")
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(acc, k, v)
    _set_default(ctx, acc)
    ctx.audit("update", "money_account", acc.id, changes)
    ctx.db.commit()
    return acc


# ---------------- categories ----------------
DEFAULT_CATEGORIES = {
    "expense": ["Rent", "Electricity", "Internet", "Salaries", "Transport", "Repairs", "Software subscriptions",
                "Office supplies", "Other"],
    "income": ["Interest", "Commission", "Scrap sales", "Other"],
}


class CategoryIn(BaseModel):
    kind: Literal["expense", "income"]
    name: str = Field(min_length=1, max_length=80)


class CategoryOut(ORM):
    id: int
    kind: str
    name: str
    is_active: bool


@router.get("/finance-categories", response_model=list[CategoryOut])
def list_categories(ctx: OrgContext = Depends(require("finance.view")), kind: str | None = None):
    q = select(FinanceCategory).where(FinanceCategory.organization_id == ctx.org_id)
    if not ctx.db.scalar(q.limit(1)):
        # First use: offer common categories. Editable names, nothing tax-related is assumed.
        for k, names in DEFAULT_CATEGORIES.items():
            for n in names:
                ctx.db.add(FinanceCategory(organization_id=ctx.org_id, kind=k, name=n))
        ctx.db.commit()
    if kind:
        q = q.where(FinanceCategory.kind == kind)
    return ctx.db.scalars(q.order_by(FinanceCategory.kind, FinanceCategory.name)).all()


@router.post("/finance-categories", response_model=CategoryOut, status_code=201)
def create_category(body: CategoryIn, ctx: OrgContext = Depends(require("finance.manage"))):
    if ctx.db.scalar(select(FinanceCategory.id).where(FinanceCategory.organization_id == ctx.org_id,
                                                      FinanceCategory.kind == body.kind,
                                                      func.lower(FinanceCategory.name) == body.name.lower())):
        raise HTTPException(409, "Category exists")
    c = FinanceCategory(organization_id=ctx.org_id, **body.model_dump())
    ctx.db.add(c)
    ctx.db.flush()
    ctx.audit("create", "finance_category", c.id, body.model_dump())
    ctx.db.commit()
    return c


# ---------------- entries ----------------
class EntryIn(BaseModel):
    kind: Literal["expense", "income", "transfer"]
    entry_date: date
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    tax_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    category_id: int | None = None
    account_id: int | None = None
    to_account_id: int | None = None
    supplier_id: int | None = None
    location_id: int | None = None
    method: PaymentMethod = "cash"
    payee: str | None = Field(default=None, max_length=200)
    reference: str | None = Field(default=None, max_length=80)
    notes: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def _shape(self):
        if self.tax_amount > self.amount:
            raise ValueError("Tax amount cannot exceed the total amount")
        if self.kind == "transfer":
            if self.to_account_id is None or self.account_id is None:
                raise ValueError("Transfers need both a from and a to account")
            if self.to_account_id == self.account_id:
                raise ValueError("Cannot transfer to the same account")
            if self.category_id or self.tax_amount:
                raise ValueError("Transfers have no category or tax")
        else:
            if self.to_account_id is not None:
                raise ValueError("Only transfers have a destination account")
            if self.category_id is None:
                raise ValueError("Category is required")
        return self


class EntryOut(ORM):
    id: int
    number: str
    kind: str
    entry_date: date
    amount: Decimal
    tax_amount: Decimal
    category_id: int | None
    category_name: str | None = None
    account_id: int
    account_name: str | None = None
    to_account_id: int | None
    to_account_name: str | None = None
    supplier_id: int | None
    location_id: int | None
    method: str
    payee: str | None
    reference: str | None
    notes: str | None
    voided_at: datetime | None
    void_reason: str | None


def _entry_out(ctx: OrgContext, e: FinanceEntry) -> EntryOut:
    o = EntryOut.model_validate(e)
    o.category_name = ctx.db.get(FinanceCategory, e.category_id).name if e.category_id else None
    o.account_name = ctx.db.get(MoneyAccount, e.account_id).name
    o.to_account_name = ctx.db.get(MoneyAccount, e.to_account_id).name if e.to_account_id else None
    return o


PERM_FOR = {"expense": "expenses.edit", "income": "finance.manage", "transfer": "finance.manage"}


@router.get("/finance-entries", response_model=Page[EntryOut])
def list_entries(ctx: OrgContext = Depends(require("expenses.view")), kind: str | None = None,
                 category_id: int | None = None, account_id: int | None = None,
                 date_from: date | None = None, date_to: date | None = None, q: str | None = None,
                 include_voided: bool = True, page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=200)):
    base = select(FinanceEntry).where(FinanceEntry.organization_id == ctx.org_id)
    if kind:
        base = base.where(FinanceEntry.kind == kind)
    if category_id:
        base = base.where(FinanceEntry.category_id == category_id)
    if account_id:
        base = base.where(or_(FinanceEntry.account_id == account_id, FinanceEntry.to_account_id == account_id))
    if date_from:
        base = base.where(FinanceEntry.entry_date >= date_from)
    if date_to:
        base = base.where(FinanceEntry.entry_date <= date_to)
    if q:
        base = base.where(or_(FinanceEntry.number.ilike(f"%{q}%"), FinanceEntry.payee.ilike(f"%{q}%"),
                              FinanceEntry.reference.ilike(f"%{q}%"), FinanceEntry.notes.ilike(f"%{q}%")))
    if not include_voided:
        base = base.where(FinanceEntry.voided_at.is_(None))
    total = ctx.db.scalar(select(func.count()).select_from(base.subquery()))
    rows = ctx.db.scalars(base.order_by(FinanceEntry.entry_date.desc(), FinanceEntry.id.desc())
                          .offset((page - 1) * size).limit(size)).all()
    return Page(items=[_entry_out(ctx, e) for e in rows], total=total, page=page, size=size)


@router.post("/finance-entries", response_model=EntryOut, status_code=201)
def create_entry(body: EntryIn, ctx: OrgContext = Depends(require("expenses.view"))):
    from ..permissions import has_permission
    if not has_permission(ctx.membership.role, PERM_FOR[body.kind]):
        raise HTTPException(403, f"Missing permission: {PERM_FOR[body.kind]}")
    if body.idempotency_key:
        prior = ctx.db.scalar(select(FinanceEntry).where(FinanceEntry.organization_id == ctx.org_id,
                                                         FinanceEntry.idempotency_key == body.idempotency_key))
        if prior:
            return _entry_out(ctx, prior)
    if body.category_id is not None:
        cat = get_owned(ctx, FinanceCategory, body.category_id, "Category", status_code=422)
        if cat.kind != body.kind:
            raise HTTPException(422, f"{cat.name} is an {cat.kind} category")
    if body.supplier_id is not None:
        get_owned(ctx, Supplier, body.supplier_id, "Supplier", status_code=422)
    if body.location_id is not None:
        get_owned(ctx, Location, body.location_id, "Location", status_code=422)
    acc = resolve_account(ctx, body.account_id, body.method)
    to_acc = resolve_account(ctx, body.to_account_id, body.method) if body.kind == "transfer" else None
    prefix_type = {"expense": "expense", "income": "income", "transfer": "transfer"}[body.kind]
    data = body.model_dump(exclude={"account_id", "to_account_id"})
    e = FinanceEntry(organization_id=ctx.org_id, account_id=acc.id, to_account_id=to_acc.id if to_acc else None,
                     created_by=ctx.user.id, number=billing.next_number(ctx.db, ctx.org_id, prefix_type,
                                                                         body.entry_date), **data)
    ctx.db.add(e)
    ctx.db.flush()
    ctx.audit("create", f"finance_{body.kind}", e.id, {"number": e.number, "amount": str(e.amount)})
    ctx.db.commit()
    return _entry_out(ctx, e)


@router.post("/finance-entries/{entry_id}/void", response_model=EntryOut)
def void_entry(entry_id: int, body: CancelIn, ctx: OrgContext = Depends(require("expenses.view"))):
    e = get_owned(ctx, FinanceEntry, entry_id, "Entry", lock=True)
    from ..permissions import has_permission
    if not has_permission(ctx.membership.role, PERM_FOR[e.kind]):
        raise HTTPException(403, f"Missing permission: {PERM_FOR[e.kind]}")
    if e.voided_at:
        raise HTTPException(409, "Already voided")
    e.voided_at = utcnow()
    e.void_reason = body.reason
    ctx.audit("void", f"finance_{e.kind}", e.id, {"number": e.number, "reason": body.reason})
    ctx.db.commit()
    return _entry_out(ctx, e)


# ---------------- tax rates (versioned) ----------------
class TaxRateIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    rate: Decimal = Field(ge=0, le=100, decimal_places=2)
    effective_from: date
    notes: str | None = None


class TaxRateOut(ORM):
    id: int
    name: str
    rate: Decimal
    effective_from: date
    effective_to: date | None
    notes: str | None
    active: bool = False


def _rate_out(r: TaxRate, on: date) -> TaxRateOut:
    o = TaxRateOut.model_validate(r)
    o.active = r.effective_from <= on and (r.effective_to is None or r.effective_to >= on)
    return o


@router.get("/tax-rates", response_model=list[TaxRateOut])
def list_tax_rates(ctx: OrgContext = Depends(require("products.view")), include_history: bool = False):
    today = local_today()
    q = select(TaxRate).where(TaxRate.organization_id == ctx.org_id)
    if not include_history:
        q = q.where(or_(TaxRate.effective_to.is_(None), TaxRate.effective_to >= today))
    return [_rate_out(r, today) for r in ctx.db.scalars(q.order_by(TaxRate.rate, TaxRate.effective_from))]


@router.post("/tax-rates", response_model=TaxRateOut, status_code=201)
def add_tax_rate(body: TaxRateIn, ctx: OrgContext = Depends(require("org.manage"))):
    """Add a rate your accountant has confirmed. Rates are versioned, never edited."""
    open_same = ctx.db.scalar(select(TaxRate).where(TaxRate.organization_id == ctx.org_id,
                                                    TaxRate.rate == body.rate, TaxRate.effective_to.is_(None)))
    if open_same:
        raise HTTPException(409, f"A {body.rate}% rate is already in effect ({open_same.name})")
    r = TaxRate(organization_id=ctx.org_id, created_by=ctx.user.id, **body.model_dump())
    ctx.db.add(r)
    ctx.db.flush()
    ctx.audit("create", "tax_rate", r.id, {k: str(v) for k, v in body.model_dump().items()})
    ctx.db.commit()
    return _rate_out(r, local_today())


class RetireIn(BaseModel):
    effective_to: date
    reason: str = Field(min_length=3, max_length=300)


@router.post("/tax-rates/{rate_id}/retire", response_model=TaxRateOut)
def retire_tax_rate(rate_id: int, body: RetireIn, ctx: OrgContext = Depends(require("org.manage"))):
    r = get_owned(ctx, TaxRate, rate_id, "Tax rate")
    if r.effective_to is not None:
        raise HTTPException(409, "Rate is already retired")
    if body.effective_to < r.effective_from:
        raise HTTPException(422, "Retirement date is before the rate started")
    r.effective_to = body.effective_to
    ctx.audit("retire", "tax_rate", r.id, {"rate": str(r.rate), "effective_to": str(body.effective_to),
                                           "reason": body.reason})
    ctx.db.commit()
    return _rate_out(r, local_today())


def rate_in_effect(ctx: OrgContext, rate: Decimal, on: date) -> bool | None:
    """None when the organization hasn't configured any rates (no validation possible)."""
    rows = ctx.db.scalars(select(TaxRate).where(TaxRate.organization_id == ctx.org_id)).all()
    if not rows:
        return None
    return any(r.rate == rate and r.effective_from <= on and (r.effective_to is None or r.effective_to >= on)
               for r in rows)
