
import { chromium } from 'playwright';
const FRONTEND='http://127.0.0.1:3000';
const outDir='D:/Shubham/HR APP/Harness';
const hr={"email": "harness.auto.hr.1779358460@example.com", "password": "HarnessAuto@123"};
const cand={"email": "harness.auto.cand.1779358460@example.com", "password": "HarnessAuto@123"};
const jobId="d07e4b8c-ed82-45d9-ba9f-ef79829d3df9";

async function login(page,creds) {
  await page.goto(`${FRONTEND}/login`,{waitUntil:'networkidle'});
  await page.waitForSelector('input[type="email"]',{timeout:20000});
  await page.fill('input[type="email"]',creds.email);
  await page.fill('input[type="password"]',creds.password);
  await page.click('button[type="submit"]');
  await page.waitForTimeout(3500);
}

(async()=>{
  const browser=await chromium.launch({headless:true});
  const hrCtx=await browser.newContext({viewport:{width:1920,height:1080}});
  const hrPage=await hrCtx.newPage();
  await login(hrPage,hr);
  await hrPage.goto(`${FRONTEND}/dashboard`,{waitUntil:'networkidle'});
  await hrPage.screenshot({path:`${outDir}/01_recruiter_dashboard_live.png`,fullPage:true});
  await hrPage.goto(`${FRONTEND}/jobs`,{waitUntil:'networkidle'});
  await hrPage.screenshot({path:`${outDir}/02_recruiter_jobs_live.png`,fullPage:true});
  if(jobId){
    await hrPage.goto(`${FRONTEND}/jobs/${jobId}`,{waitUntil:'networkidle'});
    await hrPage.screenshot({path:`${outDir}/03_recruiter_job_detail_live.png`,fullPage:true});
  }
  await hrCtx.close();

  const cCtx=await browser.newContext({viewport:{width:1920,height:1080}});
  const cPage=await cCtx.newPage();
  await login(cPage,cand);
  await cPage.goto(`${FRONTEND}/candidate/dashboard`,{waitUntil:'networkidle'});
  await cPage.screenshot({path:`${outDir}/04_candidate_dashboard_live.png`,fullPage:true});
  await cPage.goto(`${FRONTEND}/candidate/jobs`,{waitUntil:'networkidle'});
  await cPage.screenshot({path:`${outDir}/05_candidate_jobs_live.png`,fullPage:true});
  if(jobId){
    await cPage.goto(`${FRONTEND}/candidate/jobs/${jobId}`,{waitUntil:'networkidle'});
    await cPage.screenshot({path:`${outDir}/06_candidate_job_detail_live.png`,fullPage:true});
  }
  await cCtx.close();
  await browser.close();
})();
