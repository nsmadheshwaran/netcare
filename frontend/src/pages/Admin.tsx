import { useState, type FormEvent } from "react";
import { Plus } from "lucide-react";
import { api, type Page } from "../api";
import { useAuth } from "../auth";
import { ModuleSwitches } from "../components/Setup";
import { Badge, Empty, ErrorBanner, Field, Modal, PageHeader, Pager, Spinner, useAsync } from "../components/ui";

const ROLES = ["owner", "manager", "accountant", "salesperson", "inventory_manager", "technician", "receptionist", "viewer"];
type Member = { id: number; email: string; full_name: string; role: string; is_active: boolean };

export function Users() {
  const { me } = useAuth();
  const { data, error, loading, reload } = useAsync(() => api<Member[]>("/organization/members"), []);
  const [adding, setAdding] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [f, setF] = useState({ email: "", full_name: "", role: "salesperson", temporary_password: "" });
  const emailEnabled = useAsync(() => api<{ email_enabled: boolean }>("/auth/config"), []).data?.email_enabled ?? false;

  async function update(m: Member, body: Partial<Member>) {
    setActionError(null);
    try { await api(`/organization/members/${m.id}`, { method: "PATCH", json: body }); reload(); }
    catch (err: any) { setActionError(err.message); }
  }
  async function sendInvite(m: Member) {
    setActionError(null);
    try { const r = await api<{ sent_to: string }>(`/organization/members/${m.id}/send-invite`, { method: "POST" }); window.alert(`Link emailed to ${r.sent_to}.`); }
    catch (err: any) { setActionError(err.message); }
  }
  async function resetPassword(m: Member) {
    setActionError(null);
    const pw = window.prompt(`New temporary password for ${m.full_name} (at least 10 characters). Tell it to them in person; they should change it after signing in.`);
    if (!pw) return;
    try { await api(`/organization/members/${m.id}/reset-password`, { method: "POST", json: { temporary_password: pw } }); window.alert("Password reset. They have been signed out everywhere."); }
    catch (err: any) { setActionError(err.message); }
  }
  async function add(e: FormEvent) {
    e.preventDefault();
    setActionError(null);
    try { await api("/organization/members", { method: "POST", json: { ...f, temporary_password: f.temporary_password || null } }); setAdding(false); reload(); }
    catch (err: any) { setActionError(err.message); }
  }

  return (
    <>
      <PageHeader title="Users and roles" subtitle="People who can sign in to this business"
        actions={<button className="btn-primary" onClick={() => setAdding(true)}><Plus size={16} /> Add user</button>} />
      <ErrorBanner message={error || (adding ? null : actionError)} />
      <div className="card !p-0 overflow-x-auto">
        {loading && !data ? <Spinner /> : (
          <table className="w-full min-w-[600px]">
            <thead className="bg-slate-50 dark:bg-slate-800/50"><tr><th className="th">Name</th><th className="th">Email</th><th className="th">Role</th><th className="th">Status</th></tr></thead>
            <tbody>{data?.map((m) => (
              <tr key={m.id} className="border-t border-slate-100 dark:border-slate-800">
                <td className="td">{m.full_name}</td><td className="td">{m.email}</td>
                <td className="td">
                  <select className="input !w-auto !py-1" value={m.role} disabled={m.email === me?.user.email} onChange={(e) => update(m, { role: e.target.value })} aria-label="Role">
                    {ROLES.map((r) => <option key={r} value={r}>{r.replace("_", " ")}</option>)}
                  </select>
                </td>
                <td className="td">
                  {m.email === me?.user.email ? <Badge tone="indigo">you</Badge> : (
                    <span className="flex gap-1">
                      <button className="btn-ghost !py-1 text-xs" onClick={() => update(m, { is_active: !m.is_active })}>{m.is_active ? "Deactivate" : "Reactivate"}</button>
                      {emailEnabled && <button className="btn-ghost !py-1 text-xs" title="Email a link to choose a password" onClick={() => sendInvite(m)}>Email link</button>}
                      <button className="btn-ghost !py-1 text-xs" onClick={() => resetPassword(m)}>Reset password</button>
                    </span>
                  )}
                </td>
              </tr>))}</tbody>
          </table>
        )}
      </div>
      {adding && <Modal title="Add user" onClose={() => setAdding(false)}>
        <form onSubmit={add} className="space-y-3">
          <ErrorBanner message={actionError} />
          <Field label="Full name"><input className="input" required value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
          <Field label="Email"><input className="input" type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
          <Field label="Role"><select className="input" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>{ROLES.map((r) => <option key={r} value={r}>{r.replace("_", " ")}</option>)}</select></Field>
          <Field label={emailEnabled ? "Temporary password (optional)" : "Temporary password (min 10 characters)"}><input className="input" type="password" required={!emailEnabled} minLength={10} autoComplete="new-password" value={f.temporary_password} onChange={(e) => setF({ ...f, temporary_password: e.target.value })} /></Field>
          <p className="text-xs text-slate-500">{emailEnabled
            ? "Leave the password empty to email them an invitation link to choose their own. "
            : "Share the temporary password privately; ask the user to change it after first sign-in. "}
            If the email already has an account, their existing password is kept.</p>
          <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={() => setAdding(false)}>Cancel</button><button className="btn-primary">Add</button></div>
        </form>
      </Modal>}
    </>
  );
}

