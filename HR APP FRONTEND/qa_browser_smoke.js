import { chromium } from 'playwright';

const BASE = 'http://127.0.0.1:3000';
const HR = { email: '[email-redacted]', password: 'Qa!Pass2026A' };
const CAND = { email: '[email-redacted]', password: 'Qa!Pass2026A' };
const KNOWN_CANDIDATE_ID = '99e2ce15-b1af-497b-b3fa-47dee8e694e5';

function isIgnorableConsole(msgText) {
  const t = msgText || '';
  return t.includes('Download the React DevTools') || t.includes('favicon') || t.includes('Launched external handler for');
}

async function login(page, creds) {
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
  await page.waitForSelector('input[type="email"]', { timeout: 15000 });
  await page.waitForSelector('input[type="password"]', { timeout: 15000 });
  await page.fill('input[type="email"]', creds.email);
  await page.fill('input[type="password"]', creds.password);
  const submit = page.locator('button[type="submit"]');
  await submit.click();
  await page.waitForTimeout(3500);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const results = {
    recruiter: {},
    candidate: {},
    candidateDetails: {},
    timestamp: new Date().toISOString(),
  };

  {
    const context = await browser.newContext();
    const page = await context.newPage();
    const consoleErrors = [];
    const pageErrors = [];
    const apiErrors = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        const text = msg.text();
        if (!isIgnorableConsole(text)) consoleErrors.push(text);
      }
    });
    page.on('pageerror', (err) => pageErrors.push(String(err)));
    page.on('response', (res) => {
      const url = res.url();
      if (url.includes('127.0.0.1:8000') && res.status() >= 400) {
        apiErrors.push({ url, status: res.status() });
      }
    });

    let loginUrl = '';
    let dashboardOk = false;
    let jobsOk = false;
    let settingsOk = false;

    try {
      await login(page, HR);
      loginUrl = page.url();
      dashboardOk = /\/dashboard/i.test(loginUrl);
      await page.goto(`${BASE}/jobs`, { waitUntil: 'networkidle' });
      jobsOk = /\/jobs/i.test(page.url());
      await page.goto(`${BASE}/settings`, { waitUntil: 'networkidle' });
      settingsOk = /\/settings/i.test(page.url());
      await page.waitForTimeout(1500);
    } catch (e) {
      pageErrors.push(`Recruiter flow exception: ${String(e)}`);
    }

    results.recruiter = {
      login_redirect_url: loginUrl,
      dashboard_ok: dashboardOk,
      jobs_ok: jobsOk,
      settings_ok: settingsOk,
      console_errors: consoleErrors,
      page_errors: pageErrors,
      api_errors: apiErrors,
      pass: dashboardOk && jobsOk && settingsOk && consoleErrors.length === 0 && pageErrors.length === 0,
    };
    await context.close();
  }

  {
    const context = await browser.newContext();
    const page = await context.newPage();
    const consoleErrors = [];
    const pageErrors = [];
    const apiErrors = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        const text = msg.text();
        if (!isIgnorableConsole(text)) consoleErrors.push(text);
      }
    });
    page.on('pageerror', (err) => pageErrors.push(String(err)));
    page.on('response', (res) => {
      const url = res.url();
      if (url.includes('127.0.0.1:8000') && res.status() >= 400) {
        apiErrors.push({ url, status: res.status() });
      }
    });

    let loginUrl = '';
    let dashboardOk = false;
    let jobsOk = false;

    try {
      await login(page, CAND);
      loginUrl = page.url();
      dashboardOk = /\/candidate\/dashboard/i.test(loginUrl);
      await page.goto(`${BASE}/candidate/jobs`, { waitUntil: 'networkidle' });
      jobsOk = /\/candidate\/jobs/i.test(page.url());
      await page.waitForTimeout(1500);
    } catch (e) {
      pageErrors.push(`Candidate flow exception: ${String(e)}`);
    }

    results.candidate = {
      login_redirect_url: loginUrl,
      dashboard_ok: dashboardOk,
      jobs_ok: jobsOk,
      console_errors: consoleErrors,
      page_errors: pageErrors,
      api_errors: apiErrors,
      pass: dashboardOk && jobsOk && consoleErrors.length === 0 && pageErrors.length === 0,
    };
    await context.close();
  }

  {
    const context = await browser.newContext();
    const page = await context.newPage();
    const consoleErrors = [];
    const pageErrors = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        const text = msg.text();
        if (!isIgnorableConsole(text)) consoleErrors.push(text);
      }
    });
    page.on('pageerror', (err) => pageErrors.push(String(err)));
    let loaded = false;

    try {
      await login(page, HR);
      await page.goto(`${BASE}/candidates/${KNOWN_CANDIDATE_ID}`, { waitUntil: 'networkidle' });
      loaded = /\/candidates\//i.test(page.url());
      await page.waitForTimeout(1800);
    } catch (e) {
      pageErrors.push(`CandidateDetails exception: ${String(e)}`);
    }

    const hookError =
      consoleErrors.some((e) => e.includes('Rendered more hooks than during the previous render')) ||
      consoleErrors.some((e) => e.includes('change in the order of Hooks called')) ||
      pageErrors.some((e) => e.includes('Rendered more hooks than during the previous render'));

    results.candidateDetails = {
      page_loaded: loaded,
      hook_order_error_detected: hookError,
      console_errors: consoleErrors,
      page_errors: pageErrors,
      pass: loaded && !hookError && pageErrors.length === 0,
    };
    await context.close();
  }

  await browser.close();
  console.log(JSON.stringify(results, null, 2));
})();
