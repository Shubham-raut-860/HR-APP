import api from './api';
import {
  clearAccessToken,
  getAccessToken,
  getRefreshToken as getStoredRefreshToken,
  setRefreshToken as setStoredRefreshToken,
} from './tokenStore';

export interface UserOut {
  id: string;
  email: string;
  full_name: string;
  role: 'admin' | 'hr' | 'candidate';
  is_active: boolean;
  bio?: string | null;
  preferences?: Record<string, unknown> | null;
  created_at: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: UserOut;
}

let currentUserPromise: Promise<UserOut> | null = null;
let currentUserCache: { user: UserOut; token: string | null; expiresAt: number } | null = null;
const CURRENT_USER_CACHE_MS = 15_000;

export const clearCurrentUserCache = (): void => {
  currentUserPromise = null;
  currentUserCache = null;
};

export const login = async (email: string, password: string): Promise<LoginResponse> => {
  clearCurrentUserCache();
  const response = await api.post<LoginResponse>('/auth/login', { email, password });
  setStoredRefreshToken(response.data.refresh_token);
  return response.data;
};

export const register = async (
  fullName: string,
  email: string,
  password: string,
  role: 'candidate' | 'hr' = 'candidate',
): Promise<UserOut> => {
  clearCurrentUserCache();
  const response = await api.post<UserOut>('/auth/register', { full_name: fullName, email, password, role });
  return response.data;
};

export const logout = async (): Promise<void> => {
  clearCurrentUserCache();
  const accessToken = getAccessToken();
  const refreshToken = getStoredRefreshToken();
  // Clear local auth state immediately so UI routes flip to logged-out without delay.
  // Keep captured tokens in local variables so we can still revoke server-side state.
  clearAccessToken();
  setStoredRefreshToken(null);
  if (!refreshToken) return;
  try {
    const headers: Record<string, string> = {
      'X-Skip-Auth-Refresh': '1',
    };
    if (accessToken) {
      headers.Authorization = `Bearer ${accessToken}`;
    }
    await api.post(
      '/auth/logout',
      { refresh_token: refreshToken },
      {
        headers,
      }
    );
  } catch {
    // Best effort only: local teardown already completed.
  }
};

export const getCurrentUser = async (): Promise<UserOut> => {
  const token = getAccessToken();
  const now = Date.now();
  if (
    currentUserCache &&
    currentUserCache.token === token &&
    currentUserCache.expiresAt > now
  ) {
    return currentUserCache.user;
  }
  if (currentUserPromise) return currentUserPromise;

  currentUserPromise = api
    .get<UserOut>('/auth/me')
    .then((response) => {
      currentUserCache = {
        user: response.data,
        token,
        expiresAt: Date.now() + CURRENT_USER_CACHE_MS,
      };
      return response.data;
    })
    .finally(() => {
      currentUserPromise = null;
    });
  return currentUserPromise;
};

export const updateProfile = async (data: Partial<Pick<UserOut, 'full_name' | 'bio' | 'preferences'>>): Promise<UserOut> => {
  const response = await api.put<UserOut>('/auth/me', data);
  currentUserCache = {
    user: response.data,
    token: getAccessToken(),
    expiresAt: Date.now() + CURRENT_USER_CACHE_MS,
  };
  return response.data;
};

export const forgotPassword = async (email: string): Promise<{ message: string }> => {
  const response = await api.post<{ message: string }>('/auth/forgot-password', { email });
  return response.data;
};

export const resetPassword = async (token: string, new_password: string): Promise<{ message: string }> => {
  const response = await api.post<{ message: string }>('/auth/reset-password', { token, new_password });
  return response.data;
};

export const verifyResetPasswordToken = async (token: string): Promise<{ valid: boolean; message: string }> => {
  const response = await api.post<{ valid: boolean; message: string }>('/auth/reset-password/verify', { token });
  return response.data;
};

