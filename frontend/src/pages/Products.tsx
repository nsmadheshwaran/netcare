import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { Archive, Pencil, Plus, RotateCcw } from "lucide-react";
import { api, inr, qty, type Page } from "../api";
import { useAuth } from "../auth";
import { Badge, confirmAction, Empty, ErrorBanner, Field, Modal, PageHeader, Pager, Spinner, useAsync } from "../components/ui";

export type Product = {
  id: number; name: string; sku: string; category_id: number | null; category_name: string | null; barcode: string | null;
  brand: string | null; model: string | null; hsn_sac: string | null; unit: string; purchase_price: string;
  selling_price: string; gst_rate: string | null; min_stock: string; track_serial: boolean; warranty_months: number | null;
  is_service: boolean; description: string | null; status: string; stock_on_hand: string; archived_at: string | null;
};
type Category = { id: number; name: string };

const EMPTY: Partial<Product> = { name: "", sku: "", unit: "pcs", purchase_price: "0", selling_price: "0", min_stock: "0", status: "active", is_service: false, track_serial: false };
const KEYS = ["name", "sku", "category_id", "barcode", "brand", "model", "hsn_sac", "unit", "purchase_price", "selling_price",
  "gst_rate", "min_stock", "track_serial", "warranty_months", "is_service", "description", "status"] as const;

