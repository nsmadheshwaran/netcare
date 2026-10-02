import { useState, type FormEvent } from "react";
import { ArrowLeftRight, PackagePlus } from "lucide-react";
import { api, qty, type Page } from "../api";
import { useAuth } from "../auth";
import { Badge, Empty, ErrorBanner, Field, Modal, PageHeader, Pager, Spinner, useAsync } from "../components/ui";
import type { Product } from "./Products";

type Location = { id: number; name: string };
type Level = { product_id: number; product_name: string; sku: string; location_id: number; location_name: string; quantity: string; min_stock: string };
type Movement = { id: number; product_name: string; location_name: string; movement_type: string; quantity_change: string; balance_after: string; reference: string | null; note: string | null; created_at: string };

const TYPES: [string, string][] = [
  ["stock_in", "Stock in"], ["stock_out", "Stock out"], ["adjustment", "Adjustment (+/−)"],
  ["damaged", "Damaged / write-off"], ["customer_return", "Customer return"], ["supplier_return", "Return to supplier"],
];

function useProductsAndLocations() {
  const products = useAsync(() => api<Page<Product>>("/products?size=200"), []);
  const locations = useAsync(() => api<Location[]>("/organization/locations"), []);
  return { products: (products.data?.items ?? []).filter((p) => !p.is_service), locations: locations.data ?? [] };
}

