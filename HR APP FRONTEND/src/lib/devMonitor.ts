type DevUser = {
  email?: string | null;
  role?: string | null;
};

const truthy = new Set(['1', 'true', 'yes', 'on']);

function isEnabledFlag(value: string | undefined): boolean {
  return truthy.has((value || '').trim().toLowerCase());
}

function parseAllowlist(value: string | undefined): string[] {
  if (!value) return [];
  return value
    .split(',')
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
}

export function canSeeDevTokenMonitor(user: DevUser | null | undefined): boolean {
  if (!user?.email) return false;
  if (!(user.role === 'hr' || user.role === 'admin')) return false;

  const env = import.meta.env;
  const enabled = isEnabledFlag(env.VITE_DEV_TOKEN_MONITOR_ENABLED);
  if (!enabled) return false;
  const appEnv = String(env.VITE_APP_ENV || env.MODE || "").trim().toLowerCase();
  if (appEnv === "production") return false;

  const allowlist = parseAllowlist(env.VITE_DEV_TOKEN_MONITOR_USERS);
  if (allowlist.length === 0) return false;

  return allowlist.includes(user.email.trim().toLowerCase());
}
