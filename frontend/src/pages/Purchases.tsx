import { useState, type FormEvent } from "react";
import { Ban, CheckCircle2, FileText, IndianRupee, PackageCheck, Plus, Undo2 } from "lucide-react";
import { api, inr, qty, type Page } from "../api";
import { useAuth } from "../auth";
import {
  blankLine, LineEditor, linesFrom, linesPayload, LinesTable, PartySelect, StatusBadge, today, TotalsBox,
  useLocations, useProducts, useSuppliers, type Line, type LineOut, type Totals,
} from "../components/trade";
import { confirmAction, Empty, ErrorBanner, Field, Modal, PageHeader, Pager, Spinner, useAsync } from "../components/ui";

type PO = Totals & { id: number; number: string; supplier_id: number; supplier_name: string; location_id: number; status: string; order_date: string; expected_date: string | null; notes: string | null; lines: LineOut[] };
type Bill = Totals & { id: number; number: string; supplier_invoice_number: string; supplier_id: number; supplier_name: string; purchase_order_id: number | null; invoice_date: string; due_date: string | null; status: string; display_status: string; amount_paid: string; credited_amount: string; balance_due: string; lines: LineOut[] };

const METHODS = [["bank_transfer", "Bank transfer"], ["upi", "UPI"], ["cash", "Cash"], ["cheque", "Cheque"], ["card", "Card"], ["other", "Other"]];

function POForm({ initial, onSaved, onCancel }: { initial?: PO; onSaved: (id: number) => void; onCancel: () => void }) {
  const suppliers = useSuppliers();
  const locations = useLocations();
  const [f, setF] = useState<any>({ supplier_id: initial?.supplier_id ?? "", location_id: initial?.location_id ?? "", order_date: initial?.order_date ?? today(), expected_date: initial?.expected_date ?? "", notes: initial?.notes ?? "" });
  const [lines, setLines] = useState<Line[]>(initial ? linesFrom(initial.lines) : [blankLine()]);
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      const body = { ...f, supplier_id: Number(f.supplier_id), location_id: Number(f.location_id), expected_date: f.expected_date || null, notes: f.notes || null, lines: linesPayload(lines, false) };
      const r = await api(initial ? `/purchase-orders/${initial.id}` : "/purchase-orders", { method: initial ? "PUT" : "POST", json: body });
      onSaved(r.id);
    } catch (err: any) { setError(err.message); }
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <ErrorBanner message={error} />
      <div className="grid gap-3 sm:grid-cols-4">
        <PartySelect label="Supplier *" value={f.supplier_id} onChange={(v) => setF({ ...f, supplier_id: v })} options={suppliers} />
        <PartySelect label="Deliver to *" value={f.location_id} onChange={(v) => setF({ ...f, location_id: v })} options={locations} />
        <Field label="Order date"><input className="input" type="date" required value={f.order_date} onChange={(e) => setF({ ...f, order_date: e.target.value })} /></Field>
        <Field label="Expected by"><input className="input" type="date" value={f.expected_date} onChange={(e) => setF({ ...f, expected_date: e.target.value })} /></Field>
      </div>
      <LineEditor lines={lines} onChange={setLines} priceField="purchase_price" discounts={false} productsOnly />
      <Field label="Notes"><input className="input" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
      <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={onCancel}>Cancel</button><button className="btn-primary">Save draft</button></div>
    </form>
  );
}

