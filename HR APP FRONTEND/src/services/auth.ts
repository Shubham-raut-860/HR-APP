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

export const login = async (email: string, password: string): Promise<LoginResponse> => {
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
  const response = await api.post<UserOut>('/auth/register', { full_name: fullName, email, password, role });
  return response.data;
};

export const logout = async (): Promise<void> => {
  const accessToken = getAccessToken();
  const refreshToken = getStoredRefreshToken();
  // Clear local auth state immediately so UI routes flip to logged-out without delay.
  // Keep captured tokens in local variables so we can still revoke server-side state.
  clearAccessToken();
  setStoredRefreshToken(null);
  if (!refreshToken || !accessToken) return;
  try {
    await api.post(
      '/auth/logout',
      { refresh_token: refreshToken },
      {
        headers: {
          Authorization: `Bearer ${accessToken}`,
          'X-Skip-Auth-Refresh': '1',
        },
      }
    );
  } catch {
    // Best effort only: local teardown already completed.
  }
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

