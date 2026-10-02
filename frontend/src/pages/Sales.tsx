import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Ban, CheckCircle2, FileInput, IndianRupee, Plus, Send, Undo2 } from "lucide-react";
import { api, inr, qty, type Page } from "../api";
import { useAuth } from "../auth";
import {
  blankLine, LineEditor, linesFrom, linesPayload, LinesTable, PartySelect, StatusBadge, today, TotalsBox,
  useCustomers, useLocations, type Line, type LineOut, type Totals,
} from "../components/trade";
import { confirmAction, Empty, ErrorBanner, Field, Modal, PageHeader, Pager, Spinner, useAsync } from "../components/ui";

type Invoice = Totals & {
  id: number; number: string | null; customer_id: number; customer_name: string; location_id: number; quotation_id: number | null;
  invoice_date: string; due_date: string | null; status: string; display_status: string; document_discount: string;
  amount_paid: string; credited_amount: string; balance_due: string; notes: string | null; terms: string | null;
  cancel_reason: string | null; lines: LineOut[];
};
type Quote = Totals & {
  id: number; number: string; customer_id: number; customer_name: string; quote_date: string; valid_until: string | null;
  status: string; document_discount: string; notes: string | null; terms: string | null; converted_invoice_id: number | null; lines: LineOut[];
};

const METHODS = [["cash", "Cash"], ["upi", "UPI"], ["bank_transfer", "Bank transfer"], ["card", "Card"], ["cheque", "Cheque"], ["other", "Other"]];