function ReceiveForm({ po, onDone }: { po: PO; onDone: () => void }) {
  const [q, setQ] = useState<Record<number, string>>(() => Object.fromEntries(po.lines.map((l) => [l.id, String(Number(l.quantity) - Number(l.received_quantity ?? 0))])));
  const [ref, setRef] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [idem] = useState(() => crypto.randomUUID());
  async function submit(e: FormEvent) {
    e.preventDefault();
    const lines = Object.entries(q).filter(([, v]) => Number(v) > 0).map(([id, v]) => ({ purchase_order_line_id: Number(id), quantity: v }));
    if (!lines.length) return setError("Enter a received quantity");
    try { await api(`/purchase-orders/${po.id}/receipts`, { method: "POST", json: { received_date: today(), supplier_reference: ref || null, idempotency_key: idem, lines } }); onDone(); }
    catch (err: any) { setError(err.message); }
  }
  return (
    <form onSubmit={submit} className="space-y-3">
      <ErrorBanner message={error} />
      <table className="w-full text-sm"><thead><tr><th className="th">Item</th><th className="th text-right">Ordered</th><th className="th text-right">Received</th><th className="th w-28">Receiving now</th></tr></thead>
        <tbody>{po.lines.map((l) => {
          const left = Number(l.quantity) - Number(l.received_quantity ?? 0);
          return <tr key={l.id}><td className="td">{l.description}</td><td className="td text-right">{qty(l.quantity)}</td><td className="td text-right">{qty(l.received_quantity ?? 0)}</td>
            <td className="p-1"><input className="input" type="number" step="0.001" min="0" max={left} disabled={left <= 0} value={q[l.id] ?? ""} onChange={(e) => setQ({ ...q, [l.id]: e.target.value })} aria-label={`Receive ${l.description}`} /></td></tr>;
        })}</tbody></table>
      <Field label="Delivery challan / supplier reference"><input className="input" value={ref} onChange={(e) => setRef(e.target.value)} /></Field>
      <p className="text-xs text-slate-500">Received goods are added to stock immediately at the order's delivery location.</p>
      <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={onDone}>Cancel</button><button className="btn-primary">Record receipt</button></div>
    </form>
  );
}

function BillForm({ fromPO, onSaved, onCancel }: { fromPO?: PO; onSaved: (id: number) => void; onCancel: () => void }) {
  const suppliers = useSuppliers();
  const [f, setF] = useState<any>({ supplier_id: fromPO?.supplier_id ?? "", supplier_invoice_number: "", invoice_date: today(), due_date: "" });
  const [lines, setLines] = useState<Line[]>(fromPO ? linesFrom(fromPO.lines) : [blankLine()]);
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      const r = await api("/purchase-invoices", { method: "POST", json: { ...f, supplier_id: Number(f.supplier_id), purchase_order_id: fromPO?.id ?? null, due_date: f.due_date || null, lines: linesPayload(lines, false) } });
      onSaved(r.id);
    } catch (err: any) { setError(err.message); }
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <ErrorBanner message={error} />
      <div className="grid gap-3 sm:grid-cols-4">
        <PartySelect label="Supplier *" value={f.supplier_id} onChange={(v) => setF({ ...f, supplier_id: v })} options={suppliers} />
        <Field label="Supplier's bill number *"><input className="input" required value={f.supplier_invoice_number} onChange={(e) => setF({ ...f, supplier_invoice_number: e.target.value })} /></Field>
        <Field label="Bill date"><input className="input" type="date" required value={f.invoice_date} onChange={(e) => setF({ ...f, invoice_date: e.target.value })} /></Field>
        <Field label="Due date (blank = supplier terms)"><input className="input" type="date" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} /></Field>
      </div>
      <LineEditor lines={lines} onChange={setLines} priceField="purchase_price" discounts={false} />
      <p className="text-xs text-slate-500">Enter the amounts exactly as printed on the supplier's bill. Recording a bill does not change stock; stock comes in through goods receipts.</p>
      <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={onCancel}>Cancel</button><button className="btn-primary">Save bill</button></div>
    </form>
  );
}

