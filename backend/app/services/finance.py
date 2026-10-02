"""Money accounts and default resolution shared by payments, expenses and reports."""
from fastapi import HTTPException
from sqlalchemy import select

from ..deps import OrgContext
from ..models_finance import MoneyAccount

DEFAULT_NAMES = {"cash": "Cash in hand", "bank": "Bank"}


def kind_for_method(method: str) -> str:
    return "cash" if method == "cash" else "bank"


def default_account(ctx: OrgContext, kind: str) -> MoneyAccount:
    """The default account of a kind, created on first use so a new business works without setup."""
    acc = ctx.db.scalar(select(MoneyAccount).where(MoneyAccount.organization_id == ctx.org_id,
                                                   MoneyAccount.kind == kind, MoneyAccount.is_default.is_(True)))
    if acc is None:
        acc = ctx.db.scalar(select(MoneyAccount).where(MoneyAccount.organization_id == ctx.org_id,
                                                       MoneyAccount.name == DEFAULT_NAMES[kind]))
    if acc is None:
        acc = MoneyAccount(organization_id=ctx.org_id, name=DEFAULT_NAMES[kind], kind=kind, is_default=True)
        ctx.db.add(acc)
        ctx.db.flush()
    return acc


def resolve_account(ctx: OrgContext, account_id: int | None, method: str) -> MoneyAccount:
    if account_id is None:
        return default_account(ctx, kind_for_method(method))
    acc = ctx.db.get(MoneyAccount, account_id)
    if acc is None or acc.organization_id != ctx.org_id:
        raise HTTPException(422, "Account not found")
    if not acc.is_active:
        raise HTTPException(422, f"Account {acc.name} is inactive")
    return acc
