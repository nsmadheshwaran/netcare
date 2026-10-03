import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Bell, CheckCheck, Mail } from "lucide-react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Badge, Empty, ErrorBanner, PageHeader, Pager, Spinner, useAsync } from "../components/ui";

type N = { id: number; kind: string; severity: "info" | "warning" | "critical" | "success"; title: string; body: string | null; link: string | null; created_at: string; read_at: string | null };
type Prefs = { email_configured: boolean; email_address: string; kinds: { kind: string; label: string; in_app: boolean; email: boolean }[] };
const DOT: Record<string, string> = { critical: "bg-red-500", warning: "bg-amber-500", success: "bg-emerald-500", info: "bg-indigo-500" };
const ago = (iso: string) => {
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : new Date(iso).toLocaleDateString("en-IN");
};

/** Header bell: unread count, refreshed every minute and when the window regains focus. */
export function NotificationBell() {
  const [count, setCount] = useState(0);
  useEffect(() => {
    let alive = true;
    const load = () => api<{ unread: number }>("/notifications/unread-count").then((r) => alive && setCount(r.unread)).catch(() => {});
    load();
    const t = setInterval(load, 60_000);
    window.addEventListener("focus", load);
    window.addEventListener("netcare:notifications", load);
    return () => { alive = false; clearInterval(t); window.removeEventListener("focus", load); window.removeEventListener("netcare:notifications", load); };
  }, []);
  return (
    <Link to="/notifications" className="btn-ghost relative !px-2" aria-label={`Notifications${count ? `, ${count} unread` : ""}`} title="Notifications">
      <Bell size={16} />
      {count > 0 && <span className="absolute -right-1 -top-1 min-w-4 rounded-full bg-red-600 px-1 text-center text-[10px] font-semibold leading-4 text-white">{count > 99 ? "99+" : count}</span>}
    </Link>
  );
}
const refreshBell = () => window.dispatchEvent(new Event("netcare:notifications"));

function Preferences() {
  const { data, error, reload } = useAsync(() => api<Prefs>("/notifications/preferences"), []);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  if (error) return <ErrorBanner message={error} />;
  if (!data) return <Spinner />;
  const save = (kind: string, patch: { in_app?: boolean; email?: boolean }) => {
    const k = data.kinds.find((x) => x.kind === kind)!;
    api("/notifications/preferences", { method: "PUT", json: [{ ...k, ...patch }] }).then(reload).catch((e) => setErr(e.message));
  };
  return (
    <div className="card">
      <ErrorBanner message={err} />
      <h2 className="mb-1 font-semibold">What to tell me</h2>
      <p className="mb-3 text-sm text-slate-500">{data.email_configured ? <>Emails go to <b>{data.email_address}</b>.</> : "Email is not set up on this server, so only in-app notifications are delivered. Your administrator can configure it (see the notifications guide)."}</p>
      <table className="w-full text-sm">
        <thead><tr><th className="th">Notification</th><th className="th text-center">In app</th><th className="th text-center">Email</th></tr></thead>
        <tbody>{data.kinds.map((k) => (
          <tr key={k.kind} className="border-t border-slate-100 dark:border-slate-800">
            <td className="td">{k.label}</td>
            <td className="td text-center"><input type="checkbox" aria-label={`${k.label}: in app`} checked={k.in_app} onChange={(e) => save(k.kind, { in_app: e.target.checked })} /></td>
            <td className="td text-center"><input type="checkbox" aria-label={`${k.label}: email`} checked={k.email} disabled={!data.email_configured} onChange={(e) => save(k.kind, { email: e.target.checked })} /></td>
          </tr>))}</tbody>
      </table>
      {data.email_configured && <button className="btn-ghost mt-3" onClick={() => api<{ queued_to: string }>("/notifications/test-email", { method: "POST" }).then((r) => setMsg(`Test email queued to ${r.queued_to}; it should arrive within a minute or two.`)).catch((e) => setErr(e.message))}><Mail size={15} /> Send me a test email</button>}
      {msg && <p className="mt-2 text-sm text-emerald-600">{msg}</p>}
      <p className="mt-3 text-xs text-slate-500">SMS and WhatsApp alerts need an account with a messaging provider and are not set up.</p>
    </div>
  );
}

