import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { getCurrentUser, login as apiLogin, logout as apiLogout } from '@/services/auth';
import { clearAccessToken, getAccessToken, setAccessToken } from '@/services/tokenStore';

interface User {
  id: string;
  full_name: string;
  email: string;
  role: 'admin' | 'hr' | 'candidate';
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
          console.error('Failed to fetch user', error);
          if (!cancelled) {
            const currentPath = window.location.pathname;
            // Precise quiz path check — avoids false-positives on URLs like
            // /candidate/quiz-results. Only exact quiz-taking routes should
            // preserve the token on 401 (the quiz uses a separate access_token).
            const isQuizPath =
              currentPath.startsWith('/take-quiz') ||
              currentPath.startsWith('/quiz/');
            if (!isQuizPath) {
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
      // BUG #11 FIX (HIGH): Previously swallowed errors silently, leaving
      // the app in a "stale authenticated" state where the UI shows logged-in
      // but every API call would 401. Clear auth state on failure.
      console.error('Failed to refresh user — clearing auth state', error);
      apiLogout();
      setUser(null);
    }
  };

  const logout = () => {
    // Set user to null FIRST so that isAuthenticated flips to false in the
    // same render batch. If we cleared the token first, there's a render frame
    // where isAuthenticated is still true but the token is gone — any API call
    // during that frame would 401.
    setUser(null);
    apiLogout();
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
