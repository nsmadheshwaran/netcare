import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Building2 } from "lucide-react";
import { api, type Tokens } from "../api";
import { useAuth } from "../auth";
import { ErrorBanner, Field } from "../components/ui";

function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <Building2 className="mx-auto mb-2 text-indigo-600" size={36} />
          <h1 className="text-xl font-semibold">NetCare Business Suite</h1>
          <p className="text-sm text-slate-500">One platform to manage your business and IT infrastructure.</p>
        </div>
        <div className="card">
          <h2 className="mb-4 font-semibold">{title}</h2>
          {children}
        </div>
      </div>
    </div>
  );
}

export function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api<Tokens>("/auth/login", { method: "POST", json: { email, password } });
      await login(r);
      nav("/");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell title="Sign in">
      <ErrorBanner message={error} />
      <form onSubmit={submit} className="space-y-3">
        <Field label="Email"><input className="input" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Password"><input className="input" type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
        <button className="btn-primary w-full justify-center" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
      <p className="mt-3 text-center text-sm"><Link className="text-indigo-600 hover:underline" to="/forgot-password">Forgot password?</Link></p>
      <p className="mt-2 text-center text-sm text-slate-500">New business? <Link className="text-indigo-600 hover:underline" to="/register">Create an account</Link></p>
    </Shell>
  );
}

export function Register() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [f, setF] = useState({ full_name: "", email: "", password: "", organization_name: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api<Tokens>("/auth/register", { method: "POST", json: f });
      await login(r);
      nav("/");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell title="Create your business account">
      <ErrorBanner message={error} />
      <form onSubmit={submit} className="space-y-3">
        <Field label="Business name"><input className="input" required value={f.organization_name} onChange={set("organization_name")} /></Field>
        <Field label="Your name"><input className="input" required value={f.full_name} onChange={set("full_name")} /></Field>
        <Field label="Email"><input className="input" type="email" required autoComplete="email" value={f.email} onChange={set("email")} /></Field>
        <Field label="Password (min 10 characters)"><input className="input" type="password" required minLength={10} autoComplete="new-password" value={f.password} onChange={set("password")} /></Field>
        <button className="btn-primary w-full justify-center" disabled={busy}>{busy ? "Creating…" : "Create account"}</button>
      </form>
      <p className="mt-4 text-center text-sm text-slate-500">Already registered? <Link className="text-indigo-600 hover:underline" to="/login">Sign in</Link></p>
    </Shell>
  );
}

export function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [emailEnabled, setEmailEnabled] = useState<boolean | null>(null);
  useEffect(() => { api<{ email_enabled: boolean }>("/auth/config").then((c) => setEmailEnabled(c.email_enabled)).catch(() => setEmailEnabled(true)); }, []);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try { setDone((await api<{ detail: string }>("/auth/forgot-password", { method: "POST", json: { email } })).detail); }
    catch (err: any) { setError(err.message); }
  }
  return (
    <Shell title="Reset your password">
      <ErrorBanner message={error} />
      {emailEnabled === false ? (
        <p className="text-sm text-slate-600 dark:text-slate-300">Email is not set up on this NetCare server, so reset links cannot be sent. Ask your business owner or manager to reset your password under Users and Roles.</p>
      ) : done ? (
        <p className="text-sm text-slate-600 dark:text-slate-300">{done} Check your inbox (and spam folder). The link works once and expires soon.</p>
      ) : (
        <form onSubmit={submit} className="space-y-3">
          <Field label="Your email"><input className="input" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          <button className="btn-primary w-full justify-center">Send reset link</button>
        </form>
      )}
      <p className="mt-4 text-center text-sm"><Link className="text-indigo-600 hover:underline" to="/login">Back to sign in</Link></p>
    </Shell>
  );
}

/** Opened from an invite or reset email. The token is in the URL fragment, which browsers never send to servers. */
export function SetPassword() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [token] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get("token") ?? "");
  const [pw, setPw] = useState({ a: "", b: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (window.location.hash) history.replaceState(null, "", window.location.pathname); }, []);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (pw.a !== pw.b) return setError("The two passwords are different");
    setBusy(true);
    setError(null);
    try {
      const r = await api<Tokens>("/auth/set-password", { method: "POST", json: { token, password: pw.a } });
      await login(r);
      nav("/");
    } catch (err: any) { setError(err.message); } finally { setBusy(false); }
  }
  return (
    <Shell title="Choose your password">
      <ErrorBanner message={error} />
      {!token ? <p className="text-sm text-slate-600 dark:text-slate-300">This link is incomplete. Open it again from your email, or ask for a new one.</p> : (
        <form onSubmit={submit} className="space-y-3">
          <Field label="New password (min 10 characters)"><input className="input" type="password" required minLength={10} autoComplete="new-password" value={pw.a} onChange={(e) => setPw({ ...pw, a: e.target.value })} /></Field>
          <Field label="Repeat it"><input className="input" type="password" required minLength={10} autoComplete="new-password" value={pw.b} onChange={(e) => setPw({ ...pw, b: e.target.value })} /></Field>
          <button className="btn-primary w-full justify-center" disabled={busy}>{busy ? "Saving…" : "Save and sign in"}</button>
          <p className="text-xs text-slate-500">This signs you out on every other device.</p>
        </form>
      )}
    </Shell>
  );
}
