# Beta Launch Runbook (10-15 Testers)

## Scope
- Target audience: closed beta (10-15 testers)
- Goal: stable recruiter + candidate hiring flows with real DB persistence and quiz loop
- Redis optional (in-memory fallback acceptable for beta)
- Harness endpoints optional only if your beta needs direct Harness APIs

## Preflight
1. Backend env:
   - Set `APP_ENV=production`
   - Set valid `SECRET_KEY`, `ENCRYPTION_KEY`
   - Set `DATABASE_URL` (shared beta DB)
   - Set `CORS_ORIGINS` to beta frontend URL(s)
2. Frontend env:
   - Set `VITE_API_BASE_URL` to beta backend URL
3. Start services:
   - Backend: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
   - Frontend: `npm run dev` (or serve built `dist/`)

## Beta Gate Commands
0. One-command gate (recommended):
   - `powershell -ExecutionPolicy Bypass -File .\scripts\beta_gate.ps1`
1. Backend compile:
   - `python -m py_compile app\config.py app\main.py app\routers\candidate_portal.py app\routers\quiz.py app\routers\jd.py app\services\file_service.py`
2. Frontend build:
   - `npm run build`
3. API contract smoke:
   - `python scratch\probe_frontend_backend_connectivity.py`
4. Linked E2E (recruiter <-> candidate):
   - `node ..\HR APP FRONTEND\qa_linked_realtime_e2e.mjs`

## Pass Criteria
- `/health` responds `200`
- Frontend build succeeds without errors
- Linked E2E report shows `pass: true`
- Candidate application rows persist to DB
- Quiz attempt rows persist to DB
- Recruiter sees candidate score after quiz submit
- Candidate receives recruiter notification

## Known Optional/Non-Blocking for Closed Beta
- Redis unavailable: acceptable if limiter fallback active and no request hangs
- Harness API (`/harness/*`) unavailable: acceptable only if app uses native runtime path
- SMTP unconfigured: acceptable only if beta test plan does not require real external mail delivery

If Harness APIs are mandatory for your beta cohort, run:
- `powershell -ExecutionPolicy Bypass -File .\scripts\beta_gate.ps1 -RequireHarness`

## Blockers (Do Not Launch If True)
- Any core flow fails in linked E2E:
  - recruiter create/edit/publish
  - candidate apply (upload or vault)
  - quiz attempt/submit/results
- API returns `201` without DB row persistence
- Reproducible hangs (>30s) on core routes under normal conditions

## Artifacts to Save Each Beta Run
- Latest linked E2E report JSON
- Linked E2E screenshots
- Backend startup log snippet
- Frontend build output
- DB row verification snapshot (applications + quiz_attempts)
