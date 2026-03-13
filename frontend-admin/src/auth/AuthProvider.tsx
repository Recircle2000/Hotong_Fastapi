import {
  createContext,
  startTransition,
  type ReactNode,
  useContext,
  useEffect,
  useState,
} from "react";

import { ApiError, getSession, loginAdmin, logoutAdmin } from "../lib/api";
import type { SessionUser } from "../lib/types";

type AuthContextValue = {
  isLoading: boolean;
  user: SessionUser | null;
  login: (email: string, password: string) => Promise<SessionUser>;
  logout: () => Promise<void>;
  refreshSession: () => Promise<SessionUser | null>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  async function refreshSession() {
    try {
      const session = await getSession();
      startTransition(() => {
        setUser(session.user);
      });
      return session.user;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        startTransition(() => {
          setUser(null);
        });
        return null;
      }
      throw error;
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void refreshSession();
  }, []);

  async function login(email: string, password: string) {
    const session = await loginAdmin({ email, password });
    startTransition(() => {
      setUser(session.user);
    });
    return session.user;
  }

  async function logout() {
    await logoutAdmin();
    startTransition(() => {
      setUser(null);
    });
  }

  return (
    <AuthContext.Provider
      value={{
        isLoading,
        user,
        login,
        logout,
        refreshSession,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
