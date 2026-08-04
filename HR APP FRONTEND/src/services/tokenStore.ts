const TOKEN_KEY = "token";
const SESSION_EXPIRED_KEY = "session_expired";
const REFRESH_TOKEN_KEY = "refresh_token";
const QUIZ_TOKEN_KEY = "quiz_token";
const QUIZ_RUNTIME_TOKEN_KEY = "quiz_access_token";
export const AUTH_STORAGE_EVENT_KEY = "hireai_auth_event";

let accessTokenMemory: string | null = null;

const isBrowser = (): boolean => typeof window !== "undefined";

const normalizeToken = (raw: string | null): string | null => {
  if (!raw || raw === "null" || raw === "undefined") {
    return null;
  }
  return raw;
};

const readSessionToken = (): string | null => {
  if (!isBrowser()) return null;
  return normalizeToken(window.sessionStorage.getItem(TOKEN_KEY));
};

const readLocalToken = (): string | null => {
  if (!isBrowser()) return null;
  return normalizeToken(window.localStorage.getItem(TOKEN_KEY));
};

const writeAuthEvent = (type: "login" | "logout" | "refresh"): void => {
  if (!isBrowser()) return;
  window.localStorage.setItem(
    AUTH_STORAGE_EVENT_KEY,
    JSON.stringify({ type, at: Date.now() })
  );
};

const migrateSessionTokenIfNeeded = (): string | null => {
  if (!isBrowser()) return null;
  const sessionToken = readSessionToken();
  if (!sessionToken) return null;
  window.localStorage.setItem(TOKEN_KEY, sessionToken);
  window.sessionStorage.removeItem(TOKEN_KEY);
  return sessionToken;
};

export const getAccessToken = (): string | null => {
  if (!isBrowser()) return accessTokenMemory;

  const localToken = readLocalToken();
  if (localToken) {
    accessTokenMemory = localToken;
    return accessTokenMemory;
  }

  const migrated = migrateSessionTokenIfNeeded();
  if (migrated) {
    accessTokenMemory = migrated;
    return accessTokenMemory;
  }

  accessTokenMemory = null;
  return null;
};

export const setAccessToken = (token: string): void => {
  const normalized = normalizeToken(token);
  accessTokenMemory = normalized;
  if (!isBrowser()) return;
  if (normalized) {
    window.sessionStorage.removeItem(SESSION_EXPIRED_KEY);
    window.sessionStorage.removeItem(TOKEN_KEY);
    window.localStorage.setItem(TOKEN_KEY, normalized);
    writeAuthEvent("login");
  } else {
    window.sessionStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(TOKEN_KEY);
    writeAuthEvent("logout");
  }
};

export const clearAccessToken = (): void => {
  accessTokenMemory = null;
  if (!isBrowser()) return;
  window.sessionStorage.removeItem(TOKEN_KEY);
  window.sessionStorage.removeItem(SESSION_EXPIRED_KEY);
  window.localStorage.removeItem(TOKEN_KEY);
  writeAuthEvent("logout");
};

export const markSessionExpired = (): void => {
  if (!isBrowser()) return;
  window.sessionStorage.setItem(SESSION_EXPIRED_KEY, "1");
};

export const isSessionExpiredMarked = (): boolean => {
  if (!isBrowser()) return false;
  return window.sessionStorage.getItem(SESSION_EXPIRED_KEY) === "1";
};

export const clearSessionExpiredMark = (): void => {
  if (!isBrowser()) return;
  window.sessionStorage.removeItem(SESSION_EXPIRED_KEY);
};

export const getRefreshToken = (): string | null => {
  if (!isBrowser()) return null;
  const localToken = normalizeToken(window.localStorage.getItem(REFRESH_TOKEN_KEY));
  if (localToken) return localToken;
  const sessionToken = normalizeToken(window.sessionStorage.getItem(REFRESH_TOKEN_KEY));
  if (sessionToken) {
    window.localStorage.setItem(REFRESH_TOKEN_KEY, sessionToken);
    window.sessionStorage.removeItem(REFRESH_TOKEN_KEY);
  }
  return sessionToken;
};

export const setRefreshToken = (token: string | null | undefined): void => {
  if (!isBrowser()) return;
  const normalized = normalizeToken(token ?? null);
  if (normalized) {
    window.sessionStorage.removeItem(REFRESH_TOKEN_KEY);
    window.localStorage.setItem(REFRESH_TOKEN_KEY, normalized);
    writeAuthEvent("refresh");
  } else {
    window.sessionStorage.removeItem(REFRESH_TOKEN_KEY);
    window.localStorage.removeItem(REFRESH_TOKEN_KEY);
    writeAuthEvent("logout");
  }
};

export const getQuizToken = (): string | null => {
  if (!isBrowser()) return null;
  return normalizeToken(window.sessionStorage.getItem(QUIZ_TOKEN_KEY));
};

export const setQuizToken = (token: string | null | undefined): void => {
  if (!isBrowser()) return;
  const normalized = normalizeToken(token ?? null);
  if (normalized) {
    window.sessionStorage.setItem(QUIZ_TOKEN_KEY, normalized);
  } else {
    window.sessionStorage.removeItem(QUIZ_TOKEN_KEY);
  }
};

export const clearQuizToken = (): void => {
  if (!isBrowser()) return;
  window.sessionStorage.removeItem(QUIZ_TOKEN_KEY);
};

export const getQuizRuntimeToken = (): string | null => {
  if (!isBrowser()) return null;
  return normalizeToken(window.sessionStorage.getItem(QUIZ_RUNTIME_TOKEN_KEY));
};

export const setQuizRuntimeToken = (token: string | null | undefined): void => {
  if (!isBrowser()) return;
  const normalized = normalizeToken(token ?? null);
  if (normalized) {
    window.sessionStorage.setItem(QUIZ_RUNTIME_TOKEN_KEY, normalized);
  } else {
    window.sessionStorage.removeItem(QUIZ_RUNTIME_TOKEN_KEY);
  }
};
