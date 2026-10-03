import { useState, type FormEvent } from "react";
import { Archive, Download, Pencil, Plus, RotateCcw, Upload, Wallet } from "lucide-react";
import { api, download, inr, type Page } from "../api";
import { useAuth } from "../auth";
import { AttachedDocuments } from "./Documents";
import { Badge, confirmAction, Empty, ErrorBanner, Field, Modal, PageHeader, Pager, Spinner, useAsync } from "../components/ui";

type Customer = {
  id: number; customer_type: "individual" | "business"; name: string; business_name: string | null;
  contact_person: string | null; phone: string | null; email: string | null; gstin: string | null;
  billing_address: string | null; shipping_address: string | null; city: string | null; state: string | null; state_code: string | null;
  pincode: string | null; category: string | null; notes: string | null; status: "active" | "inactive";
  created_at: string; archived_at: string | null;
};

const EMPTY: Partial<Customer> = { customer_type: "individual", status: "active", name: "" };
const FIELDS = ["name", "customer_type", "business_name", "contact_person", "phone", "email", "gstin", "billing_address",
  "shipping_address", "city", "state", "state_code", "pincode", "category", "notes", "status"];

function CustomerForm({ initial, onDone }: { initial: Partial<Customer>; onDone: () => void }) {
  const [f, setF] = useState<Partial<Customer>>(initial);
  const [error, setError] = useState<string | null>(null);
  const [dupWarning, setDupWarning] = useState(false);
  const set = (k: keyof Customer) => (e: React.ChangeEvent<any>) => setF({ ...f, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const body = Object.fromEntries(FIELDS.map((k) => [k, (f as any)[k] === "" ? null : (f as any)[k] ?? null]));
    try {
      if (f.id) await api(`/customers/${f.id}`, { method: "PUT", json: body });
      else await api(`/customers${dupWarning ? "?allow_duplicate=true" : ""}`, { method: "POST", json: body });
      onDone();
    } catch (err: any) {
      if (err.status === 409 && !f.id) setDupWarning(true);
      setError(err.message);
    }
  }

  const input = (k: keyof Customer, label: string, props: any = {}) => (
    <Field label={label}><input className="input" value={(f[k] as string) ?? ""} onChange={set(k)} {...props} /></Field>
  );
  return (
    <form onSubmit={submit}>
      <ErrorBanner message={error} />
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Type">
          <select className="input" value={f.customer_type} onChange={set("customer_type")}>
            <option value="individual">Individual</option><option value="business">Business</option>
          </select>
        </Field>
        {input("name", "Name *", { required: true })}
        {f.customer_type === "business" && <>{input("business_name", "Business name")}{input("contact_person", "Contact person")}</>}
        {input("phone", "Phone", { inputMode: "tel" })}
        {input("email", "Email", { type: "email" })}
        {input("gstin", "GSTIN", { maxLength: 15, placeholder: "e.g. 33ABCDE1234F1Z5" })}
        {input("category", "Category")}
        <Field label="Billing address" className="sm:col-span-2"><textarea className="input" rows={2} value={f.billing_address ?? ""} onChange={set("billing_address")} /></Field>
        <Field label="Shipping / installation address" className="sm:col-span-2"><textarea className="input" rows={2} value={f.shipping_address ?? ""} onChange={set("shipping_address")} /></Field>
        {input("city", "City")}
        {input("state", "State")}
        {input("state_code", "GST state code", { pattern: "\\d{2}", maxLength: 2, placeholder: "e.g. 33 (Tamil Nadu)" })}
        {input("pincode", "PIN code", { pattern: "\\d{6}", maxLength: 6 })}
        <Field label="Status">
          <select className="input" value={f.status} onChange={set("status")}><option value="active">Active</option><option value="inactive">Inactive</option></select>
        </Field>
        <Field label="Notes" className="sm:col-span-2"><textarea className="input" rows={2} value={f.notes ?? ""} onChange={set("notes")} /></Field>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" className="btn-ghost" onClick={onDone}>Cancel</button>
        <button className="btn-primary">{dupWarning ? "Save anyway" : "Save"}</button>
      </div>
    </form>
  );
}

function ImportDialog({ onDone }: { onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(commit: boolean) {
    if (!file) return;
    setBusy(true);
    setError(null);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("mapping", JSON.stringify(Object.fromEntries(Object.entries(mapping).filter(([, v]) => v))));
    fd.append("commit", String(commit));
    try {
      const r = await api("/customers/import", { method: "POST", body: fd });
      setPreview(r);
      if (!commit) setMapping(r.mapping);
      else onDone();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <ErrorBanner message={error} />
      <p className="text-sm text-slate-500">Upload a UTF-8 CSV (max 2 MB). Columns named like the fields below are matched automatically. Nothing is saved until you confirm. Rows matching an existing phone, email or GSTIN are skipped.</p>
      <input type="file" accept=".csv,text/csv" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setPreview(null); setMapping({}); }} />
      {preview && (
        <>
          <div className="grid gap-2 sm:grid-cols-2">
            {preview.headers.map((h: string) => (
              <Field key={h} label={`Column "${h}"`}>
                <select className="input" value={mapping[h] ?? ""} onChange={(e) => setMapping({ ...mapping, [h]: e.target.value })}>
                  <option value="">— ignore —</option>
                  {FIELDS.map((f) => <option key={f} value={f}>{f}</option>)}
                </select>
              </Field>
            ))}
          </div>
          <div className="flex gap-2 text-sm">
            <Badge tone="green">{preview.summary.ok} ready</Badge>
            <Badge tone="amber">{preview.summary.duplicate} duplicates</Badge>
            <Badge tone="red">{preview.summary.error} errors</Badge>
          </div>
          <div className="max-h-56 overflow-auto rounded border border-slate-200 dark:border-slate-800">
            <table className="w-full"><tbody>
              {preview.rows.filter((r: any) => r.status !== "ok").map((r: any) => (
                <tr key={r.row} className="border-b border-slate-100 dark:border-slate-800">
                  <td className="td">Row {r.row}</td>
                  <td className="td">{r.status === "error" ? r.errors.join("; ") : `Duplicate of ${r.duplicate_of}`}</td>
                </tr>
              ))}
            </tbody></table>
          </div>
        </>
      )}
      <div className="flex justify-end gap-2">
        <button className="btn-ghost" disabled={!file || busy} onClick={() => run(false)}>{preview ? "Re-check" : "Preview"}</button>
        <button className="btn-primary" disabled={!preview || busy || preview.summary.ok === 0} onClick={() => run(true)}>
          Import {preview ? preview.summary.ok : ""} customers
        </button>
      </div>
    </div>
  );
}

function Account({ c }: { c: Customer }) {
  const { data, error } = useAsync(() => api(`/customers/${c.id}/account`), [c.id]);
  if (error) return <ErrorBanner message={error} />;
  if (!data) return <Spinner />;
  const stat = (label: string, v: string, tone = "") => <div className="card !p-3"><div className="text-xs text-slate-500">{label}</div><div className={`font-semibold ${tone}`}>{inr(v)}</div></div>;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {stat("Total invoiced", data.total_invoiced)}{stat("Total paid", data.total_paid)}{stat("Credited (returns)", data.total_credited)}
        {stat("Outstanding", data.outstanding, Number(data.outstanding) ? "text-amber-600" : "")}{stat("Overdue", data.overdue, Number(data.overdue) ? "text-red-600" : "")}
        {stat("Advance (unapplied)", data.unallocated_payments, Number(data.unallocated_payments) ? "text-emerald-600" : "")}
      </div>
      <div>
        <h3 className="mb-1 font-medium">Invoices</h3>
        {!data.invoices.length ? <p className="text-sm text-slate-500">None yet.</p> : <table className="w-full text-sm"><tbody>{data.invoices.map((i: any) => (
          <tr key={i.id} className="border-t border-slate-100 dark:border-slate-800"><td className="td font-mono text-xs">{i.number ?? `draft #${i.id}`}</td><td className="td">{i.invoice_date}</td><td className="td"><Badge>{i.display_status.replace("_", " ")}</Badge></td><td className="td text-right">{inr(i.total)}</td><td className="td text-right">{Number(i.balance_due) ? inr(i.balance_due) : "—"}</td></tr>))}</tbody></table>}
      </div>
      <div>
        <h3 className="mb-1 font-medium">Payments</h3>
        {!data.payments.length ? <p className="text-sm text-slate-500">None yet.</p> : <table className="w-full text-sm"><tbody>{data.payments.map((p: any) => (
          <tr key={p.id} className={`border-t border-slate-100 dark:border-slate-800 ${p.voided_at ? "opacity-50" : ""}`}><td className="td font-mono text-xs">{p.number}</td><td className="td">{p.payment_date}</td><td className="td">{p.method}{p.voided_at ? " (void)" : ""}</td><td className="td text-right">{inr(p.amount)}</td></tr>))}</tbody></table>}
      </div>
      {!!data.quotations.length && <div><h3 className="mb-1 font-medium">Quotations</h3>{data.quotations.map((q: any) => <div key={q.id} className="text-sm">{q.number} · {q.quote_date} · {q.status} · {inr(q.total)}</div>)}</div>}
      <AttachedDocuments entityType="customer" entityId={c.id} />
    </div>
  );
}