export function Audit() {
  const [page, setPage] = useState(1);
  const { data, error, loading } = useAsync(() => api<Page<any>>(`/audit-logs?page=${page}&size=50`), [page]);
  return (
    <>
      <PageHeader title="Audit log" subtitle="Who changed what, and when" />
      <ErrorBanner message={error} />
      <div className="card !p-0 overflow-x-auto">
        {loading && !data ? <Spinner /> : !data?.items.length ? <Empty title="No audit entries" /> : (
          <>
            <table className="w-full min-w-[640px]">
              <thead className="bg-slate-50 dark:bg-slate-800/50"><tr><th className="th">When</th><th className="th">User</th><th className="th">Action</th><th className="th">Entity</th><th className="th">Details</th></tr></thead>
              <tbody>{data.items.map((a) => (
                <tr key={a.id} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="td whitespace-nowrap text-xs">{new Date(a.created_at).toLocaleString("en-IN")}</td>
                  <td className="td">#{a.user_id}</td><td className="td">{a.action}</td><td className="td">{a.entity_type}{a.entity_id ? ` #${a.entity_id}` : ""}</td>
                  <td className="td max-w-xs truncate font-mono text-xs text-slate-500">{a.details ? JSON.stringify(a.details) : ""}</td>
                </tr>))}</tbody>
            </table>
            <Pager page={data.page} size={data.size} total={data.total} onPage={setPage} />
          </>
        )}
      </div>
    </>
  );
}

function LogoCard({ hasLogo, onChange }: { hasLogo: boolean; onChange: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const [v, setV] = useState(0);
  const logo = useAsync(() => hasLogo ? api<Blob>("/organization/logo").then((b) => URL.createObjectURL(b)) : Promise.resolve(null), [hasLogo, v]);
  async function upload(file: File) {
    setError(null);
    const fd = new FormData();
    fd.append("file", file);
    try { await api("/organization/logo", { method: "POST", body: fd }); setV(v + 1); onChange(); } catch (e: any) { setError(e.message); }
  }
  async function remove() {
    try { await api("/organization/logo", { method: "DELETE" }); onChange(); } catch (e: any) { setError(e.message); }
  }
  return (
    <div className="card">
      <h3 className="mb-3 font-medium">Logo on invoices</h3>
      <ErrorBanner message={error} />
      <div className="flex items-center gap-4">
        <div className="flex h-16 w-32 items-center justify-center rounded border border-dashed border-slate-300 dark:border-slate-700">
          {logo.data ? <img src={logo.data} alt="Business logo" className="max-h-14 max-w-28 object-contain" /> : <span className="text-xs text-slate-400">No logo</span>}
        </div>
        <div className="space-y-2 text-sm">
          <input type="file" accept="image/png,image/jpeg" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} aria-label="Upload logo" />
          <div className="text-xs text-slate-500">PNG or JPEG, up to 300 KB.</div>
          {hasLogo && <button className="text-xs text-red-600 hover:underline" onClick={remove}>Remove logo</button>}
        </div>
      </div>
    </div>
  );
}

type Rate = { id: number; name: string; rate: string; effective_from: string; effective_to: string | null; active: boolean; notes: string | null };

