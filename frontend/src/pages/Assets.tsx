import { useState, type FormEvent } from "react";
import { History, Plus } from "lucide-react";
import { api, type Page } from "../api";
import { useAuth } from "../auth";
import { PartySelect, useCustomers } from "../components/trade";
import { Badge, Empty, ErrorBanner, Field, Modal, PageHeader, Pager, Spinner, useAsync } from "../components/ui";
import { AttachedDocuments } from "./Documents";
import { StatusBadge, TicketDetail } from "./Service";

type Asset = { id: number; customer_id: number; customer_name: string; asset_type: string; name: string; brand: string | null; model: string | null; serial_number: string | null; site_location: string | null; ip_address: string | null; installed_on: string | null; warranty_until: string | null; warranty_status: string; status: string; open_tickets: number; notes: string | null };
const TYPES = ["camera", "dvr", "nvr", "storage", "computer", "laptop", "printer", "router", "switch", "server", "ups", "access_point", "other"];
const W_TONE: Record<string, "green" | "amber" | "red" | "slate"> = { in_warranty: "green", expiring: "amber", expired: "red", unknown: "slate" };

function AssetForm({ initial, onDone }: { initial: Partial<Asset>; onDone: () => void }) {
  const customers = useCustomers();
  const [f, setF] = useState<any>({ asset_type: "camera", status: "active", ...initial });
  const [error, setError] = useState<string | null>(null);
  const set = (k: string) => (e: React.ChangeEvent<any>) => setF({ ...f, [k]: e.target.value });
  async function submit(e: FormEvent) {
    e.preventDefault();
    const keys = ["customer_id", "asset_type", "name", "brand", "model", "serial_number", "site_location", "ip_address", "installed_on", "warranty_until", "status", "notes"];
    const body: any = Object.fromEntries(keys.map((k) => [k, f[k] === "" || f[k] === undefined ? null : f[k]]));
    body.customer_id = Number(body.customer_id);
    try { await api(f.id ? `/assets/${f.id}` : "/assets", { method: f.id ? "PUT" : "POST", json: body }); onDone(); } catch (err: any) { setError(err.message); }
  }
  const input = (k: string, label: string, props: any = {}) => <Field label={label}><input className="input" value={f[k] ?? ""} onChange={set(k)} {...props} /></Field>;
  return (
    <form onSubmit={submit} className="space-y-3">
      <ErrorBanner message={error} />
      <div className="grid gap-3 sm:grid-cols-3">
        <PartySelect label="Customer *" value={f.customer_id ?? ""} onChange={(v) => setF({ ...f, customer_id: v })} options={customers} />
        <Field label="Type"><select className="input" value={f.asset_type} onChange={set("asset_type")}>{TYPES.map((t) => <option key={t}>{t}</option>)}</select></Field>
        {input("name", "Name *", { required: true, placeholder: "e.g. Camera 4, Server room NVR" })}
        {input("brand", "Brand")}{input("model", "Model")}{input("serial_number", "Serial no.")}
        {input("site_location", "Where at site")}{input("ip_address", "IP address")}
        <Field label="Status"><select className="input" value={f.status} onChange={set("status")}><option value="active">Active</option><option value="retired">Retired</option></select></Field>
        {input("installed_on", "Installed on", { type: "date" })}{input("warranty_until", "Warranty until", { type: "date" })}
        <Field label="Notes" className="sm:col-span-3"><textarea className="input" rows={2} value={f.notes ?? ""} onChange={set("notes")} /></Field>
      </div>
      <p className="text-xs text-slate-500">IP addresses are recorded for reference. Network monitoring of these devices is a planned module.</p>
      <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={onDone}>Cancel</button><button className="btn-primary">Save</button></div>
    </form>
  );
}

function AssetHistory({ asset }: { asset: Asset }) {
  const { data, error } = useAsync(() => api<any[]>(`/assets/${asset.id}/history`), [asset.id]);
  const [open, setOpen] = useState<number | null>(null);
  if (error) return <ErrorBanner message={error} />;
  if (!data) return <Spinner />;
  if (open) return <TicketDetail id={open} />;
  return !data.length ? <Empty title="No service history" /> : (
    <ul className="divide-y divide-slate-100 dark:divide-slate-800">{data.map((t) => (
      <li key={t.id} className="cursor-pointer py-2 hover:bg-slate-50 dark:hover:bg-slate-800/40" onClick={() => setOpen(t.id)}>
        <span className="font-mono text-xs">{t.number}</span> <StatusBadge s={t.status} /> <span className="text-xs text-slate-500">{new Date(t.created_at).toLocaleDateString("en-IN")}</span>
        <div className="text-sm">{t.reported_problem}</div>{t.work_performed && <div className="text-xs text-slate-500">Done: {t.work_performed}</div>}
      </li>))}</ul>
  );
}