export default function Customers() {
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [archived, setArchived] = useState(false);
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Partial<Customer> | null>(null);
  const [importing, setImporting] = useState(false);
  const [account, setAccount] = useState<Customer | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const { data, error, loading, reload } = useAsync(
    () => api<Page<Customer>>(`/customers?page=${page}&size=25&archived=${archived}&q=${encodeURIComponent(q)}`), [page, q, archived]);

  async function toggleArchive(c: Customer) {
    const verb = c.archived_at ? "restore" : "archive";
    if (!confirmAction(`${verb[0].toUpperCase() + verb.slice(1)} ${c.name}?`)) return;
    try { await api(`/customers/${c.id}/${verb}`, { method: "POST" }); reload(); }
    catch (err: any) { setActionError(err.message); }
  }

  return (
    <>
      <PageHeader title="Customers" subtitle="Individuals and businesses you sell to or service"
        actions={<>
          <button className="btn-ghost" onClick={() => download(`/customers/export.csv?archived=${archived}`, "customers.csv").catch((e) => setActionError(e.message))}><Download size={16} /> Export</button>
          {can("customers.edit") && <button className="btn-ghost" onClick={() => setImporting(true)}><Upload size={16} /> Import CSV</button>}
          {can("customers.edit") && <button className="btn-primary" onClick={() => setEditing(EMPTY)}><Plus size={16} /> Add customer</button>}
        </>} />
      <ErrorBanner message={error || actionError} />
      <div className="card !p-0">
        <div className="flex flex-wrap gap-2 border-b border-slate-200 p-3 dark:border-slate-800">
          <input className="input max-w-xs" placeholder="Search name, phone, email, GSTIN…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
          <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
            <input type="checkbox" checked={archived} onChange={(e) => { setArchived(e.target.checked); setPage(1); }} /> Show archived
          </label>
        </div>
        {loading && !data ? <Spinner /> : data && data.items.length === 0 ? (
          <Empty title={q ? "No customers match your search" : "No customers yet"} hint={q ? undefined : "Add your first customer or import a CSV."} />
        ) : data && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px]">
              <thead className="bg-slate-50 dark:bg-slate-800/50"><tr>
                <th className="th">Name</th><th className="th">Phone</th><th className="th">Email</th><th className="th">City</th><th className="th">GSTIN</th><th className="th">Status</th><th className="th"></th>
              </tr></thead>
              <tbody>
                {data.items.map((c) => (
                  <tr key={c.id} className="border-t border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/40">
                    <td className="td"><div className="font-medium">{c.name}</div>{c.business_name && <div className="text-xs text-slate-500">{c.business_name}</div>}</td>
                    <td className="td">{c.phone}</td><td className="td">{c.email}</td><td className="td">{c.city}</td>
                    <td className="td font-mono text-xs">{c.gstin}</td>
                    <td className="td"><Badge tone={c.archived_at ? "slate" : c.status === "active" ? "green" : "amber"}>{c.archived_at ? "archived" : c.status}</Badge></td>
                    <td className="td whitespace-nowrap text-right">
                      {can("sales.view") && <button className="rounded p-1.5 hover:bg-slate-200 dark:hover:bg-slate-700" onClick={() => setAccount(c)} aria-label="Account" title="Account"><Wallet size={15} /></button>}
                      {can("customers.edit") && <>
                        {!c.archived_at && <button className="rounded p-1.5 hover:bg-slate-200 dark:hover:bg-slate-700" onClick={() => setEditing(c)} aria-label="Edit"><Pencil size={15} /></button>}
                        <button className="rounded p-1.5 hover:bg-slate-200 dark:hover:bg-slate-700" onClick={() => toggleArchive(c)} aria-label={c.archived_at ? "Restore" : "Archive"}>
                          {c.archived_at ? <RotateCcw size={15} /> : <Archive size={15} />}
                        </button>
                      </>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager page={data.page} size={data.size} total={data.total} onPage={setPage} />
          </div>
        )}
      </div>
      {editing && <Modal title={editing.id ? "Edit customer" : "Add customer"} onClose={() => setEditing(null)} wide>
        <CustomerForm initial={editing} onDone={() => { setEditing(null); reload(); }} />
      </Modal>}
      {account && <Modal title={`${account.name}: account`} onClose={() => setAccount(null)} wide><Account c={account} /></Modal>}
      {importing && <Modal title="Import customers from CSV" onClose={() => setImporting(false)} wide>
        <ImportDialog onDone={() => { setImporting(false); reload(); }} />
      </Modal>}
    </>
  );
}
