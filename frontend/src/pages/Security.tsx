import { useState } from "react";
import { AlertTriangle, CheckCircle2, HelpCircle, Link2, ShieldAlert } from "lucide-react";
import { api, type Page } from "../api";
import { useAuth } from "../auth";
import { Badge, Empty, ErrorBanner, Field, Modal, PageHeader, Spinner, useAsync } from "../components/ui";

type Row = { id: number; hostname: string; agent_name: string; asset_id: number | null; asset_name: string | null; customer_name: string | null; os_name: string | null; os_version: string | null; last_report_at: string | null; rating: Rating; reasons: string[]; defender_available: boolean; realtime_enabled: boolean | null; signature_updated_at: string | null; active_threats: number; threats_30d: number };
type Threat = { id: number; threat_name: string; severity: string; category: string | null; status: string; action_success: boolean | null; detected_at: string; resources: string | null; acknowledged_at: string | null; acknowledged_by: string | null; acknowledge_note: string | null; active: boolean };
type Detail = Row & { av_enabled: boolean | null; antispyware_enabled: boolean | null; behavior_monitor_enabled: boolean | null; tamper_protected: boolean | null; running_mode: string | null; signature_version: string | null; engine_version: string | null; product_version: string | null; quick_scan_at: string | null; full_scan_at: string | null; threats: Threat[] };
type Rating = "critical" | "warning" | "ok" | "unknown";

const TONE: Record<Rating, "red" | "amber" | "green" | "slate"> = { critical: "red", warning: "amber", ok: "green", unknown: "slate" };
const SEV: Record<string, "red" | "amber" | "slate"> = { severe: "red", high: "red", moderate: "amber", low: "slate", unknown: "slate" };
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-IN") : "never");
const yesNo = (v: boolean | null) => (v === null ? <span className="text-slate-400">not reported</span> : v ? <span className="text-emerald-600">On</span> : <span className="font-medium text-red-600">Off</span>);

function Ack({ endpointId, t, onDone }: { endpointId: number; t: Threat; onDone: () => void }) {
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      <ErrorBanner message={err} />
      <input className="input max-w-sm" placeholder="What was checked or done (e.g. file deleted, user warned)" value={note} onChange={(e) => setNote(e.target.value)} />
      <button className="btn-ghost" disabled={note.trim().length < 3} onClick={() => api(`/endpoints/${endpointId}/threats/${t.id}/acknowledge`, { method: "POST", json: { note } }).then(onDone).catch((e) => setErr(e.message))}>Mark reviewed</button>
    </div>
  );
}

function EndpointDetail({ id, onChanged }: { id: number; onChanged: () => void }) {
  const { can } = useAuth();
  const { data: d, error, reload } = useAsync(() => api<Detail>(`/endpoints/${id}`), [id]);
  const computers = useAsync(() => can("assets.view") ? Promise.all(["computer", "laptop", "server"].map((t) => api<Page<any>>(`/assets?asset_type=${t}&size=200`))).then((ps) => ps.flatMap((p) => p.items)) : Promise.resolve([]), []);
  const [err, setErr] = useState<string | null>(null);
  if (error) return <ErrorBanner message={error} />;
  if (!d) return <Spinner />;
  const refresh = () => { reload(); onChanged(); };
  return (
    <div className="space-y-4 text-sm">
      <ErrorBanner message={err} />
      <div className="flex flex-wrap items-center gap-2"><Badge tone={TONE[d.rating]}>{d.rating}</Badge><span className="text-slate-500">{d.os_name} {d.os_version} · via {d.agent_name} · last report {when(d.last_report_at)}</span></div>
      {!!d.reasons.length && <ul className="space-y-1 rounded-lg border border-slate-200 p-3 dark:border-slate-700">{d.reasons.map((r, i) => <li key={i} className="flex gap-2"><AlertTriangle size={14} className="mt-0.5 shrink-0 text-amber-600" />{r}</li>)}</ul>}
      <div className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
        <div>Antivirus: {yesNo(d.av_enabled)}</div><div>Real-time protection: {yesNo(d.realtime_enabled)}</div>
        <div>Tamper protection: {yesNo(d.tamper_protected)}</div><div>Behaviour monitoring: {yesNo(d.behavior_monitor_enabled)}</div>
        <div>Mode: {d.running_mode ?? "—"}</div><div>Definitions: {d.signature_version ?? "—"} ({when(d.signature_updated_at)})</div>
        <div>Last quick scan: {when(d.quick_scan_at)}</div><div>Last full scan: {when(d.full_scan_at)}</div>
        <div className="text-xs text-slate-500">Engine {d.engine_version ?? "—"} · platform {d.product_version ?? "—"}</div>
      </div>
      {can("security.manage") && computers.data && <Field label="Linked equipment">
        <select className="input max-w-sm" value={d.asset_id ?? ""} onChange={(e) => api(`/endpoints/${id}/asset`, { method: "PUT", json: { asset_id: e.target.value ? Number(e.target.value) : null } }).then(refresh).catch((x) => setErr(x.message))}>
          <option value="">Not linked</option>{computers.data.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.customer_name})</option>)}</select></Field>}
      <div>
        <h3 className="mb-2 font-medium">Detections in the last 30 days</h3>
        {!d.threats.length ? <p className="text-slate-500">None.</p> : <ul className="divide-y divide-slate-100 dark:divide-slate-800">{d.threats.map((t) => (
          <li key={t.id} className="py-2">
            <div className="flex flex-wrap items-center gap-2"><span className="font-medium">{t.threat_name}</span><Badge tone={SEV[t.severity] ?? "slate"}>{t.severity}</Badge>
              <Badge tone={t.active ? "red" : t.status === "allowed" ? "amber" : "green"}>{t.status.replace("_", " ")}</Badge>
              <span className="text-xs text-slate-500">{when(t.detected_at)}{t.category ? ` · ${t.category}` : ""}</span></div>
            {t.resources && <div className="mt-1 break-all font-mono text-xs text-slate-500">{t.resources}</div>}
            {t.acknowledged_at ? <div className="mt-1 text-xs text-emerald-700 dark:text-emerald-400">Reviewed by {t.acknowledged_by} on {when(t.acknowledged_at)}: {t.acknowledge_note}</div>
              : t.active ? <div className="mt-1 text-xs text-red-600">Still active on the PC. Open Windows Security there (Virus and threat protection, Protection history) to remove it, or run a full scan. NetCare cannot do this remotely.</div>
              : can("security.manage") && <Ack endpointId={id} t={t} onDone={refresh} />}
          </li>))}</ul>}
      </div>
      <p className="text-xs text-slate-500">NetCare only reads what Microsoft Defender reports. It never changes Defender settings, starts scans or removes files.</p>
    </div>
  );
}