// ---------- shared editor for invoices and quotations ----------
function SalesDocForm({ kind, initial, onSaved, onCancel }: { kind: "invoice" | "quotation"; initial?: Invoice | Quote; onSaved: (id: number) => void; onCancel: () => void }) {
  const customers = useCustomers();
  const locations = useLocations();
  const inv = initial as Invoice | undefined;
  const qt = initial as Quote | undefined;
  const [f, setF] = useState<any>({
    customer_id: initial?.customer_id ?? "", location_id: inv?.location_id ?? "",
    date: (kind === "invoice" ? inv?.invoice_date : qt?.quote_date) ?? today(),
    due: (kind === "invoice" ? inv?.due_date : qt?.valid_until) ?? "",
    place_of_supply: initial?.place_of_supply ?? "", document_discount: initial?.document_discount ?? "0",
    notes: initial?.notes ?? "", terms: initial?.terms ?? "",
  });
  const [lines, setLines] = useState<Line[]>(initial ? linesFrom(initial.lines) : [blankLine()]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [idem] = useState(() => crypto.randomUUID());
  const set = (k: string) => (e: React.ChangeEvent<any>) => setF({ ...f, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    const common = { customer_id: Number(f.customer_id), place_of_supply: f.place_of_supply || null, document_discount: f.document_discount || "0",
      notes: f.notes || null, terms: f.terms || null, lines: linesPayload(lines) };
    const body = kind === "invoice"
      ? { ...common, location_id: Number(f.location_id), invoice_date: f.date, due_date: f.due || null, ...(initial ? {} : { idempotency_key: idem }) }
      : { ...common, quote_date: f.date, valid_until: f.due || null };
    const base = kind === "invoice" ? "/invoices" : "/quotations";
    try {
      const r = await api(initial ? `${base}/${initial.id}` : base, { method: initial ? "PUT" : "POST", json: body });
      onSaved(r.id);
    } catch (err: any) { setError(err.message); } finally { setBusy(false); }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <ErrorBanner message={error} />
      <div className="grid gap-3 sm:grid-cols-3">
        <PartySelect label="Customer *" value={f.customer_id} onChange={(v) => setF({ ...f, customer_id: v })} options={customers} />
        {kind === "invoice" && <PartySelect label="Sell from location *" value={f.location_id} onChange={(v) => setF({ ...f, location_id: v })} options={locations} />}
        <Field label={kind === "invoice" ? "Invoice date" : "Quote date"}><input className="input" type="date" required value={f.date} onChange={set("date")} /></Field>
        <Field label={kind === "invoice" ? "Due date (blank = on receipt)" : "Valid until"}><input className="input" type="date" value={f.due} onChange={set("due")} /></Field>
        <Field label="Place of supply (state code)"><input className="input" pattern="\d{2}" maxLength={2} placeholder="From customer" value={f.place_of_supply} onChange={set("place_of_supply")} /></Field>
      </div>
      <LineEditor lines={lines} onChange={setLines} />
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Invoice-level discount ₹"><input className="input" type="number" step="0.01" min="0" value={f.document_discount} onChange={set("document_discount")} /></Field>
        <Field label="Notes" className="sm:col-span-2"><input className="input" value={f.notes} onChange={set("notes")} /></Field>
        <Field label="Terms and conditions" className="sm:col-span-3"><textarea className="input" rows={2} value={f.terms} placeholder="Defaults to your business terms in Settings" onChange={set("terms")} /></Field>
      </div>
      <div className="flex justify-end gap-2">
        <button type="button" className="btn-ghost" onClick={onCancel}>Cancel</button>
        <button className="btn-primary" disabled={busy}>{busy ? "Saving…" : initial ? "Save changes" : kind === "invoice" ? "Save draft" : "Save quotation"}</button>
      </div>
    </form>
  );
}

// ---------- invoice detail ----------
function PaymentForm({ inv, onDone }: { inv: Invoice; onDone: () => void }) {
  const [f, setF] = useState({ amount: inv.balance_due, method: "cash", payment_date: today(), reference: "" });
  const [error, setError] = useState<string | null>(null);
  const [idem] = useState(() => crypto.randomUUID());
  async function submit(e: FormEvent) {
    e.preventDefault();
    const alloc = Math.min(Number(f.amount), Number(inv.balance_due)).toFixed(2);
    try {
      await api("/payments", { method: "POST", json: { customer_id: inv.customer_id, payment_date: f.payment_date, amount: f.amount, method: f.method,
        reference: f.reference || null, idempotency_key: idem, allocations: [{ invoice_id: inv.id, amount: alloc }] } });
      onDone();
    } catch (err: any) { setError(err.message); }
  }
  return (
    <form onSubmit={submit} className="space-y-3">
      <ErrorBanner message={error} />
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={`Amount received ₹ (due ${inr(inv.balance_due)})`}><input className="input" type="number" step="0.01" min="0.01" required value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
        <Field label="Method"><select className="input" value={f.method} onChange={(e) => setF({ ...f, method: e.target.value })}>{METHODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
        <Field label="Date"><input className="input" type="date" required value={f.payment_date} onChange={(e) => setF({ ...f, payment_date: e.target.value })} /></Field>
        <Field label="Reference (UPI ref, cheque no.)"><input className="input" value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} /></Field>
      </div>
      {Number(f.amount) > Number(inv.balance_due) && <p className="text-xs text-amber-700">The extra {inr(Number(f.amount) - Number(inv.balance_due))} will be kept as an advance on the customer's account.</p>}
      <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={onDone}>Cancel</button><button className="btn-primary">Record payment</button></div>
    </form>
  );
}

function CreditNoteForm({ inv, onDone }: { inv: Invoice; onDone: () => void }) {
  const [q, setQ] = useState<Record<number, string>>({});
  const [reason, setReason] = useState("");
  const [restock, setRestock] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [idem] = useState(() => crypto.randomUUID());
  async function submit(e: FormEvent) {
    e.preventDefault();
    const lines = Object.entries(q).filter(([, v]) => Number(v) > 0).map(([id, v]) => ({ sales_invoice_line_id: Number(id), quantity: v }));
    if (!lines.length) return setError("Enter a quantity for at least one line");
    try {
      await api(`/invoices/${inv.id}/credit-notes`, { method: "POST", json: { note_date: today(), reason, restock, idempotency_key: idem, lines } });
      onDone();
    } catch (err: any) { setError(err.message); }
  }
  return (
    <form onSubmit={submit} className="space-y-3">
      <ErrorBanner message={error} />
      <table className="w-full text-sm"><thead><tr><th className="th">Item</th><th className="th text-right">Sold</th><th className="th text-right">Already returned</th><th className="th w-28">Return qty</th></tr></thead>
        <tbody>{inv.lines.map((l) => {
          const left = Number(l.quantity) - Number(l.returned_quantity ?? 0);
          return <tr key={l.id}><td className="td">{l.description}</td><td className="td text-right">{qty(l.quantity)}</td><td className="td text-right">{qty(l.returned_quantity ?? 0)}</td>
            <td className="p-1"><input className="input" type="number" step="0.001" min="0" max={left} disabled={left <= 0} value={q[l.id] ?? ""} onChange={(e) => setQ({ ...q, [l.id]: e.target.value })} aria-label={`Return quantity for ${l.description}`} /></td></tr>;
        })}</tbody></table>
      <Field label="Reason *"><input className="input" required minLength={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Defective on arrival" /></Field>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={restock} onChange={(e) => setRestock(e.target.checked)} /> Put returned goods back into stock (untick for damaged goods)</label>
      <p className="text-xs text-slate-500">The credit is valued at the invoice's prices and tax. It reduces what the customer owes; if they already paid, it becomes a refund due.</p>
      <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={onDone}>Cancel</button><button className="btn-primary">Issue credit note</button></div>
    </form>
  );
}

function InvoiceDetail({ id, onChanged, onClose }: { id: number; onChanged: () => void; onClose: () => void }) {
  const { can } = useAuth();
  const { data: inv, error, reload } = useAsync(() => api<Invoice>(`/invoices/${id}`), [id]);
  const credits = useAsync(() => api<Page<any>>(`/credit-notes?invoice_id=${id}`), [id]);
  const [mode, setMode] = useState<"view" | "edit" | "pay" | "credit">("view");
  const [err, setErr] = useState<string | null>(null);
  const refresh = () => { setMode("view"); reload(); credits.reload(); onChanged(); };

  async function act(path: string, confirmMsg: string, body?: unknown) {
    if (!confirmAction(confirmMsg)) return;
    setErr(null);
    try { await api(`/invoices/${id}/${path}`, { method: "POST", json: body }); refresh(); } catch (e: any) { setErr(e.message); }
  }
  async function cancel() {
    const reason = window.prompt("Reason for cancelling this invoice?");
    if (reason && reason.trim().length >= 3) act("cancel", "Cancel this invoice? Stock will be returned to the location.", { reason });
  }

  if (!inv) return error ? <ErrorBanner message={error} /> : <Spinner />;
  if (mode === "edit") return <SalesDocForm kind="invoice" initial={inv} onSaved={refresh} onCancel={() => setMode("view")} />;
  if (mode === "pay") return <PaymentForm inv={inv} onDone={refresh} />;
  if (mode === "credit") return <CreditNoteForm inv={inv} onDone={refresh} />;
  const live = ["issued", "partially_paid", "paid"].includes(inv.status);
  return (
    <div className="space-y-4">
      <ErrorBanner message={err} />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-lg font-semibold">{inv.number ?? "Draft invoice"} <StatusBadge s={inv.display_status} /></div>
          <div className="text-sm text-slate-500">{inv.customer_name} · {inv.invoice_date}{inv.due_date ? ` · due ${inv.due_date}` : ""}</div>
          {inv.cancel_reason && <div className="text-sm text-red-600">Cancelled: {inv.cancel_reason}</div>}
        </div>
        {can("sales.edit") && <div className="flex flex-wrap gap-2">
          {inv.status === "draft" && <>
            <button className="btn-ghost" onClick={() => setMode("edit")}>Edit</button>
            <button className="btn-primary" onClick={() => act("issue", "Issue this invoice? It gets a number, stock is deducted, and it can no longer be edited.")}><Send size={15} /> Issue</button>
          </>}
          {["issued", "partially_paid"].includes(inv.status) && can("payments.edit") && <button className="btn-primary" onClick={() => setMode("pay")}><IndianRupee size={15} /> Record payment</button>}
          {live && <button className="btn-ghost" onClick={() => setMode("credit")}><Undo2 size={15} /> Return / credit note</button>}
          {inv.status !== "cancelled" && <button className="btn-ghost text-red-600" onClick={cancel}><Ban size={15} /> Cancel</button>}
        </div>}
      </div>
      <LinesTable lines={inv.lines} />
      <TotalsBox t={inv}>
        {live && <>
          <div className="flex justify-between py-0.5"><span className="text-slate-500">Paid</span><span>{inr(inv.amount_paid)}</span></div>
          {Number(inv.credited_amount) > 0 && <div className="flex justify-between py-0.5"><span className="text-slate-500">Credited</span><span>{inr(inv.credited_amount)}</span></div>}
          <div className="flex justify-between py-0.5 font-semibold"><span>Balance due</span><span>{inr(inv.balance_due)}</span></div>
        </>}
      </TotalsBox>
      {!!credits.data?.items.length && <div className="text-sm"><div className="font-medium">Credit notes</div>
        {credits.data.items.map((c) => <div key={c.id} className="text-slate-600 dark:text-slate-300">{c.number} · {c.note_date} · {inr(c.total)} · {c.reason}{c.restock ? " · restocked" : ""}</div>)}</div>}
      {inv.terms && <div className="whitespace-pre-line text-xs text-slate-500">{inv.terms}</div>}
      <div className="text-right"><button className="btn-ghost" onClick={onClose}>Close</button></div>
    </div>
  );
}

export function Invoices() {
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const params = filter === "unpaid" ? "&unpaid=true" : filter === "overdue" ? "&overdue=true" : filter ? `&status=${filter}` : "";
  const { data, error, loading, reload } = useAsync(() => api<Page<Invoice>>(`/invoices?page=${page}&q=${encodeURIComponent(q)}${params}`), [page, q, filter]);

  return (
    <>
      <PageHeader title="Sales invoices" subtitle="Drafts can be edited. Issuing assigns the number and deducts stock."
        actions={can("sales.edit") && <button className="btn-primary" onClick={() => setCreating(true)}><Plus size={16} /> New invoice</button>} />
      <ErrorBanner message={error} />
      <div className="card !p-0">
        <div className="flex flex-wrap gap-2 border-b border-slate-200 p-3 dark:border-slate-800">
          <input className="input max-w-xs" placeholder="Search number or customer…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
          <select className="input !w-auto" value={filter} onChange={(e) => { setFilter(e.target.value); setPage(1); }} aria-label="Status filter">
            <option value="">All</option><option value="draft">Drafts</option><option value="unpaid">Unpaid</option><option value="overdue">Overdue</option>
            <option value="paid">Paid</option><option value="cancelled">Cancelled</option>
          </select>
        </div>
        {loading && !data ? <Spinner /> : !data?.items.length ? <Empty title="No invoices" hint="Create an invoice, or convert an accepted quotation." /> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px]">
              <thead className="bg-slate-50 dark:bg-slate-800/50"><tr><th className="th">Number</th><th className="th">Customer</th><th className="th">Date</th><th className="th">Due</th><th className="th">Status</th><th className="th text-right">Total</th><th className="th text-right">Balance</th></tr></thead>
              <tbody>{data.items.map((i) => (
                <tr key={i.id} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/40" onClick={() => setOpen(i.id)}>
                  <td className="td font-mono text-xs">{i.number ?? <span className="text-slate-400">draft #{i.id}</span>}</td>
                  <td className="td">{i.customer_name}</td><td className="td">{i.invoice_date}</td><td className="td">{i.due_date ?? "—"}</td>
                  <td className="td"><StatusBadge s={i.display_status} /></td>
                  <td className="td text-right">{inr(i.total)}</td><td className="td text-right font-medium">{Number(i.balance_due) ? inr(i.balance_due) : "—"}</td>
                </tr>))}</tbody>
            </table>
            <Pager page={data.page} size={data.size} total={data.total} onPage={setPage} />
          </div>
        )}
      </div>
      {creating && <Modal title="New invoice" onClose={() => setCreating(false)} wide>
        <SalesDocForm kind="invoice" onCancel={() => setCreating(false)} onSaved={(id) => { setCreating(false); reload(); setOpen(id); }} />
      </Modal>}
      {open && <Modal title="Invoice" onClose={() => setOpen(null)} wide><InvoiceDetail id={open} onChanged={reload} onClose={() => setOpen(null)} /></Modal>}
    </>
  );
}

// ---------- quotations ----------
function QuoteDetail({ id, onChanged, onClose }: { id: number; onChanged: () => void; onClose: () => void }) {
  const { can } = useAuth();
  const nav = useNavigate();
  const locations = useLocations();
  const { data: q, error, reload } = useAsync(() => api<Quote>(`/quotations/${id}`), [id]);
  const [edit, setEdit] = useState(false);
  const [loc, setLoc] = useState<number | "">("");
  const [err, setErr] = useState<string | null>(null);
  const refresh = () => { setEdit(false); reload(); onChanged(); };
  async function status(s: string) {
    try { await api(`/quotations/${id}/status`, { method: "POST", json: { status: s } }); refresh(); } catch (e: any) { setErr(e.message); }
  }
  async function convert() {
    if (!loc) return setErr("Choose the location the goods will be sold from");
    try { await api(`/quotations/${id}/convert?location_id=${loc}`, { method: "POST" }); onChanged(); nav("/sales"); } catch (e: any) { setErr(e.message); }
  }
  if (!q) return error ? <ErrorBanner message={error} /> : <Spinner />;
  if (edit) return <SalesDocForm kind="quotation" initial={q} onSaved={refresh} onCancel={() => setEdit(false)} />;
  const open = ["draft", "sent", "accepted"].includes(q.status);
  return (
    <div className="space-y-4">
      <ErrorBanner message={err} />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-lg font-semibold">{q.number} <StatusBadge s={q.status} /></div>
          <div className="text-sm text-slate-500">{q.customer_name} · {q.quote_date}{q.valid_until ? ` · valid until ${q.valid_until}` : ""}</div>
        </div>
        {can("sales.edit") && open && <div className="flex flex-wrap gap-2">
          {q.status !== "accepted" && <button className="btn-ghost" onClick={() => setEdit(true)}>Edit</button>}
          {q.status === "draft" && <button className="btn-ghost" onClick={() => status("sent")}><Send size={15} /> Mark sent</button>}
          {q.status !== "accepted" && <button className="btn-ghost" onClick={() => status("accepted")}><CheckCircle2 size={15} /> Accepted</button>}
          <button className="btn-ghost text-red-600" onClick={() => status("rejected")}>Rejected</button>
        </div>}
      </div>
      <LinesTable lines={q.lines} />
      <TotalsBox t={q} />
      {can("sales.edit") && open && (
        <div className="flex flex-wrap items-end justify-end gap-2 border-t border-slate-200 pt-3 dark:border-slate-800">
          <div className="w-56"><PartySelect label="Sell from location" value={loc} onChange={setLoc} options={locations} /></div>
          <button className="btn-primary" onClick={convert}><FileInput size={15} /> Convert to draft invoice</button>
        </div>
      )}
      <div className="text-right"><button className="btn-ghost" onClick={onClose}>Close</button></div>
    </div>
  );
}

export function Quotations() {
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const { data, error, loading, reload } = useAsync(() => api<Page<Quote>>(`/quotations?page=${page}&q=${encodeURIComponent(q)}`), [page, q]);
  return (
    <>
      <PageHeader title="Quotations" subtitle="Estimates for customers. They don't affect stock or balances."
        actions={can("sales.edit") && <button className="btn-primary" onClick={() => setCreating(true)}><Plus size={16} /> New quotation</button>} />
      <ErrorBanner message={error} />
      <div className="card !p-0">
        <div className="border-b border-slate-200 p-3 dark:border-slate-800"><input className="input max-w-xs" placeholder="Search number or customer…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} /></div>
        {loading && !data ? <Spinner /> : !data?.items.length ? <Empty title="No quotations yet" /> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px]">
              <thead className="bg-slate-50 dark:bg-slate-800/50"><tr><th className="th">Number</th><th className="th">Customer</th><th className="th">Date</th><th className="th">Valid until</th><th className="th">Status</th><th className="th text-right">Total</th></tr></thead>
              <tbody>{data.items.map((x) => (
                <tr key={x.id} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/40" onClick={() => setOpen(x.id)}>
                  <td className="td font-mono text-xs">{x.number}</td><td className="td">{x.customer_name}</td><td className="td">{x.quote_date}</td><td className="td">{x.valid_until ?? "—"}</td>
                  <td className="td"><StatusBadge s={x.status} /></td><td className="td text-right">{inr(x.total)}</td>
                </tr>))}</tbody>
            </table>
            <Pager page={data.page} size={data.size} total={data.total} onPage={setPage} />
          </div>
        )}
      </div>
      {creating && <Modal title="New quotation" onClose={() => setCreating(false)} wide>
        <SalesDocForm kind="quotation" onCancel={() => setCreating(false)} onSaved={(id) => { setCreating(false); reload(); setOpen(id); }} />
      </Modal>}
      {open && <Modal title="Quotation" onClose={() => setOpen(null)} wide><QuoteDetail id={open} onChanged={reload} onClose={() => setOpen(null)} /></Modal>}
    </>
  );
}
