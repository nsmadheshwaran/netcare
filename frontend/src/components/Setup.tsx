import { useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, Circle, X } from "lucide-react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBanner, Spinner, useAsync } from "./ui";

type Module = { key: string; label: string; detail: string; requires: string | null; enabled: boolean };
type Step = { key: string; title: string; hint: string; done: boolean; link: string };

/** Settings → Modules. Owners only; the API enforces it. */
export function ModuleSwitches() {
  const { can, refresh } = useAuth();
  const { data, error, reload } = useAsync(() => api<Module[]>("/organization/modules"), []);
  const [err, setErr] = useState<string | null>(null);
  if (error) return <ErrorBanner message={error} />;
  if (!data) return <Spinner />;
  const editable = can("org.manage");
  const toggle = (m: Module) => {
    const on = new Set(data.filter((x) => x.enabled).map((x) => x.key));
    if (m.enabled) {
      on.delete(m.key);
      data.filter((x) => x.requires === m.key).forEach((x) => on.delete(x.key)); // dependants go too
    } else {
      on.add(m.key);
      if (m.requires) on.add(m.requires);
    }
    api("/organization/modules", { method: "PUT", json: { enabled: [...on] } })
      .then(() => { reload(); refresh(); }).catch((e) => setErr(e.message));
  };
  return (
    <div className="card">
      <h2 className="mb-1 font-semibold">Modules</h2>
      <p className="mb-3 text-sm text-slate-500">Switch off what your business does not use. It disappears from the menu and its API is blocked for everyone; the data is kept and comes back when you switch it on again. Customers, products, stock and reports are always on.</p>
      <ErrorBanner message={err} />
      <ul className="divide-y divide-slate-100 dark:divide-slate-800">{data.map((m) => (
        <li key={m.key} className="flex items-center gap-3 py-2">
          <div className="flex-1"><div className="text-sm font-medium">{m.label}</div>
            <div className="text-xs text-slate-500">{m.detail}{m.requires ? ` · needs ${data.find((x) => x.key === m.requires)?.label}` : ""}</div></div>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={m.enabled} disabled={!editable} onChange={() => toggle(m)} aria-label={m.label} />{m.enabled ? "On" : "Off"}</label>
        </li>))}</ul>
    </div>
  );
}

/** Dashboard checklist for owners until every step is done (or hidden on this device). */
export function Onboarding() {
  const { can, current } = useAuth();
  const key = `netcare.onboarding.hidden.${current?.organization_id}`;
  const [hidden, setHidden] = useState(() => { try { return localStorage.getItem(key) === "1"; } catch { return false; } });
  const { data } = useAsync(() => can("org.manage") && !hidden ? api<{ steps: Step[]; done: number; total: number; complete: boolean }>("/organization/onboarding") : Promise.resolve(null), [hidden]);
  if (!data || data.complete) return null;
  return (
    <div className="card mb-4">
      <div className="mb-2 flex items-center gap-2">
        <h2 className="font-semibold">Get started</h2><span className="text-sm text-slate-500">{data.done} of {data.total} done</span>
        <button className="ml-auto rounded p-1 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800" aria-label="Hide checklist" title="Hide on this device"
          onClick={() => { try { localStorage.setItem(key, "1"); } catch { /* private mode */ } setHidden(true); }}><X size={16} /></button>
      </div>
      <div className="mb-3 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800"><div className="h-full bg-indigo-500" style={{ width: `${(data.done / data.total) * 100}%` }} /></div>
      <ul className="grid gap-2 sm:grid-cols-2">{data.steps.map((s) => (
        <li key={s.key}>
          <Link to={s.link} className="flex gap-2 rounded-lg p-2 hover:bg-slate-50 dark:hover:bg-slate-800/40">
            {s.done ? <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-emerald-600" /> : <Circle size={18} className="mt-0.5 shrink-0 text-slate-300" />}
            <span><span className={`block text-sm ${s.done ? "text-slate-400 line-through" : "font-medium"}`}>{s.title}</span><span className="block text-xs text-slate-500">{s.hint}</span></span>
          </Link>
        </li>))}</ul>
    </div>
  );
}
