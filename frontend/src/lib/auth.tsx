import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, setUnauthorizedHandler, token, type Me, type Role } from "./api";

const RANK: Record<Role, number> = { viewer: 0, analyst: 1, admin: 2 };

interface AuthCtx {
  me: Me | null;
  loading: boolean;
  login: (u: string, p: string) => Promise<void>;
  logout: () => Promise<void>;
  can: (role: Role) => boolean;
}

const Ctx = createContext<AuthCtx>(null as unknown as AuthCtx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const qc = useQueryClient();

  useEffect(() => {
    setUnauthorizedHandler(() => {
      token.set(null);
      setMe(null);
    });
    api<Me>("/api/auth/me")
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const r = await api<{ token: string; user: Me }>("/api/auth/login", { method: "POST", json: { username, password } });
    token.set(r.token);
    setMe({ id: r.user.id, username: r.user.username, role: r.user.role });
  }, []);

  const logout = useCallback(async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    token.set(null);
    setMe(null);
    qc.clear();
  }, [qc]);

  const can = useCallback((role: Role) => !!me && RANK[me.role] >= RANK[role], [me]);

  return <Ctx.Provider value={{ me, loading, login, logout, can }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
