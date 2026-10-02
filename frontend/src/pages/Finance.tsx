import { useState, type FormEvent } from "react";
import { Ban, Landmark, Plus, Wallet } from "lucide-react";
import { api, inr, type Page } from "../api";
import { useAuth } from "../auth";
import { today, useLocations, useSuppliers } from "../components/trade";
import { Badge, Empty, ErrorBanner, Field, Modal, PageHeader, Pager, Spinner, useAsync } from "../components/ui";
import { ReportView } from "./Reports";

type Account = { id: number; name: string; kind: string; opening_balance: string; is_default: boolean; is_active: boolean };
type Category = { id: number; kind: "expense" | "income"; name: string };
type Entry = { id: number; number: string; kind: string; entry_date: string; amount: string; tax_amount: string; category_name: string | null; account_name: string; to_account_name: string | null; payee: string | null; method: string; reference: string | null; notes: string | null; voided_at: string | null; void_reason: string | null };

const METHODS = [["cash", "Cash"], ["upi", "UPI"], ["bank_transfer", "Bank transfer"], ["card", "Card"], ["cheque", "Cheque"], ["other", "Other"]];
const KIND_LABEL: Record<string, string> = { expense: "Expense", income: "Other income", transfer: "Transfer" };

export function AccountSelect({ label, value, onChange, accounts, optional }: { label: string; value: string; onChange: (v: string) => void; accounts: Account[]; optional?: string }) {
  return (
    <Field label={label}>
      <select className="input" value={value} required={!optional} onChange={(e) => onChange(e.target.value)}>
        <option value="">{optional ?? "Select…"}</option>
        {accounts.filter((a) => a.is_active).map((a) => <option key={a.id} value={a.id}>{a.name}{a.is_default ? " (default)" : ""}</option>)}
      </select>
    </Field>
  );
}

