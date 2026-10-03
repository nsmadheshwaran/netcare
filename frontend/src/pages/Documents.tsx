import { useRef, useState, type FormEvent } from "react";
import { Download, Eye, FileText, Lock, Paperclip, RotateCcw, Trash2, Upload } from "lucide-react";
import { api, download, openPdf, type Page } from "../api";
import { useAuth } from "../auth";
import { Badge, confirmAction, Empty, ErrorBanner, Field, Modal, PageHeader, Pager, Spinner, useAsync } from "../components/ui";

export type Doc = {
  id: number; entity_type: string; entity_id: number | null; entity_label: string | null; title: string; category: string;
  tags: string | null; notes: string | null; expires_on: string | null; is_sensitive: boolean; original_name: string;
  content_type: string; extension: string; size_bytes: number; sha256: string; uploaded_by_name: string | null;
  created_at: string; deleted_at: string | null; delete_reason: string | null;
};
type Meta = { categories: string[]; entity_types: string[]; max_upload_bytes: number; quota_bytes: number; used_bytes: number; can_see_sensitive: boolean; can_purge: boolean };

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp,.docx,.xlsx,.txt,.csv";
const INLINE = ["application/pdf", "image/png", "image/jpeg", "image/webp"];
const label = (s: string) => s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
export const fmtBytes = (n: number) => n < 1024 ? `${n} B` : n < 1 << 20 ? `${(n / 1024).toFixed(0)} KB` : `${(n / (1 << 20)).toFixed(1)} MB`;

function daysLeft(d: string | null) {
  if (!d) return null;
  const ms = new Date(d + "T00:00:00").getTime() - new Date(new Date().toLocaleDateString("en-CA") + "T00:00:00").getTime();
  return Math.round(ms / 86_400_000);
}

function Expiry({ d }: { d: string | null }) {
  const n = daysLeft(d);
  if (n === null) return null;
  return <Badge tone={n < 0 ? "red" : n <= 30 ? "amber" : "slate"}>{n < 0 ? `expired ${-n}d ago` : n === 0 ? "expires today" : `expires in ${n}d`}</Badge>;
}

function useMeta() {
  return useAsync(() => api<Meta>("/documents/meta"), []);
}

function UploadForm({ meta, entityType = "general", entityId, onDone }: { meta: Meta; entityType?: string; entityId?: number; onDone: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [f, setF] = useState({ title: "", category: "other", tags: "", notes: "", expires_on: "", is_sensitive: false });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) return setError("Choose a file");
    if (file.size > meta.max_upload_bytes) return setError(`Files must be ${fmtBytes(meta.max_upload_bytes)} or smaller`);
    const body = new FormData();
    body.append("file", file);
    body.append("entity_type", entityType);
    if (entityId !== undefined) body.append("entity_id", String(entityId));
    for (const [k, v] of Object.entries(f)) if (v !== "" && v !== false) body.append(k, String(v));
    setBusy(true);
    try { await api("/documents", { method: "POST", body }); onDone(); } catch (err: any) { setError(err.message); } finally { setBusy(false); }
  }
  return (
    <form onSubmit={submit} className="space-y-3">
      <ErrorBanner message={error} />
      <Field label="File *"><input ref={fileRef} className="input" type="file" accept={ACCEPT} required /></Field>
      <p className="text-xs text-slate-500">PDF, JPEG, PNG, WebP, Word (.docx), Excel (.xlsx), text or CSV, up to {fmtBytes(meta.max_upload_bytes)}. The type is checked from the file contents. Office files with macros are refused.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Title"><input className="input" placeholder="Defaults to the file name" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} maxLength={200} /></Field>
        <Field label="Category"><select className="input" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>{meta.categories.map((c) => <option key={c} value={c}>{label(c)}</option>)}</select></Field>
        <Field label="Expires on"><input className="input" type="date" value={f.expires_on} onChange={(e) => setF({ ...f, expires_on: e.target.value })} /></Field>
        <Field label="Tags"><input className="input" placeholder="amc, school" value={f.tags} onChange={(e) => setF({ ...f, tags: e.target.value })} maxLength={200} /></Field>
        <Field label="Notes" className="sm:col-span-2"><textarea className="input" rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
      </div>
      {meta.can_see_sensitive && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.is_sensitive} onChange={(e) => setF({ ...f, is_sensitive: e.target.checked })} /> Sensitive (ID proof, contract): only owners and managers can see it</label>}
      <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={onDone}>Cancel</button><button className="btn-primary" disabled={busy}><Upload size={15} /> {busy ? "Uploading…" : "Upload"}</button></div>
    </form>
  );
}

