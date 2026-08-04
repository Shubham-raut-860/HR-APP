import { chromium } from "playwright";

const FRONTEND = "http://127.0.0.1:3000";
const outDir = "D:/Shubham/HR APP/Harness";
const cand = { email: "harness.auto.cand.1779358460@example.com", password: "HarnessAuto@123" };

async function login(page, creds){
  await page.goto(`${FRONTEND}/login`, { waitUntil: "networkidle" });
  await page.waitForSelector('input[type="email"]', { timeout: 20000 });
  await page.fill('input[type="email"]', creds.email);
  await page.fill('input[type="password"]', creds.password);
  await page.click('button[type="submit"]');
  await page.waitForTimeout(3500);
}

(async()=>{
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  const page = await ctx.newPage();
  await login(page, cand);

  await page.goto(`${FRONTEND}/candidate/settings`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${outDir}/08_candidate_settings_tabs_bar.png`, fullPage: true });

  const vaultBtn = page.getByRole('button', { name: /Resume Vault/i }).first();
  await vaultBtn.click();
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${outDir}/09_candidate_settings_resume_vault_tab.png`, fullPage: true });

  const docsBtn = page.getByRole('button', { name: /Documents/i }).first();
  await docsBtn.click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${outDir}/10_candidate_settings_documents_tab.png`, fullPage: true });

  await browser.close();
})();
