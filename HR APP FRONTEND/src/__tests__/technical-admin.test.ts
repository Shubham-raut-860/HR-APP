import { afterEach, describe, expect, it, vi } from "vitest";

async function loadTechnicalAdminModule(emailEnvValue: string) {
  vi.resetModules();
  vi.stubEnv("VITE_TECHNICAL_ADMIN_EMAIL", emailEnvValue);
  return import("@/lib/technicalAdmin");
}

describe("technical admin config", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("keeps the current backend default when no frontend override is configured", async () => {
    const { TECHNICAL_ADMIN_EMAIL, isTechnicalAdmin } = await loadTechnicalAdminModule("");

    expect(TECHNICAL_ADMIN_EMAIL).toBe("[email-redacted]");
    expect(isTechnicalAdmin({ role: "admin", email: "[email-redacted]" })).toBe(true);
  });

  it("uses and normalizes VITE_TECHNICAL_ADMIN_EMAIL when configured", async () => {
    const { TECHNICAL_ADMIN_EMAIL, isTechnicalAdmin } = await loadTechnicalAdminModule(" [email-redacted] ");

    expect(TECHNICAL_ADMIN_EMAIL).toBe("[email-redacted]");
    expect(isTechnicalAdmin({ role: "admin", email: "[email-redacted]" })).toBe(true);
    expect(isTechnicalAdmin({ role: "hr", email: "[email-redacted]" })).toBe(false);
  });
});