function PODetail({ id, onChanged, onBill }: { id: number; onChanged: () => void; onBill: (po: PO) => void }) {
  const { can } = useAuth();
  const { data: po, error, reload } = useAsync(() => api<PO>(`/purchase-orders/${id}`), [id]);
  const receipts = useAsync(() => api<any[]>(`/purchase-orders/${id}/receipts`), [id]);
  const [mode, setMode] = useState<"view" | "edit" | "receive">("view");
  const [err, setErr] = useState<string | null>(null);
  const refresh = () => { setMode("view"); reload(); receipts.reload(); onChanged(); };
  async function act(path: string, msg: string, body?: unknown) {
    if (!confirmAction(msg)) return;
    try { await api(`/purchase-orders/${id}/${path}`, { method: "POST", json: body }); refresh(); } catch (e: any) { setErr(e.message); }
  }
  if (!po) return error ? <ErrorBanner message={error} /> : <Spinner />;
  if (mode === "edit") return <POForm initial={po} onSaved={refresh} onCancel={() => setMode("view")} />;
  if (mode === "receive") return <ReceiveForm po={po} onDone={refresh} />;
  return (
    <div className="space-y-4">
      <ErrorBanner message={err} />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><div className="text-lg font-semibold">{po.number} <StatusBadge s={po.status} /></div><div className="text-sm text-slate-500">{po.supplier_name} · {po.order_date}</div></div>
        {can("purchases.edit") && <div className="flex flex-wrap gap-2">
          {po.status === "draft" && <button className="btn-ghost" onClick={() => setMode("edit")}>Edit</button>}
          {po.status === "draft" && can("purchases.approve") && <button className="btn-primary" onClick={() => act("approve", "Approve this purchase order?")}><CheckCircle2 size={15} /> Approve</button>}
          {["approved", "partially_received"].includes(po.status) && <button className="btn-primary" onClick={() => setMode("receive")}><PackageCheck size={15} /> Receive goods</button>}
          {po.status !== "draft" && po.status !== "cancelled" && <button className="btn-ghost" onClick={() => onBill(po)}><FileText size={15} /> Record supplier bill</button>}
          {po.status === "partially_received" && <button className="btn-ghost" onClick={() => act("close", "Close this order? The remaining quantity will no longer be expected.")}>Close</button>}
          {["draft", "approved"].includes(po.status) && <button className="btn-ghost text-red-600" onClick={() => { const r = window.prompt("Reason for cancelling?"); if (r && r.length >= 3) act("cancel", "Cancel this purchase order?", { reason: r }); }}><Ban size={15} /> Cancel</button>}
        </div>}
      </div>
      <LinesTable lines={po.lines} extra={(l) => <span className="whitespace-nowrap text-xs text-slate-500">{qty(l.received_quantity ?? 0)} received</span>} />
      <TotalsBox t={po} />
      {!!receipts.data?.length && <div className="text-sm"><div className="font-medium">Goods receipts</div>{receipts.data.map((r) => <div key={r.id} className="text-slate-600 dark:text-slate-300">{r.number} · {r.received_date}{r.supplier_reference ? ` · ${r.supplier_reference}` : ""}</div>)}</div>}
    </div>
  );
}

