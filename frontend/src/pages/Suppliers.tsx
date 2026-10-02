import { useState, type FormEvent } from "react";
import { Archive, Pencil, Plus, RotateCcw } from "lucide-react";
import { api, inr, type Page } from "../api";
import { useAuth } from "../auth";
import { confirmAction, Empty, ErrorBanner, Field, Modal, PageHeader, Pager, Spinner, useAsync } from "../components/ui";

type Supplier = {
  id: number; name: string; contact_person: string | null; phone: string | null; email: string | null; gstin: string | null;
  state_code: string | null; address: string | null; payment_terms_days: number | null; notes: string | null;
  archived_at: string | null; balance_due: string;
};
const KEYS = ["name", "contact_person", "phone", "email", "gstin", "state_code", "address", "payment_terms_days", "notes"] as const;

function SupplierForm({ initial, onDone }: { initial: Partial<Supplier>; onDone: () => void }) {
  const [f, setF] = useState<any>(initial);
  const [error, setError] = useState<string | null>(null);
  const set = (k: string) => (e: React.ChangeEvent<any>) => setF({ ...f, [k]: e.target.value });
  async function submit(e: FormEvent) {
    e.preventDefault();
    const body: any = Object.fromEntries(KEYS.map((k) => [k, f[k] === "" || f[k] === undefined ? null : f[k]]));
    if (body.payment_terms_days !== null) body.payment_terms_days = Number(body.payment_terms_days);
    try {
      await api(f.id ? `/suppliers/${f.id}` : "/suppliers", { method: f.id ? "PUT" : "POST", json: body });
      onDone();
    } catch (err: any) { setError(err.message); }
  }
  const input = (k: string, label: string, props: any = {}) => <Field label={label}><input className="input" value={f[k] ?? ""} onChange={set(k)} {...props} /></Field>;
  return (
    <form onSubmit={submit}>
      <ErrorBanner message={error} />
      <div className="grid gap-3 sm:grid-cols-2">
        {input("name", "Name *", { required: true })}{input("contact_person", "Contact person")}
        {input("phone", "Phone")}{input("email", "Email", { type: "email" })}
        {input("gstin", "GSTIN", { maxLength: 15 })}{input("state_code", "GST state code", { pattern: "\\d{2}", maxLength: 2, placeholder: "e.g. 33" })}
        {input("payment_terms_days", "Payment terms (days)", { type: "number", min: 0, max: 365 })}
        <Field label="Address" className="sm:col-span-2"><textarea className="input" rows={2} value={f.address ?? ""} onChange={set("address")} /></Field>
        <Field label="Notes" className="sm:col-span-2"><textarea className="input" rows={2} value={f.notes ?? ""} onChange={set("notes")} /></Field>
      </div>
      <div className="mt-4 flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={onDone}>Cancel</button><button className="btn-primary">Save</button></div>
    </form>
  );
}

export default function Suppliers() {
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [archived, setArchived] = useState(false);
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Partial<Supplier> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const { data, error, loading, reload } = useAsync(() => api<Page<Supplier>>(`/suppliers?page=${page}&archived=${archived}&q=${encodeURIComponent(q)}`), [page, q, archived]);

  async function toggle(s: Supplier) {
    const verb = s.archived_at ? "restore" : "archive";
    if (!confirmAction(`${verb === "archive" ? "Archive" : "Restore"} ${s.name}?`)) return;
    try { await api(`/suppliers/${s.id}/${verb}`, { method: "POST" }); reload(); } catch (e: any) { setErr(e.message); }
  }
  return (
    <>
      <PageHeader title="Suppliers" subtitle="Who you buy from, and what you owe them"
        actions={can("suppliers.edit") && <button className="btn-primary" onClick={() => setEditing({})}><Plus size={16} /> Add supplier</button>} />
      <ErrorBanner message={error || err} />
      <div className="card !p-0">
        <div className="flex flex-wrap gap-2 border-b border-slate-200 p-3 dark:border-slate-800">
          <input className="input max-w-xs" placeholder="Search name, phone, GSTIN…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> Archived</label>
        </div>
        {loading && !data ? <Spinner /> : !data?.items.length ? <Empty title="No suppliers yet" hint="Add the distributors you buy stock from." /> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px]">
              <thead className="bg-slate-50 dark:bg-slate-800/50"><tr><th className="th">Name</th><th className="th">Phone</th><th className="th">GSTIN</th><th className="th">Terms</th><th className="th text-right">You owe</th><th className="th" /></tr></thead>
              <tbody>{data.items.map((s) => (
                <tr key={s.id} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="td"><div className="font-medium">{s.name}</div><div className="text-xs text-slate-500">{s.contact_person}</div></td>
                  <td className="td">{s.phone}</td><td className="td font-mono text-xs">{s.gstin}</td>
                  <td className="td">{s.payment_terms_days != null ? `${s.payment_terms_days} days` : "—"}</td>
                  <td className={`td text-right ${Number(s.balance_due) > 0 ? "font-medium text-amber-700 dark:text-amber-400" : ""}`}>{inr(s.balance_due)}</td>
                  <td className="td whitespace-nowrap text-right">{can("suppliers.edit") && <>
                    {!s.archived_at && <button className="rounded p-1.5 hover:bg-slate-200 dark:hover:bg-slate-700" onClick={() => setEditing(s)} aria-label="Edit"><Pencil size={15} /></button>}
                    <button className="rounded p-1.5 hover:bg-slate-200 dark:hover:bg-slate-700" onClick={() => toggle(s)} aria-label={s.archived_at ? "Restore" : "Archive"}>{s.archived_at ? <RotateCcw size={15} /> : <Archive size={15} />}</button>
                  </>}</td>
                </tr>))}</tbody>
            </table>
            <Pager page={data.page} size={data.size} total={data.total} onPage={setPage} />
          </div>
        )}
      </div>
      {editing && <Modal title={editing.id ? "Edit supplier" : "Add supplier"} onClose={() => setEditing(null)} wide><SupplierForm initial={editing} onDone={() => { setEditing(null); reload(); }} /></Modal>}
    </>
  );
}