function DocActions({ d, meta, onChange, setErr }: { d: Doc; meta: Meta; onChange: () => void; setErr: (s: string) => void }) {
  const { can } = useAuth();
  const act = (fn: () => Promise<unknown>) => fn().then(onChange).catch((e) => setErr(e.message));
  if (d.deleted_at) return (
    <div className="flex justify-end gap-1">
      <button className="btn-ghost !px-2 !py-1 text-xs" onClick={() => act(() => api(`/documents/${d.id}/restore`, { method: "POST" }))}><RotateCcw size={13} /> Restore</button>
      {meta.can_purge && <button className="btn-ghost !px-2 !py-1 text-xs text-red-600" onClick={() => confirmAction(`Permanently remove "${d.title}"? The file cannot be recovered.`) && act(() => api(`/documents/${d.id}/purge`, { method: "POST" }))}>Purge</button>}
    </div>
  );
  return (
    <div className="flex justify-end gap-1">
      {INLINE.includes(d.content_type) && <button className="btn-ghost !px-2 !py-1" title="View" aria-label={`View ${d.title}`} onClick={() => openPdf(`/documents/${d.id}/download?inline=true`).catch((e) => setErr(e.message))}><Eye size={14} /></button>}
      <button className="btn-ghost !px-2 !py-1" title="Download" aria-label={`Download ${d.title}`} onClick={() => download(`/documents/${d.id}/download`, d.original_name).catch((e) => setErr(e.message))}><Download size={14} /></button>
      {can("documents.edit") && <button className="btn-ghost !px-2 !py-1 text-red-600" title="Delete" aria-label={`Delete ${d.title}`} onClick={() => {
        const reason = window.prompt(`Why delete "${d.title}"? (an owner or manager can restore it)`);
        if (reason) act(() => api(`/documents/${d.id}/delete`, { method: "POST", json: { reason } }));
      }}><Trash2 size={14} /></button>}
    </div>
  );
}

function DocRow({ d, meta, onChange, setErr, showEntity = true }: { d: Doc; meta: Meta; onChange: () => void; setErr: (s: string) => void; showEntity?: boolean }) {
  return (
    <tr className="border-t border-slate-100 dark:border-slate-800">
      <td className="td">
        <div className="flex items-center gap-1.5 font-medium"><FileText size={14} className="shrink-0 text-slate-400" />{d.title}{d.is_sensitive && <Lock size={12} className="text-amber-600" aria-label="Sensitive" />}</div>
        <div className="text-xs text-slate-500">{d.original_name} · {fmtBytes(d.size_bytes)}{d.tags ? ` · ${d.tags}` : ""}</div>
        {d.deleted_at && <div className="text-xs text-red-600">Deleted: {d.delete_reason}</div>}
      </td>
      <td className="td"><Badge>{label(d.category)}</Badge> <Expiry d={d.expires_on} /></td>
      {showEntity && <td className="td text-sm">{d.entity_type === "general" ? <span className="text-slate-400">General</span> : <>{label(d.entity_type)}: {d.entity_label ?? "?"}</>}</td>}
      <td className="td text-xs text-slate-500">{new Date(d.created_at).toLocaleDateString("en-IN")}<div>{d.uploaded_by_name}</div></td>
      <td className="td"><DocActions d={d} meta={meta} onChange={onChange} setErr={setErr} /></td>
    </tr>
  );
}

/** Files attached to one record, for detail views (service ticket, customer account, equipment). */
export function AttachedDocuments({ entityType, entityId }: { entityType: string; entityId: number }) {
  const { can } = useAuth();
  const meta = useMeta();
  const list = useAsync(() => api<Page<Doc>>(`/documents?entity_type=${entityType}&entity_id=${entityId}&size=100`), [entityType, entityId]);
  const [adding, setAdding] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!can("documents.view")) return null;
  return (
    <div>
      <h3 className="mb-2 flex items-center gap-2 font-medium"><Paperclip size={16} /> Documents
        {can("documents.edit") && meta.data && !adding && <button className="btn-ghost ml-auto !py-1 text-xs" onClick={() => setAdding(true)}><Upload size={13} /> Attach file</button>}</h3>
      <ErrorBanner message={err || list.error || meta.error} />
      {adding && meta.data && <div className="mb-3 rounded-lg border border-slate-200 p-3 dark:border-slate-700"><UploadForm meta={meta.data} entityType={entityType} entityId={entityId} onDone={() => { setAdding(false); list.reload(); meta.reload(); }} /></div>}
      {!list.data || !meta.data ? <Spinner /> : !list.data.items.length ? <p className="text-sm text-slate-500">No documents attached.</p> : (
        <table className="w-full text-sm"><tbody>{list.data.items.map((d) => <DocRow key={d.id} d={d} meta={meta.data!} onChange={list.reload} setErr={setErr} showEntity={false} />)}</tbody></table>
      )}
    </div>
  );
}

