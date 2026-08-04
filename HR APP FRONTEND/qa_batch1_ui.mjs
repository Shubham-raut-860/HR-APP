import { chromium } from 'playwright';
import fs from 'node:fs';

const FRONTEND = 'http://127.0.0.1:3000';
const OUT_DIR = 'D:/Shubham/HR APP/Harness';
const recruiter = {
  email: 'calib.state.hr.1779376093@example.com',
  password: 'Qa!Pass2026A',
};

fs.mkdirSync(OUT_DIR, { recursive: true });

async function loginRecruiter(page) {
  await page.goto(`${FRONTEND}/login`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('input[type="email"]', { timeout: 30000 });
  await page.fill('input[type="email"]', recruiter.email);
  await page.fill('input[type="password"]', recruiter.password);
  await page.locator('button[type="submit"]').first().click();
  await page.waitForFunction(() => !location.pathname.startsWith('/login'), {}, { timeout: 90000 });
}

async function openCreateJob(page) {
  const direct = page.getByRole('button', { name: /Create Job/i }).first();
  if (await direct.isVisible().catch(() => false)) {
    await direct.click();
    return;
  }
  const newBtn = page.getByRole('button', { name: /New/i }).first();
  await newBtn.click();
  await page.getByRole('menuitem', { name: /Create Job/i }).click();
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  const page = await ctx.newPage();

  await loginRecruiter(page);

  await page.goto(`${FRONTEND}/jobs`, { waitUntil: 'domcontentloaded' });
  await openCreateJob(page);
  await page.waitForSelector('text=Quality Guard', { timeout: 20000 });
  await page.screenshot({ path: `${OUT_DIR}/batch1_jobs_quality_guard.png`, fullPage: true });

  await page.goto(`${FRONTEND}/candidates`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('text=Candidates', { timeout: 30000 });
  await page.waitForTimeout(3000);
  await page.screenshot({ path: `${OUT_DIR}/batch1_candidates_quick_actions.png`, fullPage: true });

  await page.goto(`${FRONTEND}/dashboard`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('text=Audit Trail', { timeout: 30000 });
  await page.screenshot({ path: `${OUT_DIR}/batch1_dashboard_audit_trail.png`, fullPage: true });

  await browser.close();
  console.log(JSON.stringify({ ok: true, screenshots: [
    'batch1_jobs_quality_guard.png',
    'batch1_candidates_quick_actions.png',
    'batch1_dashboard_audit_trail.png',
  ] }));
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
