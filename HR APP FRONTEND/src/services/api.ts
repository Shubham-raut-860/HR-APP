import axios from 'axios';
import { API_BASE_URL } from '@/config';
import { clearAccessToken, getAccessToken, markSessionExpired, setAccessToken } from './tokenStore';

const REFRESH_TOKEN_KEY = 'refresh_token';

const getRefreshToken = (): string | null => {
  if (typeof window === 'undefined') return null;
  const raw = window.sessionStorage.getItem(REFRESH_TOKEN_KEY);
  if (!raw || raw === 'null' || raw === 'undefined') return null;
  return raw;
};

const setRefreshToken = (token: string | null | undefined): void => {
  if (typeof window === 'undefined') return;
  if (token) {
    window.sessionStorage.setItem(REFRESH_TOKEN_KEY, token);
  } else {
    window.sessionStorage.removeItem(REFRESH_TOKEN_KEY);
  }
};

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  // BUG #5 FIX (HIGH): 30s was too short for bulk AI operations (resume
  // parsing, JD generation). Increased to 120s so long-running requests
  // complete instead of failing with a confusing "Network Error".
  timeout: 120_000,
});

// Attach token to every request
api.interceptors.request.use(
  (config) => {
    const token = getAccessToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// FIX F-18: Exclude quiz endpoints from the global 401→logout redirect
// so candidates are not forced out mid-assessment if the token expires.
// FIX F-26 (api side): Guard against the string "null" stored in localStorage
// which is truthy but not a valid token, causing spurious auth redirects.
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = (error?.config ?? {}) as any;
    const requestUrl = String(originalRequest?.url ?? '');
    const skipAuthRefreshHeader =
      String(originalRequest?.headers?.['X-Skip-Auth-Refresh'] ?? '') === '1';
    const isAuthRequest =
      requestUrl.includes('/auth/login') ||
      requestUrl.includes('/auth/refresh') ||
      requestUrl.includes('/auth/logout');

    if (error.response?.status === 401) {
      if (!originalRequest?._retry && !skipAuthRefreshHeader && !isAuthRequest) {
        const refreshToken = getRefreshToken();
        if (refreshToken) {
          originalRequest._retry = true;
          try {
            const refreshResponse = await axios.post(
              `${API_BASE_URL}/auth/refresh`,
              { refresh_token: refreshToken },
              {
                headers: {
                  'Content-Type': 'application/json',
                  'X-Skip-Auth-Refresh': '1',
                },
                timeout: 120_000,
              }
            );
            const newAccessToken = refreshResponse?.data?.access_token as string | undefined;
            const newRefreshToken = refreshResponse?.data?.refresh_token as string | undefined;
            if (newAccessToken) {
              setAccessToken(newAccessToken);
              setRefreshToken(newRefreshToken ?? refreshToken);
              originalRequest.headers = originalRequest.headers ?? {};
              originalRequest.headers.Authorization = `Bearer ${newAccessToken}`;
              return api(originalRequest);
            }
          } catch (refreshError: any) {
            if (refreshError?.response?.status === 401 || refreshError?.response?.status === 403) {
              try {
                const { logout } = await import('./auth');
                logout();
              } catch {
                clearAccessToken();
                setRefreshToken(null);
              }
              const redirectPath = window.location.pathname + window.location.search;
              window.location.href = `/login?redirect=${encodeURIComponent(redirectPath)}`;
              return Promise.reject(refreshError);
            }
          }
        }
      }

      const hasValidToken = !!getAccessToken();
      const currentPath = window.location.pathname;
      // Don't redirect when:
      //  1. No valid token (unauthenticated 401 e.g. password check)
      //  2. Already on login
      //  3. Mid-quiz — candidates lose all answers otherwise
      const isQuizPath =
        currentPath.startsWith('/take-quiz') ||
        currentPath.startsWith('/quiz/');

      if (hasValidToken && !currentPath.startsWith('/login')) {
        if (isQuizPath) {
          // Quiz in progress: don't redirect or remove token, but flag the
          // session as stale so AuthContext can prompt re-login when the user
          // navigates away from the quiz.
          markSessionExpired();
        } else {
          clearAccessToken();
          setRefreshToken(null);
          // Dispatch a custom event instead of window.location.href so React
          // can display a "session expired" modal without destroying unsaved
          // form state (e.g. a half-filled JD form).
          // FOLLOW-UP: Add a <SessionExpiredModal> listener in App.tsx that
          // catches this event and shows a re-login prompt.
          const redirectPath = currentPath + window.location.search;
          window.dispatchEvent(
            new CustomEvent('auth:session-expired', {
              detail: { redirect: redirectPath },
            })
          );
          // Fallback: if no listener is registered (e.g. app hasn't mounted
          // the modal yet), redirect after a short delay.
          setTimeout(() => {
            // Check if token is still removed (listener didn't re-auth)
            if (!getAccessToken()) {
              window.location.href = `/login?redirect=${encodeURIComponent(redirectPath)}`;
            }
          }, 3000);
        }
      }
    }
    return Promise.reject(error);
  }
);

export default api;
