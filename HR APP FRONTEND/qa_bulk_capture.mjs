import { chromium } from 'playwright';
import fs from 'node:fs';
const FRONTEND='http://127.0.0.1:3000';
const OUT='D:/Shubham/HR APP/Harness/batch2_bulk_review_step.png';
const SAMPLE='D:/Shubham/HR APP/ATS/ATS Folder/Resumes/AshishGangwar.pdf';
const recruiter={email:'harness.auto.hr.1779358460@example.com',password:'HarnessAuto@123'};
fs.mkdirSync('D:/Shubham/HR APP/Harness',{recursive:true});

(async()=>{
  const browser=await chromium.launch({headless:true});
  const ctx=await browser.newContext({viewport:{width:1920,height:1080}});
  const page=await ctx.newPage();
  await page.goto(`${FRONTEND}/login`,{waitUntil:'domcontentloaded'});
  await page.fill('input[type="email"]',recruiter.email);
  await page.fill('input[type="password"]',recruiter.password);
  await page.click('button[type="submit"]');
  await page.waitForFunction(()=>!location.pathname.startsWith('/login'),{}, {timeout:90000});
  await page.goto(`${FRONTEND}/jobs`,{waitUntil:'domcontentloaded'});
  await page.getByRole('button', { name: /new/i }).first().click();
  await page.getByRole('menuitem', { name: /bulk upload resumes/i }).first().click();
  await page.waitForSelector('text=Drop files here or click to browse', { timeout: 30000 });
  await page.setInputFiles('input[type="file"]', SAMPLE);
  await page.waitForSelector('text=I reviewed selected files and target', { timeout: 30000 });
  await page.screenshot({path:OUT, fullPage:true});
  await browser.close();
  console.log(JSON.stringify({ok:true, shot:OUT}));
})().catch(e=>{console.error(e);process.exit(1);});