function MovementForm({ transfer, onDone }: { transfer: boolean; onDone: () => void }) {
  const { products, locations } = useProductsAndLocations();
  const [f, setF] = useState<any>({ movement_type: "stock_in", quantity: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // One key per form instance so a double-click can never record the movement twice.
  const [idem] = useState(() => crypto.randomUUID());
  const set = (k: string) => (e: React.ChangeEvent<any>) => setF({ ...f, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (transfer)
        await api("/inventory/transfers", { method: "POST", json: {
          product_id: Number(f.product_id), from_location_id: Number(f.from), to_location_id: Number(f.to),
          quantity: f.quantity, note: f.note || null, idempotency_key: idem } });
      else
        await api("/inventory/movements", { method: "POST", json: {
          product_id: Number(f.product_id), location_id: Number(f.location_id), movement_type: f.movement_type,
          quantity: f.quantity, unit_cost: f.unit_cost || null, reference: f.reference || null, note: f.note || null,
          idempotency_key: idem } });
      onDone();
    } catch (err: any) { setError(err.message); } finally { setBusy(false); }
  }

  const locSelect = (k: string, label: string) => (
    <Field label={label}>
      <select className="input" required value={f[k] ?? ""} onChange={set(k)}>
        <option value="">Select…</option>
        {locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
      </select>
    </Field>
  );
  return (
    <form onSubmit={submit} className="space-y-3">
      <ErrorBanner message={error} />
      <Field label="Product">
        <select className="input" required value={f.product_id ?? ""} onChange={set("product_id")}>
          <option value="">Select…</option>
          {products.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.sku}) — {qty(p.stock_on_hand)} on hand</option>)}
        </select>
      </Field>
      {transfer ? <div className="grid gap-3 sm:grid-cols-2">{locSelect("from", "From")}{locSelect("to", "To")}</div> : (
        <div className="grid gap-3 sm:grid-cols-2">
          {locSelect("location_id", "Location")}
          <Field label="Type">
            <select className="input" value={f.movement_type} onChange={set("movement_type")}>
              {TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </Field>
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={f.movement_type === "adjustment" && !transfer ? "Quantity change (negative to reduce)" : "Quantity"}>
          <input className="input" type="number" step="0.001" required value={f.quantity} onChange={set("quantity")} />
        </Field>
        {!transfer && <Field label="Unit cost (₹, optional)"><input className="input" type="number" step="0.01" min={0} value={f.unit_cost ?? ""} onChange={set("unit_cost")} /></Field>}
      </div>
      {!transfer && <Field label="Reference (bill no., etc.)"><input className="input" value={f.reference ?? ""} onChange={set("reference")} /></Field>}
      <Field label="Note"><input className="input" value={f.note ?? ""} onChange={set("note")} /></Field>
      <div className="flex justify-end gap-2">
        <button type="button" className="btn-ghost" onClick={onDone}>Cancel</button>
        <button className="btn-primary" disabled={busy}>Record</button>
      </div>
    </form>
  );
}

export default function Inventory() {
  const { can } = useAuth();
  const [tab, setTab] = useState<"levels" | "history">("levels");
  const [page, setPage] = useState(1);
  const [dialog, setDialog] = useState<"move" | "transfer" | null>(null);
  const levels = useAsync(() => api<Level[]>("/inventory/levels"), []);
  const history = useAsync(() => api<Page<Movement>>(`/inventory/movements?page=${page}&size=50`), [page]);
  const done = () => { setDialog(null); levels.reload(); history.reload(); };

  return (
    <>
      <PageHeader title="Inventory" subtitle="Stock by location. Every change is recorded in the movement history."
        actions={can("inventory.adjust") && <>
          <button className="btn-ghost" onClick={() => setDialog("transfer")}><ArrowLeftRight size={16} /> Transfer</button>
          <button className="btn-primary" onClick={() => setDialog("move")}><PackagePlus size={16} /> Record movement</button>
        </>} />
      <div className="mb-3 flex gap-1">
        {(["levels", "history"] as const).map((t) => (
          <button key={t} className={`btn ${tab === t ? "bg-indigo-600 text-white" : "text-slate-600 hover:bg-slate-200 dark:text-slate-300 dark:hover:bg-slate-800"}`} onClick={() => setTab(t)}>
            {t === "levels" ? "Stock levels" : "Movement history"}
          </button>
        ))}
      </div>
      <ErrorBanner message={tab === "levels" ? levels.error : history.error} />
      <div className="card !p-0 overflow-x-auto">
        {tab === "levels" ? (
          levels.loading && !levels.data ? <Spinner /> : !levels.data?.length ? <Empty title="No stock recorded yet" hint="Record a stock-in movement to get started." /> : (
            <table className="w-full min-w-[560px]">
              <thead className="bg-slate-50 dark:bg-slate-800/50"><tr><th className="th">Product</th><th className="th">SKU</th><th className="th">Location</th><th className="th text-right">Quantity</th></tr></thead>
              <tbody>{levels.data.map((l) => (
                <tr key={`${l.product_id}-${l.location_id}`} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="td">{l.product_name}</td><td className="td font-mono text-xs">{l.sku}</td><td className="td">{l.location_name}</td>
                  <td className="td text-right"><Badge tone={Number(l.quantity) <= 0 ? "red" : Number(l.quantity) <= Number(l.min_stock) ? "amber" : "green"}>{qty(l.quantity)}</Badge></td>
                </tr>))}</tbody>
            </table>
          )
        ) : history.loading && !history.data ? <Spinner /> : !history.data?.items.length ? <Empty title="No movements yet" /> : (
          <>
            <table className="w-full min-w-[760px]">
              <thead className="bg-slate-50 dark:bg-slate-800/50"><tr><th className="th">When</th><th className="th">Product</th><th className="th">Location</th><th className="th">Type</th><th className="th text-right">Change</th><th className="th text-right">Balance</th><th className="th">Reference / note</th></tr></thead>
              <tbody>{history.data.items.map((m) => (
                <tr key={m.id} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="td whitespace-nowrap text-xs">{new Date(m.created_at).toLocaleString("en-IN")}</td>
                  <td className="td">{m.product_name}</td><td className="td">{m.location_name}</td>
                  <td className="td"><Badge>{m.movement_type.replace(/_/g, " ")}</Badge></td>
                  <td className={`td text-right font-medium ${Number(m.quantity_change) < 0 ? "text-red-600" : "text-emerald-600"}`}>{Number(m.quantity_change) > 0 ? "+" : ""}{qty(m.quantity_change)}</td>
                  <td className="td text-right">{qty(m.balance_after)}</td>
                  <td className="td text-xs text-slate-500">{[m.reference, m.note].filter(Boolean).join(" · ")}</td>
                </tr>))}</tbody>
            </table>
            <Pager page={history.data.page} size={history.data.size} total={history.data.total} onPage={setPage} />
          </>
        )}
      </div>
      {dialog && <Modal title={dialog === "transfer" ? "Transfer stock" : "Record stock movement"} onClose={() => setDialog(null)}>
        <MovementForm transfer={dialog === "transfer"} onDone={done} />
      </Modal>}
    </>
  );
}