function BillDetail({ id, onChanged }: { id: number; onChanged: () => void }) {
  const { can } = useAuth();
  const { data: b, error, reload } = useAsync(() => api<Bill>(`/purchase-invoices/${id}`), [id]);
  const [pay, setPay] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [idem] = useState(() => crypto.randomUUID());
  if (!b) return error ? <ErrorBanner message={error} /> : <Spinner />;
  async function submitPay(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/payments", { method: "POST", json: { supplier_id: b!.supplier_id, payment_date: pay.date, amount: pay.amount, method: pay.method, reference: pay.reference || null, idempotency_key: idem, allocations: [{ invoice_id: b!.id, amount: pay.amount }] } });
      setPay(null); reload(); onChanged();
    } catch (e: any) { setErr(e.message); }
  }
  async function cancel() {
    const r = window.prompt("Reason for cancelling this bill?");
    if (!r || r.length < 3) return;
    try { await api(`/purchase-invoices/${id}/cancel`, { method: "POST", json: { reason: r } }); reload(); onChanged(); } catch (e: any) { setErr(e.message); }
  }
  return (
    <div className="space-y-4">
      <ErrorBanner message={err} />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><div className="text-lg font-semibold">{b.supplier_invoice_number} <StatusBadge s={b.display_status} /></div><div className="text-sm text-slate-500">{b.supplier_name} · {b.invoice_date} · ref {b.number}{b.due_date ? ` · due ${b.due_date}` : ""}</div></div>
        <div className="flex gap-2">
          {["open", "partially_paid"].includes(b.status) && can("payments.edit") && !pay && <button className="btn-primary" onClick={() => setPay({ amount: b.balance_due, method: "bank_transfer", date: today(), reference: "" })}><IndianRupee size={15} /> Pay</button>}
          {b.status !== "cancelled" && can("purchases.edit") && <button className="btn-ghost text-red-600" onClick={cancel}><Ban size={15} /> Cancel</button>}
        </div>
      </div>
      {pay && <form onSubmit={submitPay} className="grid gap-3 rounded-lg border border-slate-200 p-3 sm:grid-cols-5 dark:border-slate-800">
        <Field label="Amount ₹"><input className="input" type="number" step="0.01" min="0.01" max={b.balance_due} required value={pay.amount} onChange={(e) => setPay({ ...pay, amount: e.target.value })} /></Field>
        <Field label="Method"><select className="input" value={pay.method} onChange={(e) => setPay({ ...pay, method: e.target.value })}>{METHODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
        <Field label="Date"><input className="input" type="date" value={pay.date} onChange={(e) => setPay({ ...pay, date: e.target.value })} /></Field>
        <Field label="Reference"><input className="input" value={pay.reference} onChange={(e) => setPay({ ...pay, reference: e.target.value })} /></Field>
        <div className="flex items-end gap-2"><button className="btn-primary">Save</button><button type="button" className="btn-ghost" onClick={() => setPay(null)}>Cancel</button></div>
      </form>}
      <LinesTable lines={b.lines} />
      <TotalsBox t={b}>
        <div className="flex justify-between py-0.5"><span className="text-slate-500">Paid</span><span>{inr(b.amount_paid)}</span></div>
        {Number(b.credited_amount) > 0 && <div className="flex justify-between py-0.5"><span className="text-slate-500">Returned</span><span>{inr(b.credited_amount)}</span></div>}
        <div className="flex justify-between py-0.5 font-semibold"><span>Balance due</span><span>{inr(b.balance_due)}</span></div>
      </TotalsBox>
    </div>
  );
}

function ReturnForm({ onDone }: { onDone: () => void }) {
  const suppliers = useSuppliers();
  const locations = useLocations();
  const products = useProducts().filter((p) => !p.is_service);
  const [f, setF] = useState<any>({ supplier_id: "", location_id: "", purchase_invoice_id: "", reason: "" });
  const [lines, setLines] = useState([{ product_id: "", quantity: "1", unit_cost: "", tax_rate: "0" }]);
  const bills = useAsync(() => f.supplier_id ? api<Page<Bill>>(`/purchase-invoices?supplier_id=${f.supplier_id}&unpaid=true&size=100`) : Promise.resolve(null), [f.supplier_id]);
  const [error, setError] = useState<string | null>(null);
  const [idem] = useState(() => crypto.randomUUID());
  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/purchase-returns", { method: "POST", json: { supplier_id: Number(f.supplier_id), location_id: Number(f.location_id), purchase_invoice_id: f.purchase_invoice_id ? Number(f.purchase_invoice_id) : null, return_date: today(), reason: f.reason || null, idempotency_key: idem, lines: lines.map((l) => ({ ...l, product_id: Number(l.product_id) })) } });
      onDone();
    } catch (err: any) { setError(err.message); }
  }
  return (
    <form onSubmit={submit} className="space-y-3">
      <ErrorBanner message={error} />
      <div className="grid gap-3 sm:grid-cols-3">
        <PartySelect label="Supplier *" value={f.supplier_id} onChange={(v) => setF({ ...f, supplier_id: v, purchase_invoice_id: "" })} options={suppliers} />
        <PartySelect label="Take stock from *" value={f.location_id} onChange={(v) => setF({ ...f, location_id: v })} options={locations} />
        <Field label="Against bill (reduces what you owe)"><select className="input" value={f.purchase_invoice_id} onChange={(e) => setF({ ...f, purchase_invoice_id: e.target.value })}>
          <option value="">— none —</option>{bills.data?.items.map((b) => <option key={b.id} value={b.id}>{b.supplier_invoice_number} ({inr(b.balance_due)} due)</option>)}</select></Field>
      </div>
      {lines.map((l, i) => (
        <div key={i} className="grid grid-cols-4 gap-2">
          <select className="input" required value={l.product_id} onChange={(e) => { const p = products.find((x) => x.id === Number(e.target.value)); setLines(lines.map((x, j) => j === i ? { ...x, product_id: e.target.value, unit_cost: p?.purchase_price ?? "", tax_rate: p?.gst_rate ?? "0" } : x)); }} aria-label="Product">
            <option value="">Product…</option>{products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
          <input className="input" type="number" step="0.001" min="0.001" required placeholder="Qty" value={l.quantity} onChange={(e) => setLines(lines.map((x, j) => j === i ? { ...x, quantity: e.target.value } : x))} aria-label="Quantity" />
          <input className="input" type="number" step="0.01" min="0" required placeholder="Unit cost" value={l.unit_cost} onChange={(e) => setLines(lines.map((x, j) => j === i ? { ...x, unit_cost: e.target.value } : x))} aria-label="Unit cost" />
          <input className="input" type="number" step="0.01" min="0" placeholder="GST %" value={l.tax_rate} onChange={(e) => setLines(lines.map((x, j) => j === i ? { ...x, tax_rate: e.target.value } : x))} aria-label="GST rate" />
        </div>
      ))}
      <button type="button" className="btn-ghost" onClick={() => setLines([...lines, { product_id: "", quantity: "1", unit_cost: "", tax_rate: "0" }])}><Plus size={15} /> Add line</button>
      <Field label="Reason"><input className="input" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} /></Field>
      <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={onDone}>Cancel</button><button className="btn-primary">Return to supplier</button></div>
    </form>
  );
}

