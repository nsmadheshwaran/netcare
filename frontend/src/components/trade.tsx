import { Plus, Trash2 } from "lucide-react";
import { api, inr, qty, type Page } from "../api";
import { Badge, Field, useAsync } from "./ui";

export type Line = {
  id?: number; product_id: number | null; description: string; quantity: string; unit_price: string;
  tax_rate: string; line_discount_pct: string;
};
export type LineOut = Line & {
  id: number; hsn_sac: string | null; discount_amount: string; taxable_value: string; cgst: string; sgst: string;
  igst: string; line_total: string; received_quantity?: string | null; returned_quantity?: string | null;
};
export type Totals = {
  prices_include_tax?: boolean;
  subtotal: string; discount_total: string; taxable_total: string; cgst_total: string; sgst_total: string;
  igst_total: string; round_off: string; total: string; is_interstate: boolean; place_of_supply: string | null;
};

type ProductLite = { id: number; name: string; sku: string; selling_price: string; purchase_price: string; gst_rate: string | null; is_service: boolean; stock_on_hand: string };
type Party = { id: number; name: string };

export const today = () => new Date().toISOString().slice(0, 10);
export const blankLine = (): Line => ({ product_id: null, description: "", quantity: "1", unit_price: "", tax_rate: "", line_discount_pct: "0" });

export function useProducts() {
  return useAsync(() => api<Page<ProductLite>>("/products?size=200&sort=name"), []).data?.items ?? [];
}
export function useCustomers() {
  return useAsync(() => api<Page<Party>>("/customers?size=200&sort=name"), []).data?.items ?? [];
}
export function useSuppliers() {
  return useAsync(() => api<Page<Party>>("/suppliers?size=200"), []).data?.items ?? [];
}
export function useLocations() {
  return useAsync(() => api<Party[]>("/organization/locations"), []).data ?? [];
}