function ProductForm({ initial, categories, onDone, onCategory }: { initial: Partial<Product>; categories: Category[]; onDone: () => void; onCategory: () => void }) {
  const [f, setF] = useState<any>(initial);
  const [error, setError] = useState<string | null>(null);
  const [newCat, setNewCat] = useState("");
  const set = (k: string) => (e: React.ChangeEvent<any>) =>
    setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  async function addCategory() {
    if (!newCat.trim()) return;
    try {
      const c = await api<Category>("/product-categories", { method: "POST", json: { name: newCat.trim() } });
      setF({ ...f, category_id: c.id });
      setNewCat("");
      onCategory();
    } catch (err: any) { setError(err.message); }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const body: any = Object.fromEntries(KEYS.map((k) => [k, f[k] === "" ? null : f[k] ?? null]));
    body.category_id = body.category_id ? Number(body.category_id) : null;
    body.warranty_months = body.warranty_months ? Number(body.warranty_months) : null;
    try {
      if (f.id) await api(`/products/${f.id}`, { method: "PUT", json: body });
      else await api("/products", { method: "POST", json: body });
      onDone();
    } catch (err: any) { setError(err.message); }
  }

  const input = (k: string, label: string, props: any = {}) => (
    <Field label={label}><input className="input" value={f[k] ?? ""} onChange={set(k)} {...props} /></Field>
  );
  return (
    <form onSubmit={submit}>
      <ErrorBanner message={error} />
      <div className="grid gap-3 sm:grid-cols-3">
        {input("name", "Name *", { required: true })}
        {input("sku", "SKU *", { required: true, pattern: "[A-Za-z0-9._\\-/]+" })}
        <Field label="Category">
          <select className="input" value={f.category_id ?? ""} onChange={set("category_id")}>
            <option value="">— none —</option>
            {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        <div className="flex items-end gap-2 sm:col-span-3">
          <Field label="New category" className="flex-1"><input className="input" value={newCat} onChange={(e) => setNewCat(e.target.value)} placeholder="e.g. CCTV Cameras" /></Field>
          <button type="button" className="btn-ghost" onClick={addCategory} disabled={!newCat.trim()}>Add category</button>
        </div>
        {input("brand", "Brand")}{input("model", "Model")}{input("barcode", "Barcode")}
        {input("purchase_price", "Purchase price (₹)", { type: "number", step: "0.01", min: 0 })}
        {input("selling_price", "Selling price (₹)", { type: "number", step: "0.01", min: 0 })}
        {input("gst_rate", "GST rate %", { type: "number", step: "0.01", min: 0, max: 100 })}
        {input("hsn_sac", "HSN / SAC", { pattern: "\\d{4,8}" })}
        {input("unit", "Unit")}
        {input("min_stock", "Minimum stock", { type: "number", step: "0.001", min: 0 })}
        {input("warranty_months", "Warranty (months)", { type: "number", min: 0, max: 240 })}
        <Field label="Status">
          <select className="input" value={f.status} onChange={set("status")}><option value="active">Active</option><option value="inactive">Inactive</option></select>
        </Field>
        <div className="flex items-center gap-4 text-sm sm:col-span-3">
          <label className="flex items-center gap-2"><input type="checkbox" checked={!!f.track_serial} onChange={set("track_serial")} /> Track serial numbers</label>
          <label className="flex items-center gap-2"><input type="checkbox" checked={!!f.is_service} onChange={set("is_service")} /> This is a service (no stock)</label>
        </div>
        <Field label="Description" className="sm:col-span-3"><textarea className="input" rows={2} value={f.description ?? ""} onChange={set("description")} /></Field>
      </div>
      <p className="mt-2 text-xs text-slate-500">GST rate and HSN/SAC are stored for your records. Have your accountant confirm them before invoicing.</p>
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" className="btn-ghost" onClick={onDone}>Cancel</button>
        <button className="btn-primary">Save</button>
      </div>
    </form>
  );
}

export default function Products() {
  const { can } = useAuth();
  const [params] = useSearchParams();
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [lowStock, setLowStock] = useState(params.has("low_stock"));
  const [archived, setArchived] = useState(false);
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Partial<Product> | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const cats = useAsync(() => api<Category[]>("/product-categories"), []);
  const { data, error, loading, reload } = useAsync(
    () => api<Page<Product>>(`/products?page=${page}&size=25&archived=${archived}&low_stock=${lowStock}&q=${encodeURIComponent(q)}${cat ? `&category_id=${cat}` : ""}`),
    [page, q, cat, lowStock, archived]);

  async function toggleArchive(p: Product) {
    const verb = p.archived_at ? "restore" : "archive";
    if (!confirmAction(`${verb[0].toUpperCase() + verb.slice(1)} ${p.name}?`)) return;
    try { await api(`/products/${p.id}/${verb}`, { method: "POST" }); reload(); }
    catch (err: any) { setActionError(err.message); }
  }

  return (
    <>
      <PageHeader title="Products" subtitle="Goods and services you sell"
        actions={can("products.edit") && <button className="btn-primary" onClick={() => setEditing(EMPTY)}><Plus size={16} /> Add product</button>} />
      <ErrorBanner message={error || actionError} />
      <div className="card !p-0">
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 p-3 dark:border-slate-800">
          <input className="input max-w-xs" placeholder="Search name, SKU, brand, barcode…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
          <select className="input !w-auto" value={cat} onChange={(e) => { setCat(e.target.value); setPage(1); }} aria-label="Category">
            <option value="">All categories</option>
            {cats.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={lowStock} onChange={(e) => { setLowStock(e.target.checked); setPage(1); }} /> Low stock only</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={archived} onChange={(e) => { setArchived(e.target.checked); setPage(1); }} /> Archived</label>
        </div>
        {loading && !data ? <Spinner /> : data && data.items.length === 0 ? (
          <Empty title="No products found" hint="Add products to start tracking stock." />
        ) : data && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px]">
              <thead className="bg-slate-50 dark:bg-slate-800/50"><tr>
                <th className="th">Product</th><th className="th">SKU</th><th className="th">Category</th><th className="th text-right">Cost</th><th className="th text-right">Price</th><th className="th text-right">On hand</th><th className="th"></th>
              </tr></thead>
              <tbody>
                {data.items.map((p) => {
                  const low = !p.is_service && Number(p.stock_on_hand) <= Number(p.min_stock);
                  return (
                    <tr key={p.id} className="border-t border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/40">
                      <td className="td"><div className="font-medium">{p.name}</div><div className="text-xs text-slate-500">{[p.brand, p.model].filter(Boolean).join(" ")}</div></td>
                      <td className="td font-mono text-xs">{p.sku}</td>
                      <td className="td">{p.category_name}</td>
                      <td className="td text-right">{inr(p.purchase_price)}</td>
                      <td className="td text-right">{inr(p.selling_price)}</td>
                      <td className="td text-right">{p.is_service ? <Badge tone="indigo">service</Badge> : <Badge tone={Number(p.stock_on_hand) <= 0 ? "red" : low ? "amber" : "green"}>{qty(p.stock_on_hand)} {p.unit}</Badge>}</td>
                      <td className="td whitespace-nowrap text-right">
                        {can("products.edit") && <>
                          {!p.archived_at && <button className="rounded p-1.5 hover:bg-slate-200 dark:hover:bg-slate-700" onClick={() => setEditing(p)} aria-label="Edit"><Pencil size={15} /></button>}
                          <button className="rounded p-1.5 hover:bg-slate-200 dark:hover:bg-slate-700" onClick={() => toggleArchive(p)} aria-label={p.archived_at ? "Restore" : "Archive"}>
                            {p.archived_at ? <RotateCcw size={15} /> : <Archive size={15} />}
                          </button>
                        </>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <Pager page={data.page} size={data.size} total={data.total} onPage={setPage} />
          </div>
        )}
      </div>
      {editing && <Modal title={editing.id ? "Edit product" : "Add product"} onClose={() => setEditing(null)} wide>
        <ProductForm initial={editing} categories={cats.data ?? []} onCategory={cats.reload} onDone={() => { setEditing(null); reload(); }} />
      </Modal>}
    </>
  );
}