function Outbox() {
  const { data, error } = useAsync(() => api<any>("/notifications/outbox"), []);
  if (error) return <ErrorBanner message={error} />;
  if (!data) return <Spinner />;
  return (
    <div className="card !p-0">
      <div className="border-b border-slate-200 p-3 text-sm dark:border-slate-800"><b>Email delivery</b> <span className="text-slate-500">(last 100) {data.email_configured ? "" : "· email not configured"}</span></div>
      {!data.items.length ? <Empty title="No emails yet" /> : <div className="overflow-x-auto"><table className="w-full min-w-[640px] text-sm"><tbody>{data.items.map((e: any) => (
        <tr key={e.id} className="border-t border-slate-100 dark:border-slate-800"><td className="td">{e.subject}</td><td className="td text-xs">{e.to}</td>
          <td className="td"><Badge tone={e.status === "sent" ? "green" : e.status === "failed" ? "red" : "amber"}>{e.status}</Badge>{e.attempts > 1 && <span className="ml-1 text-xs text-slate-500">{e.attempts} tries</span>}</td>
          <td className="td text-xs text-red-600">{e.last_error}</td><td className="td text-xs text-slate-500">{ago(e.created_at)}</td></tr>))}</tbody></table></div>}
    </div>
  );
}

export default function Notifications() {
  const { can } = useAuth();
  const nav = useNavigate();
  const [tab, setTab] = useState<"all" | "unread" | "prefs" | "outbox">("unread");
  const [page, setPage] = useState(1);
  const [err, setErr] = useState<string | null>(null);
  const list = useAsync(() => tab === "all" || tab === "unread" ? api<{ items: N[]; total: number; page: number; size: number }>(`/notifications?page=${page}${tab === "unread" ? "&unread=true" : ""}`) : Promise.resolve(null), [tab, page]);
  const open = (n: N) => {
    const go = () => n.link && nav(n.link);
    if (n.read_at) return go();
    api(`/notifications/${n.id}/read`, { method: "POST" }).then(() => { refreshBell(); go(); if (!n.link) list.reload(); }).catch((e) => setErr(e.message));
  };
  const tabs: [typeof tab, string][] = [["unread", "Unread"], ["all", "All"], ["prefs", "Preferences"], ...(can("org.manage") ? [["outbox", "Email delivery"] as [typeof tab, string]] : [])];
  return (
    <>
      <PageHeader title="Alerts" subtitle="Notifications about your work and the businesses you manage"
        actions={(tab === "unread" || tab === "all") && <button className="btn-ghost" onClick={() => api("/notifications/read-all", { method: "POST" }).then(() => { refreshBell(); list.reload(); }).catch((e) => setErr(e.message))}><CheckCheck size={15} /> Mark all read</button>} />
      <ErrorBanner message={err || list.error} />
      <div className="mb-3 flex gap-1 border-b border-slate-200 dark:border-slate-800">
        {tabs.map(([k, l]) => <button key={k} onClick={() => { setTab(k); setPage(1); }} className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === k ? "border-indigo-600 font-medium text-indigo-700 dark:text-indigo-300" : "border-transparent text-slate-500"}`}>{l}</button>)}
      </div>
      {tab === "prefs" ? <Preferences /> : tab === "outbox" ? <Outbox /> : (
        <div className="card !p-0">
          {!list.data ? <Spinner /> : !list.data.items.length ? <Empty title={tab === "unread" ? "You're all caught up" : "No notifications yet"} hint="Device outages, jobs assigned to you, leave requests and daily summaries appear here." /> : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">{list.data.items.map((n) => (
              <li key={n.id}>
                <button onClick={() => open(n)} className={`flex w-full gap-3 p-3 text-left hover:bg-slate-50 dark:hover:bg-slate-800/40 ${n.read_at ? "opacity-70" : ""}`}>
                  <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${n.read_at ? "bg-transparent" : DOT[n.severity]}`} />
                  <span className="min-w-0 flex-1"><span className={`block text-sm ${n.read_at ? "" : "font-medium"}`}>{n.title}</span>
                    {n.body && <span className="block text-sm text-slate-500">{n.body}</span>}</span>
                  <span className="shrink-0 text-xs text-slate-400">{ago(n.created_at)}</span>
                </button>
              </li>))}</ul>
          )}
          {list.data && list.data.total > list.data.size && <Pager page={page} size={list.data.size} total={list.data.total} onPage={setPage} />}
        </div>
      )}
    </>
  );
}
