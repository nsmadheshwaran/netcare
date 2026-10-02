import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, session } from "./api";

export type Membership = { organization_id: number; organization_name: string; role: string; permissions: string[] };
type Me = { user: { id: number; email: string; full_name: string }; memberships: Membership[] };

type AuthState = {
  me: Me | null;
  loading: boolean;
  current: Membership | null;
  can: (perm: string) => boolean;
  login: (token: string) => Promise<void>;
  logout: () => void;
  switchOrg: (id: number) => void;
  refresh: () => Promise<void>;
};

const Ctx = createContext<AuthState>(null!);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!session.token) { setMe(null); setLoading(false); return; }
    try {
      const m = await api<Me>("/auth/me");
      if (!m.memberships.some((x) => String(x.organization_id) === session.orgId))
        session.orgId = m.memberships[0] ? String(m.memberships[0].organization_id) : null;
      setMe(m);
    } catch {
      setMe(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const current = me?.memberships.find((m) => String(m.organization_id) === session.orgId) ?? null;
  const value: AuthState = {
    me, loading, current,
    // UI hint only; the API enforces every permission.
    can: (p) => !!current?.permissions.includes(p),
    login: async (token) => { session.token = token; session.orgId = null; await refresh(); },
    logout: () => { session.token = null; session.orgId = null; setMe(null); },
    switchOrg: (id) => { session.orgId = String(id); window.location.assign("/"); },
    refresh,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
