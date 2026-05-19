import axios, { AxiosHeaders } from 'axios';
import { API_BASE_URL } from '@/config';
import {
  clearAccessToken,
  getAccessToken,
  getRefreshToken,
  isSessionExpiredMarked,
  markSessionExpired,
  setAccessToken,
  setRefreshToken,
} from './tokenStore';

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

let refreshAccessPromise: Promise<string | null> | null = null;

// Attach token to every request
api.interceptors.request.use(
  (config) => {
    const requestUrl = String(config.url ?? '');
    const headers = (config.headers ?? {}) as Record<string, string>;

    // Attach a client-generated request id for backend log correlation.
    if (!headers['X-Client-Request-Id']) {
      const rid =
        typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
          ? crypto.randomUUID()
          : `req-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
      headers['X-Client-Request-Id'] = rid;
    }

    // Enforce fast-fail timeout policy for high-frequency sidebar polling,
    // even if callers omit overrides or a stale bundle loads older call-sites.
    if (requestUrl.includes('/analytics/metrics/untagged')) {
      headers['X-Skip-Auth-Refresh'] = '1';
      config.timeout = Math.min(Number(config.timeout ?? 8_000), 8_000);
    }

    if (!config.headers) {
      config.headers = new AxiosHeaders();
    }
    Object.assign(config.headers as Record<string, string>, headers);
    const token = getAccessToken();
    if (token) {
      (config.headers as Record<string, string>)['Authorization'] = `Bearer ${token}`;
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
            if (!refreshAccessPromise) {
              refreshAccessPromise = (async () => {
                const refreshResponse = await axios.post(
                  `${API_BASE_URL}/auth/refresh`,
                  { refresh_token: refreshToken },
                  {
                    headers: {
                      'Content-Type': 'application/json',
                      'X-Skip-Auth-Refresh': '1',
                    },
                    // Keep refresh bounded; 2-minute hangs cascade into repeated
                    // UI timeouts and make the app appear frozen.
                    timeout: 15_000,
                  }
                );
                const newAccessToken = refreshResponse?.data?.access_token as string | undefined;
                const newRefreshToken = refreshResponse?.data?.refresh_token as string | undefined;
                if (newAccessToken) {
                  setAccessToken(newAccessToken);
                  setRefreshToken(newRefreshToken ?? refreshToken);
                  return newAccessToken;
                }
                return null;
              })().finally(() => {
                refreshAccessPromise = null;
              });
            }
            const newAccessToken = await refreshAccessPromise;
            if (newAccessToken) {
              originalRequest.headers = originalRequest.headers ?? {};
              originalRequest.headers.Authorization = `Bearer ${newAccessToken}`;
              return api(originalRequest);
            }
          } catch (refreshError: any) {
            if (refreshError?.response?.status === 401 || refreshError?.response?.status === 403) {
              clearAccessToken();
              setRefreshToken(null);
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
          markSessionExpired();
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
            // and only auto-redirect if the modal listener did not consume the
            // expiry event (it clears the marker immediately on open).
            if (
              isSessionExpiredMarked() &&
              !getAccessToken() &&
              !window.location.pathname.startsWith('/login')
            ) {
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
