import { chromium } from 'playwright';
import fs from 'node:fs';

const FRONTEND = 'http://127.0.0.1:3000';
const OUT_DIR = 'D:/Shubham/HR APP/Harness';
const recruiter = { email: 'harness.auto.hr.1779358460@example.com', password: 'HarnessAuto@123' };
const candidate = { email: 'harness.auto.cand.1779358460@example.com', password: 'HarnessAuto@123' };

fs.mkdirSync(OUT_DIR, { recursive: true });

async function login(page, creds) {
  await page.goto(`${FRONTEND}/login`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('input[type="email"]', { timeout: 30000 });
  await page.fill('input[type="email"]', creds.email);
  await page.fill('input[type="password"]', creds.password);
  await page.locator('button[type="submit"]').first().click();
  await page.waitForFunction(() => !location.pathname.startsWith('/login'), {}, { timeout: 90000 });
}

async function captureRecruiter(page) {
  const shots = [];

  await page.goto(`${FRONTEND}/jobs`, { waitUntil: 'domcontentloaded' });
  const createBtn = page.getByRole('button', { name: /Create Job/i }).first();
  if (await createBtn.isVisible().catch(() => false)) {
    await createBtn.click();
  } else {
    const newBtn = page.getByRole('button', { name: /New/i }).first();
    await newBtn.click();
    await page.getByRole('menuitem', { name: /Create Job/i }).click();
  }
  await page.waitForSelector('text=Quality Guard', { timeout: 30000 });
  const qgPath = `${OUT_DIR}/batch2_recruiter_quality_guard.png`;
  await page.screenshot({ path: qgPath, fullPage: true });
  shots.push(qgPath);

  await page.goto(`${FRONTEND}/candidates`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  const bulkBtn = page.getByRole('button', { name: /bulk upload/i }).first();
  if (await bulkBtn.isVisible().catch(() => false)) {
    await bulkBtn.click();
    await page.waitForTimeout(1000);
    const bulkPath = `${OUT_DIR}/batch2_bulk_review_step.png`;
    await page.screenshot({ path: bulkPath, fullPage: true });
    shots.push(bulkPath);
  }

  await page.goto(`${FRONTEND}/dashboard`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('text=Audit Trail', { timeout: 30000 });
  const auditPath = `${OUT_DIR}/batch2_recruiter_audit_trail.png`;
  await page.screenshot({ path: auditPath, fullPage: true });
  shots.push(auditPath);

  await page.goto(`${FRONTEND}/notifications`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('text=Notifications', { timeout: 30000 });
  const notifPath = `${OUT_DIR}/batch2_recruiter_notifications_center.png`;
  await page.screenshot({ path: notifPath, fullPage: true });
  shots.push(notifPath);

  return shots;
}

async function captureCandidate(page) {
  const shots = [];

  await page.goto(`${FRONTEND}/candidate/progress`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('text=Application Status Timeline', { timeout: 30000 });
  const timelinePath = `${OUT_DIR}/batch2_candidate_timeline.png`;
  await page.screenshot({ path: timelinePath, fullPage: true });
  shots.push(timelinePath);

  await page.goto(`${FRONTEND}/candidate/notifications`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('text=Notifications', { timeout: 30000 });
  const cnotifPath = `${OUT_DIR}/batch2_candidate_notifications_center.png`;
  await page.screenshot({ path: cnotifPath, fullPage: true });
  shots.push(cnotifPath);

  await page.goto(`${FRONTEND}/candidate/dashboard`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200);
  const startBtn = page.getByRole('link', { name: /Start Assessment/i }).first();
  if (await startBtn.isVisible().catch(() => false)) {
    await startBtn.click();
    await page.waitForURL('**/take-quiz**', { timeout: 45000 });
    await page.waitForSelector('text=Question 1 of', { timeout: 30000 });
    const quizPath = `${OUT_DIR}/batch2_quiz_flow_polish.png`;
    await page.screenshot({ path: quizPath, fullPage: true });
    shots.push(quizPath);
  } else {
    const noQuizPath = `${OUT_DIR}/batch2_quiz_flow_no_pending_quiz.png`;
    await page.screenshot({ path: noQuizPath, fullPage: true });
    shots.push(noQuizPath);
  }

  return shots;
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const allShots = [];

  const hrCtx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  const hrPage = await hrCtx.newPage();
  await login(hrPage, recruiter);
  allShots.push(...(await captureRecruiter(hrPage)));
  await hrCtx.close();

  const candCtx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  const candPage = await candCtx.newPage();
  await login(candPage, candidate);
  allShots.push(...(await captureCandidate(candPage)));
  await candCtx.close();

  await browser.close();
  console.log(JSON.stringify({ ok: true, screenshots: allShots }, null, 2));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
