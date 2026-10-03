import { useEffect, useState, type FormEvent } from "react";
import { Copy, KeyRound, Pencil, Plus, Radio, RefreshCw, ShieldOff, Trash2 } from "lucide-react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, type Page } from "../api";
import { useAuth } from "../auth";
import { useCustomers } from "../components/trade";
import { Badge, confirmAction, Empty, ErrorBanner, Field, Modal, PageHeader, Spinner, useAsync } from "../components/ui";

type Agent = { id: number; name: string; customer_id: number | null; customer_name: string | null; site_note: string | null; token_prefix: string; status: string; online: boolean; last_seen_at: string | null; last_ip: string | null; agent_version: string | null; hostname: string | null; checks: number };
export type Check = { id: number; agent_id: number; agent_name: string; asset_id: number | null; asset_name: string | null; customer_name: string | null; name: string; kind: "icmp" | "tcp"; host: string; port: number | null; interval_seconds: number; timeout_ms: number; failure_threshold: number; latency_warn_ms: number | null; enabled: boolean; status: string; stored_status: string; status_since: string | null; last_checked_at: string | null; last_latency_ms: number | null; last_error: string | null; consecutive_failures: number };
type Window = { samples: number; uptime_pct: number | null; avg_latency_ms: number | null; p95_latency_ms: number | null; incidents: number; downtime_minutes: number };
type Stats = { windows: Record<"24h" | "7d" | "30d", Window>; series: { t: string; samples: number; failures: number; avg_latency_ms: number | null }[]; incidents: { id: number; started_at: string; ended_at: string | null; reason: string | null; minutes: number }[] };

