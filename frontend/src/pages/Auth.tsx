import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Building2 } from "lucide-react";
import { api } from "../api";
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
      const r = await api<{ access_token: string }>("/auth/login", { method: "POST", json: { email, password } });
      await login(r.access_token);
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
      <p className="mt-4 text-center text-sm text-slate-500">New business? <Link className="text-indigo-600 hover:underline" to="/register">Create an account</Link></p>
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
      const r = await api<{ access_token: string }>("/auth/register", { method: "POST", json: f });
      await login(r.access_token);
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
