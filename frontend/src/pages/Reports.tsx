import { useState } from "react";
import { AlertTriangle, Archive, Download, FileSpreadsheet, FileText } from "lucide-react";
import { api, download, inr, qty } from "../api";
import { useLocations } from "../components/trade";
import { ErrorBanner, Field, Modal, PageHeader, Spinner, useAsync } from "../components/ui";

type Col = { key: string; label: string; kind: string };
type ReportJson = { title: string; subtitle: string; draft: boolean; notes: string[]; columns: Col[]; rows: any[]; totals: any | null; sections: ReportJson[] };
type CatalogItem = { key: string; title: string; params: "period" | "day" | "as_of" | "location" };

const DESCRIPTIONS: Record<string, string> = {
  "profit-loss": "Net sales, cost of goods sold, expenses and indicative profit",
  "cash-flow": "Opening and closing balance of every cash and bank account",
  "daily-closing": "One day: invoices, money received and paid by method, expenses",
  "sales-register": "Every issued invoice with tax breakdown, plus credit notes",
  "purchase-register": "Every supplier bill with tax breakdown",
  "expenses": "Expenses and other income, with a category analysis",
  "receivables-ageing": "Who owes you, by how overdue",
  "payables-ageing": "Who you owe, by how overdue",
  "gst-summary": "Draft tax summary for your accountant. Not a return",
  "stock-valuation": "Quantity on hand at moving-average cost",
  "service-performance": "Jobs opened and completed, turnaround, by technician",
  "warranty-expiry": "Customer equipment whose warranty is ending",
  "maintenance-due": "Maintenance visits overdue or due soon",
  "task-completion": "Tasks completed, late and open, per employee",
  "attendance": "Days present, absent and on leave, per employee",
  "documents-expiring": "Contracts, warranty cards and licences expiring within 60 days",
};

function PackForm({ onDone }: { onDone: () => void }) {
  const [f, setF] = useState({ date_from: firstOfMonth(), date_to: todayLocal(), format: "xlsx" });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const go = () => {
    setBusy(true);
    download(`/reports/pack?date_from=${f.date_from}&date_to=${f.date_to}&format=${f.format}`, `reports_${f.date_from}_${f.date_to}.zip`)
      .then(onDone).catch((e) => setErr(e.message)).finally(() => setBusy(false));
  };
  return (
    <div className="space-y-3">
      <ErrorBanner message={err} />
      <p className="text-sm text-slate-500">Every report you can see, for one period, in a single ZIP file: useful for the month-end handover to your accountant. Dues, warranty and document reports are taken as of the last day.</p>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="From"><input className="input" type="date" value={f.date_from} onChange={(e) => setF({ ...f, date_from: e.target.value })} /></Field>
        <Field label="To"><input className="input" type="date" value={f.date_to} onChange={(e) => setF({ ...f, date_to: e.target.value })} /></Field>
        <Field label="Format"><select className="input" value={f.format} onChange={(e) => setF({ ...f, format: e.target.value })}><option value="xlsx">Excel</option><option value="pdf">PDF</option><option value="csv">CSV</option></select></Field>
      </div>
      <div className="flex justify-end gap-2"><button className="btn-ghost" onClick={onDone}>Cancel</button><button className="btn-primary" disabled={busy} onClick={go}><Archive size={15} /> {busy ? "Preparing…" : "Download ZIP"}</button></div>
    </div>
  );
}

const fmtCell = (v: any, kind: string) =>
  v === null || v === undefined || v === "" ? "" : kind === "money" ? inr(v) : kind === "qty" ? qty(v) : String(v);

function Table({ r }: { r: ReportJson }) {
  if (!r.columns.length) return null;
  const num = (k: string) => ["money", "qty", "int", "pct"].includes(k);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[480px] text-sm">
        <thead className="bg-slate-50 dark:bg-slate-800/50"><tr>{r.columns.map((c) => <th key={c.key} className={`th ${num(c.kind) ? "text-right" : ""}`}>{c.label}</th>)}</tr></thead>
        <tbody>
          {r.rows.length === 0 && <tr><td className="td text-slate-500" colSpan={r.columns.length}>No records in this period.</td></tr>}
          {r.rows.map((row, i) => (
            <tr key={i} className={`border-t border-slate-100 dark:border-slate-800 ${row.bold ? "font-semibold" : ""}`}>
              {r.columns.map((c) => <td key={c.key} className={`td ${num(c.kind) ? "text-right tabular-nums" : ""} ${c.kind === "money" && Number(row[c.key]) < 0 ? "text-red-600" : ""}`}>{fmtCell(row[c.key], c.kind)}</td>)}
            </tr>
          ))}
          {r.totals && <tr className="border-t-2 border-slate-300 font-semibold dark:border-slate-600">
            {r.columns.map((c) => <td key={c.key} className={`td ${num(c.kind) ? "text-right tabular-nums" : ""}`}>{fmtCell(r.totals[c.key], c.kind)}</td>)}
          </tr>}
        </tbody>
      </table>
    </div>
  );
}