export default function Security() {
  const [rating, setRating] = useState<"" | Rating>("");
  const list = useAsync(() => api<Row[]>(`/endpoints${rating ? `?rating=${rating}` : ""}`), [rating]);
  const summary = useAsync(() => api<any>("/endpoints/summary"), []);
  const [open, setOpen] = useState<number | null>(null);
  const s = summary.data;
  const tiles: [Rating, string, any][] = [["critical", "Critical", ShieldAlert], ["warning", "Needs attention", AlertTriangle], ["ok", "Protected", CheckCircle2], ["unknown", "Not reporting", HelpCircle]];
  return (
    <>
      <PageHeader title="Endpoint security" subtitle="Microsoft Defender status of PCs running the NetCare agent with endpoint reporting switched on" />
      <ErrorBanner message={list.error || summary.error} />
      {s && <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        {tiles.map(([k, l, Icon]) => <button key={k} onClick={() => setRating(rating === k ? "" : k)} className={`card !p-3 text-left ${rating === k ? "ring-2 ring-indigo-500" : ""}`}>
          <div className="flex items-center gap-1.5 text-xs text-slate-500"><Icon size={13} />{l}</div><div className="text-2xl font-semibold">{s[k]}</div></button>)}
        <div className="card !p-3"><div className="text-xs text-slate-500">Active threats</div><div className={`text-2xl font-semibold ${s.active_threats ? "text-red-600" : ""}`}>{s.active_threats}</div></div>
      </div>}
      <div className="card !p-0">
        {!list.data ? <Spinner /> : !list.data.length ? <Empty title={rating ? `No ${rating} PCs` : "No PCs reporting"} hint={rating ? undefined : "Under Network monitoring, edit an agent and switch on \"Report this PC's Microsoft Defender status\". The PC appears here after its first report."} /> : (
          <div className="overflow-x-auto"><table className="w-full min-w-[760px] text-sm">
            <thead className="bg-slate-50 dark:bg-slate-800/50"><tr><th className="th">Rating</th><th className="th">Computer</th><th className="th">Site</th><th className="th">What needs attention</th><th className="th">Last report</th></tr></thead>
            <tbody>{list.data.map((r) => (
              <tr key={r.id} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/40" onClick={() => setOpen(r.id)}>
                <td className="td"><Badge tone={TONE[r.rating]}>{r.rating}</Badge></td>
                <td className="td"><div className="font-medium">{r.hostname}</div><div className="text-xs text-slate-500">{r.asset_name ? <><Link2 size={11} className="inline" /> {r.asset_name}</> : r.os_name}</div></td>
                <td className="td">{r.customer_name ?? "—"}</td>
                <td className="td text-xs">{r.reasons.length ? <>{r.reasons[0]}{r.reasons.length > 1 && <span className="text-slate-500"> (+{r.reasons.length - 1} more)</span>}</> : <span className="text-emerald-600">Nothing</span>}</td>
                <td className="td text-xs text-slate-500">{when(r.last_report_at)}</td>
              </tr>))}</tbody></table></div>
        )}
      </div>
      {open !== null && <Modal title={list.data?.find((r) => r.id === open)?.hostname ?? "Computer"} onClose={() => setOpen(null)} wide>
        <EndpointDetail id={open} onChanged={() => { list.reload(); summary.reload(); }} /></Modal>}
    </>
  );
}
