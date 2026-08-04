const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const FRONTEND = process.env.FRONTEND_URL || "http://127.0.0.1:3000";
const ARTIFACT_DIR =
  process.env.QA_ARTIFACT_DIR ||
  path.join(process.cwd(), "e2e_artifacts", `form-accessibility-${new Date().toISOString().replace(/[:.]/g, "-")}`);

fs.mkdirSync(ARTIFACT_DIR, { recursive: true });

const report = { startedAt: new Date().toISOString(), checks: [], screenshots: [], failures: [] };

const check = (name, passed, details = {}) => {
  const row = { name, passed, ...details };
  report.checks.push(row);
  if (!passed) report.failures.push(row);
};

const screenshot = async (page, name) => {
  const file = path.join(ARTIFACT_DIR, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true }).catch(() => null);
  report.screenshots.push(file);
};

async function signup(page, role, email) {
  await page.goto(`${FRONTEND}/signup`, { waitUntil: "domcontentloaded" });
  if (role === "hr") await page.getByRole("button", { name: /recruiter/i }).click();
  await page.getByLabel("First name").fill(role === "hr" ? "A11yRecruiter" : "A11yCandidate");
  await page.getByLabel("Last name").fill("QA");
  await page.getByLabel("Email address").fill(email);
  await page.locator("#auth-password").fill("QaTest!2345");
  const responsePromise = page.waitForResponse((resp) => resp.url().includes("/auth/register"), { timeout: 30000 });
  await page.getByRole("button", { name: /create account/i }).click();
  const response = await responsePromise;
  await page.waitForTimeout(1200);
  return response.status();
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1366, height: 768 } });
  const page = await context.newPage();

  await page.goto(`${FRONTEND}/forgot-password`, { waitUntil: "domcontentloaded" });
  await page.getByLabel("Email address").fill("not-an-email");
  await page.getByRole("button", { name: /send reset link/i }).click();
  await page.waitForTimeout(300);
  const forgotError = await page.getByText(/enter a valid email address/i).isVisible().catch(() => false);
  check("forgot-password shows inline invalid email feedback", forgotError);
  await screenshot(page, "a11y-forgot-invalid-email");

  const recruiterEmail = `a11y.recruiter.${Date.now()}@hireai-test.com`;
  check("recruiter signup for form audit succeeds", (await signup(page, "hr", recruiterEmail)) === 201, { email: recruiterEmail });
  await page.goto(`${FRONTEND}/jobs`, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: /open new job actions/i }).click();
  await page.getByRole("menuitem", { name: /create job manually/i }).click();
  await page.getByLabel("Job Title / Role").fill("Accessibility QA Engineer");
  await page.getByLabel("Location").fill("Remote");
  await page.getByLabel("Min Experience (Years)").fill("2");
  await page.getByLabel("Max Experience (Years)").fill("5");
  await page.getByLabel("Must-Have Skills").fill("Playwright, Accessibility");
  await page.getByLabel("Good-to-Have Skills").fill("Security testing");
  await page.getByRole("textbox", { name: "Description" }).fill("Own real browser accessibility and production QA for recruiter workflows.");
  check("JD create fields are locatable by accessible labels", true);
  await screenshot(page, "a11y-jd-create-labels");

  await page.getByRole("button", { name: /cancel/i }).click();
  await page.getByRole("button", { name: /open new job actions/i }).click();
  await page.getByRole("menuitem", { name: /job from document/i }).click();
  const docDropzoneVisible = await page.getByRole("button", { name: /choose job description document files/i }).isVisible().catch(() => false);
  const docFileInputCount = await page.locator("input[aria-label='Job description document files']").count();
  check("JD document upload has accessible dropzone and file input", docDropzoneVisible && docFileInputCount === 1, {
    docDropzoneVisible,
    docFileInputCount,
  });
  await screenshot(page, "a11y-jd-document-upload");

  const candidateContext = await browser.newContext({ viewport: { width: 1366, height: 768 } });
  const candidatePage = await candidateContext.newPage();
  const candidateEmail = `a11y.candidate.${Date.now()}@hireai-test.com`;
  check("candidate signup for form audit succeeds", (await signup(candidatePage, "candidate", candidateEmail)) === 201, { email: candidateEmail });
  await candidatePage.goto(`${FRONTEND}/candidate/settings?tab=vault`, { waitUntil: "domcontentloaded" });
  await candidatePage.getByRole("button", { name: /upload your first resume|add another resume/i }).click();
  const resumeLabel = await candidatePage.getByLabel("Resume label").isVisible().catch(() => false);
  const resumeFileInput = await candidatePage.locator("[data-testid='resume-vault-file-input']").count();
  check("candidate resume vault upload controls are accessible", resumeLabel && resumeFileInput === 1, {
    resumeLabel,
    resumeFileInput,
  });
  await screenshot(candidatePage, "a11y-candidate-vault-upload");

  await candidateContext.close();
  await context.close();
  await browser.close();

  report.finishedAt = new Date().toISOString();
  const reportPath = path.join(ARTIFACT_DIR, "form-accessibility-regression-report.json");
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ reportPath, checks: report.checks.length, failed: report.failures.length }, null, 2));
  if (report.failures.length) process.exitCode = 1;
})();
