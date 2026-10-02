import { useState, type FormEvent } from "react";
import { Ban, Link2, Plus } from "lucide-react";
import { api, inr, type Page } from "../api";
import { useAuth } from "../auth";
import { PartySelect, today, useCustomers, useSuppliers } from "../components/trade";
import { Badge, Empty, ErrorBanner, Field, Modal, PageHeader, Pager, Spinner, useAsync } from "../components/ui";

type Payment = {
  id: number; number: string; direction: "in" | "out"; customer_id: number | null; supplier_id: number | null; party_name: string;
  payment_date: string; amount: string; unallocated: string; method: string; reference: string | null; voided_at: string | null;
  void_reason: string | null; allocations: { id: number; amount: string; invoice_number: string | null }[];
};
type OpenDoc = { id: number; number: string | null; supplier_invoice_number?: string; balance_due: string; invoice_date: string };
const METHODS = [["cash", "Cash"], ["upi", "UPI"], ["bank_transfer", "Bank transfer"], ["card", "Card"], ["cheque", "Cheque"], ["other", "Other"]];

/** Allocation rows for one party's open invoices/bills. */
function OpenDocs({ direction, partyId, max, value, onChange }: { direction: "in" | "out"; partyId: number | ""; max: number; value: Record<number, string>; onChange: (v: Record<number, string>) => void }) {
  const docs = useAsync(() => !partyId ? Promise.resolve(null)
    : api<Page<OpenDoc>>(direction === "in" ? `/invoices?customer_id=${partyId}&unpaid=true&size=100` : `/purchase-invoices?supplier_id=${partyId}&unpaid=true&size=100`), [direction, partyId]);
  if (!partyId) return null;
  if (!docs.data) return <Spinner />;
  if (!docs.data.items.length) return <p className="text-sm text-slate-500">No unpaid {direction === "in" ? "invoices" : "bills"}. The whole amount will be kept as an advance.</p>;
  const used = Object.values(value).reduce((s, v) => s + Number(v || 0), 0);
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-slate-500">Apply to {direction === "in" ? "invoices" : "bills"} (allocated {inr(used)} of {inr(max)})</div>
      {docs.data.items.map((d) => (
        <div key={d.id} className="flex items-center gap-2 py-1 text-sm">
          <span className="flex-1">{d.supplier_invoice_number ?? d.number} · {d.invoice_date} · due {inr(d.balance_due)}</span>
          <input className="input !w-32" type="number" step="0.01" min="0" max={d.balance_due} value={value[d.id] ?? ""} onChange={(e) => onChange({ ...value, [d.id]: e.target.value })} aria-label={`Allocate to ${d.number}`} />
          <button type="button" className="text-xs text-indigo-600 hover:underline" onClick={() => onChange({ ...value, [d.id]: Math.min(Number(d.balance_due), Math.max(0, max - used + Number(value[d.id] || 0))).toFixed(2) })}>max</button>
        </div>
      ))}
    </div>
  );
}

function PaymentForm({ onDone }: { onDone: () => void }) {
  const customers = useCustomers();
  const suppliers = useSuppliers();
  const [direction, setDirection] = useState<"in" | "out">("in");
  const [party, setParty] = useState<number | "">("");
  const [f, setF] = useState({ amount: "", method: "cash", payment_date: today(), reference: "", notes: "" });
  const [alloc, setAlloc] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [idem] = useState(() => crypto.randomUUID());
  async function submit(e: FormEvent) {
    e.preventDefault();
    const allocations = Object.entries(alloc).filter(([, v]) => Number(v) > 0).map(([id, v]) => ({ invoice_id: Number(id), amount: v }));
    try {
      await api("/payments", { method: "POST", json: { ...f, reference: f.reference || null, notes: f.notes || null, idempotency_key: idem, allocations,
        ...(direction === "in" ? { customer_id: party } : { supplier_id: party }) } });
      onDone();
    } catch (err: any) { setError(err.message); }
  }
  return (
    <form onSubmit={submit} className="space-y-3">
      <ErrorBanner message={error} />
      <div className="flex gap-2">
        {(["in", "out"] as const).map((d) => <button type="button" key={d} className={`btn ${direction === d ? "bg-indigo-600 text-white" : "btn-ghost"}`} onClick={() => { setDirection(d); setParty(""); setAlloc({}); }}>{d === "in" ? "Received from customer" : "Paid to supplier"}</button>)}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <PartySelect label={direction === "in" ? "Customer *" : "Supplier *"} value={party} onChange={(v) => { setParty(v); setAlloc({}); }} options={direction === "in" ? customers : suppliers} />
        <Field label="Amount ₹ *"><input className="input" type="number" step="0.01" min="0.01" required value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
        <Field label="Method"><select className="input" value={f.method} onChange={(e) => setF({ ...f, method: e.target.value })}>{METHODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
        <Field label="Date"><input className="input" type="date" required value={f.payment_date} onChange={(e) => setF({ ...f, payment_date: e.target.value })} /></Field>
        <Field label="Reference"><input className="input" value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} /></Field>
        <Field label="Notes"><input className="input" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
      </div>
      <OpenDocs direction={direction} partyId={party} max={Number(f.amount || 0)} value={alloc} onChange={setAlloc} />
      <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={onDone}>Cancel</button><button className="btn-primary">Save payment</button></div>
    </form>
  );
}