function TaxRatesCard({ editable }: { editable: boolean }) {
  const [history, setHistory] = useState(false);
  const rates = useAsync(() => api<Rate[]>(`/tax-rates?include_history=${history}`), [history]);
  const [f, setF] = useState({ name: "", rate: "", effective_from: new Date().toLocaleDateString("en-CA"), notes: "" });
  const [error, setError] = useState<string | null>(null);
  async function add(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try { await api("/tax-rates", { method: "POST", json: { ...f, notes: f.notes || null } }); setF({ ...f, name: "", rate: "", notes: "" }); rates.reload(); }
    catch (err: any) { setError(err.message); }
  }
  async function retire(r: Rate) {
    const effective_to = window.prompt(`Last day ${r.name} applies (YYYY-MM-DD):`, new Date().toLocaleDateString("en-CA"));
    if (!effective_to) return;
    const reason = window.prompt("Reason (e.g. notification number):");
    if (!reason || reason.length < 3) return;
    try { await api(`/tax-rates/${r.id}/retire`, { method: "POST", json: { effective_to, reason } }); rates.reload(); } catch (e: any) { setError(e.message); }
  }
  return (
    <div className="card">
      <div className="mb-2 flex items-center justify-between"><h3 className="font-medium">GST rates</h3>
        <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={history} onChange={(e) => setHistory(e.target.checked)} /> Show retired</label></div>
      <p className="mb-3 text-xs text-slate-500">Add only rates your accountant has confirmed. Once any rate is listed, documents may use only rates in effect on their date. Rates are never edited: retire the old one and add the new one, so past invoices stay explainable.</p>
      <ErrorBanner message={error || rates.error} />
      {!rates.data?.length ? <p className="mb-3 text-sm text-amber-700 dark:text-amber-400">No rates configured. Any rate can be used on documents.</p> : (
        <table className="mb-3 w-full text-sm"><tbody>{rates.data.map((r) => (
          <tr key={r.id} className="border-t border-slate-100 dark:border-slate-800">
            <td className="td">{r.name}</td><td className="td text-right">{Number(r.rate)}%</td>
            <td className="td text-xs text-slate-500">from {r.effective_from}{r.effective_to ? ` to ${r.effective_to}` : ""}</td>
            <td className="td">{r.active ? <Badge tone="green">in effect</Badge> : <Badge>{r.effective_to ? "retired" : "future"}</Badge>}</td>
            <td className="td text-right">{editable && !r.effective_to && <button className="text-xs text-red-600 hover:underline" onClick={() => retire(r)}>Retire</button>}</td>
          </tr>))}</tbody></table>
      )}
      {editable && <form onSubmit={add} className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <input className="input" required placeholder="Name, e.g. GST 18%" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} aria-label="Rate name" />
        <input className="input" required type="number" step="0.01" min="0" max="100" placeholder="Rate %" value={f.rate} onChange={(e) => setF({ ...f, rate: e.target.value })} aria-label="Rate percent" />
        <input className="input" required type="date" value={f.effective_from} onChange={(e) => setF({ ...f, effective_from: e.target.value })} aria-label="Effective from" />
        <button className="btn-ghost justify-center">Add rate</button>
      </form>}
    </div>
  );
}