export default function Purchases() {
  const { can } = useAuth();
  const [tab, setTab] = useState<"orders" | "bills" | "returns">("orders");
  const [page, setPage] = useState(1);
  const [dialog, setDialog] = useState<{ kind: "po-new" | "po" | "bill-new" | "bill" | "return-new"; id?: number; po?: PO } | null>(null);
  const orders = useAsync(() => api<Page<PO>>(`/purchase-orders?page=${page}`), [page, tab === "orders"]);
  const bills = useAsync(() => api<Page<Bill>>(`/purchase-invoices?page=${page}`), [page, tab === "bills"]);
  const returns = useAsync(() => api<Page<any>>(`/purchase-returns?page=${page}`), [page, tab === "returns"]);
  const reloadAll = () => { orders.reload(); bills.reload(); returns.reload(); };
  const switchTab = (t: typeof tab) => { setTab(t); setPage(1); };

  return (
    <>
      <PageHeader title="Purchases" subtitle="Order → approve → receive goods (adds stock) → record the supplier's bill → pay"
        actions={can("purchases.edit") && <>
          <button className="btn-ghost" onClick={() => setDialog({ kind: "return-new" })}><Undo2 size={16} /> Return to supplier</button>
          <button className="btn-ghost" onClick={() => setDialog({ kind: "bill-new" })}><FileText size={16} /> Record bill</button>
          <button className="btn-primary" onClick={() => setDialog({ kind: "po-new" })}><Plus size={16} /> New purchase order</button>
        </>} />
      <div className="mb-3 flex gap-1">
        {([["orders", "Purchase orders"], ["bills", "Supplier bills"], ["returns", "Returns"]] as const).map(([t, l]) => (
          <button key={t} className={`btn ${tab === t ? "bg-indigo-600 text-white" : "text-slate-600 hover:bg-slate-200 dark:text-slate-300 dark:hover:bg-slate-800"}`} onClick={() => switchTab(t)}>{l}</button>
        ))}
      </div>
      <ErrorBanner message={tab === "orders" ? orders.error : tab === "bills" ? bills.error : returns.error} />
      <div className="card !p-0 overflow-x-auto">
        {tab === "orders" && (!orders.data ? <Spinner /> : !orders.data.items.length ? <Empty title="No purchase orders" /> : <>
          <table className="w-full min-w-[640px]"><thead className="bg-slate-50 dark:bg-slate-800/50"><tr><th className="th">Number</th><th className="th">Supplier</th><th className="th">Date</th><th className="th">Status</th><th className="th text-right">Total</th></tr></thead>
            <tbody>{orders.data.items.map((p) => <tr key={p.id} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/40" onClick={() => setDialog({ kind: "po", id: p.id })}>
              <td className="td font-mono text-xs">{p.number}</td><td className="td">{p.supplier_name}</td><td className="td">{p.order_date}</td><td className="td"><StatusBadge s={p.status} /></td><td className="td text-right">{inr(p.total)}</td></tr>)}</tbody></table>
          <Pager page={orders.data.page} size={orders.data.size} total={orders.data.total} onPage={setPage} /></>)}
        {tab === "bills" && (!bills.data ? <Spinner /> : !bills.data.items.length ? <Empty title="No supplier bills" /> : <>
          <table className="w-full min-w-[640px]"><thead className="bg-slate-50 dark:bg-slate-800/50"><tr><th className="th">Bill no.</th><th className="th">Supplier</th><th className="th">Date</th><th className="th">Due</th><th className="th">Status</th><th className="th text-right">Total</th><th className="th text-right">Balance</th></tr></thead>
            <tbody>{bills.data.items.map((b) => <tr key={b.id} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/40" onClick={() => setDialog({ kind: "bill", id: b.id })}>
              <td className="td">{b.supplier_invoice_number}</td><td className="td">{b.supplier_name}</td><td className="td">{b.invoice_date}</td><td className="td">{b.due_date ?? "—"}</td><td className="td"><StatusBadge s={b.display_status} /></td><td className="td text-right">{inr(b.total)}</td><td className="td text-right font-medium">{Number(b.balance_due) ? inr(b.balance_due) : "—"}</td></tr>)}</tbody></table>
          <Pager page={bills.data.page} size={bills.data.size} total={bills.data.total} onPage={setPage} /></>)}
        {tab === "returns" && (!returns.data ? <Spinner /> : !returns.data.items.length ? <Empty title="No returns" /> : <>
          <table className="w-full min-w-[560px]"><thead className="bg-slate-50 dark:bg-slate-800/50"><tr><th className="th">Number</th><th className="th">Date</th><th className="th">Reason</th><th className="th text-right">Value</th></tr></thead>
            <tbody>{returns.data.items.map((r) => <tr key={r.id} className="border-t border-slate-100 dark:border-slate-800"><td className="td font-mono text-xs">{r.number}</td><td className="td">{r.return_date}</td><td className="td">{r.reason}</td><td className="td text-right">{inr(r.total)}</td></tr>)}</tbody></table>
          <Pager page={returns.data.page} size={returns.data.size} total={returns.data.total} onPage={setPage} /></>)}
      </div>
      {dialog?.kind === "po-new" && <Modal title="New purchase order" wide onClose={() => setDialog(null)}><POForm onCancel={() => setDialog(null)} onSaved={(id) => { reloadAll(); setDialog({ kind: "po", id }); }} /></Modal>}
      {dialog?.kind === "po" && <Modal title="Purchase order" wide onClose={() => setDialog(null)}><PODetail id={dialog.id!} onChanged={reloadAll} onBill={(po) => setDialog({ kind: "bill-new", po })} /></Modal>}
      {dialog?.kind === "bill-new" && <Modal title="Record supplier bill" wide onClose={() => setDialog(null)}><BillForm fromPO={dialog.po} onCancel={() => setDialog(null)} onSaved={(id) => { reloadAll(); setTab("bills"); setDialog({ kind: "bill", id }); }} /></Modal>}
      {dialog?.kind === "bill" && <Modal title="Supplier bill" wide onClose={() => setDialog(null)}><BillDetail id={dialog.id!} onChanged={reloadAll} /></Modal>}
      {dialog?.kind === "return-new" && <Modal title="Return goods to supplier" wide onClose={() => setDialog(null)}><ReturnForm onDone={() => { setDialog(null); reloadAll(); setTab("returns"); }} /></Modal>}
    </>
  );
}
