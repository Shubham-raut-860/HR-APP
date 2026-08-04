import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import {
  clearCurrentUserCache,
  getCurrentUser,
  login as apiLogin,
  logout as apiLogout,
} from '@/services/auth';
import {
  AUTH_STORAGE_EVENT_KEY,
  clearAccessToken,
  getAccessToken,
  getRefreshToken,
  setAccessToken,
} from '@/services/tokenStore';

interface User {
  id: string;
  full_name: string;
  email: string;
  role: 'admin' | 'hr' | 'candidate';
  preferences?: Record<string, unknown> | null;
}

interface AuthContextType {
  user: User | null;
  login: (email: string, password: string) => Promise<User>;  // FIX (Bug #3): was Promise<void> — mismatch with actual impl that returns User for role-based routing
  logout: () => void;
  refreshUser: () => Promise<void>;
  isAuthenticated: boolean;
  loading: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);
const EXPECTED_AUTH_STATUSES = new Set([401, 403, 429]);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Stale-closure guard: if the component unmounts (HMR, StrictMode double-
    // mount) before the API call resolves, we must NOT call setUser with the
    // response — it would update unmounted state and could race with a second
    // mount's checkAuth.
    let cancelled = false;

    const checkAuth = async () => {
      const token = getAccessToken();
      if (token) {
        try {
          const userData = await getCurrentUser();
          if (!cancelled) setUser(userData);
        } catch (error) {
          const status = (error as any)?.response?.status as number | undefined;
          if (!status || !EXPECTED_AUTH_STATUSES.has(status)) {
            console.warn('Failed to fetch user', error);
          }
          if (!cancelled) {
            const currentPath = window.location.pathname;
            // Precise quiz path check — avoids false-positives on URLs like
            // /candidate/quiz-results. Only exact quiz-taking routes should
            // preserve the token on 401 (the quiz uses a separate access_token).
            const isQuizPath =
              currentPath.startsWith('/take-quiz') ||
              currentPath.startsWith('/quiz/');
            const hasRefreshToken = !!getRefreshToken();
            const isAuthFailure = status === 401 || status === 403;
            // Keep token when a refresh token still exists. The axios interceptor
            // may still complete rotation for this bootstrap request.
            if (!isQuizPath && (!isAuthFailure || !hasRefreshToken)) {
              clearAccessToken();
            }
          }
        }
      }
      if (!cancelled) setLoading(false);
    };
    checkAuth();

    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const handleAuthStorage = async (event: StorageEvent) => {
      if (
        event.key !== AUTH_STORAGE_EVENT_KEY &&
        event.key !== 'token' &&
        event.key !== 'refresh_token'
      ) {
        return;
      }

      clearCurrentUserCache();
      const token = getAccessToken();
      if (!token) {
        setUser(null);
        return;
      }

      try {
        const userData = await getCurrentUser();
        setUser(userData);
      } catch (error) {
        const status = (error as any)?.response?.status as number | undefined;
        if (status === 401 || status === 403) {
          clearAccessToken();
          setUser(null);
        }
      }
    };

    window.addEventListener('storage', handleAuthStorage);
    return () => window.removeEventListener('storage', handleAuthStorage);
  }, []);

  const login = async (email: string, password: string) => {
    try {
      const { access_token, user } = await apiLogin(email, password);
      setAccessToken(access_token);
      setUser(user);
      return user;
    } catch (error: any) {
      // Surface the actual API error message so callers can show it in the UI
      // instead of always showing a generic "Login failed" message.
      const message =
        error?.response?.data?.detail ||
        error?.message ||
        'Login failed. Please check your credentials.';
      throw new Error(message);
    }
  };

  const refreshUser = async () => {
    try {
      const userData = await getCurrentUser();
      setUser(userData);
    } catch (error) {
      const status = (error as any)?.response?.status as number | undefined;
      const isAuthFailure = status === 401 || status === 403;
      if (isAuthFailure) {
        await apiLogout();
        setUser(null);
        return;
      }
      // Transient upstream/network errors should not force logout.
      console.warn('Failed to refresh user (transient)', error);
    }
  };

  const logout = () => {
    // Set user to null FIRST so that isAuthenticated flips to false in the
    // same render batch. If we cleared the token first, there's a render frame
    // where isAuthenticated is still true but the token is gone — any API call
    // during that frame would 401.
    setUser(null);
    void apiLogout();
  };

  return (
    <AuthContext.Provider value={{ user, login, logout, refreshUser, isAuthenticated: !!user, loading }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