export default function Documents() {
  const { can } = useAuth();
  const meta = useMeta();
  const [f, setF] = useState({ q: "", category: "", entity_type: "", view: "all" });
  const [page, setPage] = useState(1);
  const [uploading, setUploading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const qs = `page=${page}&q=${encodeURIComponent(f.q)}${f.category ? `&category=${f.category}` : ""}${f.entity_type ? `&entity_type=${f.entity_type}` : ""}${f.view === "expiring" ? "&expiring_days=30" : ""}${f.view === "deleted" ? "&deleted=true" : ""}`;
  const { data, error, loading, reload } = useAsync(() => api<Page<Doc>>(`/documents?${qs}`), [qs]);
  const upd = (k: string) => (e: React.ChangeEvent<any>) => { setF({ ...f, [k]: e.target.value }); setPage(1); };
  const m = meta.data;
  const refresh = () => { reload(); meta.reload(); };
  return (
    <>
      <PageHeader title="Documents" subtitle="Bills, warranty cards, contracts, photos and ID proofs, attached to your records"
        actions={can("documents.edit") && m && <button className="btn-primary" onClick={() => setUploading(true)}><Upload size={16} /> Upload</button>} />
      <ErrorBanner message={error || meta.error || err} />
      {m && <div className="mb-3 text-xs text-slate-500">
        Storage used: {fmtBytes(m.used_bytes)} of {fmtBytes(m.quota_bytes)}
        <div className="mt-1 h-1.5 w-60 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700"><div className="h-full bg-indigo-500" style={{ width: `${Math.min(100, (m.used_bytes / m.quota_bytes) * 100)}%` }} /></div>
      </div>}
      <div className="card !p-0">
        <div className="flex flex-wrap gap-2 border-b border-slate-200 p-3 dark:border-slate-800">
          <input className="input max-w-xs" placeholder="Search title, file name, tags…" value={f.q} onChange={upd("q")} />
          <select className="input !w-auto" value={f.category} onChange={upd("category")} aria-label="Category"><option value="">All categories</option>{m?.categories.map((c) => <option key={c} value={c}>{label(c)}</option>)}</select>
          <select className="input !w-auto" value={f.entity_type} onChange={upd("entity_type")} aria-label="Attached to"><option value="">Attached to anything</option>{m?.entity_types.map((c) => <option key={c} value={c}>{label(c)}</option>)}</select>
          <select className="input !w-auto" value={f.view} onChange={upd("view")} aria-label="Show">
            <option value="all">All current</option><option value="expiring">Expired or expiring in 30 days</option>
            {m?.can_see_sensitive && <option value="deleted">Deleted</option>}
          </select>
        </div>
        {loading && !data ? <Spinner /> : !data?.items.length ? (
          <Empty title={f.view === "deleted" ? "No deleted documents" : "No documents"} hint={f.q || f.category || f.entity_type ? "Try clearing the filters." : "Upload a bill, warranty card or photo, or attach files from a service ticket or customer account."} />
        ) : m && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead className="bg-slate-50 dark:bg-slate-800/50"><tr><th className="th">Document</th><th className="th">Category</th><th className="th">Attached to</th><th className="th">Added</th><th className="th" /></tr></thead>
              <tbody>{data.items.map((d) => <DocRow key={d.id} d={d} meta={m} onChange={refresh} setErr={setErr} />)}</tbody>
            </table>
          </div>
        )}
        {data && <Pager page={page} size={data.size} total={data.total} onPage={setPage} />}
      </div>
      {uploading && m && <Modal title="Upload document" onClose={() => setUploading(false)} wide><UploadForm meta={m} onDone={() => { setUploading(false); refresh(); }} /></Modal>}
    </>
  );
}
