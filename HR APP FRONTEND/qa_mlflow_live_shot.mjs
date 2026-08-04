import { chromium } from "playwright";
(async()=>{
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1920,height:1080}});
await page.goto("http://127.0.0.1:5000/#/experiments/1",{waitUntil:"domcontentloaded",timeout:60000});
await page.waitForTimeout(5000);
await page.screenshot({path:"D:/Shubham/HR APP/Harness/07_mlflow_harness_live.png",fullPage:true});
await browser.close();
})();
