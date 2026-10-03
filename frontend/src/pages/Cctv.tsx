import { useState } from "react";
import { Camera, HardDrive } from "lucide-react";
import { api, type Page } from "../api";
import { useCustomers } from "../components/trade";
import { Badge, Empty, ErrorBanner, PageHeader, Spinner, useAsync } from "../components/ui";
import { MonitorBadge } from "./Monitoring";

type A = { id: number; customer_id: number; customer_name: string; asset_type: string; name: string; brand: string | null; model: string | null; ip_address: string | null; site_location: string | null; recorder_id: number | null; channel: number | null; resolution: string | null; hdd_capacity_gb: number | null; retention_days: number | null; warranty_status: string; warranty_until: string | null; monitor_status: string | null; open_tickets: number };

const fetchType = (t: string, customer: string) => api<Page<A>>(`/assets?asset_type=${t}&size=200${customer ? `&customer_id=${customer}` : ""}`).then((p) => p.items);
const W: Record<string, "green" | "amber" | "red" | "slate"> = { in_warranty: "green", expiring: "amber", expired: "red", unknown: "slate" };

function CameraRow({ c }: { c: A }) {
  return (
    <tr className="border-t border-slate-100 dark:border-slate-800">
      <td className="td w-14 text-center font-mono text-xs">{c.channel ?? "—"}</td>
      <td className="td"><div className="font-medium">{c.name}</div><div className="text-xs text-slate-500">{[c.brand, c.model, c.resolution].filter(Boolean).join(" · ")}{c.site_location ? ` · ${c.site_location}` : ""}</div></td>
      <td className="td font-mono text-xs">{c.ip_address}</td>
      <td className="td">{c.warranty_until && <Badge tone={W[c.warranty_status]}>{c.warranty_status.replace("_", " ")}</Badge>}</td>
      <td className="td"><MonitorBadge s={c.monitor_status} />{c.open_tickets > 0 && <div className="text-xs text-amber-700">{c.open_tickets} open job(s)</div>}</td>
    </tr>
  );
}

export default function Cctv() {
  const customers = useCustomers();
  const [customer, setCustomer] = useState("");
  const { data, error, loading } = useAsync(() => Promise.all(["dvr", "nvr", "camera"].map((t) => fetchType(t, customer))), [customer]);
  const recorders = data ? [...data[0], ...data[1]].sort((a, b) => a.customer_name.localeCompare(b.customer_name) || a.name.localeCompare(b.name)) : [];
  const cameras = data?.[2] ?? [];
  const loose = cameras.filter((c) => !c.recorder_id || !recorders.some((r) => r.id === c.recorder_id));
  return (
    <>
      <PageHeader title="CCTV" subtitle="Recorders and the cameras on each channel, with warranty and live network status" />
      <ErrorBanner message={error} />
      <div className="mb-3 flex flex-wrap gap-2">
        <select className="input !w-auto" value={customer} onChange={(e) => setCustomer(e.target.value)} aria-label="Customer"><option value="">All customers</option>{customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
        {data && <span className="self-center text-sm text-slate-500">{recorders.length} recorder{recorders.length === 1 ? "" : "s"} · {cameras.length} camera{cameras.length === 1 ? "" : "s"}</span>}
      </div>
      {loading && !data ? <Spinner /> : !recorders.length && !cameras.length ? (
        <div className="card"><Empty title="No CCTV equipment" hint="Add DVRs, NVRs and cameras under IT Assets (or register them from an installation job), choosing the recorder and channel for each camera." /></div>
      ) : <div className="space-y-4">
        {recorders.map((r) => {
          const cams = cameras.filter((c) => c.recorder_id === r.id).sort((a, b) => (a.channel ?? 999) - (b.channel ?? 999));
          return (
            <div key={r.id} className="card !p-0">
              <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 p-3 dark:border-slate-800">
                <HardDrive size={18} className="text-slate-400" />
                <div><div className="font-medium">{r.name} <span className="text-xs uppercase text-slate-500">{r.asset_type}</span></div>
                  <div className="text-xs text-slate-500">{r.customer_name}{r.site_location ? ` · ${r.site_location}` : ""}{r.ip_address ? ` · ${r.ip_address}` : ""}</div></div>
                <div className="ml-auto flex flex-wrap items-center gap-3 text-xs text-slate-500">
                  {r.hdd_capacity_gb !== null && <span>{r.hdd_capacity_gb >= 1000 ? `${(r.hdd_capacity_gb / 1000).toFixed(1)} TB` : `${r.hdd_capacity_gb} GB`}</span>}
                  {r.retention_days !== null && <span>keeps {r.retention_days} days</span>}
                  <span>{cams.length} camera{cams.length === 1 ? "" : "s"}</span>
                  <MonitorBadge s={r.monitor_status} />
                </div>
              </div>
              {!cams.length ? <p className="p-3 text-sm text-slate-500">No cameras linked to this recorder.</p> : (
                <div className="overflow-x-auto"><table className="w-full min-w-[600px] text-sm">
                  <thead><tr><th className="th">Ch</th><th className="th">Camera</th><th className="th">IP</th><th className="th">Warranty</th><th className="th">Network</th></tr></thead>
                  <tbody>{cams.map((c) => <CameraRow key={c.id} c={c} />)}</tbody></table></div>
              )}
            </div>
          );
        })}
        {!!loose.length && <div className="card !p-0">
          <div className="flex items-center gap-2 border-b border-slate-200 p-3 dark:border-slate-800"><Camera size={18} className="text-slate-400" /><span className="font-medium">Cameras not linked to a recorder</span></div>
          <div className="overflow-x-auto"><table className="w-full min-w-[600px] text-sm"><tbody>{loose.map((c) => <CameraRow key={c.id} c={c} />)}</tbody></table></div>
        </div>}
      </div>}
    </>
  );
}
