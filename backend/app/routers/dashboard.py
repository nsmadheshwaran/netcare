from datetime import date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from ..deps import OrgContext, require
from ..models import AuditLog, Customer, Product, StockLevel, StockMovement, User
from ..models_finance import FinanceEntry
from ..models_service import Asset, MaintenanceSchedule, ServiceTicket, Task
from ..models_trade import Payment, PurchaseInvoice, SalesInvoice
from ..services.timeutil import BUSINESS_TZ, today as local_today

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Modules whose metrics are not built yet. Reported explicitly so the UI never shows fake numbers.
PENDING_MODULES = ["network", "endpoint_security"]
LIVE_SALES = ["issued", "partially_paid", "paid"]


def period_range(period: str, today: date) -> tuple[datetime, datetime]:
    if period == "day":
        start = today
    elif period == "week":
        start = today - timedelta(days=today.weekday())
    elif period == "month":
        start = today.replace(day=1)
    elif period == "quarter":
        start = today.replace(month=(today.month - 1) // 3 * 3 + 1, day=1)
    else:  # Indian financial year: 1 April
        start = date(today.year if today.month >= 4 else today.year - 1, 4, 1)
    tz = BUSINESS_TZ
    return datetime.combine(start, time.min, tz), datetime.combine(today + timedelta(days=1), time.min, tz)


@router.get("/summary")
def summary(ctx: OrgContext = Depends(require("dashboard.view")),
            period: str = Query("month", pattern="^(day|week|month|quarter|year)$"),
            location_id: int | None = None):
    db, org = ctx.db, ctx.org_id
    start, end = period_range(period, local_today())

    active_customers = select(Customer).where(Customer.organization_id == org, Customer.archived_at.is_(None))
    total_customers = db.scalar(select(func.count()).select_from(active_customers.subquery()))
    new_customers = db.scalar(select(func.count()).select_from(
        active_customers.where(Customer.created_at >= start, Customer.created_at < end).subquery()))

    lvl = select(StockLevel.product_id, func.sum(StockLevel.quantity).label("qty")).where(
        StockLevel.organization_id == org)
    if location_id:
        lvl = lvl.where(StockLevel.location_id == location_id)
    lvl = lvl.group_by(StockLevel.product_id).subquery()
    qty = func.coalesce(lvl.c.qty, 0)
    goods = (select(Product.id, Product.name, Product.sku, Product.min_stock, Product.purchase_price,
                    Product.avg_cost, qty.label("qty"))
             .outerjoin(lvl, lvl.c.product_id == Product.id)
             .where(Product.organization_id == org, Product.archived_at.is_(None), Product.is_service.is_(False)))
    rows = db.execute(goods).all()
    # Same basis as the stock valuation report: the average cost recorded on stock-in, else the list purchase price.
    valuation = sum((Decimal(r.qty) * Decimal(r.avg_cost or r.purchase_price)
                     for r in rows), Decimal("0"))
    low = [r for r in rows if Decimal(r.qty) <= Decimal(r.min_stock)]

    mv = select(StockMovement.movement_type, func.sum(StockMovement.quantity_change)).where(
        StockMovement.organization_id == org, StockMovement.created_at >= start, StockMovement.created_at < end)
    if location_id:
        mv = mv.where(StockMovement.location_id == location_id)
    movement_totals = {t: str(q) for t, q in db.execute(mv.group_by(StockMovement.movement_type))}

    daily = db.execute(
        select(func.date(StockMovement.created_at), func.count())
        .where(StockMovement.organization_id == org, StockMovement.created_at >= start,
               StockMovement.created_at < end)
        .group_by(func.date(StockMovement.created_at)).order_by(func.date(StockMovement.created_at))).all()
    cust_daily = db.execute(
        select(func.date(Customer.created_at), func.count())
        .where(Customer.organization_id == org, Customer.created_at >= start, Customer.created_at < end)
        .group_by(func.date(Customer.created_at)).order_by(func.date(Customer.created_at))).all()

    d0, d1 = start.date(), (end - timedelta(days=1)).date()
    today = local_today()

    def inv_sum(col, *conds):
        q = select(func.coalesce(func.sum(col), 0)).where(SalesInvoice.organization_id == org,
                                                          SalesInvoice.status.in_(LIVE_SALES), *conds)
        if location_id:
            q = q.where(SalesInvoice.location_id == location_id)
        return Decimal(db.scalar(q))

    sales_period = inv_sum(SalesInvoice.total, SalesInvoice.invoice_date >= d0, SalesInvoice.invoice_date <= d1)
    sales_today = inv_sum(SalesInvoice.total, SalesInvoice.invoice_date == today)
    credited_period = inv_sum(SalesInvoice.credited_amount, SalesInvoice.invoice_date >= d0,
                              SalesInvoice.invoice_date <= d1)
    receivable = inv_sum(SalesInvoice.total - SalesInvoice.amount_paid - SalesInvoice.credited_amount,
                         SalesInvoice.status != "paid")
    overdue = inv_sum(SalesInvoice.total - SalesInvoice.amount_paid - SalesInvoice.credited_amount,
                      SalesInvoice.status != "paid", SalesInvoice.due_date < today)
    purchases_period = Decimal(db.scalar(select(func.coalesce(func.sum(PurchaseInvoice.total), 0)).where(
        PurchaseInvoice.organization_id == org, PurchaseInvoice.status != "cancelled",
        PurchaseInvoice.invoice_date >= d0, PurchaseInvoice.invoice_date <= d1)))
    payable = Decimal(db.scalar(select(func.coalesce(func.sum(
        PurchaseInvoice.total - PurchaseInvoice.amount_paid - PurchaseInvoice.credited_amount), 0)).where(
        PurchaseInvoice.organization_id == org, PurchaseInvoice.status.in_(["open", "partially_paid"]))))

    def pay_sum(direction):
        return Decimal(db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.organization_id == org, Payment.direction == direction, Payment.voided_at.is_(None),
            Payment.payment_date >= d0, Payment.payment_date <= d1)))

    expenses_period = Decimal(db.scalar(select(func.coalesce(func.sum(FinanceEntry.amount), 0)).where(
        FinanceEntry.organization_id == org, FinanceEntry.kind == "expense", FinanceEntry.voided_at.is_(None),
        FinanceEntry.entry_date >= d0, FinanceEntry.entry_date <= d1)))

    open_states = ("new", "assigned", "in_progress", "waiting_parts", "waiting_customer")

    def count(q):
        return db.scalar(select(func.count()).select_from(q.subquery()))

    tickets = select(ServiceTicket.id).where(ServiceTicket.organization_id == org)
    service = {
        "open_tickets": count(tickets.where(ServiceTicket.status.in_(open_states))),
        "waiting_parts": count(tickets.where(ServiceTicket.status == "waiting_parts")),
        "awaiting_approval": count(tickets.where(ServiceTicket.status.in_(open_states),
                                                 ServiceTicket.customer_approval == "pending")),
        "pending_installations": count(tickets.where(ServiceTicket.ticket_type == "installation",
                                                     ServiceTicket.status.in_(open_states))),
        "completed_in_period": count(tickets.where(ServiceTicket.completed_at >= start,
                                                   ServiceTicket.completed_at < end)),
        "maintenance_due_30d": count(select(MaintenanceSchedule.id).where(
            MaintenanceSchedule.organization_id == org, MaintenanceSchedule.is_active.is_(True),
            MaintenanceSchedule.next_due <= today + timedelta(days=30))),
        "warranty_expiring_30d": count(select(Asset.id).where(
            Asset.organization_id == org, Asset.status == "active", Asset.warranty_until >= today,
            Asset.warranty_until <= today + timedelta(days=30))),
        "overdue_tasks": count(select(Task.id).where(Task.organization_id == org,
                                                     Task.status.in_(["todo", "in_progress"]),
                                                     Task.due_date < today)),
    }

    sales_daily = db.execute(
        select(SalesInvoice.invoice_date, func.sum(SalesInvoice.total))
        .where(SalesInvoice.organization_id == org, SalesInvoice.status.in_(LIVE_SALES),
               SalesInvoice.invoice_date >= d0, SalesInvoice.invoice_date <= d1,
               *([SalesInvoice.location_id == location_id] if location_id else []))
        .group_by(SalesInvoice.invoice_date).order_by(SalesInvoice.invoice_date)).all()
    purchase_daily = db.execute(
        select(PurchaseInvoice.invoice_date, func.sum(PurchaseInvoice.total))
        .where(PurchaseInvoice.organization_id == org, PurchaseInvoice.status != "cancelled",
               PurchaseInvoice.invoice_date >= d0, PurchaseInvoice.invoice_date <= d1)
        .group_by(PurchaseInvoice.invoice_date).order_by(PurchaseInvoice.invoice_date)).all()

    recent = db.execute(select(AuditLog, User.full_name).outerjoin(User, User.id == AuditLog.user_id)
                        .where(AuditLog.organization_id == org).order_by(AuditLog.id.desc()).limit(10)).all()

    return {
        "period": period, "start": start.isoformat(), "end": end.isoformat(), "location_id": location_id,
        "customers": {"total": total_customers, "new_in_period": new_customers},
        "inventory": {
            "products": db.scalar(select(func.count()).select_from(Product).where(
                Product.organization_id == org, Product.archived_at.is_(None))),
            "stock_valuation_at_cost": str(valuation.quantize(Decimal("0.01"))),
            "low_stock_count": len(low),
            "out_of_stock_count": sum(1 for r in rows if Decimal(r.qty) <= 0),
            "low_stock": [{"id": r.id, "name": r.name, "sku": r.sku, "qty": str(r.qty),
                           "min_stock": str(r.min_stock)} for r in low[:10]],
            "movement_totals": movement_totals,
        },
        "sales": {
            # Invoiced value (incl. tax) of issued invoices dated in the period. Not cash: see payments.
            "invoiced_in_period": str(sales_period), "invoiced_today": str(sales_today),
            "credited_in_period": str(credited_period),
            "receivable_outstanding": str(receivable), "receivable_overdue": str(overdue),
            "received_in_period": str(pay_sum("in")),
        },
        "purchases": {
            "billed_in_period": str(purchases_period), "payable_outstanding": str(payable),
            "paid_in_period": str(pay_sum("out")),
        },
        "expenses": {"paid_in_period": str(expenses_period)},
        "service": service,
        "trends": {
            "sales_per_day": [{"date": str(d), "total": str(v)} for d, v in sales_daily],
            "purchases_per_day": [{"date": str(d), "total": str(v)} for d, v in purchase_daily],
            "stock_movements_per_day": [{"date": str(d), "count": c} for d, c in daily],
            "new_customers_per_day": [{"date": str(d), "count": c} for d, c in cust_daily],
        },
        "recent_activity": [{"id": a.id, "action": a.action, "entity_type": a.entity_type,
                             "entity_id": a.entity_id, "user": name, "at": a.created_at.isoformat()}
                            for a, name in recent],
        "not_yet_available": PENDING_MODULES,
    }
