import { useState, type FormEvent } from "react";
import { CalendarClock, CheckCircle2, FileSignature, MessageSquare, Package, Plus, Printer, Receipt, Undo2, Wrench, XCircle } from "lucide-react";
import { api, inr, openPdf, qty, type Page } from "../api";
import { useAuth } from "../auth";
import { PartySelect, today, useCustomers, useLocations, useProducts } from "../components/trade";
import { AttachedDocuments } from "./Documents";
import { Badge, confirmAction, Empty, ErrorBanner, Field, Modal, PageHeader, Pager, Spinner, useAsync } from "../components/ui";

export type Ticket = {
  id: number; number: string; ticket_type: string; priority: string; status: string; customer_id: number; customer_name: string;
  contact_name: string | null; contact_phone: string | null; asset_id: number | null; asset_name: string | null; equipment: string | null;
  serial_number: string | null; accessories_received: string | null; reported_problem: string; diagnosis: string | null;
  work_performed: string | null; resolution: string | null; assigned_to: number | null; technician_name: string | null;
  scheduled_visit: string | null; estimate_amount: string | null; labour_charge: string; customer_approval: string;
  approval_note: string | null; is_warranty: boolean; sales_invoice_id: number | null; invoice_number: string | null;
  parts_total: string; charges_total: string; created_at: string; completed_at: string | null;
  parts: { id: number; product_name: string; sku: string; quantity: string; unit_price: string; returned: boolean }[];
  events: { id: number; kind: string; message: string; user_name: string | null; created_at: string }[];
};
type Employee = { id: number; name: string; is_technician: boolean; user_id: number | null };
type Asset = { id: number; name: string; asset_type: string; serial_number: string | null; site_location: string | null };

const STATUS_TONE: Record<string, "slate" | "green" | "amber" | "red" | "indigo"> = {
  new: "indigo", assigned: "indigo", in_progress: "amber", waiting_parts: "red", waiting_customer: "amber",
  completed: "green", closed: "slate", cancelled: "slate",
};
const PRIO_TONE: Record<string, "slate" | "amber" | "red"> = { low: "slate", normal: "slate", high: "amber", urgent: "red" };
const NEXT: Record<string, string[]> = {
  new: ["in_progress", "waiting_customer"], assigned: ["in_progress", "waiting_parts", "waiting_customer"],
  in_progress: ["waiting_parts", "waiting_customer", "completed"], waiting_parts: ["in_progress"],
  waiting_customer: ["in_progress"], completed: ["closed", "in_progress"], closed: [], cancelled: [],
};
const LABEL: Record<string, string> = { in_progress: "Start work", waiting_parts: "Waiting for parts", waiting_customer: "Waiting for customer", completed: "Mark completed", closed: "Close", assigned: "Assigned" };

export const StatusBadge = ({ s }: { s: string }) => <Badge tone={STATUS_TONE[s] ?? "slate"}>{s.replace(/_/g, " ")}</Badge>;
const toLocalInput = (iso: string | null) => (iso ? new Date(iso).toLocaleString("sv-SE").slice(0, 16).replace(" ", "T") : "");
const fromLocalInput = (v: string) => (v ? new Date(v).toISOString() : null);
const fmtWhen = (iso: string) => new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });

export function useEmployees(technicians = false) {
  return useAsync(() => api<Page<Employee>>(`/employees?size=200${technicians ? "&technicians=true" : ""}`), [technicians]).data?.items ?? [];
}

