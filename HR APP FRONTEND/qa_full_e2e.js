import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const FRONTEND = 'http://127.0.0.1:3000';
const BACKEND = 'http://127.0.0.1:8000';
const ASSETS_ROOT = 'D:\\Shubham\\HR APP\\HR APP BACKEND\\test_docs\\e2e_assets';
const BULK_DIR = path.join(ASSETS_ROOT, 'bulk_resumes');
const VAULT_DIR = path.join(ASSETS_ROOT, 'vault_resumes');

const STAMP = Date.now();
const PASSWORD = 'Qa!Pass2026A';

const recruiter = {
  first: 'QA',
  last: `Recruiter${STAMP}`,
  email: `qa.recruiter.${STAMP}@example.com`,
  password: PASSWORD,
};

const candidate = {
  first: 'QA',
  last: `Candidate${STAMP}`,
  email: `qa.candidate.${STAMP}@example.com`,
  password: PASSWORD,
};

const jdTitle = `QA E2E Backend Engineer ${STAMP}`;

function isIgnorableConsole(msg) {
  const t = msg || '';
  return (
    t.includes('Download the React DevTools') ||
    t.includes('Launched external handler for') ||
    t.includes('favicon')
  );
}

function attachDiagnostics(page, bag) {
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      const text = msg.text();
      if (!isIgnorableConsole(text)) bag.consoleErrors.push(text);
    }
  });
  page.on('pageerror', (err) => bag.pageErrors.push(String(err)));
  page.on('response', async (res) => {
    const url = res.url();
    if (url.includes('127.0.0.1:8000') && res.status() >= 400) {
      let body = '';
      try {
        body = (await res.text()).slice(0, 500);
      } catch {
        body = '';
      }
      bag.apiErrors.push({ status: res.status(), url, body });
    }
  });
}