export default function Assets() {
  const { can } = useAuth();
  const customers = useCustomers();
  const [f, setF] = useState({ q: "", customer_id: "", asset_type: "", warranty: "" });
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Partial<Asset> | null>(null);
  const [history, setHistory] = useState<Asset | null>(null);
  const qs = `page=${page}&q=${encodeURIComponent(f.q)}${f.customer_id ? `&customer_id=${f.customer_id}` : ""}${f.asset_type ? `&asset_type=${f.asset_type}` : ""}${f.warranty ? `&warranty=${f.warranty}` : ""}`;
  const { data, error, loading, reload } = useAsync(() => api<Page<Asset>>(`/assets?${qs}`), [qs]);
  const upd = (k: string) => (e: React.ChangeEvent<any>) => { setF({ ...f, [k]: e.target.value }); setPage(1); };
  return (
    <>
      <PageHeader title="IT assets" subtitle="Equipment at your customers' sites: cameras, recorders, computers, network gear"
        actions={can("assets.edit") && <button className="btn-primary" onClick={() => setEditing({})}><Plus size={16} /> Add equipment</button>} />
      <ErrorBanner message={error} />
      <div className="card !p-0">
        <div className="flex flex-wrap gap-2 border-b border-slate-200 p-3 dark:border-slate-800">
          <input className="input max-w-xs" placeholder="Search name, serial, IP, site…" value={f.q} onChange={upd("q")} />
          <select className="input !w-auto" value={f.customer_id} onChange={upd("customer_id")} aria-label="Customer"><option value="">All customers</option>{customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
          <select className="input !w-auto" value={f.asset_type} onChange={upd("asset_type")} aria-label="Type"><option value="">All types</option>{TYPES.map((t) => <option key={t}>{t}</option>)}</select>
          <select className="input !w-auto" value={f.warranty} onChange={upd("warranty")} aria-label="Warranty"><option value="">Any warranty</option><option value="expiring">Expiring in 30 days</option><option value="expired">Expired</option><option value="in_warranty">In warranty</option></select>
        </div>
        {loading && !data ? <Spinner /> : !data?.items.length ? <Empty title="No equipment registered" hint="Register equipment when you finish an installation ticket, or add it here." /> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px]">
              <thead className="bg-slate-50 dark:bg-slate-800/50"><tr><th className="th">Equipment</th><th className="th">Customer / site</th><th className="th">Serial / IP</th><th className="th">Warranty</th><th className="th">Status</th><th className="th" /></tr></thead>
              <tbody>{data.items.map((a) => (
                <tr key={a.id} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="td"><div className="font-medium">{a.name}</div><div className="text-xs text-slate-500">{a.asset_type}{a.brand ? ` · ${a.brand}` : ""}{a.model ? ` ${a.model}` : ""}</div></td>
                  <td className="td">{a.customer_name}<div className="text-xs text-slate-500">{a.site_location}</div></td>
                  <td className="td font-mono text-xs">{a.serial_number}<div>{a.ip_address}</div></td>
                  <td className="td">{a.warranty_until ? <><Badge tone={W_TONE[a.warranty_status]}>{a.warranty_status.replace("_", " ")}</Badge><div className="text-xs text-slate-500">{a.warranty_until}</div></> : <span className="text-xs text-slate-400">unknown</span>}</td>
                  <td className="td"><Badge tone={a.status === "active" ? "green" : "slate"}>{a.status}</Badge>{a.open_tickets > 0 && <div className="text-xs text-amber-700">{a.open_tickets} open ticket(s)</div>}</td>
                  <td className="td whitespace-nowrap text-right">
                    <button className="rounded p-1.5 hover:bg-slate-200 dark:hover:bg-slate-700" onClick={() => setHistory(a)} title="Service history" aria-label="Service history"><History size={15} /></button>
                    {can("assets.edit") && <button className="btn-ghost !py-1 text-xs" onClick={() => setEditing(a)}>Edit</button>}
                  </td>
                </tr>))}</tbody>
            </table>
            <Pager page={data.page} size={data.size} total={data.total} onPage={setPage} />
          </div>
        )}
      </div>
      {editing && <Modal title={editing.id ? "Edit equipment" : "Add equipment"} wide onClose={() => setEditing(null)}><AssetForm initial={editing} onDone={() => { setEditing(null); reload(); }} /></Modal>}
      {history && <Modal title={`${history.name}: service history`} wide onClose={() => setHistory(null)}><div className="space-y-4"><AssetHistory asset={history} /><AttachedDocuments entityType="asset" entityId={history.id} /></div></Modal>}
    </>
  );
}
