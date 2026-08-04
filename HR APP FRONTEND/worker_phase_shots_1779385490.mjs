
import { chromium } from 'playwright';

const FRONTEND = 'http://127.0.0.1:3000';
const OUT = 'D:/Shubham/HR APP/Harness';
const STAMP = '1779385490';
const recruiter = {"first": "QA", "last": "Recruiter1779385510448", "email": "qa.recruiter.1779385510448@example.com", "password": "Qa!Pass2026A"};
const candidate = {"first": "QA", "last": "Candidate1779385510448", "email": "qa.candidate.1779385510448@example.com", "password": "Qa!Pass2026A"};
const jobId = '4ddddabb-1c63-423e-8822-3fbffefa8d82';

async function login(page, creds) {
  await page.goto(`${FRONTEND}/login`, { waitUntil: 'networkidle' });
  await page.waitForSelector('input[type="email"]', { timeout: 20000 });
  await page.fill('input[type="email"]', creds.email);
  await page.fill('input[type="password"]', creds.password);
  await page.click('button[type="submit"]');
  await page.waitForTimeout(3000);
}

(async()=>{
  const browser = await chromium.launch({ headless: true });
  const hrCtx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  const hr = await hrCtx.newPage();
  await login(hr, recruiter);
  await hr.goto(`${FRONTEND}/dashboard`, { waitUntil: 'networkidle' });
  await hr.screenshot({ path: `${OUT}/worker_phase_1779385490_01_recruiter_dashboard.png`, fullPage: true });
  await hr.goto(`${FRONTEND}/jobs`, { waitUntil: 'networkidle' });
  await hr.screenshot({ path: `${OUT}/worker_phase_1779385490_02_recruiter_jobs.png`, fullPage: true });
  await hr.goto(`${FRONTEND}/jobs/${jobId}`, { waitUntil: 'networkidle' });
  await hr.screenshot({ path: `${OUT}/worker_phase_1779385490_03_recruiter_job_detail.png`, fullPage: true });
  await hr.goto(`${FRONTEND}/jobs/${jobId}`, { waitUntil: 'networkidle' });
  await hr.getByRole('tab', { name: /Quiz/i }).click();
  await hr.waitForTimeout(1200);
  await hr.screenshot({ path: `${OUT}/worker_phase_1779385490_04_recruiter_quiz_tab.png`, fullPage: true });
  await hrCtx.close();

  const cCtx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  const c = await cCtx.newPage();
  await login(c, candidate);
  await c.goto(`${FRONTEND}/candidate/dashboard`, { waitUntil: 'networkidle' });
  await c.screenshot({ path: `${OUT}/worker_phase_1779385490_05_candidate_dashboard.png`, fullPage: true });
  await c.goto(`${FRONTEND}/candidate/jobs`, { waitUntil: 'networkidle' });
  await c.screenshot({ path: `${OUT}/worker_phase_1779385490_06_candidate_jobs.png`, fullPage: true });
  await c.goto(`${FRONTEND}/candidate/jobs/${jobId}`, { waitUntil: 'networkidle' });
  await c.screenshot({ path: `${OUT}/worker_phase_1779385490_07_candidate_job_detail.png`, fullPage: true });
  await c.goto(`${FRONTEND}/candidate/mock-test`, { waitUntil: 'networkidle' });
  await c.screenshot({ path: `${OUT}/worker_phase_1779385490_08_candidate_mock_test.png`, fullPage: true });
  await cCtx.close();
  await browser.close();
})();
