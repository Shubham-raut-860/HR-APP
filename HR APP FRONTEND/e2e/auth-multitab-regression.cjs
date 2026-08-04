const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const FRONTEND = process.env.FRONTEND_URL || "http://127.0.0.1:3000";
const ARTIFACT_DIR =
  process.env.QA_ARTIFACT_DIR ||
  path.join(process.cwd(), "e2e_artifacts", `auth-multitab-${new Date().toISOString().replace(/[:.]/g, "-")}`);

fs.mkdirSync(ARTIFACT_DIR, { recursive: true });

const report = {
  startedAt: new Date().toISOString(),
  checks: [],
  console: [],
  network: [],
  screenshots: [],
  failures: [],
};

const check = (name, passed, details = {}) => {
  const row = { name, passed, ...details };
  report.checks.push(row);
  if (!passed) report.failures.push(row);
};

const observe = (page, label) => {
  page.on("console", (msg) => {
    report.console.push({ label, type: msg.type(), text: msg.text(), url: page.url() });
  });
  page.on("requestfailed", (request) => {
    report.network.push({
      label,
      method: request.method(),
      url: request.url(),
      failed: true,
      failure: request.failure()?.errorText,
      pageUrl: page.url(),
    });
  });
  page.on("response", (response) => {
    const url = response.url();
    if (!url.startsWith(FRONTEND) && !url.includes("127.0.0.1:8000")) return;
    report.network.push({
      label,
      method: response.request().method(),
      status: response.status(),
      url,
      pageUrl: page.url(),
    });
  });
};

const screenshot = async (page, name) => {
  const file = path.join(ARTIFACT_DIR, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true }).catch(() => null);
  report.screenshots.push(file);
};

const bodyText = (page) => page.locator("body").innerText({ timeout: 5000 }).catch(() => "");

async function signup(page, role, email) {
  await page.goto(`${FRONTEND}/signup`, { waitUntil: "domcontentloaded" });
  if (role === "hr") await page.getByRole("button", { name: /recruiter/i }).click();
  await page.getByLabel("First name").fill(role === "hr" ? "MultiRecruiter" : "MultiCandidate");
  await page.getByLabel("Last name").fill("QA");
  await page.getByLabel("Email address").fill(email);
  await page.locator("#auth-password").fill("QaTest!2345");
  const registerResponse = page.waitForResponse((resp) => resp.url().includes("/auth/register"), { timeout: 30000 });
  await page.getByRole("button", { name: /create account/i }).click();
  const response = await registerResponse;
  await page.waitForTimeout(1200);
  return response.status();
}

async function login(page, email) {
  await page.goto(`${FRONTEND}/login`, { waitUntil: "domcontentloaded" });
  await page.getByLabel("Email address").fill(email);
  await page.locator("#auth-password").fill("QaTest!2345");
  const loginResponse = page.waitForResponse((resp) => resp.url().includes("/auth/login"), { timeout: 30000 });
  await page.getByRole("button", { name: /sign in/i }).click();
  const response = await loginResponse;
  await page.waitForTimeout(1200);
  return response.status();
}

async function logout(page) {
  const button = page.getByRole("button", { name: /log out/i }).first();
  await button.click({ timeout: 10000 });
  await page.waitForTimeout(1200);
}

async function testRole(browser, role) {
  const context = await browser.newContext({ viewport: { width: 1366, height: 768 } });
  const page = await context.newPage();
  observe(page, `${role}-primary`);
  const email = `multitab.${role}.${Date.now()}@hireai-test.com`;
  const expectedPath = role === "hr" ? "/dashboard" : "/candidate/dashboard";
  const expectedText = role === "hr" ? /Dashboard|Jobs|Candidates/i : /Dashboard|Browse Jobs|Mock Test/i;

  const signupStatus = await signup(page, role, email);
  check(`${role}: signup succeeds`, signupStatus === 201, { status: signupStatus, url: page.url() });
  await screenshot(page, `${role}-after-signup`);

  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1200);
  let text = await bodyText(page);
  check(`${role}: same-tab refresh after signup stays authenticated`, page.url().includes(expectedPath) && expectedText.test(text), {
    url: page.url(),
    bodySample: text.slice(0, 500),
  });
  await screenshot(page, `${role}-same-tab-refresh`);

  const secondTab = await context.newPage();
  observe(secondTab, `${role}-second-tab`);
  await secondTab.goto(`${FRONTEND}${expectedPath}`, { waitUntil: "domcontentloaded" });
  await secondTab.waitForTimeout(1500);
  text = await bodyText(secondTab);
  check(`${role}: second tab shares session`, secondTab.url().includes(expectedPath) && expectedText.test(text), {
    url: secondTab.url(),
    bodySample: text.slice(0, 500),
  });
  await screenshot(secondTab, `${role}-second-tab-authenticated`);

  await logout(page);
  await secondTab.waitForTimeout(1500);
  text = await bodyText(secondTab);
  check(`${role}: logout propagates to second tab`, secondTab.url().includes("/login") || /sign in|welcome back/i.test(text), {
    url: secondTab.url(),
    bodySample: text.slice(0, 500),
  });
  await screenshot(secondTab, `${role}-second-tab-after-logout`);

  const loginStatus = await login(page, email);
  check(`${role}: explicit login succeeds`, loginStatus === 200, { status: loginStatus, url: page.url() });

  const thirdTab = await context.newPage();
  observe(thirdTab, `${role}-third-tab`);
  await thirdTab.goto(`${FRONTEND}${expectedPath}`, { waitUntil: "domcontentloaded" });
  await thirdTab.waitForTimeout(1500);
  text = await bodyText(thirdTab);
  check(`${role}: second tab shares session after explicit login`, thirdTab.url().includes(expectedPath) && expectedText.test(text), {
    url: thirdTab.url(),
    bodySample: text.slice(0, 500),
  });
  await screenshot(thirdTab, `${role}-second-tab-after-login`);

  await context.close();
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  await testRole(browser, "hr");
  await testRole(browser, "candidate");
  await browser.close();

  report.finishedAt = new Date().toISOString();
  const reportPath = path.join(ARTIFACT_DIR, "auth-multitab-regression-report.json");
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ reportPath, checks: report.checks.length, failed: report.failures.length }, null, 2));
  if (report.failures.length) process.exitCode = 1;
})();
