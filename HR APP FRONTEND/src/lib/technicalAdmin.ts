const DEFAULT_TECHNICAL_ADMIN_EMAIL = "[email-redacted]";

export const TECHNICAL_ADMIN_EMAIL = (
  import.meta.env.VITE_TECHNICAL_ADMIN_EMAIL || DEFAULT_TECHNICAL_ADMIN_EMAIL
)
  .trim()
  .toLowerCase();

export function isTechnicalAdmin(user: { email?: string | null; role?: string | null } | null | undefined): boolean {
  return user?.role === "admin" && user?.email?.trim().toLowerCase() === TECHNICAL_ADMIN_EMAIL;
}
