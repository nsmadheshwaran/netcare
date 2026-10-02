import { useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlertTriangle, Boxes, HandCoins, IndianRupee, Package, Receipt, ShoppingCart, UserPlus, Users, Wallet } from "lucide-react";
import { api, inr, qty } from "../api";
import { Badge, Empty, ErrorBanner, PageHeader, Spinner, useAsync } from "../components/ui";

const PERIODS = [["day", "Today"], ["week", "This week"], ["month", "This month"], ["quarter", "This quarter"], ["year", "Financial year"]];

function Stat({ label, value, icon: Icon, tone = "text-indigo-600", to }: { label: string; value: string | number; icon: any; tone?: string; to?: string }) {
  const body = (
    <div className="card flex items-center gap-3 transition hover:shadow-md">
      <div className={`rounded-lg bg-slate-100 p-2.5 dark:bg-slate-800 ${tone}`}><Icon size={20} /></div>
      <div className="min-w-0">
        <div className="truncate text-xs text-slate-500">{label}</div>
        <div className="text-lg font-semibold">{value}</div>
      </div>
    </div>
  );
  return to ? <Link to={to}>{body}</Link> : body;
}

function merge<T extends { date: string }>(a: T[], b: T[], ka: string, kb: string, va: (r: T) => number, vb: (r: T) => number) {
  const map = new Map<string, any>();
  for (const r of a) map.set(r.date, { date: r.date, [ka]: va(r), [kb]: 0 });
  for (const r of b) map.set(r.date, { ...(map.get(r.date) || { date: r.date, [ka]: 0 }), [kb]: vb(r) });
  return [...map.values()].sort((x, y) => x.date.localeCompare(y.date));
}

