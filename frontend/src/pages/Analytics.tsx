import { useState } from "react";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, inr, qty } from "../api";
import { ErrorBanner, Field, PageHeader, Spinner, useAsync } from "../components/ui";

type Kpi = { key: string; value: string | number | null; previous: string | number | null; change_pct: number | null };
type Overview = {
  period: { from: string; to: string; days: number; granularity: "day" | "month" };
  previous: { from: string; to: string };
  kpis: Kpi[];
  trend: { bucket: string; sales: string; gross_profit: string; collections: string; expenses: string }[];
  top_products: { product_id: number; name: string; revenue: string; quantity: string; profit: string | null }[];
  top_customers: { customer_id: number; name: string; revenue: string; invoices: number }[];
  sales_by_category: { category: string; revenue: string }[];
  collections_by_method: { method: string; amount: string }[];
  service_by_type: { type: string; opened: number; completed: number }[];
  notes: string[];
};

// label, formatter, whether a rise is good (expenses and turnaround are better when lower)
const KPI: Record<string, [string, (v: any) => string, boolean]> = {
  net_sales: ["Net sales", inr, true],
  gross_profit: ["Gross profit", inr, true],
  collections: ["Money collected", inr, true],
  expenses: ["Expenses", inr, false],
  invoices: ["Invoices", String, true],
  avg_invoice: ["Average invoice", inr, true],
  new_customers: ["New customers", String, true],
  tickets_opened: ["Service jobs opened", String, true],
  tickets_completed: ["Service jobs completed", String, true],
  avg_turnaround_days: ["Average turnaround", (v) => `${v} days`, false],
};
const METHOD: Record<string, string> = { cash: "Cash", upi: "UPI", bank_transfer: "Bank transfer", card: "Card", cheque: "Cheque", other: "Other" };
const PRESETS: [string, () => [string, string]][] = [
  ["This month", () => { const d = new Date(); return [iso(new Date(d.getFullYear(), d.getMonth(), 1)), iso(d)]; }],
  ["Last 30 days", () => { const d = new Date(); return [iso(new Date(d.getTime() - 29 * 86_400_000)), iso(d)]; }],
  ["Last 6 months", () => { const d = new Date(); return [iso(new Date(d.getFullYear(), d.getMonth() - 5, 1)), iso(d)]; }],
  ["This financial year", () => { const d = new Date(); const y = d.getMonth() < 3 ? d.getFullYear() - 1 : d.getFullYear(); return [iso(new Date(y, 3, 1)), iso(d)]; }],
];
function iso(d: Date) { return d.toLocaleDateString("en-CA"); }
const compact = (v: number) => new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(v);
const bucketLabel = (b: string, g: string) => g === "month"
  ? new Date(b + "-01T00:00:00").toLocaleDateString("en-IN", { month: "short", year: "2-digit" })
  : new Date(b + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" });

function KpiTile({ k }: { k: Kpi }) {
  const [lbl, fmt, upGood] = KPI[k.key] ?? [k.key, String, true];
  const good = k.change_pct !== null && (k.change_pct >= 0) === upGood;
  return (
    <div className="card !p-3">
      <div className="text-xs text-slate-500">{lbl}</div>
      <div className="text-lg font-semibold tabular-nums">{k.value === null ? "—" : fmt(k.value)}</div>
      <div className="text-xs text-slate-500">
        {k.change_pct === null ? <>previous: {k.previous === null ? "—" : fmt(k.previous)}</> : (
          <span className={good ? "text-emerald-600" : "text-red-600"}>
            {k.change_pct >= 0 ? <ArrowUpRight size={12} className="inline" /> : <ArrowDownRight size={12} className="inline" />}
            {Math.abs(k.change_pct)}% vs previous period
          </span>
        )}
      </div>
    </div>
  );
}

function Ranked({ title, rows, empty }: { title: string; rows: { name: string; value: number; sub?: string }[]; empty: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="card">
      <h3 className="mb-3 font-medium">{title}</h3>
      {!rows.length ? <p className="text-sm text-slate-500">{empty}</p> : (
        <ul className="space-y-2">{rows.map((r, i) => (
          <li key={i}>
            <div className="flex justify-between gap-2 text-sm"><span className="truncate">{r.name}</span><span className="tabular-nums">{inr(r.value)}</span></div>
            <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800"><div className="h-full bg-indigo-500" style={{ width: `${(r.value / max) * 100}%` }} /></div>
            {r.sub && <div className="text-xs text-slate-500">{r.sub}</div>}
          </li>))}</ul>
      )}
    </div>
  );
}

export default function Analytics() {
  const [range, setRange] = useState<[string, string]>(PRESETS[2][1]());
  const { data, error, loading } = useAsync(() => api<Overview>(`/analytics/overview?date_from=${range[0]}&date_to=${range[1]}`), [range[0], range[1]]);
  const trend = data?.trend.map((t) => ({ label: bucketLabel(t.bucket, data.period.granularity), sales: +t.sales, gross_profit: +t.gross_profit, collections: +t.collections, expenses: +t.expenses })) ?? [];
  return (
    <>
      <PageHeader title="Analytics" subtitle="How the business is doing, compared with the previous period of the same length" />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="From"><input className="input" type="date" value={range[0]} onChange={(e) => setRange([e.target.value, range[1]])} /></Field>
        <Field label="To"><input className="input" type="date" value={range[1]} onChange={(e) => setRange([range[0], e.target.value])} /></Field>
        <div className="flex flex-wrap gap-1">{PRESETS.map(([n, fn]) => <button key={n} className="btn-ghost !py-1 text-xs" onClick={() => setRange(fn())}>{n}</button>)}</div>
      </div>
      <ErrorBanner message={error} />
      {loading && !data ? <Spinner /> : data && <div className="space-y-4">
        <p className="text-xs text-slate-500">Compared with {new Date(data.previous.from).toLocaleDateString("en-IN")} to {new Date(data.previous.to).toLocaleDateString("en-IN")}.</p>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">{data.kpis.map((k) => <KpiTile key={k.key} k={k} />)}</div>

        <div className="card">
          <h3 className="mb-3 font-medium">Sales, gross profit and expenses by {data.period.granularity}</h3>
          <div className="h-72">
            <ResponsiveContainer>
              <BarChart data={trend}>
                <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.2} />
                <XAxis dataKey="label" fontSize={12} />
                <YAxis fontSize={12} tickFormatter={compact} />
                <Tooltip formatter={(v) => inr(Number(v))} />
                <Legend />
                <Bar dataKey="sales" name="Net sales" fill="#6366f1" />
                <Bar dataKey="gross_profit" name="Gross profit" fill="#10b981" />
                <Bar dataKey="expenses" name="Expenses" fill="#f59e0b" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="card">
          <h3 className="mb-3 font-medium">Money collected</h3>
          <div className="h-56">
            <ResponsiveContainer>
              <LineChart data={trend}>
                <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.2} />
                <XAxis dataKey="label" fontSize={12} />
                <YAxis fontSize={12} tickFormatter={compact} />
                <Tooltip formatter={(v) => inr(Number(v))} />
                <Line dataKey="collections" name="Collected" stroke="#6366f1" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <Ranked title="Top products and services" empty="No sales in this period."
            rows={data.top_products.map((p) => ({ name: p.name, value: +p.revenue, sub: `${qty(p.quantity)} sold${p.profit !== null ? ` · gross profit ${inr(p.profit)}` : ""}` }))} />
          <Ranked title="Top customers" empty="No sales in this period."
            rows={data.top_customers.map((c) => ({ name: c.name, value: +c.revenue, sub: `${c.invoices} invoice${c.invoices === 1 ? "" : "s"}` }))} />
          <Ranked title="Sales by category" empty="No product sales in this period."
            rows={data.sales_by_category.map((c) => ({ name: c.category, value: +c.revenue }))} />
          <Ranked title="Collections by payment method" empty="No payments received in this period."
            rows={data.collections_by_method.map((m) => ({ name: METHOD[m.method] ?? m.method, value: +m.amount }))} />
        </div>

        <div className="card">
          <h3 className="mb-3 font-medium">Service jobs by type</h3>
          {!data.service_by_type.length ? <p className="text-sm text-slate-500">No service jobs in this period.</p> : (
            <table className="w-full text-sm"><thead><tr><th className="th">Type</th><th className="th text-right">Opened</th><th className="th text-right">Completed</th></tr></thead>
              <tbody>{data.service_by_type.map((s) => <tr key={s.type} className="border-t border-slate-100 dark:border-slate-800"><td className="td capitalize">{s.type}</td><td className="td text-right">{s.opened}</td><td className="td text-right">{s.completed}</td></tr>)}</tbody></table>
          )}
        </div>
        <ul className="list-disc space-y-1 pl-5 text-xs text-slate-500">{data.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
      </div>}
    </>
  );
}