function AllocateForm({ p, onDone }: { p: Payment; onDone: () => void }) {
  const [alloc, setAlloc] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    const allocations = Object.entries(alloc).filter(([, v]) => Number(v) > 0).map(([id, v]) => ({ invoice_id: Number(id), amount: v }));
    try { await api(`/payments/${p.id}/allocate`, { method: "POST", json: { allocations } }); onDone(); } catch (err: any) { setError(err.message); }
  }
  return (
    <form onSubmit={submit} className="space-y-3">
      <ErrorBanner message={error} />
      <p className="text-sm">{p.number} from {p.party_name}: {inr(p.unallocated)} not yet applied.</p>
      <OpenDocs direction={p.direction} partyId={(p.customer_id ?? p.supplier_id)!} max={Number(p.unallocated)} value={alloc} onChange={setAlloc} />
      <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={onDone}>Cancel</button><button className="btn-primary">Apply</button></div>
    </form>
  );
}

export default function Payments() {
  const { can } = useAuth();
  const [direction, setDirection] = useState("");
  const [page, setPage] = useState(1);
  const [dialog, setDialog] = useState<"new" | Payment | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const { data, error, loading, reload } = useAsync(() => api<Page<Payment>>(`/payments?page=${page}${direction ? `&direction=${direction}` : ""}`), [page, direction]);

  async function voidPayment(p: Payment) {
    const reason = window.prompt(`Void ${p.number} (${inr(p.amount)})? This reverses its effect on invoices. Reason:`);
    if (!reason || reason.trim().length < 3) return;
    try { await api(`/payments/${p.id}/void`, { method: "POST", json: { reason } }); reload(); } catch (e: any) { setErr(e.message); }
  }
  return (
    <>
      <PageHeader title="Payments" subtitle="Money actually received and paid. Invoices count only when payment is recorded here."
        actions={can("payments.edit") && <button className="btn-primary" onClick={() => setDialog("new")}><Plus size={16} /> Record payment</button>} />
      <ErrorBanner message={error || err} />
      <div className="card !p-0">
        <div className="border-b border-slate-200 p-3 dark:border-slate-800">
          <select className="input !w-auto" value={direction} onChange={(e) => { setDirection(e.target.value); setPage(1); }} aria-label="Direction">
            <option value="">All payments</option><option value="in">Received</option><option value="out">Paid out</option>
          </select>
        </div>
        {loading && !data ? <Spinner /> : !data?.items.length ? <Empty title="No payments recorded" /> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px]">
              <thead className="bg-slate-50 dark:bg-slate-800/50"><tr><th className="th">Number</th><th className="th">Date</th><th className="th">Party</th><th className="th">Method</th><th className="th">Applied to</th><th className="th text-right">Amount</th><th className="th" /></tr></thead>
              <tbody>{data.items.map((p) => (
                <tr key={p.id} className={`border-t border-slate-100 dark:border-slate-800 ${p.voided_at ? "opacity-50" : ""}`}>
                  <td className="td font-mono text-xs">{p.number}</td><td className="td">{p.payment_date}</td>
                  <td className="td">{p.party_name} <Badge tone={p.direction === "in" ? "green" : "amber"}>{p.direction === "in" ? "received" : "paid"}</Badge></td>
                  <td className="td">{p.method.replace("_", " ")}{p.reference ? <div className="text-xs text-slate-500">{p.reference}</div> : null}</td>
                  <td className="td text-xs">
                    {p.voided_at ? <span className="text-red-600">Voided: {p.void_reason}</span> : <>
                      {p.allocations.map((a) => <div key={a.id}>{a.invoice_number}: {inr(a.amount)}</div>)}
                      {Number(p.unallocated) > 0 && <div className="text-amber-700 dark:text-amber-400">Advance: {inr(p.unallocated)}</div>}
                    </>}
                  </td>
                  <td className="td text-right font-medium">{inr(p.amount)}</td>
                  <td className="td whitespace-nowrap text-right">{can("payments.edit") && !p.voided_at && <>
                    {Number(p.unallocated) > 0 && <button className="rounded p-1.5 hover:bg-slate-200 dark:hover:bg-slate-700" title="Apply to invoices" onClick={() => setDialog(p)} aria-label="Apply advance"><Link2 size={15} /></button>}
                    <button className="rounded p-1.5 text-red-600 hover:bg-slate-200 dark:hover:bg-slate-700" title="Void" onClick={() => voidPayment(p)} aria-label="Void payment"><Ban size={15} /></button>
                  </>}</td>
                </tr>))}</tbody>
            </table>
            <Pager page={data.page} size={data.size} total={data.total} onPage={setPage} />
          </div>
        )}
      </div>
      {dialog === "new" && <Modal title="Record payment" wide onClose={() => setDialog(null)}><PaymentForm onDone={() => { setDialog(null); reload(); }} /></Modal>}
      {dialog && dialog !== "new" && <Modal title="Apply advance" wide onClose={() => setDialog(null)}><AllocateForm p={dialog} onDone={() => { setDialog(null); reload(); }} /></Modal>}
    </>
  );
}
