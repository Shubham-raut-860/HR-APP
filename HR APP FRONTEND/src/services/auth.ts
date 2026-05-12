import api from './api';
import { clearAccessToken } from './tokenStore';

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

const REFRESH_TOKEN_KEY = 'refresh_token';

const getStoredRefreshToken = (): string | null => {
  if (typeof window === 'undefined') return null;
  const raw = window.sessionStorage.getItem(REFRESH_TOKEN_KEY);
  if (!raw || raw === 'null' || raw === 'undefined') return null;
  return raw;
};

const setStoredRefreshToken = (token: string | null | undefined): void => {
  if (typeof window === 'undefined') return;
  if (token) {
    window.sessionStorage.setItem(REFRESH_TOKEN_KEY, token);
  } else {
    window.sessionStorage.removeItem(REFRESH_TOKEN_KEY);
  }
};

export const login = async (email: string, password: string): Promise<LoginResponse> => {
  const response = await api.post<LoginResponse>('/auth/login', { email, password });
  setStoredRefreshToken(response.data.refresh_token);
  return response.data;
};

// Bug Audit #3: Backend now accepts role ('hr' | 'candidate') — 'admin' is blocked
// by server-side validation. This enables proper candidate self-registration.
export const register = async (
  fullName: string,
  email: string,
  password: string,
  role: 'hr' | 'candidate' = 'hr',
): Promise<UserOut> => {
  const response = await api.post<UserOut>('/auth/register', { full_name: fullName, email, password, role });
  return response.data;
};

export const logout = (): void => {
  const refreshToken = getStoredRefreshToken();
  void (async () => {
    try {
      await api.post(
        '/auth/logout',
        { refresh_token: refreshToken },
        { headers: { 'X-Skip-Auth-Refresh': '1' } }
      );
    } catch {
      // Local teardown must still proceed even if backend logout fails.
    } finally {
      clearAccessToken();
      setStoredRefreshToken(null);
    }
  })();
};

export const getCurrentUser = async (): Promise<UserOut> => {
  const response = await api.get<UserOut>('/auth/me');
  return response.data;
};

export const updateProfile = async (data: Partial<Pick<UserOut, 'full_name' | 'bio' | 'preferences'>>): Promise<UserOut> => {
  const response = await api.put<UserOut>('/auth/me', data);
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