export function PartySelect({ label, value, onChange, options }: { label: string; value: number | ""; onChange: (v: number) => void; options: Party[] }) {
  return (
    <Field label={label}>
      <select className="input" required value={value} onChange={(e) => onChange(Number(e.target.value))}>
        <option value="">Select…</option>
        {options.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
      </select>
    </Field>
  );
}

/** Editable lines. Picking a product fills description, price and GST rate from the product master. */
export function LineEditor({ lines, onChange, priceField = "selling_price", discounts = true, productsOnly = false }: {
  lines: Line[]; onChange: (l: Line[]) => void; priceField?: "selling_price" | "purchase_price"; discounts?: boolean; productsOnly?: boolean;
}) {
  const products = useProducts().filter((p) => !productsOnly || !p.is_service);
  const set = (i: number, patch: Partial<Line>) => onChange(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const pick = (i: number, id: string) => {
    const p = products.find((x) => x.id === Number(id));
    if (!p) return set(i, { product_id: null });
    set(i, { product_id: p.id, description: p.name, unit_price: p[priceField], tax_rate: p.gst_rate ?? "0" });
  };
  const net = (l: Line) => Number(l.quantity || 0) * Number(l.unit_price || 0) * (1 - Number(l.line_discount_pct || 0) / 100);

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px]">
        <thead><tr>
          <th className="th w-56">Product</th><th className="th">Description</th><th className="th w-20">Qty</th>
          <th className="th w-28">Unit price ₹</th>{discounts && <th className="th w-20">Disc %</th>}<th className="th w-20">GST %</th>
          <th className="th w-28 text-right">Net</th><th className="w-8" />
        </tr></thead>
        <tbody>
          {lines.map((l, i) => {
            const p = products.find((x) => x.id === l.product_id);
            return (
              <tr key={i} className="align-top">
                <td className="p-1">
                  <select className="input" value={l.product_id ?? ""} required={productsOnly} onChange={(e) => pick(i, e.target.value)} aria-label="Product">
                    <option value="">{productsOnly ? "Select…" : "— free text —"}</option>
                    {products.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.sku})</option>)}
                  </select>
                  {p && !p.is_service && <div className="mt-0.5 text-[11px] text-slate-500">{qty(p.stock_on_hand)} in stock</div>}
                </td>
                <td className="p-1"><input className="input" value={l.description} required={!l.product_id} onChange={(e) => set(i, { description: e.target.value })} aria-label="Description" /></td>
                <td className="p-1"><input className="input" type="number" step="0.001" min="0.001" required value={l.quantity} onChange={(e) => set(i, { quantity: e.target.value })} aria-label="Quantity" /></td>
                <td className="p-1"><input className="input" type="number" step="0.01" min="0" required={!l.product_id} value={l.unit_price} onChange={(e) => set(i, { unit_price: e.target.value })} aria-label="Unit price" /></td>
                {discounts && <td className="p-1"><input className="input" type="number" step="0.01" min="0" max="100" value={l.line_discount_pct} onChange={(e) => set(i, { line_discount_pct: e.target.value })} aria-label="Discount percent" /></td>}
                <td className="p-1"><input className="input" type="number" step="0.01" min="0" max="100" value={l.tax_rate} onChange={(e) => set(i, { tax_rate: e.target.value })} aria-label="GST rate" /></td>
                <td className="p-1 pt-3 text-right text-sm">{inr(net(l))}</td>
                <td className="p-1 pt-2">
                  <button type="button" className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600 disabled:opacity-30 dark:hover:bg-slate-800" disabled={lines.length === 1} onClick={() => onChange(lines.filter((_, j) => j !== i))} aria-label="Remove line"><Trash2 size={15} /></button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <button type="button" className="btn-ghost mt-2" onClick={() => onChange([...lines, blankLine()])}><Plus size={15} /> Add line</button>
      <p className="mt-2 text-xs text-slate-500">Net is before tax and document discount. Final tax and totals are calculated by the server when you save.</p>
    </div>
  );
}

export function linesPayload(lines: Line[], discounts = true) {
  return lines.map((l) => ({
    product_id: l.product_id, description: l.description || null, quantity: l.quantity,
    unit_price: l.unit_price === "" ? null : l.unit_price, tax_rate: l.tax_rate === "" ? null : l.tax_rate,
    ...(discounts ? { line_discount_pct: l.line_discount_pct || "0" } : {}),
  }));
}

export function linesFrom(out: LineOut[]): Line[] {
  return out.map((l) => ({ product_id: l.product_id, description: l.description, quantity: String(Number(l.quantity)), unit_price: l.unit_price, tax_rate: l.tax_rate, line_discount_pct: l.line_discount_pct ?? "0" }));
}

export function LinesTable({ lines, extra }: { lines: LineOut[]; extra?: (l: LineOut) => React.ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm">
        <thead className="bg-slate-50 dark:bg-slate-800/50"><tr>
          <th className="th">Item</th><th className="th">HSN/SAC</th><th className="th text-right">Qty</th><th className="th text-right">Rate</th>
          <th className="th text-right">Discount</th><th className="th text-right">Taxable</th><th className="th text-right">GST</th><th className="th text-right">Amount</th>{extra && <th className="th" />}
        </tr></thead>
        <tbody>
          {lines.map((l) => (
            <tr key={l.id} className="border-t border-slate-100 dark:border-slate-800">
              <td className="td">{l.description}</td><td className="td text-xs">{l.hsn_sac}</td>
              <td className="td text-right">{qty(l.quantity)}</td><td className="td text-right">{inr(l.unit_price)}</td>
              <td className="td text-right">{Number(l.discount_amount) ? inr(l.discount_amount) : "—"}</td>
              <td className="td text-right">{inr(l.taxable_value)}</td>
              <td className="td text-right">{Number(l.tax_rate)}%<div className="text-[11px] text-slate-500">{inr(Number(l.cgst) + Number(l.sgst) + Number(l.igst))}</div></td>
              <td className="td text-right font-medium">{inr(l.line_total)}</td>
              {extra && <td className="td">{extra(l)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function TotalsBox({ t, children }: { t: Totals; children?: React.ReactNode }) {
  const row = (label: string, v: string, strong = false) =>
    <div className={`flex justify-between py-0.5 ${strong ? "border-t border-slate-200 pt-1.5 text-base font-semibold dark:border-slate-700" : ""}`}><span className="text-slate-500">{label}</span><span>{inr(v)}</span></div>;
  return (
    <div className="ml-auto w-full max-w-xs text-sm">
      {row(t.prices_include_tax ? "Subtotal (incl. GST)" : "Subtotal", t.subtotal)}
      {Number(t.discount_total) > 0 && row("Discount", `-${t.discount_total}`)}
      {row("Taxable value", t.taxable_total)}
      {t.is_interstate ? row("IGST", t.igst_total) : <>{row("CGST", t.cgst_total)}{row("SGST", t.sgst_total)}</>}
      {Number(t.round_off) !== 0 && row("Round off", t.round_off)}
      {row("Total", t.total, true)}
      {children}
      <div className="mt-2 text-[11px] text-slate-500">
        {t.place_of_supply ? `Place of supply: state ${t.place_of_supply} (${t.is_interstate ? "inter-state" : "intra-state"})` : "Place of supply unknown, treated as intra-state. Set the party's GST state code."}
        <br />Tax amounts are for your records and have not been verified for GST compliance.
      </div>
    </div>
  );
}

const TONES: Record<string, "slate" | "green" | "amber" | "red" | "indigo"> = {
  draft: "slate", sent: "indigo", accepted: "green", rejected: "red", converted: "green", expired: "amber",
  approved: "indigo", partially_received: "amber", received: "green", closed: "slate", cancelled: "red",
  open: "indigo", issued: "indigo", partially_paid: "amber", paid: "green", overdue: "red",
};
export const StatusBadge = ({ s }: { s: string }) => <Badge tone={TONES[s] ?? "slate"}>{s.replace(/_/g, " ")}</Badge>;
