export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const TOKEN_KEY = "netcare.token";
const ORG_KEY = "netcare.org";

export const session = {
  get token() { return localStorage.getItem(TOKEN_KEY); },
  set token(v: string | null) { v ? localStorage.setItem(TOKEN_KEY, v) : localStorage.removeItem(TOKEN_KEY); },
  get orgId() { return localStorage.getItem(ORG_KEY); },
  set orgId(v: string | null) { v ? localStorage.setItem(ORG_KEY, v) : localStorage.removeItem(ORG_KEY); },
};

function formatDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail.map((d: any) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
  return "Request failed";
}

export async function api<T = any>(path: string, opts: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers = new Headers(opts.headers);
  if (session.token) headers.set("Authorization", `Bearer ${session.token}`);
  if (session.orgId) headers.set("X-Organization-ID", session.orgId);
  let body = opts.body;
  if (opts.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(opts.json);
  }
  const res = await fetch(`/api/v1${path}`, { ...opts, headers, body });
  if (res.status === 401 && session.token) {
    session.token = null;
    window.location.assign("/login");
  }
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = formatDetail((await res.json()).detail); } catch { /* non-JSON */ }
    throw new ApiError(res.status, msg);
  }
  if (res.status === 204) return undefined as T;
  const type = res.headers.get("content-type") || "";
  return (type.includes("json") ? res.json() : res.blob()) as Promise<T>;
}

export async function download(path: string, filename: string) {
  const blob = await api<Blob>(path);
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}

export const inr = (v: string | number) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" }).format(Number(v));
export const qty = (v: string | number) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 3 }).format(Number(v));

export type Page<T> = { items: T[]; total: number; page: number; size: number };