export function ReportView({ r }: { r: ReportJson }) {
  return (
    <div className="space-y-4">
      {r.draft && <div className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
        <AlertTriangle size={16} className="mt-0.5 shrink-0" /><span><b>Draft, not for filing.</b> Prepared from your records for review by a qualified accountant.</span></div>}
      <Table r={r} />
      {r.sections.map((s, i) => <div key={i}><h3 className="mb-2 font-medium">{s.title}</h3><Table r={s} /></div>)}
      {!!r.notes.length && <ul className="list-disc space-y-1 pl-5 text-xs text-slate-500">{r.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
    </div>
  );
}

const firstOfMonth = () => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), 1).toLocaleDateString("en-CA"); };
const todayLocal = () => new Date().toLocaleDateString("en-CA");

export default function Reports() {
  const catalog = useAsync(() => api<CatalogItem[]>("/reports"), []);
  const locations = useLocations();
  const [key, setKey] = useState("profit-loss");
  const [p, setP] = useState({ date_from: firstOfMonth(), date_to: todayLocal(), day: todayLocal(), as_of: todayLocal(), location_id: "" });
  const [err, setErr] = useState<string | null>(null);
  const [pack, setPack] = useState(false);
  const item = catalog.data?.find((c) => c.key === key);
  const query = () => {
    if (!item) return "";
    const q = item.params === "period" ? `date_from=${p.date_from}&date_to=${p.date_to}`
      : item.params === "day" ? `day=${p.day}` : item.params === "as_of" ? `as_of=${p.as_of}` : p.location_id ? `location_id=${p.location_id}` : "";
    return q;
  };
  const report = useAsync(() => item ? api<ReportJson>(`/reports/${key}?${query()}`) : Promise.resolve(null), [key, item?.params, p.date_from, p.date_to, p.day, p.as_of, p.location_id]);
  const exp = (fmt: string) => download(`/reports/${key}?${query()}&format=${fmt}`, `${key}.${fmt}`).catch((e) => setErr(e.message));

  return (
    <>
      <PageHeader title="Reports" subtitle="Generated from your saved records. Export for your accountant."
        actions={<button className="btn-ghost" onClick={() => setPack(true)}><Archive size={15} /> Export all reports</button>} />
      {pack && <Modal title="Export all reports" onClose={() => setPack(false)}><PackForm onDone={() => setPack(false)} /></Modal>}
      <ErrorBanner message={catalog.error || err} />
      <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
        <div className="card !p-2">
          {catalog.data?.map((c) => (
            <button key={c.key} onClick={() => setKey(c.key)} className={`mb-0.5 w-full rounded-lg px-3 py-2 text-left ${key === c.key ? "bg-indigo-50 dark:bg-indigo-950" : "hover:bg-slate-100 dark:hover:bg-slate-800"}`}>
              <div className={`text-sm ${key === c.key ? "font-medium text-indigo-700 dark:text-indigo-300" : ""}`}>{c.title}</div>
              <div className="text-xs text-slate-500">{DESCRIPTIONS[c.key]}</div>
            </button>
          ))}
        </div>
        <div className="card min-w-0">
          <div className="mb-4 flex flex-wrap items-end gap-3">
            {item?.params === "period" && <>
              <Field label="From"><input className="input" type="date" value={p.date_from} onChange={(e) => setP({ ...p, date_from: e.target.value })} /></Field>
              <Field label="To"><input className="input" type="date" value={p.date_to} onChange={(e) => setP({ ...p, date_to: e.target.value })} /></Field>
            </>}
            {item?.params === "day" && <Field label="Day"><input className="input" type="date" value={p.day} onChange={(e) => setP({ ...p, day: e.target.value })} /></Field>}
            {item?.params === "as_of" && <Field label="As of"><input className="input" type="date" value={p.as_of} onChange={(e) => setP({ ...p, as_of: e.target.value })} /></Field>}
            {item?.params === "location" && <Field label="Location"><select className="input" value={p.location_id} onChange={(e) => setP({ ...p, location_id: e.target.value })}>
              <option value="">All locations</option>{locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></Field>}
            <div className="ml-auto flex gap-2">
              <button className="btn-ghost" onClick={() => exp("pdf")}><FileText size={15} /> PDF</button>
              <button className="btn-ghost" onClick={() => exp("xlsx")}><FileSpreadsheet size={15} /> Excel</button>
              <button className="btn-ghost" onClick={() => exp("csv")}><Download size={15} /> CSV</button>
            </div>
          </div>
          <ErrorBanner message={report.error} />
          {report.loading && !report.data ? <Spinner /> : report.data && <>
            <h2 className="text-lg font-semibold">{report.data.title}</h2>
            <p className="mb-3 text-sm text-slate-500">{report.data.subtitle}</p>
            <ReportView r={report.data} />
          </>}
        </div>
      </div>
    </>
  );
}