function EntryForm({ kind, onDone }: { kind: "expense" | "income" | "transfer"; onDone: () => void }) {
  const cats = useAsync(() => api<Category[]>(`/finance-categories?kind=${kind === "transfer" ? "expense" : kind}`), [kind]);
  const accounts = useAsync(() => api<Account[]>("/accounts"), []);
  const suppliers = useSuppliers();
  const locations = useLocations();
  const [f, setF] = useState<any>({ entry_date: today(), amount: "", tax_amount: "", category_id: "", account_id: "", to_account_id: "", method: kind === "transfer" ? "bank_transfer" : "cash", supplier_id: "", location_id: "", payee: "", reference: "", notes: "" });
  const [error, setError] = useState<string | null>(null);
  const [idem] = useState(() => crypto.randomUUID());
  const set = (k: string) => (e: React.ChangeEvent<any>) => setF({ ...f, [k]: e.target.value });
  async function submit(e: FormEvent) {
    e.preventDefault();
    const n = (v: string) => (v ? Number(v) : null);
    const body = { kind, entry_date: f.entry_date, amount: f.amount, tax_amount: f.tax_amount || "0", method: f.method, idempotency_key: idem,
      category_id: kind === "transfer" ? null : n(f.category_id), account_id: n(f.account_id), to_account_id: kind === "transfer" ? n(f.to_account_id) : null,
      supplier_id: n(f.supplier_id), location_id: n(f.location_id), payee: f.payee || null, reference: f.reference || null, notes: f.notes || null };
    try { await api("/finance-entries", { method: "POST", json: body }); onDone(); } catch (err: any) { setError(err.message); }
  }
  const accs = accounts.data ?? [];
  return (
    <form onSubmit={submit} className="space-y-3">
      <ErrorBanner message={error} />
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Date"><input className="input" type="date" required value={f.entry_date} onChange={set("entry_date")} /></Field>
        <Field label="Amount ₹ *"><input className="input" type="number" step="0.01" min="0.01" required value={f.amount} onChange={set("amount")} /></Field>
        {kind !== "transfer" && <Field label="Category *"><select className="input" required value={f.category_id} onChange={set("category_id")}>
          <option value="">Select…</option>{cats.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>}
        {kind === "transfer" ? <>
          <AccountSelect label="From account *" value={f.account_id} onChange={(v) => setF({ ...f, account_id: v })} accounts={accs} />
          <AccountSelect label="To account *" value={f.to_account_id} onChange={(v) => setF({ ...f, to_account_id: v })} accounts={accs} />
        </> : <>
          <Field label="Method"><select className="input" value={f.method} onChange={set("method")}>{METHODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
          <AccountSelect label={kind === "expense" ? "Paid from" : "Received into"} value={f.account_id} onChange={(v) => setF({ ...f, account_id: v })} accounts={accs} optional="Default for method" />
        </>}
        {kind === "expense" && <>
          <Field label="GST on the bill you can claim (if any) ₹"><input className="input" type="number" step="0.01" min="0" value={f.tax_amount} onChange={set("tax_amount")} placeholder="0" /></Field>
          <Field label="Supplier (optional)"><select className="input" value={f.supplier_id} onChange={set("supplier_id")}><option value="">—</option>{suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>
          <Field label="Paid to (if not a supplier)"><input className="input" value={f.payee} onChange={set("payee")} placeholder="e.g. Landlord, TNEB" /></Field>
          <Field label="Location (optional)"><select className="input" value={f.location_id} onChange={set("location_id")}><option value="">—</option>{locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></Field>
        </>}
        {kind === "income" && <Field label="Received from"><input className="input" value={f.payee} onChange={set("payee")} /></Field>}
        <Field label="Reference"><input className="input" value={f.reference} onChange={set("reference")} placeholder="Bill no., UTR, cheque no." /></Field>
        <Field label="Notes" className="sm:col-span-3"><input className="input" value={f.notes} onChange={set("notes")} /></Field>
      </div>
      {kind === "expense" && <p className="text-xs text-slate-500">Leave GST at 0 unless your accountant confirms you can claim input credit on this bill. Claimable GST is left out of expenses in the profit and loss summary.</p>}
      <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={onDone}>Cancel</button><button className="btn-primary">Save</button></div>
    </form>
  );
}

export function Expenses() {
  const { can } = useAuth();
  const [kind, setKind] = useState("");
  const [page, setPage] = useState(1);
  const [dialog, setDialog] = useState<"expense" | "income" | "transfer" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const { data, error, loading, reload } = useAsync(() => api<Page<Entry>>(`/finance-entries?page=${page}${kind ? `&kind=${kind}` : ""}`), [page, kind]);
  async function voidEntry(e: Entry) {
    const reason = window.prompt(`Void ${e.number} (${inr(e.amount)})? It stays on record but is excluded from reports. Reason:`);
    if (!reason || reason.trim().length < 3) return;
    try { await api(`/finance-entries/${e.id}/void`, { method: "POST", json: { reason } }); reload(); } catch (x: any) { setErr(x.message); }
  }
  return (
    <>
      <PageHeader title="Expenses and income" subtitle="Running costs, other income, and money moved between your accounts"
        actions={<>
          {can("finance.manage") && <button className="btn-ghost" onClick={() => setDialog("transfer")}>Transfer</button>}
          {can("finance.manage") && <button className="btn-ghost" onClick={() => setDialog("income")}>Other income</button>}
          {can("expenses.edit") && <button className="btn-primary" onClick={() => setDialog("expense")}><Plus size={16} /> Record expense</button>}
        </>} />
      <ErrorBanner message={error || err} />
      <div className="card !p-0">
        <div className="border-b border-slate-200 p-3 dark:border-slate-800">
          <select className="input !w-auto" value={kind} onChange={(e) => { setKind(e.target.value); setPage(1); }} aria-label="Type">
            <option value="">All entries</option><option value="expense">Expenses</option><option value="income">Other income</option><option value="transfer">Transfers</option>
          </select>
        </div>
        {loading && !data ? <Spinner /> : !data?.items.length ? <Empty title="Nothing recorded yet" hint="Record rent, electricity, salaries and other running costs here." /> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px]">
              <thead className="bg-slate-50 dark:bg-slate-800/50"><tr><th className="th">Number</th><th className="th">Date</th><th className="th">Type</th><th className="th">Category / details</th><th className="th">Account</th><th className="th text-right">Amount</th><th className="th" /></tr></thead>
              <tbody>{data.items.map((e) => (
                <tr key={e.id} className={`border-t border-slate-100 dark:border-slate-800 ${e.voided_at ? "opacity-50" : ""}`}>
                  <td className="td font-mono text-xs">{e.number}</td><td className="td">{e.entry_date}</td>
                  <td className="td"><Badge tone={e.kind === "expense" ? "amber" : e.kind === "income" ? "green" : "slate"}>{KIND_LABEL[e.kind]}</Badge></td>
                  <td className="td">{e.category_name}{e.payee ? <span className="text-slate-500"> · {e.payee}</span> : null}
                    {e.voided_at && <div className="text-xs text-red-600">Voided: {e.void_reason}</div>}
                    {Number(e.tax_amount) > 0 && <div className="text-xs text-slate-500">incl. claimable GST {inr(e.tax_amount)}</div>}</td>
                  <td className="td text-sm">{e.kind === "transfer" ? `${e.account_name} → ${e.to_account_name}` : e.account_name}</td>
                  <td className={`td text-right font-medium ${e.kind === "expense" ? "text-red-600" : e.kind === "income" ? "text-emerald-600" : ""}`}>{inr(e.amount)}</td>
                  <td className="td text-right">{!e.voided_at && (e.kind === "expense" ? can("expenses.edit") : can("finance.manage")) &&
                    <button className="rounded p-1.5 text-red-600 hover:bg-slate-200 dark:hover:bg-slate-700" onClick={() => voidEntry(e)} title="Void" aria-label="Void entry"><Ban size={15} /></button>}</td>
                </tr>))}</tbody>
            </table>
            <Pager page={data.page} size={data.size} total={data.total} onPage={setPage} />
          </div>
        )}
      </div>
      {dialog && <Modal title={dialog === "expense" ? "Record expense" : dialog === "income" ? "Record other income" : "Transfer between accounts"} wide onClose={() => setDialog(null)}>
        <EntryForm kind={dialog} onDone={() => { setDialog(null); reload(); }} />
      </Modal>}
    </>
  );
}

function AccountForm({ onDone }: { onDone: () => void }) {
  const [f, setF] = useState({ name: "", kind: "bank", opening_balance: "0", opening_date: today(), is_default: false });
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    try { await api("/accounts", { method: "POST", json: f }); onDone(); } catch (err: any) { setError(err.message); }
  }
  return (
    <form onSubmit={submit} className="space-y-3">
      <ErrorBanner message={error} />
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name *"><input className="input" required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="e.g. HDFC Current A/c" /></Field>
        <Field label="Type"><select className="input" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}><option value="bank">Bank</option><option value="cash">Cash</option><option value="other">Other</option></select></Field>
        <Field label="Opening balance ₹"><input className="input" type="number" step="0.01" value={f.opening_balance} onChange={(e) => setF({ ...f, opening_balance: e.target.value })} /></Field>
        <Field label="As of"><input className="input" type="date" value={f.opening_date} onChange={(e) => setF({ ...f, opening_date: e.target.value })} /></Field>
      </div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.is_default} onChange={(e) => setF({ ...f, is_default: e.target.checked })} /> Use as the default {f.kind} account for payments</label>
      <p className="text-xs text-slate-500">The opening balance can't be changed later. Correct mistakes with an income or expense entry.</p>
      <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={onDone}>Cancel</button><button className="btn-primary">Add account</button></div>
    </form>
  );
}

