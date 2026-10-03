"""Business reports built from persisted records. Each returns an export.Report.

Every figure is derived from issued documents and recorded payments/entries; nothing is estimated except
where a note says so (cost of goods uses moving-average cost).
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select

from ..deps import OrgContext
from ..models import Customer, Product, StockLevel, StockMovement
from ..models_finance import FinanceCategory, FinanceEntry, MoneyAccount
from ..models_service import Asset, Attendance, Employee, MaintenanceSchedule, ServiceTicket, Task
from ..models_trade import (
    CreditNote, Payment, PurchaseInvoice, PurchaseReturn, SalesInvoice,
    SalesInvoiceLine, Supplier,
)
from .export import Column, Report
from .finance import default_account, kind_for_method
from .timeutil import BUSINESS_TZ, today

ZERO = Decimal("0")
LIVE = ("issued", "partially_paid", "paid")
METHOD_LABEL = {"cash": "Cash", "upi": "UPI", "bank_transfer": "Bank transfer", "card": "Card", "cheque": "Cheque",
                "other": "Other"}


def period_label(d0: date, d1: date) -> str:
    return f"{d0.strftime('%d %b %Y')} to {d1.strftime('%d %b %Y')}"


def _live_invoices(ctx: OrgContext, d0: date, d1: date):
    return ctx.db.scalars(select(SalesInvoice).where(
        SalesInvoice.organization_id == ctx.org_id, SalesInvoice.status.in_(LIVE),
        SalesInvoice.invoice_date >= d0, SalesInvoice.invoice_date <= d1)
        .order_by(SalesInvoice.invoice_date, SalesInvoice.number)).all()


def _credit_notes(ctx: OrgContext, d0: date, d1: date):
    return ctx.db.scalars(select(CreditNote).where(
        CreditNote.organization_id == ctx.org_id, CreditNote.note_date >= d0, CreditNote.note_date <= d1)
        .order_by(CreditNote.note_date, CreditNote.number)).all()


def _entries(ctx: OrgContext, kind: str, d0: date, d1: date):
    return ctx.db.scalars(select(FinanceEntry).where(
        FinanceEntry.organization_id == ctx.org_id, FinanceEntry.kind == kind, FinanceEntry.voided_at.is_(None),
        FinanceEntry.entry_date >= d0, FinanceEntry.entry_date <= d1)
        .order_by(FinanceEntry.entry_date, FinanceEntry.id)).all()


def _movements_local(ctx: OrgContext, types: tuple[str, ...], d0: date, d1: date):
    """Stock movements whose business-local date falls in the period."""
    start = datetime.combine(d0, time.min, BUSINESS_TZ)
    end = datetime.combine(d1 + timedelta(days=1), time.min, BUSINESS_TZ)
    return ctx.db.scalars(select(StockMovement).where(
        StockMovement.organization_id == ctx.org_id, StockMovement.movement_type.in_(types),
        StockMovement.created_at >= start, StockMovement.created_at < end)).all()


# ---------------- registers ----------------
def sales_register(ctx: OrgContext, d0: date, d1: date) -> Report:
    rows, tot = [], defaultdict(Decimal)
    cust = {c.id: c for c in ctx.db.scalars(select(Customer).where(Customer.organization_id == ctx.org_id))}
    for i in _live_invoices(ctx, d0, d1):
        c = cust[i.customer_id]
        r = {"number": i.number, "date": i.invoice_date, "customer": c.name, "gstin": c.gstin or "",
             "pos": i.place_of_supply or "", "taxable": i.taxable_total, "cgst": i.cgst_total, "sgst": i.sgst_total,
             "igst": i.igst_total, "total": i.total, "status": i.status.replace("_", " ")}
        rows.append(r)
        for k in ("taxable", "cgst", "sgst", "igst", "total"):
            tot[k] += r[k]
    cols = [Column("number", "Invoice"), Column("date", "Date", "date"), Column("customer", "Customer"),
            Column("gstin", "GSTIN"), Column("pos", "Place of supply"), Column("taxable", "Taxable value", "money"),
            Column("cgst", "CGST", "money"), Column("sgst", "SGST", "money"), Column("igst", "IGST", "money"),
            Column("total", "Invoice total", "money"), Column("status", "Status")]
    cn_rows = [{"number": n.number, "date": n.note_date, "invoice": ctx.db.get(SalesInvoice, n.sales_invoice_id).number,
                "customer": cust[n.customer_id].name, "reason": n.reason, "taxable": n.taxable_total,
                "tax": n.tax_total, "total": n.total} for n in _credit_notes(ctx, d0, d1)]
    cn = Report("Credit notes", [Column("number", "Credit note"), Column("date", "Date", "date"),
                                 Column("invoice", "Against invoice"), Column("customer", "Customer"),
                                 Column("reason", "Reason"), Column("taxable", "Taxable", "money"),
                                 Column("tax", "Tax", "money"), Column("total", "Total", "money")],
                cn_rows, totals={"number": "Total", **{k: sum((r[k] for r in cn_rows), ZERO)
                                                        for k in ("taxable", "tax", "total")}})
    return Report("Sales register", cols, rows, period_label(d0, d1), totals={"number": "Total", **tot},
                  notes=["Issued invoices only; drafts and cancelled invoices are excluded."], sections=[cn])


def purchase_register(ctx: OrgContext, d0: date, d1: date) -> Report:
    sup = {s.id: s for s in ctx.db.scalars(select(Supplier).where(Supplier.organization_id == ctx.org_id))}
    bills = ctx.db.scalars(select(PurchaseInvoice).where(
        PurchaseInvoice.organization_id == ctx.org_id, PurchaseInvoice.status != "cancelled",
        PurchaseInvoice.invoice_date >= d0, PurchaseInvoice.invoice_date <= d1)
        .order_by(PurchaseInvoice.invoice_date)).all()
    rows, tot = [], defaultdict(Decimal)
    for b in bills:
        s = sup[b.supplier_id]
        r = {"bill": b.supplier_invoice_number, "ref": b.number, "date": b.invoice_date, "supplier": s.name,
             "gstin": s.gstin or "", "taxable": b.taxable_total, "cgst": b.cgst_total, "sgst": b.sgst_total,
             "igst": b.igst_total, "total": b.total, "balance": max(b.total - b.amount_paid - b.credited_amount, ZERO)}
        rows.append(r)
        for k in ("taxable", "cgst", "sgst", "igst", "total", "balance"):
            tot[k] += r[k]
    cols = [Column("bill", "Supplier bill no."), Column("ref", "Our ref"), Column("date", "Date", "date"),
            Column("supplier", "Supplier"), Column("gstin", "GSTIN"), Column("taxable", "Taxable value", "money"),
            Column("cgst", "CGST", "money"), Column("sgst", "SGST", "money"), Column("igst", "IGST", "money"),
            Column("total", "Total", "money"), Column("balance", "Unpaid", "money")]
    return Report("Purchase register", cols, rows, period_label(d0, d1), totals={"bill": "Total", **tot})


def expense_register(ctx: OrgContext, d0: date, d1: date) -> Report:
    cats = {c.id: c.name for c in ctx.db.scalars(select(FinanceCategory).where(
        FinanceCategory.organization_id == ctx.org_id))}
    accs = {a.id: a.name for a in ctx.db.scalars(select(MoneyAccount).where(MoneyAccount.organization_id == ctx.org_id))}
    rows = [{"number": e.number, "date": e.entry_date, "kind": e.kind, "category": cats.get(e.category_id, ""),
             "payee": e.payee or "", "account": accs.get(e.account_id, ""), "method": METHOD_LABEL.get(e.method, e.method),
             "reference": e.reference or "", "net": e.amount - e.tax_amount, "tax": e.tax_amount, "amount": e.amount}
            for kind in ("expense", "income") for e in _entries(ctx, kind, d0, d1)]
    rows.sort(key=lambda r: (r["date"], r["number"]))
    by_cat = defaultdict(lambda: defaultdict(Decimal))
    for r in rows:
        by_cat[(r["kind"], r["category"])]["net"] += r["net"]
        by_cat[(r["kind"], r["category"])]["amount"] += r["amount"]
    analysis = Report("By category", [Column("kind", "Type"), Column("category", "Category"),
                                      Column("net", "Excl. claimable GST", "money"), Column("amount", "Paid", "money")],
                      [{"kind": k, "category": c, **v} for (k, c), v in sorted(by_cat.items())])
    return Report("Expenses and other income", [
        Column("number", "Number"), Column("date", "Date", "date"), Column("kind", "Type"),
        Column("category", "Category"), Column("payee", "Payee"), Column("account", "Account"),
        Column("method", "Method"), Column("reference", "Reference"), Column("net", "Excl. GST", "money"),
        Column("tax", "Claimable GST", "money"), Column("amount", "Amount", "money")],
        rows, period_label(d0, d1), sections=[analysis], notes=["Voided entries are excluded."])


# ---------------- profit and loss ----------------
def profit_and_loss(ctx: OrgContext, d0: date, d1: date) -> Report:
    invoices = _live_invoices(ctx, d0, d1)
    sales = sum((i.taxable_total for i in invoices), ZERO)
    notes_ = _credit_notes(ctx, d0, d1)
    returns = sum((n.taxable_total for n in notes_), ZERO)

    cogs, missing_cost = ZERO, 0
    for i in invoices:
        for li in i.lines:
            if li.product_id is None:
                continue
            if li.unit_cost is None:
                if not ctx.db.get(Product, li.product_id).is_service:
                    missing_cost += 1
                continue
            cogs += Decimal(li.quantity) * Decimal(li.unit_cost)
    restocked_cost = ZERO
    for n in notes_:
        if not n.restock:
            continue
        for cl in n.lines:
            line = ctx.db.get(SalesInvoiceLine, cl.sales_invoice_line_id)
            if line.unit_cost is not None:
                restocked_cost += Decimal(cl.quantity) * Decimal(line.unit_cost)
    cogs = (cogs - restocked_cost).quantize(Decimal("0.01"))

    writeoffs = sum((-Decimal(m.quantity_change) * Decimal(m.unit_cost or 0)
                     for m in _movements_local(ctx, ("damaged",), d0, d1)), ZERO).quantize(Decimal("0.01"))
    adjustments = sum((-Decimal(m.quantity_change) * Decimal(m.unit_cost or 0)
                       for m in _movements_local(ctx, ("adjustment", "stock_out"), d0, d1)), ZERO).quantize(
        Decimal("0.01"))

    cats = {c.id: c.name for c in ctx.db.scalars(select(FinanceCategory).where(
        FinanceCategory.organization_id == ctx.org_id))}
    exp_by, inc_by = defaultdict(Decimal), defaultdict(Decimal)
    for e in _entries(ctx, "expense", d0, d1):
        exp_by[cats.get(e.category_id, "Uncategorised")] += e.amount - e.tax_amount
    for e in _entries(ctx, "income", d0, d1):
        inc_by[cats.get(e.category_id, "Uncategorised")] += e.amount - e.tax_amount

    net_sales = sales - returns
    gross = net_sales - cogs
    total_exp = sum(exp_by.values(), ZERO) + writeoffs + adjustments
    total_inc = sum(inc_by.values(), ZERO)
    net = gross - total_exp + total_inc

    rows = [{"item": "Sales (taxable value of issued invoices)", "amount": sales},
            {"item": "Less: sales returns and credit notes", "amount": -returns},
            {"item": "Net sales", "amount": net_sales, "bold": True},
            {"item": "Less: cost of goods sold", "amount": -cogs},
            {"item": "Gross profit", "amount": gross, "bold": True}]
    rows += [{"item": f"Expense: {k}", "amount": -v} for k, v in sorted(exp_by.items())]
    if writeoffs:
        rows.append({"item": "Expense: stock written off (damaged)", "amount": -writeoffs})
    if adjustments:
        rows.append({"item": "Expense: stock adjustments and stock-outs (net)", "amount": -adjustments})
    rows += [{"item": f"Other income: {k}", "amount": v} for k, v in sorted(inc_by.items())]
    rows.append({"item": "Net profit (indicative)", "amount": net, "bold": True})
    notes = ["Basic operating summary for management use. It is not a statutory profit and loss statement and "
             "has not been prepared or reviewed by an accountant.",
             "Cost of goods sold uses the moving-average purchase cost at the time each invoice was issued.",
             "Expenses and other income exclude any GST you marked as claimable on the entry.",
             "Figures exclude GST collected on sales. Depreciation, owner drawings and loan movements are not "
             "recorded in NetCare."]
    if missing_cost:
        notes.append(f"{missing_cost} invoice line(s) have no recorded cost (issued before costing existed); "
                     "cost of goods sold is understated by those lines.")
    return Report("Profit and loss summary", [Column("item", "Item"), Column("amount", "Amount", "money")], rows,
                  period_label(d0, d1), notes=notes)


# ---------------- cash and accounts ----------------
def _account_flows(ctx: OrgContext, upto: date):
    """Yield (date, account_id, signed_amount, kind, label) for every money movement up to `upto`."""
    defaults = {}

    def acc_for(p: Payment) -> int:
        if p.account_id:
            return p.account_id
        k = kind_for_method(p.method)
        if k not in defaults:
            defaults[k] = default_account(ctx, k).id
        return defaults[k]

    for p in ctx.db.scalars(select(Payment).where(Payment.organization_id == ctx.org_id,
                                                  Payment.voided_at.is_(None), Payment.payment_date <= upto)):
        sign = 1 if p.direction == "in" else -1
        yield p.payment_date, acc_for(p), sign * p.amount, \
            "Customer receipts" if p.direction == "in" else "Supplier payments", p.method
    for e in ctx.db.scalars(select(FinanceEntry).where(FinanceEntry.organization_id == ctx.org_id,
                                                       FinanceEntry.voided_at.is_(None),
                                                       FinanceEntry.entry_date <= upto)):
        if e.kind == "expense":
            yield e.entry_date, e.account_id, -e.amount, "Expenses", e.method
        elif e.kind == "income":
            yield e.entry_date, e.account_id, e.amount, "Other income", e.method
        else:
            yield e.entry_date, e.account_id, -e.amount, "Transfers out", e.method
            yield e.entry_date, e.to_account_id, e.amount, "Transfers in", e.method


def cash_flow(ctx: OrgContext, d0: date, d1: date) -> Report:
    flows = list(_account_flows(ctx, d1))  # may create default accounts on first use
    accounts = ctx.db.scalars(select(MoneyAccount).where(MoneyAccount.organization_id == ctx.org_id)
                              .order_by(MoneyAccount.kind, MoneyAccount.name)).all()
    per = {a.id: {"account": a.name, "kind": a.kind, "opening": Decimal(a.opening_balance), "in": ZERO, "out": ZERO}
           for a in accounts}
    by_type = defaultdict(Decimal)
    for d, acc, amt, label, _ in flows:
        if d < d0:
            per[acc]["opening"] += amt
        else:
            per[acc]["in" if amt > 0 else "out"] += abs(amt)
            if not label.startswith("Transfers"):
                by_type[label] += amt
    rows = [{**v, "closing": v["opening"] + v["in"] - v["out"]} for v in per.values()]
    tot = {k: sum((r[k] for r in rows), ZERO) for k in ("opening", "in", "out", "closing")}
    summary = Report("Where the money came from and went", [Column("type", "Type"), Column("amount", "Net", "money")],
                     [{"type": k, "amount": v} for k, v in sorted(by_type.items())],
                     totals={"type": "Net change (excluding transfers)", "amount": sum(by_type.values(), ZERO)})
    return Report("Cash flow by account", [
        Column("account", "Account"), Column("kind", "Type"), Column("opening", "Opening", "money"),
        Column("in", "Money in", "money"), Column("out", "Money out", "money"), Column("closing", "Closing", "money")],
        rows, period_label(d0, d1), totals={"account": "All accounts", **tot}, sections=[summary],
        notes=["Based on recorded payments, expenses, income and transfers only. Reconcile with your bank "
               "statement regularly.",
               "Payments recorded without an account are counted in the default cash account (cash) or the "
               "default bank account (all other methods)."])


def daily_closing(ctx: OrgContext, day: date) -> Report:
    invoices = _live_invoices(ctx, day, day)
    pays = ctx.db.scalars(select(Payment).where(Payment.organization_id == ctx.org_id, Payment.voided_at.is_(None),
                                                Payment.payment_date == day)).all()
    rows = [{"item": "Invoices issued", "count": len(invoices), "amount": sum((i.total for i in invoices), ZERO)}]
    cns = _credit_notes(ctx, day, day)
    rows.append({"item": "Credit notes", "count": len(cns), "amount": -sum((n.total for n in cns), ZERO)})
    for direction, label in (("in", "Received"), ("out", "Paid to suppliers")):
        by_m = defaultdict(lambda: [0, ZERO])
        for p in pays:
            if p.direction == direction:
                by_m[p.method][0] += 1
                by_m[p.method][1] += p.amount
        for m, (n, a) in sorted(by_m.items()):
            rows.append({"item": f"{label}: {METHOD_LABEL.get(m, m)}", "count": n,
                         "amount": a if direction == "in" else -a})
    for kind, label, sign in (("expense", "Expenses paid", -1), ("income", "Other income", 1)):
        es = _entries(ctx, kind, day, day)
        if es:
            rows.append({"item": label, "count": len(es), "amount": sign * sum((e.amount for e in es), ZERO)})
    acct = cash_flow(ctx, day, day)
    acct.title = "Account balances"
    return Report("Daily closing summary", [Column("item", "Item"), Column("count", "Count", "int"),
                                            Column("amount", "Amount", "money")],
                  rows, day.strftime("%A, %d %b %Y"), sections=[acct],
                  notes=["Count the cash drawer and compare it with the cash account's closing balance."])


# ---------------- ageing ----------------
BUCKETS = [("not_due", "Not yet due"), ("d0_30", "1-30 days"), ("d31_60", "31-60 days"), ("d61_90", "61-90 days"),
           ("d90", "Over 90 days")]


def _bucket(due: date | None, as_of: date) -> str:
    days = (as_of - (due or as_of)).days
    return ("not_due" if days <= 0 else "d0_30" if days <= 30 else "d31_60" if days <= 60
            else "d61_90" if days <= 90 else "d90")


def _ageing(title: str, party_label: str, docs, party_name, as_of: date) -> Report:
    per = defaultdict(lambda: defaultdict(Decimal))
    for d in docs:
        bal = Decimal(d.total) - Decimal(d.amount_paid) - Decimal(d.credited_amount)
        if bal <= 0:
            continue
        name = party_name(d)
        per[name][_bucket(d.due_date, as_of)] += bal
        per[name]["total"] += bal
    rows = [{"party": k, **v} for k, v in sorted(per.items(), key=lambda kv: -kv[1]["total"])]
    totals = {"party": "Total", **{k: sum((r.get(k, ZERO) for r in rows), ZERO) for k, _ in BUCKETS},
              "total": sum((r["total"] for r in rows), ZERO)}
    return Report(title, [Column("party", party_label)] + [Column(k, lbl, "money") for k, lbl in BUCKETS]
                  + [Column("total", "Total due", "money")], rows, f"As of {as_of.strftime('%d %b %Y')}",
                  totals=totals, notes=["Days are counted past each document's due date."])


def receivables_ageing(ctx: OrgContext, as_of: date) -> Report:
    cust = {c.id: c.name for c in ctx.db.scalars(select(Customer).where(Customer.organization_id == ctx.org_id))}
    docs = ctx.db.scalars(select(SalesInvoice).where(SalesInvoice.organization_id == ctx.org_id,
                                                     SalesInvoice.status.in_(("issued", "partially_paid")),
                                                     SalesInvoice.invoice_date <= as_of)).all()
    return _ageing("Customer dues (receivables ageing)", "Customer", docs, lambda d: cust[d.customer_id], as_of)


def payables_ageing(ctx: OrgContext, as_of: date) -> Report:
    sup = {s.id: s.name for s in ctx.db.scalars(select(Supplier).where(Supplier.organization_id == ctx.org_id))}
    docs = ctx.db.scalars(select(PurchaseInvoice).where(PurchaseInvoice.organization_id == ctx.org_id,
                                                        PurchaseInvoice.status.in_(("open", "partially_paid")),
                                                        PurchaseInvoice.invoice_date <= as_of)).all()
    return _ageing("Supplier dues (payables ageing)", "Supplier", docs, lambda d: sup[d.supplier_id], as_of)


# ---------------- GST summary (draft) ----------------
def gst_summary(ctx: OrgContext, d0: date, d1: date) -> Report:
    cust = {c.id: c for c in ctx.db.scalars(select(Customer).where(Customer.organization_id == ctx.org_id))}
    out = defaultdict(lambda: defaultdict(Decimal))
    hsn = defaultdict(lambda: defaultdict(Decimal))
    for i in _live_invoices(ctx, d0, d1):
        kind = "B2B" if cust[i.customer_id].gstin else "B2C"
        for li in i.lines:
            k = (kind, Decimal(li.tax_rate))
            for f in ("taxable_value", "cgst", "sgst", "igst"):
                out[k][f] += getattr(li, f)
            h = (li.hsn_sac or "(none)", Decimal(li.tax_rate))
            hsn[h]["quantity"] += Decimal(li.quantity)
            hsn[h]["taxable_value"] += li.taxable_value
            hsn[h]["tax"] += li.cgst + li.sgst + li.igst
    out_rows = [{"type": t, "rate": f"{r.normalize()}%", **v} for (t, r), v in sorted(out.items())]

    cn = defaultdict(lambda: defaultdict(Decimal))
    for n in _credit_notes(ctx, d0, d1):
        inv = ctx.db.get(SalesInvoice, n.sales_invoice_id)
        for cl in n.lines:
            line = ctx.db.get(SalesInvoiceLine, cl.sales_invoice_line_id)
            k = Decimal(line.tax_rate)
            cn[k]["taxable_value"] += cl.taxable_value
            cn[k]["igst" if inv.is_interstate else "cgst_sgst"] += cl.tax_amount
    cn_rows = [{"rate": f"{r.normalize()}%", **v} for r, v in sorted(cn.items())]

    inward = defaultdict(lambda: defaultdict(Decimal))
    for b in ctx.db.scalars(select(PurchaseInvoice).where(
            PurchaseInvoice.organization_id == ctx.org_id, PurchaseInvoice.status != "cancelled",
            PurchaseInvoice.invoice_date >= d0, PurchaseInvoice.invoice_date <= d1)):
        for li in b.lines:
            k = Decimal(li.tax_rate)
            for f in ("taxable_value", "cgst", "sgst", "igst"):
                inward[k][f] += getattr(li, f)
    in_rows = [{"rate": f"{r.normalize()}%", **v} for r, v in sorted(inward.items())]
    exp_tax = sum((e.tax_amount for e in _entries(ctx, "expense", d0, d1)), ZERO)
    pret = ctx.db.scalars(select(PurchaseReturn).where(PurchaseReturn.organization_id == ctx.org_id,
                                                       PurchaseReturn.return_date >= d0,
                                                       PurchaseReturn.return_date <= d1)).all()

    tax_cols = [Column("taxable_value", "Taxable value", "money"), Column("cgst", "CGST", "money"),
                Column("sgst", "SGST", "money"), Column("igst", "IGST", "money")]

    def tot(rows, keys):
        return {k: sum((r.get(k, ZERO) for r in rows), ZERO) for k in keys}

    outward = Report("Outward supplies (issued invoices) by type and rate",
                     [Column("type", "B2B / B2C"), Column("rate", "Rate")] + tax_cols, out_rows,
                     totals={"type": "Total", **tot(out_rows, ("taxable_value", "cgst", "sgst", "igst"))})
    credit = Report("Credit notes issued, by rate",
                    [Column("rate", "Rate"), Column("taxable_value", "Taxable value", "money"),
                     Column("cgst_sgst", "CGST + SGST", "money"), Column("igst", "IGST", "money")], cn_rows,
                    totals={"rate": "Total", **tot(cn_rows, ("taxable_value", "cgst_sgst", "igst"))})
    hsn_rep = Report("HSN/SAC summary of outward supplies",
                     [Column("hsn", "HSN/SAC"), Column("rate", "Rate"), Column("quantity", "Quantity", "qty"),
                      Column("taxable_value", "Taxable value", "money"), Column("tax", "Tax", "money")],
                     [{"hsn": h, "rate": f"{r.normalize()}%", **v} for (h, r), v in sorted(hsn.items())])
    inward_rep = Report("Inward supplies (supplier bills) by rate", [Column("rate", "Rate")] + tax_cols, in_rows,
                        totals={"rate": "Total", **tot(in_rows, ("taxable_value", "cgst", "sgst", "igst"))})
    other = Report("Other figures", [Column("item", "Item"), Column("amount", "Amount", "money")], [
        {"item": "GST marked claimable on expense entries", "amount": exp_tax},
        {"item": f"Purchase returns in period ({len(pret)}), value incl. tax", "amount": sum((p.total for p in pret), ZERO)},
    ])
    return Report("GST summary", [Column("item", "Section")], [], period_label(d0, d1), draft=True,
                  sections=[outward, credit, hsn_rep, inward_rep, other],
                  notes=["DRAFT for accountant review. This is not a GSTR-1 or GSTR-3B return and must not be "
                         "filed as-is.",
                         "B2B means the customer has a GSTIN recorded; it is not validated against the GST portal.",
                         "Input tax shown here is what your records contain. Eligibility for input tax credit "
                         "depends on rules NetCare does not check (e.g. supplier filing, blocked credits).",
                         "Place of supply is taken from the customer's state code or the invoice override; "
                         "invoices with an unknown place of supply were treated as intra-state."])


# ---------------- stock valuation ----------------
def stock_valuation(ctx: OrgContext, location_id: int | None = None) -> Report:
    q = select(StockLevel, Product).join(Product, Product.id == StockLevel.product_id).where(
        StockLevel.organization_id == ctx.org_id, Product.archived_at.is_(None))
    if location_id:
        q = q.where(StockLevel.location_id == location_id)
    agg = defaultdict(Decimal)
    prods = {}
    for lvl, p in ctx.db.execute(q):
        agg[p.id] += Decimal(lvl.quantity)
        prods[p.id] = p
    rows = [{"sku": p.sku, "name": p.name, "quantity": agg[pid], "avg_cost": p.avg_cost,
             "value": (agg[pid] * Decimal(p.avg_cost)).quantize(Decimal("0.01")),
             "selling_price": p.selling_price}
            for pid, p in sorted(prods.items(), key=lambda kv: kv[1].name) if agg[pid] != 0]
    return Report("Stock valuation", [
        Column("sku", "SKU"), Column("name", "Product"), Column("quantity", "On hand", "qty"),
        Column("avg_cost", "Average cost", "money"), Column("value", "Value at cost", "money"),
        Column("selling_price", "Selling price", "money")], rows, f"As of {today().strftime('%d %b %Y')}",
        totals={"sku": "Total", "value": sum((r["value"] for r in rows), ZERO)},
        notes=["Valued at moving-average purchase cost."])


# ---------------- service and people ----------------
def _local_range(d0: date, d1: date):
    return (datetime.combine(d0, time.min, BUSINESS_TZ), datetime.combine(d1 + timedelta(days=1), time.min, BUSINESS_TZ))


def service_performance(ctx: OrgContext, d0: date, d1: date) -> Report:
    start, end = _local_range(d0, d1)
    emps = {e.id: e.name for e in ctx.db.scalars(select(Employee).where(Employee.organization_id == ctx.org_id))}
    opened = ctx.db.scalars(select(ServiceTicket).where(ServiceTicket.organization_id == ctx.org_id,
                                                        ServiceTicket.created_at >= start,
                                                        ServiceTicket.created_at < end)).all()
    completed = ctx.db.scalars(select(ServiceTicket).where(ServiceTicket.organization_id == ctx.org_id,
                                                           ServiceTicket.completed_at >= start,
                                                           ServiceTicket.completed_at < end)).all()
    per = defaultdict(lambda: {"assigned": 0, "completed": 0, "hours": [], "parts": ZERO, "labour": ZERO})
    for t in opened:
        per[emps.get(t.assigned_to, "Unassigned")]["assigned"] += 1
    for t in completed:
        row = per[emps.get(t.assigned_to, "Unassigned")]
        row["completed"] += 1
        row["hours"].append((t.completed_at - t.created_at).total_seconds() / 3600)
        if not t.is_warranty:
            row["labour"] += t.labour_charge
            row["parts"] += sum((Decimal(p.quantity) * Decimal(p.unit_price) for p in t.parts
                                 if p.returned_movement_id is None), ZERO)
    rows = [{"technician": k, "assigned": v["assigned"], "completed": v["completed"],
             "avg_days": (f"{sum(v['hours']) / len(v['hours']) / 24:.1f}" if v["hours"] else ""),
             "labour": v["labour"], "parts": v["parts"]} for k, v in sorted(per.items())]
    by_type = defaultdict(lambda: defaultdict(int))
    for t in opened:
        by_type[t.ticket_type]["opened"] += 1
    for t in completed:
        by_type[t.ticket_type]["completed"] += 1
    open_now = defaultdict(int)
    for t in ctx.db.scalars(select(ServiceTicket).where(ServiceTicket.organization_id == ctx.org_id,
                                                        ServiceTicket.status.in_(("new", "assigned", "in_progress",
                                                                                  "waiting_parts",
                                                                                  "waiting_customer")))):
        open_now[t.status] += 1
    return Report("Service performance", [
        Column("technician", "Technician"), Column("assigned", "Opened in period", "int"),
        Column("completed", "Completed", "int"), Column("avg_days", "Avg. days to complete", "pct"),
        Column("labour", "Labour charged", "money"), Column("parts", "Parts charged", "money")], rows,
        period_label(d0, d1),
        totals={"technician": "Total", "assigned": len(opened), "completed": len(completed),
                "labour": sum((r["labour"] for r in rows), ZERO), "parts": sum((r["parts"] for r in rows), ZERO)},
        sections=[Report("By type", [Column("type", "Type"), Column("opened", "Opened", "int"),
                                     Column("completed", "Completed", "int")],
                         [{"type": k.title(), **v} for k, v in sorted(by_type.items())]),
                  Report("Open right now", [Column("status", "Status"), Column("count", "Tickets", "int")],
                         [{"status": k.replace("_", " ").title(), "count": v} for k, v in sorted(open_now.items())])],
        notes=["Labour and parts are amounts recorded on non-warranty tickets, before GST; invoices are the "
               "billing record.", "Days to complete are measured from ticket creation to completion."])


def warranty_expiry(ctx: OrgContext, as_of: date) -> Report:
    cust = {c.id: c.name for c in ctx.db.scalars(select(Customer).where(Customer.organization_id == ctx.org_id))}
    assets = ctx.db.scalars(select(Asset).where(
        Asset.organization_id == ctx.org_id, Asset.status == "active", Asset.warranty_until.is_not(None),
        Asset.warranty_until >= as_of - timedelta(days=30), Asset.warranty_until <= as_of + timedelta(days=90))
        .order_by(Asset.warranty_until)).all()
    rows = [{"customer": cust[a.customer_id], "asset": a.name, "type": a.asset_type, "serial": a.serial_number or "",
             "site": a.site_location or "", "warranty_until": a.warranty_until,
             "days": (a.warranty_until - as_of).days} for a in assets]
    return Report("Warranty expiry", [
        Column("customer", "Customer"), Column("asset", "Equipment"), Column("type", "Type"),
        Column("serial", "Serial no."), Column("site", "Site location"), Column("warranty_until", "Warranty until", "date"),
        Column("days", "Days left", "int")], rows,
        f"Expired in the last 30 days or expiring in the next 90, as of {as_of:%d %b %Y}",
        notes=["Negative days means the warranty has already expired. A good list for AMC renewal calls."])


def maintenance_due(ctx: OrgContext, as_of: date) -> Report:
    cust = {c.id: c.name for c in ctx.db.scalars(select(Customer).where(Customer.organization_id == ctx.org_id))}
    emps = {e.id: e.name for e in ctx.db.scalars(select(Employee).where(Employee.organization_id == ctx.org_id))}
    rows = [{"customer": cust[s.customer_id], "title": s.title, "every": f"{s.interval_months} mo",
             "last_done": s.last_done or "", "next_due": s.next_due, "days": (s.next_due - as_of).days,
             "technician": emps.get(s.assigned_to, "")}
            for s in ctx.db.scalars(select(MaintenanceSchedule).where(
                MaintenanceSchedule.organization_id == ctx.org_id, MaintenanceSchedule.is_active.is_(True),
                MaintenanceSchedule.next_due <= as_of + timedelta(days=30)).order_by(MaintenanceSchedule.next_due))]
    return Report("Maintenance due", [
        Column("customer", "Customer"), Column("title", "Schedule"), Column("every", "Every"),
        Column("last_done", "Last done", "date"), Column("next_due", "Next due", "date"),
        Column("days", "Days", "int"), Column("technician", "Technician")], rows,
        f"Overdue or due within 30 days of {as_of:%d %b %Y}", notes=["Negative days means overdue."])


def task_completion(ctx: OrgContext, d0: date, d1: date) -> Report:
    start, end = _local_range(d0, d1)
    emps = {e.id: e.name for e in ctx.db.scalars(select(Employee).where(Employee.organization_id == ctx.org_id))}
    per = defaultdict(lambda: defaultdict(int))
    t_today = today()
    for t in ctx.db.scalars(select(Task).where(Task.organization_id == ctx.org_id)):
        name = emps.get(t.assigned_to, "Unassigned")
        if t.completed_at and start <= t.completed_at < end:
            per[name]["done"] += 1
            if t.due_date and t.completed_at.astimezone(BUSINESS_TZ).date() > t.due_date:
                per[name]["late"] += 1
        if t.status in ("todo", "in_progress"):
            per[name]["open"] += 1
            if t.due_date and t.due_date < t_today:
                per[name]["overdue"] += 1
    rows = [{"employee": k, "done": v["done"], "late": v["late"], "open": v["open"], "overdue": v["overdue"]}
            for k, v in sorted(per.items())]
    return Report("Task completion", [
        Column("employee", "Employee"), Column("done", "Completed in period", "int"),
        Column("late", "Completed late", "int"), Column("open", "Open now", "int"),
        Column("overdue", "Overdue now", "int")], rows, period_label(d0, d1),
        notes=["Based only on tasks recorded in NetCare; it is not a performance appraisal."])


def attendance_summary(ctx: OrgContext, d0: date, d1: date) -> Report:
    emps = ctx.db.scalars(select(Employee).where(Employee.organization_id == ctx.org_id)
                          .order_by(Employee.name)).all()
    counts = defaultdict(lambda: defaultdict(int))
    for a in ctx.db.scalars(select(Attendance).where(Attendance.organization_id == ctx.org_id,
                                                     Attendance.work_date >= d0, Attendance.work_date <= d1)):
        counts[a.employee_id][a.status] += 1
    days = (d1 - d0).days + 1
    keys = ("present", "half_day", "absent", "leave", "holiday", "week_off")
    rows = []
    for e in emps:
        c = counts.get(e.id, {})
        if e.status != "active" and not c:
            continue
        rows.append({"employee": e.name, **{k: c.get(k, 0) for k in keys},
                     "unrecorded": days - sum(c.get(k, 0) for k in keys)})
    return Report("Attendance summary", [Column("employee", "Employee")] +
                  [Column(k, k.replace("_", " ").title(), "int") for k in keys] +
                  [Column("unrecorded", "Not recorded", "int")], rows, period_label(d0, d1),
                  notes=["For record-keeping only. NetCare does not calculate salaries or statutory dues."])


CATALOG = {
    "sales-register": ("Sales register", "period", sales_register),
    "purchase-register": ("Purchase register", "period", purchase_register),
    "expenses": ("Expenses and other income", "period", expense_register),
    "profit-loss": ("Profit and loss summary", "period", profit_and_loss),
    "cash-flow": ("Cash flow by account", "period", cash_flow),
    "daily-closing": ("Daily closing summary", "day", daily_closing),
    "receivables-ageing": ("Customer dues", "as_of", receivables_ageing),
    "payables-ageing": ("Supplier dues", "as_of", payables_ageing),
    "gst-summary": ("GST summary (draft)", "period", gst_summary),
    "stock-valuation": ("Stock valuation", "location", stock_valuation),
    "service-performance": ("Service performance", "period", service_performance),
    "warranty-expiry": ("Warranty expiry", "as_of", warranty_expiry),
    "maintenance-due": ("Maintenance due", "as_of", maintenance_due),
    "task-completion": ("Task completion", "period", task_completion),
    "attendance": ("Attendance summary", "period", attendance_summary),
}
