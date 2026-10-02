import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import {
  Activity, BarChart3, Bell, Boxes, Building2, Camera, ClipboardList, Cpu, FileText, FolderSearch, LayoutDashboard,
  LogOut, Menu, Moon, Package, Receipt, ScrollText, Settings, ShieldCheck, ShoppingCart, Sun, Truck, UserCog, Users,
  Wallet, Wrench, Briefcase, CreditCard, FileSignature, type LucideIcon,
} from "lucide-react";
import { useAuth } from "../auth";

type Item = { label: string; to?: string; icon: LucideIcon; perm?: string };

// Items without `to` are not built yet and are shown disabled, never as fake pages.
const NAV: Item[] = [
  { label: "Overview", to: "/", icon: LayoutDashboard, perm: "dashboard.view" },
  { label: "Customers", to: "/customers", icon: Users, perm: "customers.view" },
  { label: "Suppliers", to: "/suppliers", icon: Truck, perm: "suppliers.view" },
  { label: "Products", to: "/products", icon: Package, perm: "products.view" },
  { label: "Inventory", to: "/inventory", icon: Boxes, perm: "inventory.view" },
  { label: "Sales", to: "/sales", icon: Receipt, perm: "sales.view" },
  { label: "Quotations", to: "/quotations", icon: FileSignature, perm: "sales.view" },
  { label: "Purchases", to: "/purchases", icon: ShoppingCart, perm: "purchases.view" },
  { label: "Payments", to: "/payments", icon: CreditCard, perm: "payments.view" },
  { label: "Expenses", icon: Wallet },
  { label: "Finance", icon: BarChart3 },
  { label: "Employees", icon: Briefcase },
  { label: "Tasks", icon: ClipboardList },
  { label: "Service Management", icon: Wrench },
  { label: "Documents", icon: FileText },
  { label: "IT Assets", icon: Cpu },
  { label: "Network Monitoring", icon: Activity },
  { label: "CCTV Management", icon: Camera },
  { label: "Endpoint Security", icon: ShieldCheck },
  { label: "Data Organizer", icon: FolderSearch },
  { label: "Alerts", icon: Bell },
  { label: "Reports", icon: BarChart3 },
  { label: "Users and Roles", to: "/users", icon: UserCog, perm: "users.manage" },
  { label: "Audit Logs", to: "/audit", icon: ScrollText, perm: "audit.view" },
  { label: "Settings", to: "/settings", icon: Settings },
];

function useTheme() {
  const [dark, setDark] = useState(() => {
    const saved = localStorage.getItem("netcare.theme");
    return saved ? saved === "dark" : window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  });
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("netcare.theme", dark ? "dark" : "light");
  }, [dark]);
  return [dark, setDark] as const;
}

export default function Layout() {
  const { me, current, can, logout, switchOrg } = useAuth();
  const [dark, setDark] = useTheme();
  const [open, setOpen] = useState(false);
  const [showPlanned, setShowPlanned] = useState(false);

  const visible = NAV.filter((i) => (i.to ? !i.perm || can(i.perm) : showPlanned));

  return (
    <div className="flex min-h-screen">
      <aside className={`fixed inset-y-0 left-0 z-40 w-60 transform border-r border-slate-200 bg-white transition dark:border-slate-800 dark:bg-slate-900 lg:static lg:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}>
        <div className="flex h-14 items-center gap-2 border-b border-slate-200 px-4 dark:border-slate-800">
          <Building2 className="text-indigo-600" size={22} />
          <span className="font-semibold">NetCare</span>
        </div>
        <nav className="h-[calc(100vh-3.5rem)] overflow-y-auto p-2">
          {visible.map((i) =>
            i.to ? (
              <NavLink key={i.label} to={i.to} end={i.to === "/"} onClick={() => setOpen(false)}
                className={({ isActive }) => `mb-0.5 flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm ${isActive ? "bg-indigo-50 font-medium text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300" : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"}`}>
                <i.icon size={17} /> {i.label}
              </NavLink>
            ) : (
              <div key={i.label} title="Planned module, not yet available" className="mb-0.5 flex cursor-not-allowed items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-slate-400 dark:text-slate-600">
                <i.icon size={17} /> {i.label} <span className="ml-auto text-[10px] uppercase">Planned</span>
              </div>
            ),
          )}
          <button className="mt-2 w-full px-3 py-1 text-left text-xs text-slate-400 hover:text-slate-600" onClick={() => setShowPlanned((v) => !v)}>
            {showPlanned ? "Hide planned modules" : "Show planned modules"}
          </button>
        </nav>
      </aside>
      {open && <div className="fixed inset-0 z-30 bg-black/30 lg:hidden" onClick={() => setOpen(false)} />}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-slate-200 bg-white/90 px-4 backdrop-blur dark:border-slate-800 dark:bg-slate-900/90">
          <button className="lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu"><Menu /></button>
          {me && me.memberships.length > 1 ? (
            <select className="input !w-auto" value={current?.organization_id} onChange={(e) => switchOrg(Number(e.target.value))} aria-label="Organization">
              {me.memberships.map((m) => <option key={m.organization_id} value={m.organization_id}>{m.organization_name}</option>)}
            </select>
          ) : (
            <span className="truncate font-medium">{current?.organization_name}</span>
          )}
          <span className="hidden text-xs capitalize text-slate-500 sm:inline">{current?.role.replace("_", " ")}</span>
          <div className="ml-auto flex items-center gap-2">
            <button className="btn-ghost !px-2" onClick={() => setDark(!dark)} aria-label="Toggle theme">{dark ? <Sun size={16} /> : <Moon size={16} />}</button>
            <span className="hidden text-sm text-slate-600 dark:text-slate-300 md:inline">{me?.user.full_name}</span>
            <button className="btn-ghost !px-2" onClick={logout} aria-label="Sign out" title="Sign out"><LogOut size={16} /></button>
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