const TONE: Record<string, "green" | "amber" | "red" | "slate"> = { up: "green", degraded: "amber", down: "red", unknown: "slate" };
export function MonitorBadge({ s }: { s: string | null | undefined }) {
  if (!s) return null;
  return <Badge tone={TONE[s] ?? "slate"}>{s}</Badge>;
}
const ago = (iso: string | null) => {
  if (!iso) return "never";
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : new Date(iso).toLocaleString("en-IN");
};
const dur = (m: number) => m < 60 ? `${m} min` : m < 1440 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${Math.floor(m / 1440)} d ${Math.floor((m % 1440) / 60)} h`;

function AgentToken({ agent, token }: { agent: Agent; token: string }) {
  const server = window.location.origin;
  const cfg = JSON.stringify({ server_url: server, token }, null, 2);
  const [copied, setCopied] = useState(false);
  return (
    <div className="space-y-3 text-sm">
      <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
        <b>Copy this now.</b> The token for <b>{agent.name}</b> is shown only once. NetCare keeps only a fingerprint of it.
      </div>
      <p>1. On a computer at the site (always on, on the same network as the devices), install Python 3.10 or newer and copy <code>agent/netcare_agent.py</code> from the NetCare package.</p>
      <p>2. Save this next to it as <code>agent.json</code>:</p>
      <pre className="overflow-x-auto rounded-lg bg-slate-100 p-3 text-xs dark:bg-slate-800">{cfg}</pre>
      <button className="btn-ghost !py-1 text-xs" onClick={() => navigator.clipboard?.writeText(cfg).then(() => setCopied(true))}><Copy size={13} /> {copied ? "Copied" : "Copy agent.json"}</button>
      <p>3. Test it: <code>python netcare_agent.py --config agent.json --once</code>, then run it as a service (see the Monitoring agent guide in the docs).</p>
      <p className="text-xs text-slate-500">The agent only connects out to NetCare over HTTPS and only checks the hosts you add here. If the computer is lost, revoke the token.</p>
    </div>
  );
}

function AgentForm({ initial, onDone }: { initial: Partial<Agent>; onDone: (created?: { agent: Agent; token: string }) => void }) {
  const customers = useCustomers();
  const [f, setF] = useState<any>({ name: "", customer_id: "", site_note: "", ...initial });
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    const body = { name: f.name, customer_id: f.customer_id ? Number(f.customer_id) : null, site_note: f.site_note || null };
    try {
      if (f.id) { await api(`/monitoring/agents/${f.id}`, { method: "PUT", json: body }); onDone(); }
      else { const r = await api<Agent & { token: string }>("/monitoring/agents", { method: "POST", json: body }); onDone({ agent: r, token: r.token }); }
    } catch (err: any) { setError(err.message); }
  }
  return (
    <form onSubmit={submit} className="space-y-3">
      <ErrorBanner message={error} />
      <Field label="Name *"><input className="input" required maxLength={100} placeholder="e.g. School office PC" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
      <Field label="Customer site"><select className="input" value={f.customer_id ?? ""} onChange={(e) => setF({ ...f, customer_id: e.target.value })}>
        <option value="">Your own office / not a customer site</option>{customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
      <Field label="Where it runs"><input className="input" maxLength={200} placeholder="Reception desktop, server room" value={f.site_note ?? ""} onChange={(e) => setF({ ...f, site_note: e.target.value })} /></Field>
      <p className="text-xs text-slate-500">Install agents only on networks you are authorised to monitor.</p>
      <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={() => onDone()}>Cancel</button><button className="btn-primary">Save</button></div>
    </form>
  );
}

function CheckForm({ initial, agents, onDone }: { initial: Partial<Check>; agents: Agent[]; onDone: () => void }) {
  const [f, setF] = useState<any>({ kind: "icmp", interval_seconds: 60, timeout_ms: 2000, failure_threshold: 3, enabled: true, agent_id: agents.find((a) => a.status === "active")?.id ?? "", ...initial });
  const [error, setError] = useState<string | null>(null);
  const agent = agents.find((a) => a.id === Number(f.agent_id));
  const assets = useAsync(() => api<Page<any>>(`/assets?size=200${agent?.customer_id ? `&customer_id=${agent.customer_id}` : ""}`), [agent?.customer_id]);
  const set = (k: string) => (e: React.ChangeEvent<any>) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  async function submit(e: FormEvent) {
    e.preventDefault();
    const num = (v: any) => (v === "" || v === null || v === undefined ? null : Number(v));
    const body = { agent_id: Number(f.agent_id), asset_id: num(f.asset_id), name: f.name, kind: f.kind, host: f.host || null, port: f.kind === "tcp" ? num(f.port) : null,
      interval_seconds: Number(f.interval_seconds), timeout_ms: Number(f.timeout_ms), failure_threshold: Number(f.failure_threshold), latency_warn_ms: num(f.latency_warn_ms), enabled: f.enabled };
    try { await api(f.id ? `/monitoring/checks/${f.id}` : "/monitoring/checks", { method: f.id ? "PUT" : "POST", json: body }); onDone(); } catch (err: any) { setError(err.message); }
  }
  const pickAsset = (id: string) => {
    const a = assets.data?.items.find((x) => x.id === Number(id));
    setF({ ...f, asset_id: id, name: f.name || a?.name || "", host: f.host || "" });
  };
  const selected = assets.data?.items.find((x) => x.id === Number(f.asset_id));
  return (
    <form onSubmit={submit} className="space-y-3">
      <ErrorBanner message={error} />
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Agent *"><select className="input" required value={f.agent_id} onChange={set("agent_id")}>{agents.filter((a) => a.status === "active").map((a) => <option key={a.id} value={a.id}>{a.name}{a.customer_name ? ` (${a.customer_name})` : ""}</option>)}</select></Field>
        <Field label="Equipment"><select className="input" value={f.asset_id ?? ""} onChange={(e) => pickAsset(e.target.value)}><option value="">Not linked</option>{assets.data?.items.map((a) => <option key={a.id} value={a.id}>{a.name}{a.ip_address ? ` · ${a.ip_address}` : ""}</option>)}</select></Field>
        <Field label="Name *"><input className="input" required maxLength={120} value={f.name ?? ""} onChange={set("name")} placeholder="NVR web port" /></Field>
        <Field label="Check"><select className="input" value={f.kind} onChange={set("kind")}><option value="icmp">Ping (ICMP)</option><option value="tcp">TCP port open</option></select></Field>
        <Field label={`Host${selected?.ip_address ? ` (blank = ${selected.ip_address})` : " *"}`}><input className="input" value={f.host ?? ""} onChange={set("host")} placeholder="192.168.1.50 or nvr.local" /></Field>
        {f.kind === "tcp" && <Field label="Port *"><input className="input" type="number" min={1} max={65535} required value={f.port ?? ""} onChange={set("port")} placeholder="554 (RTSP), 80, 8000" /></Field>}
        <Field label="Every (seconds)"><input className="input" type="number" min={30} max={3600} value={f.interval_seconds} onChange={set("interval_seconds")} /></Field>
        <Field label="Timeout (ms)"><input className="input" type="number" min={200} max={10000} value={f.timeout_ms} onChange={set("timeout_ms")} /></Field>
        <Field label="Down after (failures in a row)"><input className="input" type="number" min={1} max={20} value={f.failure_threshold} onChange={set("failure_threshold")} /></Field>
        <Field label="Slow above (ms)"><input className="input" type="number" min={1} value={f.latency_warn_ms ?? ""} onChange={set("latency_warn_ms")} placeholder="optional" /></Field>
      </div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.enabled} onChange={set("enabled")} /> Enabled</label>
      <p className="text-xs text-slate-500">One host per check. Ranges, subnets and scanning are not supported, by design.</p>
      <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={onDone}>Cancel</button><button className="btn-primary">Save</button></div>
    </form>
  );
}

export function CheckDetail({ check }: { check: Check }) {
  const [range, setRange] = useState<"24h" | "7d" | "30d">("24h");
  const { data, error } = useAsync(() => api<Stats>(`/monitoring/checks/${check.id}/stats?range=${range}`), [check.id, range]);
  if (error) return <ErrorBanner message={error} />;
  if (!data) return <Spinner />;
  const pts = data.series.map((b) => ({ t: new Date(b.t).toLocaleString("en-IN", range === "24h" ? { hour: "2-digit", minute: "2-digit" } : { day: "numeric", month: "short" }), latency: b.avg_latency_ms, failures: b.failures }));
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <MonitorBadge s={check.status} /> <span className="font-mono">{check.kind.toUpperCase()} {check.host}{check.port ? `:${check.port}` : ""}</span>
        <span className="text-slate-500">· every {check.interval_seconds}s via {check.agent_name} · last result {ago(check.last_checked_at)}</span>
      </div>
      {check.last_error && check.status !== "up" && <div className="text-sm text-red-600">Last error: {check.last_error}</div>}
      <div className="grid gap-3 sm:grid-cols-3">{(["24h", "7d", "30d"] as const).map((k) => { const w = data.windows[k]; return (
        <div key={k} className="card !p-3"><div className="text-xs text-slate-500">Last {k}</div>
          <div className="text-lg font-semibold">{w.uptime_pct === null ? "No data" : `${w.uptime_pct}% up`}</div>
          <div className="text-xs text-slate-500">{w.samples} results · {w.incidents} outage{w.incidents === 1 ? "" : "s"}{w.downtime_minutes ? ` · ${dur(w.downtime_minutes)} down` : ""}</div>
          <div className="text-xs text-slate-500">latency avg {w.avg_latency_ms ?? "—"} ms · 95% {w.p95_latency_ms ?? "—"} ms</div></div>); })}</div>
      <div>
        <div className="mb-2 flex items-center gap-2"><h3 className="font-medium">Latency</h3>
          <div className="ml-auto flex gap-1">{(["24h", "7d", "30d"] as const).map((r) => <button key={r} className={`btn-ghost !py-0.5 text-xs ${range === r ? "!bg-indigo-50 dark:!bg-indigo-950" : ""}`} onClick={() => setRange(r)}>{r}</button>)}</div></div>
        <div className="h-48"><ResponsiveContainer><LineChart data={pts}>
          <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.2} /><XAxis dataKey="t" fontSize={11} minTickGap={30} /><YAxis fontSize={11} unit=" ms" width={60} />
          <Tooltip formatter={(v, n) => n === "latency" ? [`${v} ms`, "Avg latency"] : [v, "Failures"]} />
          <Line dataKey="latency" stroke="#6366f1" strokeWidth={2} dot={false} connectNulls={false} />
        </LineChart></ResponsiveContainer></div>
        <p className="text-xs text-slate-500">Gaps mean no successful results in that interval (device down or agent not reporting).</p>
      </div>
      <div>
        <h3 className="mb-2 font-medium">Outages</h3>
        {!data.incidents.length ? <p className="text-sm text-slate-500">No outages recorded.</p> : (
          <table className="w-full text-sm"><tbody>{data.incidents.map((i) => (
            <tr key={i.id} className="border-t border-slate-100 dark:border-slate-800">
              <td className="td">{new Date(i.started_at).toLocaleString("en-IN")}</td>
              <td className="td">{i.ended_at ? `to ${new Date(i.ended_at).toLocaleString("en-IN")}` : <Badge tone="red">ongoing</Badge>}</td>
              <td className="td text-right">{dur(i.minutes)}</td><td className="td text-xs text-slate-500">{i.reason}</td></tr>))}</tbody></table>
        )}
      </div>
    </div>
  );
}

export default function Monitoring() {
  const { can } = useAuth();
  const manage = can("monitoring.manage");
  const [tab, setTab] = useState<"status" | "agents">("status");
  const [statusFilter, setStatusFilter] = useState("");
  const [tick, setTick] = useState(0);
  useEffect(() => { const t = setInterval(() => setTick((n) => n + 1), 30_000); return () => clearInterval(t); }, []);
  const overview = useAsync(() => api<any>("/monitoring/overview"), [tick]);
  const checks = useAsync(() => api<Check[]>(`/monitoring/checks${statusFilter ? `?status=${statusFilter}` : ""}`), [tick, statusFilter]);
  const agents = useAsync(() => api<Agent[]>("/monitoring/agents"), [tick]);
  const [editCheck, setEditCheck] = useState<Partial<Check> | null>(null);
  const [editAgent, setEditAgent] = useState<Partial<Agent> | null>(null);
  const [token, setToken] = useState<{ agent: Agent; token: string } | null>(null);
  const [detail, setDetail] = useState<Check | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const reload = () => setTick((n) => n + 1);
  const o = overview.data;
  const act = (fn: () => Promise<any>) => fn().then(reload).catch((e) => setErr(e.message));

  return (
    <>
      <PageHeader title="Network monitoring" subtitle="Ping and port checks run by agents at customer sites. Refreshes every 30 seconds."
        actions={manage && <>
          <button className="btn-ghost" onClick={() => setEditAgent({})}><Radio size={16} /> Add agent</button>
          <button className="btn-primary" disabled={!agents.data?.some((a) => a.status === "active")} onClick={() => setEditCheck({})}><Plus size={16} /> Add check</button>
        </>} />
      <ErrorBanner message={err || overview.error || checks.error || agents.error} />
      {o && <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {[["Down", o.checks.down, "text-red-600", "down"], ["Slow", o.checks.degraded, "text-amber-600", "degraded"], ["Up", o.checks.up, "text-emerald-600", "up"], ["Unknown", o.checks.unknown, "text-slate-500", "unknown"]].map(([l, v, c, s]) => (
          <button key={l as string} onClick={() => { setTab("status"); setStatusFilter(statusFilter === s ? "" : s as string); }} className={`card !p-3 text-left ${statusFilter === s ? "ring-2 ring-indigo-500" : ""}`}>
            <div className="text-xs text-slate-500">{l}</div><div className={`text-2xl font-semibold ${c}`}>{v}</div></button>))}
        <div className="card !p-3"><div className="text-xs text-slate-500">Agents online</div><div className="text-2xl font-semibold">{o.agents_online}/{o.agents_total}</div></div>
        <div className="card !p-3"><div className="text-xs text-slate-500">Open outages</div><div className={`text-2xl font-semibold ${o.open_incidents ? "text-red-600" : ""}`}>{o.open_incidents}</div></div>
      </div>}

      <div className="mb-3 flex gap-1 border-b border-slate-200 dark:border-slate-800">
        {(["status", "agents"] as const).map((t) => <button key={t} onClick={() => setTab(t)} className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === t ? "border-indigo-600 font-medium text-indigo-700 dark:text-indigo-300" : "border-transparent text-slate-500"}`}>{t === "status" ? "Checks" : "Agents"}</button>)}
        <button className="btn-ghost ml-auto !py-1 text-xs" onClick={reload}><RefreshCw size={13} /> Refresh</button>
      </div>

      {tab === "status" && <div className="card !p-0">
        {!checks.data ? <Spinner /> : !checks.data.length ? (
          <Empty title={statusFilter ? `No ${statusFilter} checks` : "No checks yet"} hint={statusFilter ? undefined : manage ? "Add an agent for the site, run it there, then add checks for routers, recorders and cameras." : "An owner or manager sets up monitoring."} />
        ) : <div className="overflow-x-auto"><table className="w-full min-w-[760px] text-sm">
          <thead className="bg-slate-50 dark:bg-slate-800/50"><tr><th className="th">Status</th><th className="th">Check</th><th className="th">Site</th><th className="th">Target</th><th className="th text-right">Latency</th><th className="th">Last result</th><th className="th" /></tr></thead>
          <tbody>{checks.data.map((c) => (
            <tr key={c.id} className={`cursor-pointer border-t border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/40 ${c.enabled ? "" : "opacity-50"}`} onClick={() => setDetail(c)}>
              <td className="td"><MonitorBadge s={c.status} />{c.status !== c.stored_status && c.enabled && <div className="text-[10px] text-slate-400">last known: {c.stored_status}</div>}</td>
              <td className="td"><div className="font-medium">{c.name}</div>{c.asset_name && <div className="text-xs text-slate-500">{c.asset_name}</div>}</td>
              <td className="td">{c.customer_name ?? "—"}</td>
              <td className="td font-mono text-xs">{c.kind.toUpperCase()} {c.host}{c.port ? `:${c.port}` : ""}</td>
              <td className="td text-right tabular-nums">{c.last_latency_ms !== null ? `${c.last_latency_ms} ms` : "—"}</td>
              <td className="td text-xs text-slate-500">{ago(c.last_checked_at)}{c.status === "down" && c.last_error && <div className="text-red-600">{c.last_error}</div>}</td>
              <td className="td text-right" onClick={(e) => e.stopPropagation()}>{manage && <>
                <button className="btn-ghost !px-2 !py-1" aria-label={`Edit ${c.name}`} onClick={() => setEditCheck(c)}><Pencil size={13} /></button>
                <button className="btn-ghost !px-2 !py-1 text-red-600" aria-label={`Delete ${c.name}`} onClick={() => confirmAction(`Delete check "${c.name}" and its history?`) && act(() => api(`/monitoring/checks/${c.id}`, { method: "DELETE" }))}><Trash2 size={13} /></button></>}</td>
            </tr>))}</tbody></table></div>}
      </div>}

      {tab === "agents" && <div className="card !p-0">
        {!agents.data ? <Spinner /> : !agents.data.length ? <Empty title="No agents" hint="An agent is a small program at the customer's site that runs the checks and reports here over HTTPS." /> : (
          <div className="overflow-x-auto"><table className="w-full min-w-[720px] text-sm">
            <thead className="bg-slate-50 dark:bg-slate-800/50"><tr><th className="th">Agent</th><th className="th">Site</th><th className="th">State</th><th className="th">Last seen</th><th className="th text-right">Checks</th><th className="th" /></tr></thead>
            <tbody>{agents.data.map((a) => (
              <tr key={a.id} className="border-t border-slate-100 dark:border-slate-800">
                <td className="td"><div className="font-medium">{a.name}</div><div className="font-mono text-xs text-slate-500">token nca_{a.token_prefix}…{a.hostname ? ` · ${a.hostname}` : ""}{a.agent_version ? ` · v${a.agent_version}` : ""}</div></td>
                <td className="td">{a.customer_name ?? "—"}{a.site_note && <div className="text-xs text-slate-500">{a.site_note}</div>}</td>
                <td className="td">{a.status === "revoked" ? <Badge tone="red">revoked</Badge> : a.online ? <Badge tone="green">online</Badge> : <Badge>offline</Badge>}</td>
                <td className="td text-xs text-slate-500">{ago(a.last_seen_at)}{a.last_ip && <div>from {a.last_ip}</div>}</td>
                <td className="td text-right">{a.checks}</td>
                <td className="td text-right">{manage && <div className="flex justify-end gap-1">
                  <button className="btn-ghost !px-2 !py-1" aria-label={`Edit ${a.name}`} onClick={() => setEditAgent(a)}><Pencil size={13} /></button>
                  <button className="btn-ghost !px-2 !py-1 text-xs" title="Issue a new token" onClick={() => confirmAction(`Issue a new token for ${a.name}? The current one stops working immediately.`) && api<Agent & { token: string }>(`/monitoring/agents/${a.id}/rotate-token`, { method: "POST" }).then((r) => { setToken({ agent: r, token: r.token }); reload(); }).catch((e) => setErr(e.message))}><KeyRound size={13} /> New token</button>
                  {a.status === "active" && <button className="btn-ghost !px-2 !py-1 text-xs text-red-600" onClick={() => confirmAction(`Revoke ${a.name}? It stops reporting at once.`) && act(() => api(`/monitoring/agents/${a.id}/revoke`, { method: "POST" }))}><ShieldOff size={13} /> Revoke</button>}
                </div>}</td>
              </tr>))}</tbody></table></div>
        )}
      </div>}

      {editAgent && <Modal title={editAgent.id ? "Edit agent" : "Add agent"} onClose={() => setEditAgent(null)}>
        <AgentForm initial={editAgent} onDone={(created) => { setEditAgent(null); if (created) setToken(created); reload(); }} /></Modal>}
      {token && <Modal title="Agent token" onClose={() => setToken(null)} wide><AgentToken agent={token.agent} token={token.token} /></Modal>}
      {editCheck && agents.data && <Modal title={editCheck.id ? "Edit check" : "Add check"} onClose={() => setEditCheck(null)} wide>
        <CheckForm initial={editCheck} agents={agents.data} onDone={() => { setEditCheck(null); reload(); }} /></Modal>}
      {detail && <Modal title={detail.name} onClose={() => setDetail(null)} wide><CheckDetail check={detail} /></Modal>}
    </>
  );
}
