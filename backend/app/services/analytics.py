"""Business analytics: period KPIs against the previous period of the same length, trends and rankings.

Built from the same persisted records as the reports (issued invoices, credit notes, payments, finance
entries, service tickets). Gross profit counts only lines with a recorded cost; the response says how many
product lines had none so the figure is never silently overstated.
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select

from ..deps import OrgContext
from ..models import Customer, Product, ProductCategory
from ..models_finance import FinanceEntry
from ..models_service import ServiceTicket
from ..models_trade import CreditNote, Payment, SalesInvoice
from .timeutil import BUSINESS_TZ

ZERO = Decimal("0")
LIVE = ("issued", "partially_paid", "paid")
CENT = Decimal("0.01")


def _local_range(d0: date, d1: date) -> tuple[datetime, datetime]:
    return (datetime.combine(d0, time.min, BUSINESS_TZ),
            datetime.combine(d1 + timedelta(days=1), time.min, BUSINESS_TZ))


def bucket_of(d: date, monthly: bool) -> str:
    return d.strftime("%Y-%m") if monthly else d.isoformat()


def buckets(d0: date, d1: date, monthly: bool) -> list[str]:
    out, d = [], d0
    while d <= d1:
        b = bucket_of(d, monthly)
        if not out or out[-1] != b:
            out.append(b)
        d += timedelta(days=1)
    return out


def _invoices(ctx: OrgContext, d0: date, d1: date):
    return ctx.db.scalars(select(SalesInvoice).where(
        SalesInvoice.organization_id == ctx.org_id, SalesInvoice.status.in_(LIVE),
        SalesInvoice.invoice_date >= d0, SalesInvoice.invoice_date <= d1)).all()


def _credits(ctx: OrgContext, d0: date, d1: date):
    return ctx.db.scalars(select(CreditNote).where(
        CreditNote.organization_id == ctx.org_id, CreditNote.note_date >= d0, CreditNote.note_date <= d1)).all()


def _payments_in(ctx: OrgContext, d0: date, d1: date):
    return ctx.db.scalars(select(Payment).where(
        Payment.organization_id == ctx.org_id, Payment.direction == "in", Payment.voided_at.is_(None),
        Payment.payment_date >= d0, Payment.payment_date <= d1)).all()


def _expenses(ctx: OrgContext, d0: date, d1: date):
    return ctx.db.scalars(select(FinanceEntry).where(
        FinanceEntry.organization_id == ctx.org_id, FinanceEntry.kind == "expense",
        FinanceEntry.voided_at.is_(None), FinanceEntry.entry_date >= d0, FinanceEntry.entry_date <= d1)).all()


def _line_cost(li) -> Decimal | None:
    return None if li.unit_cost is None else Decimal(li.quantity) * Decimal(li.unit_cost)


def _kpis(ctx: OrgContext, d0: date, d1: date) -> dict:
    invs = _invoices(ctx, d0, d1)
    sales = sum((i.taxable_total for i in invs), ZERO) - sum((n.taxable_total for n in _credits(ctx, d0, d1)), ZERO)
    gp = ZERO
    for i in invs:
        for li in i.lines:
            c = _line_cost(li)
            if c is not None:
                gp += Decimal(li.taxable_value) - c
    start, end = _local_range(d0, d1)
    tickets = ctx.db.scalars(select(ServiceTicket).where(ServiceTicket.organization_id == ctx.org_id)).all()
    opened = [t for t in tickets if start <= t.created_at < end]
    done = [t for t in tickets if t.completed_at and start <= t.completed_at < end]
    tat = [(t.completed_at - t.created_at).total_seconds() / 86400 for t in done]
    new_customers = sum(1 for c in ctx.db.scalars(select(Customer.created_at).where(
        Customer.organization_id == ctx.org_id)) if start <= c < end)
    return {
        "net_sales": sales.quantize(CENT),
        "invoices": len(invs),
        "avg_invoice": (sum((i.taxable_total for i in invs), ZERO) / len(invs)).quantize(CENT) if invs else ZERO,
        "gross_profit": gp.quantize(CENT),
        "collections": sum((p.amount for p in _payments_in(ctx, d0, d1)), ZERO),
        "expenses": sum((e.amount - e.tax_amount for e in _expenses(ctx, d0, d1)), ZERO),
        "new_customers": new_customers,
        "tickets_opened": len(opened),
        "tickets_completed": len(done),
        "avg_turnaround_days": round(sum(tat) / len(tat), 1) if tat else None,
    }


def _change(cur, prev):
    if cur is None or prev is None:
        return None
    cur, prev = Decimal(str(cur)), Decimal(str(prev))
    if prev == 0:
        return None
    return float(((cur - prev) / abs(prev) * 100).quantize(Decimal("0.1")))


def overview(ctx: OrgContext, d0: date, d1: date) -> dict:
    days = (d1 - d0).days + 1
    p1 = d0 - timedelta(days=1)
    p0 = p1 - timedelta(days=days - 1)
    cur, prev = _kpis(ctx, d0, d1), _kpis(ctx, p0, p1)
    monthly = days > 62
    keys = buckets(d0, d1, monthly)
    trend = {k: defaultdict(Decimal) for k in keys}

    invs = _invoices(ctx, d0, d1)
    prod_names = {p.id: (p.name, p.category_id, p.is_service) for p in ctx.db.scalars(
        select(Product).where(Product.organization_id == ctx.org_id))}
    cat_names = {c.id: c.name for c in ctx.db.scalars(
        select(ProductCategory).where(ProductCategory.organization_id == ctx.org_id))}
    cust_names = {c.id: c.name for c in ctx.db.scalars(
        select(Customer).where(Customer.organization_id == ctx.org_id))}
    by_product = defaultdict(lambda: {"revenue": ZERO, "quantity": ZERO, "profit": ZERO, "costed": True})
    by_customer = defaultdict(lambda: {"revenue": ZERO, "invoices": 0})
    by_category = defaultdict(Decimal)
    uncosted = 0
    for i in invs:
        b = bucket_of(i.invoice_date, monthly)
        trend[b]["sales"] += i.taxable_total
        by_customer[i.customer_id]["revenue"] += i.taxable_total
        by_customer[i.customer_id]["invoices"] += 1
        for li in i.lines:
            c = _line_cost(li)
            if c is not None:
                trend[b]["gross_profit"] += Decimal(li.taxable_value) - c
            if li.product_id is None:
                continue
            name, cat, is_service = prod_names.get(li.product_id, ("Unknown", None, False))
            row = by_product[li.product_id]
            row["revenue"] += li.taxable_value
            row["quantity"] += Decimal(li.quantity)
            by_category[cat_names.get(cat, "Uncategorised")] += li.taxable_value
            if c is None:
                if not is_service:
                    row["costed"] = False
                    uncosted += 1
            else:
                row["profit"] += Decimal(li.taxable_value) - c
    for n in _credits(ctx, d0, d1):
        trend[bucket_of(n.note_date, monthly)]["sales"] -= n.taxable_total
    for p in _payments_in(ctx, d0, d1):
        trend[bucket_of(p.payment_date, monthly)]["collections"] += p.amount
    for e in _expenses(ctx, d0, d1):
        trend[bucket_of(e.entry_date, monthly)]["expenses"] += e.amount - e.tax_amount

    methods = defaultdict(Decimal)
    for p in _payments_in(ctx, d0, d1):
        methods[p.method] += p.amount

    start, end = _local_range(d0, d1)
    svc = defaultdict(lambda: {"opened": 0, "completed": 0})
    for t in ctx.db.scalars(select(ServiceTicket).where(ServiceTicket.organization_id == ctx.org_id)):
        if start <= t.created_at < end:
            svc[t.ticket_type]["opened"] += 1
        if t.completed_at and start <= t.completed_at < end:
            svc[t.ticket_type]["completed"] += 1

    top_products = sorted(by_product.items(), key=lambda kv: kv[1]["revenue"], reverse=True)[:10]
    top_customers = sorted(by_customer.items(), key=lambda kv: kv[1]["revenue"], reverse=True)[:10]
    s = str
    return {
        "period": {"from": d0.isoformat(), "to": d1.isoformat(), "days": days, "granularity":
                   "month" if monthly else "day"},
        "previous": {"from": p0.isoformat(), "to": p1.isoformat()},
        "kpis": [{"key": k, "value": s(v) if isinstance(v, Decimal) else v,
                  "previous": s(prev[k]) if isinstance(prev[k], Decimal) else prev[k],
                  "change_pct": _change(v, prev[k])} for k, v in cur.items()],
        "trend": [{"bucket": k, **{m: s(trend[k][m].quantize(CENT)) for m in
                                   ("sales", "gross_profit", "collections", "expenses")}} for k in keys],
        "top_products": [{"product_id": pid, "name": prod_names.get(pid, ("Unknown",))[0],
                          "revenue": s(r["revenue"]), "quantity": s(r["quantity"].normalize()),
                          "profit": s(r["profit"].quantize(CENT)) if r["costed"] else None}
                         for pid, r in top_products],
        "top_customers": [{"customer_id": cid, "name": cust_names.get(cid, "Unknown"),
                           "revenue": s(r["revenue"]), "invoices": r["invoices"]} for cid, r in top_customers],
        "sales_by_category": [{"category": k, "revenue": s(v)} for k, v in
                              sorted(by_category.items(), key=lambda kv: kv[1], reverse=True)],
        "collections_by_method": [{"method": k, "amount": s(v)} for k, v in
                                  sorted(methods.items(), key=lambda kv: kv[1], reverse=True)],
        "service_by_type": [{"type": k, **v} for k, v in sorted(svc.items())],
        "notes": ([f"{uncosted} product line(s) had no recorded cost and are left out of gross profit."]
                  if uncosted else []) +
                 ["Sales are taxable value (before GST) less credit notes. Expenses exclude claimable GST."],
    }