export default function Dashboard() {
  const [period, setPeriod] = useState("month");
  const [location, setLocation] = useState("");
  const locations = useAsync(() => api<{ id: number; name: string }[]>("/organization/locations"), []);
  const { data: d, error, loading } = useAsync(
    () => api(`/dashboard/summary?period=${period}${location ? `&location_id=${location}` : ""}`), [period, location]);

  const money = d ? merge<any>(d.trends.sales_per_day, d.trends.purchases_per_day, "sales", "purchases", (r) => Number(r.total), (r) => Number(r.total)) : [];
  const activity = d ? merge<any>(d.trends.new_customers_per_day, d.trends.stock_movements_per_day, "customers", "movements", (r) => r.count, (r) => r.count) : [];

  return (
    <>
      <PageHeader title="Overview" subtitle="Live figures from your records"
        actions={<>
          <select className="input !w-auto" value={period} onChange={(e) => setPeriod(e.target.value)} aria-label="Period">
            {PERIODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <select className="input !w-auto" value={location} onChange={(e) => setLocation(e.target.value)} aria-label="Location">
            <option value="">All locations</option>
            {locations.data?.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        </>} />
      <ErrorBanner message={error} />
      {loading && !d ? <Spinner /> : d && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Stat label="Invoiced today" value={inr(d.sales.invoiced_today)} icon={Receipt} to="/sales" />
            <Stat label="Invoiced in period" value={inr(d.sales.invoiced_in_period)} icon={Receipt} to="/sales" />
            <Stat label="Received in period" value={inr(d.sales.received_in_period)} icon={HandCoins} tone="text-emerald-600" to="/payments" />
            <Stat label="Purchases billed in period" value={inr(d.purchases.billed_in_period)} icon={ShoppingCart} tone="text-slate-600" to="/purchases" />
            <Stat label="Customers owe you" value={inr(d.sales.receivable_outstanding)} icon={Wallet} tone="text-amber-600" to="/sales" />
            <Stat label="Overdue from customers" value={inr(d.sales.receivable_overdue)} icon={AlertTriangle} tone="text-red-600" to="/sales" />
            <Stat label="You owe suppliers" value={inr(d.purchases.payable_outstanding)} icon={Wallet} tone="text-amber-600" to="/purchases" />
            <Stat label="Paid to suppliers in period" value={inr(d.purchases.paid_in_period)} icon={HandCoins} tone="text-slate-600" to="/payments" />
          </div>

          <div className="card">
            <h3 className="mb-3 font-medium">Sales and purchases (invoiced value incl. tax)</h3>
            {money.length === 0 ? <Empty title="No issued invoices or supplier bills in this period" /> : (
              <div className="h-64">
                <ResponsiveContainer>
                  <BarChart data={money}>
                    <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.2} />
                    <XAxis dataKey="date" fontSize={11} />
                    <YAxis fontSize={11} tickFormatter={(v) => `₹${Number(v).toLocaleString("en-IN")}`} />
                    <Tooltip formatter={(v) => inr(Number(v))} />
                    <Bar dataKey="sales" name="Sales" fill="#6366f1" />
                    <Bar dataKey="purchases" name="Purchases" fill="#f59e0b" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
            <p className="mt-2 text-xs text-slate-500">Invoiced amounts are not cash. Money received and paid comes only from recorded payments.</p>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <Stat label="Total customers" value={d.customers.total} icon={Users} to="/customers" />
            <Stat label="New customers in period" value={d.customers.new_in_period} icon={UserPlus} tone="text-emerald-600" />
            <Stat label="Products" value={d.inventory.products} icon={Package} to="/products" />
            <Stat label="Stock value (at cost)" value={inr(d.inventory.stock_valuation_at_cost)} icon={IndianRupee} tone="text-emerald-600" to="/inventory" />
            <Stat label="Low-stock products" value={d.inventory.low_stock_count} icon={AlertTriangle} tone="text-amber-600" to="/products?low_stock=1" />
            <Stat label="Out of stock" value={d.inventory.out_of_stock_count} icon={Boxes} tone="text-red-600" />
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <div className="card lg:col-span-2">
              <h3 className="mb-3 font-medium">Customers and stock activity</h3>
              {activity.length === 0 ? <Empty title="No activity in this period" hint="Add customers or record stock movements to see trends." /> : (
                <div className="h-64">
                  <ResponsiveContainer>
                    <BarChart data={activity}>
                      <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.2} />
                      <XAxis dataKey="date" fontSize={11} />
                      <YAxis allowDecimals={false} fontSize={11} />
                      <Tooltip />
                      <Bar dataKey="customers" name="New customers" fill="#6366f1" />
                      <Bar dataKey="movements" name="Stock movements" fill="#10b981" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
            <div className="card">
              <h3 className="mb-3 font-medium">Low stock</h3>
              {d.inventory.low_stock.length === 0 ? <p className="text-sm text-slate-500">All products are above their minimum level.</p> : (
                <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                  {d.inventory.low_stock.map((p: any) => (
                    <li key={p.id} className="flex justify-between py-2 text-sm">
                      <span className="truncate">{p.name} <span className="text-slate-400">{p.sku}</span></span>
                      <Badge tone={Number(p.qty) <= 0 ? "red" : "amber"}>{qty(p.qty)} / min {qty(p.min_stock)}</Badge>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="card">
              <h3 className="mb-3 font-medium">Recent activity</h3>
              {d.recent_activity.length === 0 ? <p className="text-sm text-slate-500">No activity yet.</p> : (
                <ul className="space-y-2 text-sm">
                  {d.recent_activity.map((a: any) => (
                    <li key={a.id} className="flex justify-between gap-2">
                      <span><span className="font-medium">{a.user ?? "System"}</span> {a.action.replace(/_/g, " ")} {a.entity_type.replace(/_/g, " ")}{a.entity_id ? ` #${a.entity_id}` : ""}</span>
                      <span className="shrink-0 text-xs text-slate-400">{new Date(a.at).toLocaleString("en-IN")}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="card">
              <h3 className="mb-1 font-medium">Not yet available</h3>
              <p className="mb-3 text-sm text-slate-500">These figures will appear once the corresponding modules are built. Nothing here is estimated.</p>
              <div className="flex flex-wrap gap-2">
                {d.not_yet_available.map((m: string) => <Badge key={m}>{m.replace(/_/g, " ")}</Badge>)}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