function NewTicketForm({ onDone }: { onDone: (id?: number) => void }) {
  const customers = useCustomers();
  const locations = useLocations();
  const techs = useEmployees(true);
  const [f, setF] = useState<any>({ ticket_type: "repair", priority: "normal", customer_id: "", asset_id: "", equipment: "", serial_number: "", accessories_received: "", reported_problem: "", assigned_to: "", scheduled_visit: "", estimate_amount: "", labour_charge: "", is_warranty: false, location_id: "" });
  const assets = useAsync(() => f.customer_id ? api<Page<Asset>>(`/assets?customer_id=${f.customer_id}&size=200`) : Promise.resolve(null), [f.customer_id]);
  const [error, setError] = useState<string | null>(null);
  const set = (k: string) => (e: React.ChangeEvent<any>) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  async function submit(e: FormEvent) {
    e.preventDefault();
    const n = (v: string) => (v ? Number(v) : null);
    const body = { ...f, customer_id: Number(f.customer_id), asset_id: n(f.asset_id), assigned_to: n(f.assigned_to), location_id: n(f.location_id),
      scheduled_visit: fromLocalInput(f.scheduled_visit), estimate_amount: f.estimate_amount || null, labour_charge: f.labour_charge || "0",
      equipment: f.equipment || null, serial_number: f.serial_number || null, accessories_received: f.accessories_received || null };
    try { const t = await api<Ticket>("/service-tickets", { method: "POST", json: body }); onDone(t.id); } catch (err: any) { setError(err.message); }
  }
  return (
    <form onSubmit={submit} className="space-y-3">
      <ErrorBanner message={error} />
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Type"><select className="input" value={f.ticket_type} onChange={set("ticket_type")}>
          <option value="repair">Repair</option><option value="installation">Installation</option><option value="maintenance">Maintenance</option><option value="complaint">Complaint</option></select></Field>
        <PartySelect label="Customer *" value={f.customer_id} onChange={(v) => setF({ ...f, customer_id: v, asset_id: "" })} options={customers} />
        <Field label="Priority"><select className="input" value={f.priority} onChange={set("priority")}>
          {["low", "normal", "high", "urgent"].map((p) => <option key={p} value={p}>{p}</option>)}</select></Field>
        <Field label="Registered equipment"><select className="input" value={f.asset_id} onChange={set("asset_id")} disabled={!assets.data?.items.length}>
          <option value="">{assets.data?.items.length ? "— none / walk-in item —" : "No registered equipment"}</option>
          {assets.data?.items.map((a) => <option key={a.id} value={a.id}>{a.name}{a.serial_number ? ` (${a.serial_number})` : ""}{a.site_location ? `, ${a.site_location}` : ""}</option>)}</select></Field>
        {!f.asset_id && <>
          <Field label="Equipment (walk-in)"><input className="input" value={f.equipment} onChange={set("equipment")} placeholder="e.g. HP laptop 15s" /></Field>
          <Field label="Serial no."><input className="input" value={f.serial_number} onChange={set("serial_number")} /></Field>
        </>}
        <Field label="Problem reported *" className="sm:col-span-3"><textarea className="input" rows={2} required minLength={3} value={f.reported_problem} onChange={set("reported_problem")} /></Field>
        <Field label="Received with (accessories)" className="sm:col-span-2"><input className="input" value={f.accessories_received} onChange={set("accessories_received")} placeholder="e.g. charger, bag" /></Field>
        <Field label="Parts taken from"><select className="input" value={f.location_id} onChange={set("location_id")}><option value="">Main location</option>{locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></Field>
        <Field label="Assign technician"><select className="input" value={f.assigned_to} onChange={set("assigned_to")}><option value="">— later —</option>{techs.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</select></Field>
        <Field label="Visit / pickup time"><input className="input" type="datetime-local" value={f.scheduled_visit} onChange={set("scheduled_visit")} /></Field>
        <Field label="Estimate ₹ (needs customer OK)"><input className="input" type="number" step="0.01" min="0" value={f.estimate_amount} onChange={set("estimate_amount")} /></Field>
      </div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.is_warranty} onChange={set("is_warranty")} /> Warranty / free of charge job</label>
      {techs.length === 0 && <p className="text-xs text-amber-700">No technicians yet. Add employees with "Technician" ticked under Employees.</p>}
      <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={() => onDone()}>Cancel</button><button className="btn-primary">Open ticket</button></div>
    </form>
  );
}

function RegisterAssets({ t, onDone }: { t: Ticket; onDone: () => void }) {
  const [rows, setRows] = useState([{ asset_type: "camera", name: "", serial_number: "", site_location: "", ip_address: "", warranty_months: "12" }]);
  const [maint, setMaint] = useState({ on: true, title: "Quarterly CCTV maintenance", interval_months: "3" });
  const [error, setError] = useState<string | null>(null);
  const set = (i: number, k: string, v: string) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  async function submit(e: FormEvent) {
    e.preventDefault();
    const assets = rows.map((r) => ({ ...r, serial_number: r.serial_number || null, site_location: r.site_location || null, ip_address: r.ip_address || null, warranty_months: r.warranty_months ? Number(r.warranty_months) : null }));
    try {
      await api(`/service-tickets/${t.id}/assets`, { method: "POST", json: { assets, maintenance: maint.on ? { title: maint.title, interval_months: Number(maint.interval_months) } : null } });
      onDone();
    } catch (err: any) { setError(err.message); }
  }
  return (
    <form onSubmit={submit} className="space-y-3">
      <ErrorBanner message={error} />
      <p className="text-sm text-slate-500">Record what was installed at {t.customer_name}. Each item gets a warranty date and its own service history.</p>
      {rows.map((r, i) => (
        <div key={i} className="grid grid-cols-2 gap-2 sm:grid-cols-6">
          <select className="input" value={r.asset_type} onChange={(e) => set(i, "asset_type", e.target.value)} aria-label="Type">
            {["camera", "dvr", "nvr", "storage", "router", "switch", "access_point", "computer", "printer", "ups", "other"].map((x) => <option key={x}>{x}</option>)}</select>
          <input className="input" required placeholder="Name, e.g. Camera 3" value={r.name} onChange={(e) => set(i, "name", e.target.value)} aria-label="Name" />
          <input className="input" placeholder="Serial no." value={r.serial_number} onChange={(e) => set(i, "serial_number", e.target.value)} aria-label="Serial" />
          <input className="input" placeholder="Where (Gate 2…)" value={r.site_location} onChange={(e) => set(i, "site_location", e.target.value)} aria-label="Site location" />
          <input className="input" placeholder="IP address" value={r.ip_address} onChange={(e) => set(i, "ip_address", e.target.value)} aria-label="IP address" />
          <input className="input" type="number" min="0" max="120" placeholder="Warranty months" value={r.warranty_months} onChange={(e) => set(i, "warranty_months", e.target.value)} aria-label="Warranty months" />
        </div>
      ))}
      <button type="button" className="btn-ghost" onClick={() => setRows([...rows, { ...rows[rows.length - 1], name: "", serial_number: "", ip_address: "" }])}><Plus size={15} /> Add item</button>
      <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={maint.on} onChange={(e) => setMaint({ ...maint, on: e.target.checked })} /> Start a maintenance schedule</label>
        {maint.on && <div className="mt-2 grid grid-cols-3 gap-2">
          <input className="input col-span-2" value={maint.title} onChange={(e) => setMaint({ ...maint, title: e.target.value })} aria-label="Schedule title" />
          <select className="input" value={maint.interval_months} onChange={(e) => setMaint({ ...maint, interval_months: e.target.value })} aria-label="Interval">
            {[["1", "Monthly"], ["3", "Every 3 months"], ["6", "Every 6 months"], ["12", "Yearly"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        </div>}
      </div>
      <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={onDone}>Cancel</button><button className="btn-primary">Register {rows.length} item(s)</button></div>
    </form>
  );
}

function SignaturePad({ ticketId, onDone }: { ticketId: number; onDone: () => void }) {
  const [name, setName] = useState("");
  const [drawing, setDrawing] = useState(false);
  const [hasDraw, setHasDraw] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canvas = () => document.getElementById("sig-canvas") as HTMLCanvasElement | null;
  const startDraw = (e: any) => { setDrawing(true); drawAt(e, true); };
  const stopDraw = () => { setDrawing(false); canvas()?.getContext("2d")?.beginPath(); };
  const draw = (e: any) => drawAt(e, false);
  const drawAt = (e: any, force: boolean) => {
    if (!drawing && !force) return;
    const canvas = document.getElementById("sig-canvas") as HTMLCanvasElement;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const rect = canvas.getBoundingClientRect();
    const x = ((e.touches ? e.touches[0].clientX : e.clientX) - rect.left) * (canvas.width / rect.width);
    const y = ((e.touches ? e.touches[0].clientY : e.clientY) - rect.top) * (canvas.height / rect.height);
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.strokeStyle = "#0f172a";
    ctx.lineTo(x, y);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x, y);
    setHasDraw(true);
  };
  const clear = () => {
    const canvas = document.getElementById("sig-canvas") as HTMLCanvasElement;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    ctx?.clearRect(0, 0, canvas.width, canvas.height);
    ctx?.beginPath();
    setHasDraw(false);
  };

  async function save() {
    if (!name.trim()) { setError("Customer name is required"); return; }
    if (!hasDraw) { setError("Please sign in the box first"); return; }
    try {
      await api(`/service-tickets/${ticketId}/approval`, {
        method: "POST",
        json: { decision: "approved", note: `Signed on screen by ${name.trim()} (signature image is not stored)` },
      });
      onDone();
    } catch (err: any) { setError(err.message); }
  }

  return (
    <div className="space-y-3">
      <ErrorBanner message={error} />
      <Field label="Customer Full Name *"><input className="input" required value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Ramesh Kumar" /></Field>
      <Field label="Sign on touchscreen / tablet below">
        <div className="rounded border border-slate-300 bg-white dark:border-slate-700">
          <canvas id="sig-canvas" width={400} height={150} className="w-full touch-none" onMouseDown={startDraw} onMouseUp={stopDraw} onMouseMove={draw} onTouchStart={startDraw} onTouchEnd={stopDraw} onTouchMove={draw} />
        </div>
      </Field>
      <div className="flex justify-between">
        <button type="button" className="btn-ghost !py-1 text-xs" onClick={clear}>Clear canvas</button>
        <div className="flex gap-2">
          <button type="button" className="btn-ghost" onClick={onDone}>Cancel</button>
          <button className="btn-primary" onClick={save}>Save signature & approve</button>
        </div>
      </div>
    </div>
  );
}



export function TicketDetail({ id, onChanged }: { id: number; onChanged?: () => void }) {
  const { can } = useAuth();
  const { data: t, error, reload } = useAsync(() => api<Ticket>(`/service-tickets/${id}`), [id]);
  const products = useProducts().filter((p) => !p.is_service);
  const services = useProducts().filter((p) => p.is_service);
  const techs = useEmployees(true);
  const [err, setErr] = useState<string | null>(null);
  const [edit, setEdit] = useState<any>(null);
  const [part, setPart] = useState({ product_id: "", quantity: "1" });
  const [note, setNote] = useState("");
  const [mode, setMode] = useState<"view" | "assets" | "sig">("view");
  const office = can("service.edit");

  async function run(fn: () => Promise<unknown>) {
    setErr(null);
    try { await fn(); reload(); onChanged?.(); } catch (e: any) { setErr(e.message); }
  }
  const post = (path: string, json?: unknown) => run(() => api(`/service-tickets/${id}${path}`, { method: "POST", json }));

  if (!t) return error ? <ErrorBanner message={error} /> : <Spinner />;
  if (mode === "assets") return <RegisterAssets t={t} onDone={() => { setMode("view"); reload(); }} />;
  if (mode === "sig") return <SignaturePad ticketId={t.id} onDone={() => { setMode("view"); reload(); onChanged?.(); }} />;
  const open = !["closed", "cancelled"].includes(t.status);
  const form = edit ?? { diagnosis: t.diagnosis ?? "", work_performed: t.work_performed ?? "", resolution: t.resolution ?? "", labour_charge: t.labour_charge, estimate_amount: t.estimate_amount ?? "", scheduled_visit: toLocalInput(t.scheduled_visit) };
  const dirty = edit !== null;

  async function invoice() {
    let body: any = {};
    if (Number(t!.labour_charge) > 0) {
      const svc = services[0];
      const choice = window.prompt(services.length
        ? `Labour ${inr(t!.labour_charge)}: type the GST rate %, or leave blank to bill it as "${svc.name}" (${svc.gst_rate ?? 0}%)`
        : `Labour ${inr(t!.labour_charge)}: GST rate % for labour?`, "");
      if (choice === null) return;
      body = choice.trim() ? { labour_tax_rate: choice.trim() } : svc ? { labour_product_id: svc.id } : {};
    }
    run(async () => { const inv = await api<any>(`/service-tickets/${id}/invoice`, { method: "POST", json: body }); window.alert(`Draft invoice created for ${inr(inv.total)}. Review and issue it under Sales.`); });
  }

  return (
    <div className="space-y-4">
      <ErrorBanner message={err} />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-lg font-semibold">{t.number} <StatusBadge s={t.status} /> <Badge tone={PRIO_TONE[t.priority]}>{t.priority}</Badge> {t.is_warranty && <Badge tone="green">warranty</Badge>}</div>
          <div className="text-sm text-slate-500">{t.ticket_type} · {t.customer_name}{t.contact_phone ? ` · ${t.contact_phone}` : ""} · opened {fmtWhen(t.created_at)}</div>
          <div className="text-sm">{t.asset_name ?? t.equipment ?? "No equipment recorded"}{t.serial_number ? ` · S/N ${t.serial_number}` : ""}{t.accessories_received ? ` · with ${t.accessories_received}` : ""}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn-ghost" onClick={() => openPdf(`/service-tickets/${id}/pdf`).catch((e) => setErr(e.message))}><Printer size={15} /> {["completed", "closed"].includes(t.status) ? "Completion report" : "Job sheet"}</button>
          {open && NEXT[t.status].filter((s) => office || s !== "closed").map((s) => (
            <button key={s} className={s === "completed" || s === "in_progress" ? "btn-primary" : "btn-ghost"} onClick={() => post("/status", { status: s })}>
              {s === "completed" ? <CheckCircle2 size={15} /> : null}{t.status === "completed" && s === "in_progress" ? "Reopen" : LABEL[s]}
            </button>
          ))}
          {office && open && <button className="btn-ghost text-red-600" onClick={() => { const r = window.prompt("Reason for cancelling?"); if (r) post("/status", { status: "cancelled", note: r }); }}><XCircle size={15} /> Cancel</button>}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="card !p-3"><div className="text-xs text-slate-500">Technician</div>
          {office && open ? <select className="input mt-1" value={t.assigned_to ?? ""} onChange={(e) => post("/assign", { employee_id: e.target.value ? Number(e.target.value) : null })} aria-label="Technician">
            <option value="">Unassigned</option>{techs.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</select> : <div className="font-medium">{t.technician_name ?? "Unassigned"}</div>}
        </div>
        <div className="card !p-3"><div className="text-xs text-slate-500">Estimate / approval</div>
          <div className="font-medium">{t.estimate_amount ? inr(t.estimate_amount) : "No estimate"} {t.customer_approval !== "not_required" && <Badge tone={t.customer_approval === "approved" ? "green" : t.customer_approval === "pending" ? "amber" : "red"}>{t.customer_approval}</Badge>}</div>
          {t.customer_approval === "pending" && <div className="mt-1 flex flex-wrap gap-2">
            <button className="btn-ghost !py-1 text-xs" onClick={() => { const n = window.prompt("How was it approved? (e.g. by phone, spoke to Mr. Ravi)"); if (n !== null) post("/approval", { decision: "approved", note: n || null }); }}>Approved</button>
            <button className="btn-primary !py-1 text-xs" onClick={() => setMode("sig")}><FileSignature size={13} /> Sign on tablet</button>
            <button className="btn-ghost !py-1 text-xs text-red-600" onClick={() => post("/approval", { decision: "declined" })}>Declined</button></div>}
          {t.approval_note && <div className="text-xs text-slate-500">{t.approval_note}</div>}
        </div>
        <div className="card !p-3"><div className="text-xs text-slate-500">Charges (before GST)</div>
          <div className="font-medium">{t.is_warranty ? "No charge (warranty)" : inr(t.charges_total)}</div>
          <div className="text-xs text-slate-500">Parts {inr(t.parts_total)} + labour {inr(t.labour_charge)}</div>
          {t.invoice_number ? <div className="text-xs text-emerald-600">Invoice {t.invoice_number}</div>
            : office && can("sales.edit") && ["completed", "closed"].includes(t.status) && !t.is_warranty && Number(t.charges_total) > 0 &&
              <button className="btn-ghost mt-1 !py-1 text-xs" onClick={invoice}><Receipt size={13} /> Create invoice</button>}
        </div>
      </div>

      <div className="rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-800/40"><span className="font-medium">Problem: </span>{t.reported_problem}</div>
      {open ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Diagnosis"><textarea className="input" rows={2} value={form.diagnosis} onChange={(e) => setEdit({ ...form, diagnosis: e.target.value })} /></Field>
          <Field label="Work performed (needed to complete)"><textarea className="input" rows={2} value={form.work_performed} onChange={(e) => setEdit({ ...form, work_performed: e.target.value })} /></Field>
          <Field label="Resolution / advice to customer"><textarea className="input" rows={2} value={form.resolution} onChange={(e) => setEdit({ ...form, resolution: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Labour ₹"><input className="input" type="number" step="0.01" min="0" disabled={!!t.sales_invoice_id} value={form.labour_charge} onChange={(e) => setEdit({ ...form, labour_charge: e.target.value })} /></Field>
            <Field label="Estimate ₹"><input className="input" type="number" step="0.01" min="0" value={form.estimate_amount} onChange={(e) => setEdit({ ...form, estimate_amount: e.target.value })} /></Field>
            <Field label="Visit time" className="col-span-2"><input className="input" type="datetime-local" value={form.scheduled_visit} onChange={(e) => setEdit({ ...form, scheduled_visit: e.target.value })} /></Field>
          </div>
          {dirty && <div className="flex gap-2 sm:col-span-2">
            <button className="btn-primary" onClick={() => { const b: any = { diagnosis: form.diagnosis || null, work_performed: form.work_performed || null, resolution: form.resolution || null, scheduled_visit: fromLocalInput(form.scheduled_visit) };
              if (!t.sales_invoice_id) b.labour_charge = form.labour_charge || "0";
              if (form.estimate_amount !== (t.estimate_amount ?? "")) b.estimate_amount = form.estimate_amount || null;
              run(() => api(`/service-tickets/${id}`, { method: "PATCH", json: b })).then(() => setEdit(null)); }}>Save</button>
            <button className="btn-ghost" onClick={() => setEdit(null)}>Discard</button></div>}
        </div>
      ) : (
        <div className="space-y-1 text-sm">{[["Diagnosis", t.diagnosis], ["Work performed", t.work_performed], ["Resolution", t.resolution]].map(([k, v]) => v && <div key={k}><span className="font-medium">{k}: </span>{v}</div>)}</div>
      )}

      <div>
        <h3 className="mb-2 flex items-center gap-2 font-medium"><Package size={16} /> Parts used <span className="text-xs font-normal text-slate-500">taken from stock when added</span></h3>
        {!t.parts.length ? <p className="text-sm text-slate-500">No parts used.</p> : (
          <table className="w-full text-sm"><tbody>{t.parts.map((p) => (
            <tr key={p.id} className={`border-t border-slate-100 dark:border-slate-800 ${p.returned ? "text-slate-400 line-through" : ""}`}>
              <td className="td">{p.product_name} <span className="text-xs text-slate-400">{p.sku}</span></td><td className="td text-right">{qty(p.quantity)} × {inr(p.unit_price)}</td>
              <td className="td text-right">{!p.returned && open && !t.sales_invoice_id && <button className="text-xs text-indigo-600 hover:underline" onClick={() => confirmAction(`Return ${p.product_name} to stock?`) && post(`/parts/${p.id}/return`)}><Undo2 size={12} className="inline" /> return to stock</button>}</td>
            </tr>))}</tbody></table>
        )}
        {(open || t.status === "completed") && !t.sales_invoice_id && (
          <div className="mt-2 flex flex-wrap gap-2">
            <select className="input !w-auto min-w-56" value={part.product_id} onChange={(e) => setPart({ ...part, product_id: e.target.value })} aria-label="Part">
              <option value="">Add part from stock…</option>{products.map((p) => <option key={p.id} value={p.id}>{p.name} ({qty(p.stock_on_hand)} in stock)</option>)}</select>
            <input className="input !w-24" type="number" step="0.001" min="0.001" value={part.quantity} onChange={(e) => setPart({ ...part, quantity: e.target.value })} aria-label="Quantity" />
            <button className="btn-ghost" disabled={!part.product_id} onClick={() => post("/parts", { product_id: Number(part.product_id), quantity: part.quantity, idempotency_key: crypto.randomUUID() }).then(() => setPart({ product_id: "", quantity: "1" }))}>Add</button>
          </div>
        )}
      </div>

      {office && can("assets.edit") && t.ticket_type === "installation" && t.status !== "cancelled" &&
        <button className="btn-ghost" onClick={() => setMode("assets")}><Wrench size={15} /> Register installed equipment</button>}

      <AttachedDocuments entityType="service_ticket" entityId={t.id} />

      <div>
        <h3 className="mb-2 flex items-center gap-2 font-medium"><MessageSquare size={16} /> Timeline</h3>
        <div className="mb-2 flex gap-2">
          <input className="input" placeholder="Add a note: call made, customer said…" value={note} onChange={(e) => setNote(e.target.value)} />
          <button className="btn-ghost" disabled={!note.trim()} onClick={() => post("/notes", { message: note }).then(() => setNote(""))}>Add</button>
        </div>
        <ol className="space-y-1.5 border-l-2 border-slate-200 pl-3 text-sm dark:border-slate-700">
          {[...t.events].reverse().map((e) => (
            <li key={e.id}><span className="text-xs text-slate-400">{fmtWhen(e.created_at)}{e.user_name ? ` · ${e.user_name}` : ""}</span><div>{e.message}</div></li>
          ))}
        </ol>
      </div>
    </div>
  );
}

function Maintenance() {
  const { can } = useAuth();
  const customers = useCustomers();
  const techs = useEmployees(true);
  const { data, error, reload } = useAsync(() => api<any[]>("/maintenance-schedules"), []);
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState<any>({ customer_id: "", title: "", interval_months: "3", next_due: today(), assigned_to: "" });
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  async function add(e: FormEvent) {
    e.preventDefault();
    try { await api("/maintenance-schedules", { method: "POST", json: { ...f, customer_id: Number(f.customer_id), interval_months: Number(f.interval_months), assigned_to: f.assigned_to ? Number(f.assigned_to) : null } }); setAdding(false); reload(); }
    catch (x: any) { setErr(x.message); }
  }
  async function makeTicket(id: number) {
    try { const t = await api<Ticket>(`/maintenance-schedules/${id}/ticket`, { method: "POST" }); reload(); setOpen(t.id); } catch (x: any) { setErr(x.message); }
  }
  return (
    <>
      <ErrorBanner message={error || err} />
      {can("service.edit") && <div className="mb-3 text-right"><button className="btn-primary" onClick={() => setAdding(true)}><Plus size={16} /> New schedule</button></div>}
      <div className="card !p-0 overflow-x-auto">
        {!data ? <Spinner /> : !data.length ? <Empty title="No maintenance schedules" hint="Schedules are created when you register an installation, or add one here for AMC customers." /> : (
          <table className="w-full min-w-[640px]"><thead className="bg-slate-50 dark:bg-slate-800/50"><tr><th className="th">Customer</th><th className="th">Schedule</th><th className="th">Every</th><th className="th">Last done</th><th className="th">Next due</th><th className="th">Technician</th><th className="th" /></tr></thead>
            <tbody>{data.map((s) => (
              <tr key={s.id} className="border-t border-slate-100 dark:border-slate-800">
                <td className="td">{s.customer_name}</td><td className="td">{s.title}</td><td className="td">{s.interval_months} mo</td><td className="td">{s.last_done ?? "—"}</td>
                <td className="td">{s.next_due} {s.overdue && <Badge tone="red">overdue</Badge>}</td><td className="td">{s.technician_name ?? "—"}</td>
                <td className="td text-right">{s.open_ticket_id ? <button className="text-xs text-indigo-600 hover:underline" onClick={() => setOpen(s.open_ticket_id)}>open ticket</button>
                  : can("service.edit") && <button className="btn-ghost !py-1 text-xs" onClick={() => makeTicket(s.id)}><CalendarClock size={13} /> Create visit ticket</button>}</td>
              </tr>))}</tbody></table>
        )}
      </div>
      {adding && <Modal title="New maintenance schedule" onClose={() => setAdding(false)}>
        <form onSubmit={add} className="space-y-3">
          <PartySelect label="Customer *" value={f.customer_id} onChange={(v) => setF({ ...f, customer_id: v })} options={customers} />
          <Field label="Title *"><input className="input" required minLength={3} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="e.g. AMC: half-yearly server and network check" /></Field>
          <div className="grid grid-cols-3 gap-2">
            <Field label="Every (months)"><input className="input" type="number" min="1" max="60" required value={f.interval_months} onChange={(e) => setF({ ...f, interval_months: e.target.value })} /></Field>
            <Field label="First due"><input className="input" type="date" required value={f.next_due} onChange={(e) => setF({ ...f, next_due: e.target.value })} /></Field>
            <Field label="Technician"><select className="input" value={f.assigned_to} onChange={(e) => setF({ ...f, assigned_to: e.target.value })}><option value="">—</option>{techs.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</select></Field>
          </div>
          <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={() => setAdding(false)}>Cancel</button><button className="btn-primary">Save</button></div>
        </form>
      </Modal>}
      {open && <Modal title="Ticket" wide onClose={() => setOpen(null)}><TicketDetail id={open} onChanged={reload} /></Modal>}
    </>
  );
}

export default function Service() {
  const { can } = useAuth();
  const [tab, setTab] = useState<"tickets" | "maintenance">("tickets");
  const [statusF, setStatusF] = useState("open");
  const [typeF, setTypeF] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const { data, error, loading, reload } = useAsync(() => api<Page<Ticket>>(`/service-tickets?page=${page}&q=${encodeURIComponent(q)}${statusF ? `&status=${statusF}` : ""}${typeF ? `&ticket_type=${typeF}` : ""}`), [page, q, statusF, typeF]);
  return (
    <>
      <PageHeader title="Service management" subtitle="Repairs, installations, complaints and maintenance visits"
        actions={can("service.edit") && tab === "tickets" && <button className="btn-primary" onClick={() => setCreating(true)}><Plus size={16} /> New ticket</button>} />
      <div className="mb-3 flex gap-1">
        {(["tickets", "maintenance"] as const).map((x) => <button key={x} className={`btn ${tab === x ? "bg-indigo-600 text-white" : "text-slate-600 hover:bg-slate-200 dark:text-slate-300 dark:hover:bg-slate-800"}`} onClick={() => setTab(x)}>{x === "tickets" ? "Tickets" : "Maintenance schedules"}</button>)}
      </div>
      {tab === "maintenance" ? <Maintenance /> : <>
        <ErrorBanner message={error} />
        <div className="card !p-0">
          <div className="flex flex-wrap gap-2 border-b border-slate-200 p-3 dark:border-slate-800">
            <input className="input max-w-xs" placeholder="Search number, customer, phone, serial…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
            <select className="input !w-auto" value={statusF} onChange={(e) => { setStatusF(e.target.value); setPage(1); }} aria-label="Status">
              <option value="open">Open</option><option value="">All</option>
              {["new", "assigned", "in_progress", "waiting_parts", "waiting_customer", "completed", "closed", "cancelled"].map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}</select>
            <select className="input !w-auto" value={typeF} onChange={(e) => { setTypeF(e.target.value); setPage(1); }} aria-label="Type">
              <option value="">All types</option>{["repair", "installation", "maintenance", "complaint"].map((s) => <option key={s} value={s}>{s}</option>)}</select>
          </div>
          {loading && !data ? <Spinner /> : !data?.items.length ? <Empty title="No tickets" hint="Open a ticket when a customer brings equipment in or calls with a problem." /> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px]">
                <thead className="bg-slate-50 dark:bg-slate-800/50"><tr><th className="th">Ticket</th><th className="th">Customer</th><th className="th">Equipment / problem</th><th className="th">Technician</th><th className="th">Visit</th><th className="th">Status</th></tr></thead>
                <tbody>{data.items.map((t) => (
                  <tr key={t.id} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/40" onClick={() => setOpen(t.id)}>
                    <td className="td"><div className="font-mono text-xs">{t.number}</div><div className="text-xs text-slate-500">{t.ticket_type}</div></td>
                    <td className="td">{t.customer_name}</td>
                    <td className="td max-w-xs"><div className="truncate">{t.asset_name ?? t.equipment ?? "—"}</div><div className="truncate text-xs text-slate-500">{t.reported_problem}</div></td>
                    <td className="td">{t.technician_name ?? <span className="text-slate-400">unassigned</span>}</td>
                    <td className="td text-xs">{t.scheduled_visit ? fmtWhen(t.scheduled_visit) : "—"}</td>
                    <td className="td"><StatusBadge s={t.status} /> {t.priority !== "normal" && <Badge tone={PRIO_TONE[t.priority]}>{t.priority}</Badge>} {t.customer_approval === "pending" && <Badge tone="amber">needs OK</Badge>}</td>
                  </tr>))}</tbody>
              </table>
              <Pager page={data.page} size={data.size} total={data.total} onPage={setPage} />
            </div>
          )}
        </div>
      </>}
      {creating && <Modal title="New service ticket" wide onClose={() => setCreating(false)}><NewTicketForm onDone={(id) => { setCreating(false); reload(); if (id) setOpen(id); }} /></Modal>}
      {open && <Modal title="Service ticket" wide onClose={() => setOpen(null)}><TicketDetail id={open} onChanged={reload} /></Modal>}
    </>
  );
}
