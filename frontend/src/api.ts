export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const TOKEN_KEY = "netcare.token";
const REFRESH_KEY = "netcare.refresh";
const ORG_KEY = "netcare.org";

export const session = {
  get token() { return localStorage.getItem(TOKEN_KEY); },
  set token(v: string | null) { v ? localStorage.setItem(TOKEN_KEY, v) : localStorage.removeItem(TOKEN_KEY); },
  get refresh() { return localStorage.getItem(REFRESH_KEY); },
  set refresh(v: string | null) { v ? localStorage.setItem(REFRESH_KEY, v) : localStorage.removeItem(REFRESH_KEY); },
  get orgId() { return localStorage.getItem(ORG_KEY); },
  set orgId(v: string | null) { v ? localStorage.setItem(ORG_KEY, v) : localStorage.removeItem(ORG_KEY); },
};

function formatDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail.map((d: any) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
  return "Request failed";
}

export type Tokens = { access_token: string; refresh_token?: string | null };

export function storeTokens(t: Tokens) {
  session.token = t.access_token;
  if (t.refresh_token) session.refresh = t.refresh_token;
}

let refreshing: Promise<boolean> | null = null;

/** Swap the refresh token for new tokens. Parallel requests share one attempt (tokens rotate on use). */
function refreshTokens(): Promise<boolean> {
  if (!session.refresh) return Promise.resolve(false);
  refreshing ??= fetch("/api/v1/auth/refresh", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: session.refresh }),
  }).then(async (r) => {
    if (!r.ok) { session.refresh = null; return false; }
    storeTokens(await r.json());
    return true;
  }).catch(() => false).finally(() => { refreshing = null; });
  return refreshing;
}

export async function api<T = any>(path: string, opts: RequestInit & { json?: unknown } = {}, retried = false): Promise<T> {
  const headers = new Headers(opts.headers);
  if (session.token) headers.set("Authorization", `Bearer ${session.token}`);
  if (session.orgId) headers.set("X-Organization-ID", session.orgId);
  let body = opts.body;
  if (opts.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(opts.json);
  }
  const res = await fetch(`/api/v1${path}`, { ...opts, headers, body });
  if (res.status === 401 && session.token && !path.startsWith("/auth/login")) {
    if (!retried && await refreshTokens()) return api<T>(path, opts, true);
    session.token = null;
    session.refresh = null;
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

/** Open an authenticated PDF in a new tab for viewing/printing. The tab is opened before the request
 *  so popup blockers treat it as a direct result of the click. */
export async function openPdf(path: string) {
  const win = window.open("", "_blank");
  try {
    const blob = await api<Blob>(path);
    const url = URL.createObjectURL(blob);
    if (win) win.location.href = url;
    else window.location.href = url;
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (e) {
    win?.close();
    throw e;
  }
}

export const inr = (v: string | number) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" }).format(Number(v));
export const qty = (v: string | number) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 3 }).format(Number(v));

export type Page<T> = { items: T[]; total: number; page: number; size: number };
