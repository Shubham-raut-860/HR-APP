# HR App Production Release Checklist

Date: 2026-05-07

## 1) Security and Environment (must pass)

- `APP_ENV=production`
- `DATABASE_URL` points to managed Postgres (not local SQLite)
- `SECRET_KEY` is unique and at least 32 chars
- `ENCRYPTION_KEY` is unique and non-placeholder
- `AZURE_OPENAI_ENDPOINT` is set
- `AZURE_OPENAI_API_KEY` is set
- `CORS_ORIGINS` contains only production origins (no localhost/127.0.0.1)
- `SMTP_USERNAME` and `SMTP_PASSWORD` are set
- `VITE_API_BASE_URL` points to production backend URL

Important:
- Never deploy with committed `.env` secrets from development.
- Rotate all previously exposed API keys/passwords before production cutover.

## 2) Build and Compile (must pass)

Backend:
```powershell
.\.venv\Scripts\python.exe -m py_compile app\config.py app\main.py
```

Frontend:
```powershell
npm.cmd run build
```

## 3) Connectivity and Contract Smoke (must pass)

Run:
```powershell
.\.venv\Scripts\python.exe scratch\probe_frontend_backend_connectivity.py
```

Expected:
- `/health` -> 200
- `/openapi.json` -> 200
- `/settings/smtp-credentials` path present and GET responds
- `/ai/lyzr/status` and `/ai/lyzr/match` respond (fallback is acceptable if not configured)
- `/quiz/generate` responds successfully

## 4) Harness Production Readiness (must pass)

Run:
```powershell
.\.venv\Scripts\python.exe scratch\validate_harness_production_readiness.py
```

Expected:
- `checks_fail_like = 0`
- Pipelines available: `resume_screening`, `jd_generation`, `jd_parsing`, `quiz_generation`, `ranking`, `candidate_tools`

## 5) Bulk Resume Throughput Benchmark (recommended)

Run:
```powershell
.\.venv\Scripts\python.exe scratch\bench_harness_native_vs_harness.py
```

Use results to pick orchestrator mode for production:
- `orchestrator=native` for lowest latency
- `orchestrator=harness` when agent traceability/guardrails are prioritized

## 6) Operational Readiness

- Use a process manager (Windows service, NSSM, PM2, supervisor-equivalent)
- Ensure log rotation and retention
- Configure DB backups and restore test
- Add uptime checks for:
  - backend `/health`
  - frontend `/login`
- Verify CORS + HTTPS termination at edge/load balancer

## 7) Final Go/No-Go Rule

Go only when:
- Section 1 all pass
- Section 2 all pass
- Section 3 all pass
- Section 4 all pass

If any fail, release is blocked.
