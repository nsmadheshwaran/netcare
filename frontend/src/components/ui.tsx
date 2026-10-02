import { useCallback, useEffect, useState, type ReactNode } from "react";
import { AlertCircle, ChevronLeft, ChevronRight, Inbox, Loader2, X } from "lucide-react";

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fn, deps);
  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    run().then(setData).catch((e) => setError(e.message)).finally(() => setLoading(false));
  }, [run]);
  useEffect(reload, [reload]);
  return { data, error, loading, reload };
}

export function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div role="alert" className="mb-3 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
      <AlertCircle size={16} className="mt-0.5 shrink-0" /> {message}
    </div>
  );
}

export function Spinner() {
  return <div className="flex justify-center p-8 text-slate-400"><Loader2 className="animate-spin" /></div>;
}

export function Empty({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 p-10 text-center text-slate-500">
      <Inbox size={32} className="text-slate-300 dark:text-slate-600" />
      <div className="font-medium text-slate-700 dark:text-slate-300">{title}</div>
      {hint && <div className="text-sm">{hint}</div>}
      {action}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold">{title}</h1>
        {subtitle && <p className="text-sm text-slate-500">{subtitle}</p>}
      </div>
      <div className="flex flex-wrap gap-2">{actions}</div>
    </div>
  );
}

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/50 p-4" onMouseDown={onClose}>
      <div role="dialog" aria-label={title} onMouseDown={(e) => e.stopPropagation()}
        className={`card mt-10 w-full ${wide ? "max-w-3xl" : "max-w-lg"}`}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button className="rounded p-1 hover:bg-slate-100 dark:hover:bg-slate-800" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Field({ label, children, className = "" }: { label: string; children: ReactNode; className?: string }) {
  return <label className={`block ${className}`}><span className="label">{label}</span>{children}</label>;
}

export function Pager({ page, size, total, onPage }: { page: number; size: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / size));
  return (
    <div className="flex items-center justify-between border-t border-slate-200 px-3 py-2 text-sm text-slate-500 dark:border-slate-800">
      <span>{total} record{total === 1 ? "" : "s"}</span>
      <div className="flex items-center gap-2">
        <button className="btn-ghost !px-2 !py-1" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page"><ChevronLeft size={16} /></button>
        <span>Page {page} of {pages}</span>
        <button className="btn-ghost !px-2 !py-1" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page"><ChevronRight size={16} /></button>
      </div>
    </div>
  );
}

export function Badge({ children, tone = "slate" }: { children: ReactNode; tone?: "slate" | "green" | "amber" | "red" | "indigo" }) {
  const tones = {
    slate: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
    green: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
    amber: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
    red: "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300",
    indigo: "bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300",
  };
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${tones[tone]}`}>{children}</span>;
}

export function confirmAction(message: string) {
  return window.confirm(message);
}