async function pause(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function signup(page, user, role) {
  await page.goto(`${FRONTEND}/signup`, { waitUntil: 'networkidle' });
  await page.waitForSelector('input[type="email"]', { timeout: 20000 });

  if (role === 'hr') {
    await page.getByRole('button', { name: 'Recruiter', exact: true }).first().click();
  } else {
    await page.getByRole('button', { name: 'Candidate', exact: true }).first().click();
  }

  const textInputs = page.locator('form input:not([type="email"]):not([type="password"])');
  await textInputs.nth(0).fill(user.first);
  await textInputs.nth(1).fill(user.last);
  await page.fill('input[type="email"]', user.email);
  await page.fill('input[type="password"]', user.password);
  await page.getByRole('button', { name: /Join as/i }).click();

  const expected = role === 'hr' ? /\/dashboard$/ : /\/candidate\/dashboard$/;
  await page.waitForURL(expected, { timeout: 45000 });
  return page.url();
}

async function getSessionToken(page) {
  return page.evaluate(() => window.sessionStorage.getItem('token'));
}

async function fetchCandidatesForJob(request, token, jobId) {
  const res = await request.get(`${BACKEND}/resumes/?job_id=${jobId}&limit=500`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok()) {
    throw new Error(`fetchCandidates failed: ${res.status()} ${await res.text()}`);
  }
  return res.json();
}

async function fetchRecruiterJobs(request, token) {
  const res = await request.get(`${BACKEND}/jd/?active_only=true`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok()) {
    throw new Error(`fetchRecruiterJobs failed: ${res.status()} ${await res.text()}`);
  }
  return res.json();
}

function computeScoreStats(candidates) {
  const scores = candidates.map((c) => Number(c.final_score ?? c.resume_score ?? 0));
  const n = scores.length;
  if (!n) return { count: 0, min: null, max: null, avg: null, std: null };
  const sum = scores.reduce((a, b) => a + b, 0);
  const avg = sum / n;
  const variance = scores.reduce((acc, s) => acc + (s - avg) ** 2, 0) / n;
  return {
    count: n,
    min: Math.min(...scores),
    max: Math.max(...scores),
    avg: Number(avg.toFixed(2)),
    std: Number(Math.sqrt(variance).toFixed(2)),
  };
}

function countTags(candidates) {
  const out = { Strong: 0, Medium: 0, Reject: 0, Unknown: 0 };
  for (const c of candidates) {
    const raw = String(c.tag ?? '').toLowerCase();
    if (raw === 'strong') out.Strong += 1;
    else if (raw === 'medium') out.Medium += 1;
    else if (raw === 'reject') out.Reject += 1;
    else out.Unknown += 1;
  }
  return out;
}

(async () => {
  const report = {
    timestamp: new Date().toISOString(),
    recruiter,
    candidate,
    job: { title: jdTitle, id: null },
    recruiterFlow: {},
    candidateFlow: {},
    findings: [],
    verdict: 'UNKNOWN',
  };

  const bulkFiles = fs
    .readdirSync(BULK_DIR)
    .filter((f) => f.toLowerCase().endsWith('.docx'))
    .map((f) => path.join(BULK_DIR, f));

  const vaultFiles = fs
    .readdirSync(VAULT_DIR)
    .filter((f) => f.toLowerCase().endsWith('.docx'))
    .slice(0, 5)
    .map((f) => path.join(VAULT_DIR, f));

  const tempJdDir = path.join(process.cwd(), 'stitch_previews');
  fs.mkdirSync(tempJdDir, { recursive: true });
  const jdPath = path.join(tempJdDir, `qa_jd_${STAMP}.txt`);
  const jdContent = [
    jdTitle,
    'Location: Remote',
    'Experience: 3-6 years',
    'Must Have Skills: Python, FastAPI, SQL, PostgreSQL, REST API, Docker',
    'Good To Have Skills: AWS, Redis, Kubernetes, CI/CD',
    'Responsibilities:',
    '- Build scalable backend APIs for hiring workflows',
    '- Optimize database queries and schema design',
  ].join('\n');
  fs.writeFileSync(jdPath, jdContent, 'utf-8');

  const browser = await chromium.launch({ headless: true });

  // Recruiter flow
  {
    const context = await browser.newContext();
    const page = await context.newPage();
    const diag = { consoleErrors: [], pageErrors: [], apiErrors: [] };
    attachDiagnostics(page, diag);

    const r = {
      signupOk: false,
      jdUploadOk: false,
      jobOpenOk: false,
      bulkUploadTriggered: false,
      shortlistRan: false,
      quizGenerateAttempted: false,
      quizGenerated: false,
      candidatesAfterUpload: 0,
      scoreStats: null,
      tagCounts: null,
      topCandidates: [],
      diagnostics: diag,
    };

    try {
      const redirect = await signup(page, recruiter, 'hr');
      r.signupOk = /\/dashboard$/.test(redirect);

      await page.goto(`${FRONTEND}/jobs`, { waitUntil: 'networkidle' });
      await page.getByRole('button', { name: /\bNew\b/ }).click();
      await page.getByText('Job from document').click();
      await page.setInputFiles('#jd-doc-input', jdPath);
      await page.getByRole('button', { name: /Create .* Job/ }).click();

      await page.getByText(/Created \(/).waitFor({ timeout: 120000 });
      r.jdUploadOk = true;

      await page.getByRole('button', { name: /Close|Cancel/ }).first().click();
      const token = await getSessionToken(page);
      const jobs = await fetchRecruiterJobs(context.request, token);
      const latest = Array.isArray(jobs) ? jobs[0] : null;
      if (!latest?.id) throw new Error('Could not resolve created recruiter job id from /jd/');
      report.job.id = latest.id;
      report.job.title = latest.title || report.job.title;
      await page.goto(`${FRONTEND}/jobs/${latest.id}`, { waitUntil: 'networkidle' });
      await page.waitForURL(/\/jobs\/[0-9a-f\-]+$/i, { timeout: 30000 });
      r.jobOpenOk = true;

      await page.setInputFiles('#file-upload-jd', bulkFiles);
      await page.getByRole('button', { name: /Parse & Rank/i }).click();
      r.bulkUploadTriggered = true;

      await page.getByRole('button', { name: /Parse & Rank/i }).waitFor({ timeout: 360000 });
      await pause(3000);

      const afterUpload = await fetchCandidatesForJob(context.request, token, report.job.id);
      r.candidatesAfterUpload = afterUpload.length;

      await page.getByRole('tab', { name: /Shortlist/i }).click();
      await page.getByRole('button', { name: /Re-run Shortlisting/i }).click();
      await page.getByRole('button', { name: /Re-run Shortlisting/i }).waitFor({ timeout: 120000 });
      r.shortlistRan = true;
      await pause(3000);

      const rescored = await fetchCandidatesForJob(context.request, token, report.job.id);
      r.scoreStats = computeScoreStats(rescored);
      r.tagCounts = countTags(rescored);
      r.topCandidates = rescored
        .slice()
        .sort((a, b) => Number((b.final_score ?? b.resume_score ?? 0)) - Number((a.final_score ?? a.resume_score ?? 0)))
        .slice(0, 5)
        .map((c) => ({
          name: c.name,
          score: Number(c.final_score ?? c.resume_score ?? 0),
          tag: c.tag ?? null,
          skills: Array.isArray(c.skills) ? c.skills.slice(0, 6) : [],
        }));

      await page.getByRole('tab', { name: /^Quiz$/i }).click();
      r.quizGenerateAttempted = true;
      await page.getByRole('button', { name: /^Generate$/ }).first().click();
      try {
        await page.getByRole('button', { name: /Show Quiz/i }).first().waitFor({ timeout: 90000 });
        r.quizGenerated = true;
      } catch {
        r.quizGenerated = false;
      }
    } catch (err) {
      r.fatalError = String(err);
    }

    report.recruiterFlow = r;
    await context.close();
  }

  // Candidate flow
  {
    const context = await browser.newContext();
    const page = await context.newPage();
    const diag = { consoleErrors: [], pageErrors: [], apiErrors: [] };
    attachDiagnostics(page, diag);

    const c = {
      signupOk: false,
      vaultUploadCount: 0,
      vaultFullReached: false,
      appliedToJob: false,
      mockTestStarted: false,
      mockTestSubmitted: false,
      mockScoreText: null,
      diagnostics: diag,
    };

    try {
      const redirect = await signup(page, candidate, 'candidate');
      c.signupOk = /\/candidate\/dashboard$/.test(redirect);

      await page.goto(`${FRONTEND}/candidate/settings?tab=vault`, { waitUntil: 'networkidle' });

      for (let i = 0; i < vaultFiles.length; i += 1) {
        const addBtn = page.getByRole('button', { name: /Upload your first resume|Add another resume/i }).first();
        await addBtn.waitFor({ timeout: 30000 });
        await addBtn.click();

        const label = `QA Vault ${i + 1}`;
        await page.locator('input[placeholder*="Label"]').fill(label);

        const fileInput = page.locator('input[type="file"]').last();
        await fileInput.setInputFiles(vaultFiles[i]);

        await page.getByText(new RegExp(`Slots used:\\s*${i + 1}\\/5`, 'i')).first().waitFor({ timeout: 120000 });
        c.vaultUploadCount += 1;
      }

      try {
        await page.getByText(/Slots used:\s*5\/5/i).waitFor({ timeout: 20000 });
        await page.getByText(/Vault full/i).first().waitFor({ timeout: 20000 });
        c.vaultFullReached = true;
      } catch {
        c.vaultFullReached = false;
      }

      if (!report.job.id) throw new Error('No recruiter job id available for candidate apply test.');
      try {
        await page.goto(`${FRONTEND}/candidate/jobs/${report.job.id}`, { waitUntil: 'networkidle' });
        await page.waitForURL(/\/candidate\/jobs\/[0-9a-f\-]+$/i, { timeout: 30000 });

        const applyBtn = page.getByRole('button', { name: /Apply with this Resume|Apply Anyway/i }).first();
        await applyBtn.click();

        const confirmBtn = page.getByRole('button', { name: /Confirm & Apply|Apply Anyway/i }).last();
        await confirmBtn.click();

        await page.getByText(/Under Review/i).first().waitFor({ timeout: 60000 });
        c.appliedToJob = true;
      } catch (applyErr) {
        c.applyError = String(applyErr);
      }

      await page.goto(`${FRONTEND}/candidate/mock-test`, { waitUntil: 'networkidle' });
      await page.getByRole('button', { name: /Specific Topic/i }).click();
      await page.getByRole('combobox').click();
      await page.getByRole('option', { name: /Python/i }).click();
      await page.getByRole('button', { name: /Launch Practice Environment/i }).click();

      try {
        await page.getByText(/In Progress/i).waitFor({ timeout: 90000 });
        c.mockTestStarted = true;

        for (let i = 0; i < 10; i += 1) {
          const firstRadio = page.locator('button[role="radio"]').first();
          await firstRadio.waitFor({ timeout: 20000 });
          await firstRadio.click();

          const submitBtn = page.getByRole('button', { name: /Next Question|Submit Exam/i }).first();
          const label = await submitBtn.innerText();
          await submitBtn.click();
          if (/Submit Exam/i.test(label)) break;
        }

        await page.getByText(/Test Results/i).waitFor({ timeout: 90000 });
        c.mockTestSubmitted = true;

        const scoreText = await page.locator('div.text-3xl.font-bold').first().textContent();
        c.mockScoreText = scoreText ? scoreText.trim() : null;
      } catch {
        c.mockTestStarted = false;
      }
    } catch (err) {
      c.fatalError = String(err);
    }

    report.candidateFlow = c;
    await context.close();
  }

  await browser.close();

  // Brutal findings
  const findings = [];
  const rf = report.recruiterFlow;
  const cf = report.candidateFlow;

  if (!rf.signupOk) findings.push('Recruiter signup failed or did not route to /dashboard.');
  if (!rf.jdUploadOk) findings.push('JD upload-from-document failed (core recruiter flow broken).');
  if (!rf.jobOpenOk || !report.job.id) findings.push('Created job was not opened reliably (routing/list refresh issue).');
  if (!rf.bulkUploadTriggered) findings.push('Bulk resume upload did not trigger from recruiter job detail.');
  if ((rf.candidatesAfterUpload ?? 0) < 5) findings.push(`Bulk upload processed too few resumes: ${rf.candidatesAfterUpload || 0}.`);

  if (rf.scoreStats) {
    if ((rf.scoreStats.std ?? 0) < 5) {
      findings.push(`Score spread is too narrow (std=${rf.scoreStats.std}); ranking quality is suspicious.`);
    }
  } else {
    findings.push('No score statistics available after shortlist run.');
  }

  if (rf.tagCounts) {
    const totalTagged = (rf.tagCounts.Strong + rf.tagCounts.Medium + rf.tagCounts.Reject + rf.tagCounts.Unknown);
    if (totalTagged > 0 && rf.tagCounts.Strong === totalTagged) {
      findings.push('All candidates tagged Strong: tagging logic is not discriminating enough.');
    }
  }

  if (!rf.quizGenerateAttempted) findings.push('Quiz generation step was not reached.');
  if (rf.quizGenerateAttempted && !rf.quizGenerated) findings.push('Quiz generation failed or timed out.');

  if (!cf.signupOk) findings.push('Candidate signup failed or did not route to /candidate/dashboard.');
  if (cf.vaultUploadCount < 5) findings.push(`Candidate vault uploads incomplete (${cf.vaultUploadCount}/5).`);
  if (!cf.vaultFullReached) findings.push('Vault did not clearly enforce/show 5-resume full state.');
  if (!cf.appliedToJob) findings.push('Candidate could not complete apply flow to recruiter-created job.');
  if (!cf.mockTestStarted) findings.push('Candidate mock test did not start (AI generation/service issue).');
  if (cf.mockTestStarted && !cf.mockTestSubmitted) findings.push('Candidate mock test started but submit/result flow failed.');

  const totalApiErrors = (rf.diagnostics.apiErrors?.length || 0) + (cf.diagnostics.apiErrors?.length || 0);
  if (totalApiErrors > 0) {
    findings.push(`Observed ${totalApiErrors} backend API error responses during E2E run.`);
  }

  report.findings = findings;
  report.verdict = findings.length === 0 ? 'PASS_WITH_RESERVATIONS' : 'FAIL_NOT_PRODUCTION_READY';

  const outPath = path.join(process.cwd(), 'qa_full_e2e_report.json');
  fs.writeFileSync(outPath, JSON.stringify(report, null, 2), 'utf-8');
  console.log(JSON.stringify(report, null, 2));
})();