export function Settings() {
  const { can, refresh } = useAuth();
  const org = useAsync(() => api("/organization"), []);
  const locations = useAsync(() => api<{ id: number; name: string; address: string | null }[]>("/organization/locations"), []);
  const [f, setF] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loc, setLoc] = useState("");
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const form = f ?? org.data;
  const editable = can("org.manage");

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null); setMsg(null);
    // Modules are saved by their own switches; sending the copy loaded with this form could undo a change.
    const { id: _id, currency: _c, has_logo: _l, enabled_modules: _m, ...body } = form;
    for (const k of Object.keys(body)) if (body[k] === "") body[k] = null;
    try { await api("/organization", { method: "PUT", json: body }); setMsg("Saved."); refresh(); }
    catch (err: any) { setError(err.message); }
  }
  async function addLoc() {
    setError(null);
    try { await api("/organization/locations", { method: "POST", json: { name: loc } }); setLoc(""); locations.reload(); }
    catch (err: any) { setError(err.message); }
  }
  async function changePw(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try { await api("/auth/change-password", { method: "POST", json: pw }); window.location.assign("/login"); }
    catch (err: any) { setError(err.message); }
  }

  if (!form) return <Spinner />;
  const input = (k: string, label: string, props: any = {}) => (
    <Field label={label}><input className="input" disabled={!editable} value={form[k] ?? ""} onChange={(e) => setF({ ...form, [k]: e.target.value })} {...props} /></Field>
  );
  return (
    <>
      <PageHeader title="Settings" />
      <ErrorBanner message={error} />
      {msg && <div className="mb-3 text-sm text-emerald-600">{msg}</div>}
      <div className="mb-4"><ModuleSwitches /></div>
      <div className="grid gap-4 lg:grid-cols-2">
        <form className="card space-y-3" onSubmit={save}>
          <h3 className="font-medium">Business details</h3>
          {input("name", "Business name", { required: true })}
          {input("legal_name", "Legal name")}
          <div className="grid gap-3 sm:grid-cols-2">{input("gstin", "GSTIN", { maxLength: 15 })}{input("state_code", "GST state code", { pattern: "\\d{2}", maxLength: 2, placeholder: "e.g. 33" })}</div>
          <div className="grid gap-3 sm:grid-cols-2">{input("phone", "Phone")}{input("email", "Email", { type: "email" })}</div>
          <Field label="Address"><textarea className="input" rows={2} disabled={!editable} value={form.address ?? ""} onChange={(e) => setF({ ...form, address: e.target.value })} /></Field>
          <h3 className="pt-2 font-medium">Invoicing</h3>
          <Field label="Default terms and conditions"><textarea className="input" rows={2} disabled={!editable} value={form.invoice_terms ?? ""} onChange={(e) => setF({ ...form, invoice_terms: e.target.value })} /></Field>
          <Field label="Payment instructions (bank / UPI details)"><textarea className="input" rows={2} disabled={!editable} value={form.payment_instructions ?? ""} onChange={(e) => setF({ ...form, payment_instructions: e.target.value })} /></Field>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={!editable} checked={!!form.round_invoices_to_rupee} onChange={(e) => setF({ ...form, round_invoices_to_rupee: e.target.checked })} /> Round invoice totals to the nearest rupee</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={!editable} checked={!!form.prices_include_tax_default} onChange={(e) => setF({ ...form, prices_include_tax_default: e.target.checked })} /> Prices I enter include GST (MRP-style). Can be changed per invoice.</label>
          <div className="grid gap-3 sm:grid-cols-3">
            {[["sales_invoice", "Invoice prefix", "INV"], ["quotation", "Quotation prefix", "QT"], ["purchase_order", "PO prefix", "PO"]].map(([k, label, def]) => (
              <Field key={k} label={label}><input className="input" disabled={!editable} maxLength={12} pattern="[A-Za-z0-9-]+" placeholder={def}
                value={form.numbering_prefixes?.[k] ?? ""} onChange={(e) => {
                  const p = { ...(form.numbering_prefixes ?? {}) };
                  if (e.target.value) p[k] = e.target.value; else delete p[k];
                  setF({ ...form, numbering_prefixes: Object.keys(p).length ? p : null });
                }} /></Field>
            ))}
          </div>
          <p className="text-xs text-slate-500">Numbers look like INV/2026-27/00001 and restart every financial year (1 April). A new prefix applies from the next sequence started, so set it before your first invoice.</p>
          {editable && <button className="btn-primary">Save</button>}
        </form>
        <div className="space-y-4">
          <LogoCard hasLogo={!!form.has_logo} onChange={() => { setF(null); org.reload(); }} />
          <TaxRatesCard editable={editable} />
          <div className="card">
            <h3 className="mb-3 font-medium">Locations / warehouses</h3>
            <ul className="mb-3 space-y-1 text-sm">{locations.data?.map((l) => <li key={l.id}>• {l.name}</li>)}</ul>
            {can("locations.manage") && <div className="flex gap-2"><input className="input" placeholder="New location name" value={loc} onChange={(e) => setLoc(e.target.value)} /><button className="btn-ghost" disabled={!loc.trim()} onClick={addLoc}>Add</button></div>}
          </div>
          <form className="card space-y-3" onSubmit={changePw}>
            <h3 className="font-medium">Change your password</h3>
            <Field label="Current password"><input className="input" type="password" required autoComplete="current-password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} /></Field>
            <Field label="New password (min 10)"><input className="input" type="password" required minLength={10} autoComplete="new-password" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></Field>
            <p className="text-xs text-slate-500">Changing your password signs you out on all devices.</p>
            <button className="btn-ghost">Change password</button>
          </form>
        </div>
      </div>
    </>
  );
}