export function Finance() {
  const { can } = useAuth();
  const now = new Date();
  const d0 = new Date(now.getFullYear(), now.getMonth(), 1).toLocaleDateString("en-CA");
  const d1 = now.toLocaleDateString("en-CA");
  const cash = useAsync(() => api<any>(`/reports/cash-flow?date_from=${d0}&date_to=${d1}`), []);
  const pl = useAsync(() => api<any>(`/reports/profit-loss?date_from=${d0}&date_to=${d1}`), []);
  const [adding, setAdding] = useState(false);
  return (
    <>
      <PageHeader title="Finance" subtitle="Account balances and this month's summary"
        actions={can("finance.manage") && <button className="btn-primary" onClick={() => setAdding(true)}><Plus size={16} /> Add account</button>} />
      <ErrorBanner message={cash.error || pl.error} />
      {!cash.data ? <Spinner /> : (
        <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {cash.data.rows.map((a: any) => (
            <div key={a.account} className="card">
              <div className="flex items-center gap-2 text-sm text-slate-500">{a.kind === "cash" ? <Wallet size={16} /> : <Landmark size={16} />} {a.account}</div>
              <div className="mt-1 text-xl font-semibold">{inr(a.closing)}</div>
              <div className="text-xs text-slate-500">This month: <span className="text-emerald-600">+{inr(a.in)}</span> <span className="text-red-600">−{inr(a.out)}</span></div>
            </div>
          ))}
          {!cash.data.rows.length && <div className="card sm:col-span-2"><Empty title="No accounts yet" hint="A cash and a bank account are created automatically when you record your first payment, or add yours now." /></div>}
        </div>
      )}
      <div className="card">
        <h3 className="mb-1 font-medium">Profit and loss this month</h3>
        {pl.data ? <ReportView r={pl.data} /> : <Spinner />}
      </div>
      {adding && <Modal title="Add account" onClose={() => setAdding(false)}><AccountForm onDone={() => { setAdding(false); cash.reload(); }} /></Modal>}
    </>
  );
}
