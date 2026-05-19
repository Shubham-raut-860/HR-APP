# HR Analytics & Smart Hiring Platform

## Overview
This platform is a full-stack AI hiring system for recruiters and candidates. Recruiters can create job descriptions, ingest resumes, run AI-assisted scoring, generate assessments, and track pipeline analytics. Candidates can browse jobs, apply with resume uploads/vault resumes, and complete quiz workflows. The stack supports both local development and production-style deployment using Docker Compose.

## Architecture
- **Backend**: FastAPI (`HR APP BACKEND/app/main.py`) with SQLAlchemy, Alembic, Redis-backed rate limiting, Harness integration, and AI orchestration.
- **Frontend**: React + TypeScript + Vite (`HR APP FRONTEND/`) served in production via Nginx.
- **Database**: SQLite for local/dev flows, PostgreSQL expected in production.
- **Caching / coordination**: Redis for limiter state and Harness-related runtime dependencies.
- **AI providers**: Azure OpenAI (chat + embeddings) and Gemini for parsing/scoring support.

## Prerequisites
- Docker 24+
- Docker Compose v2
- Node.js 20+ (only for non-Docker local frontend workflows)
- Python 3.12+ (only for non-Docker local backend workflows)

## Quick Start (Dev)
1. From repo root:
   ```bash
   docker compose up --build
   ```
2. Verify backend:
   ```bash
   curl http://localhost:8000/health
   ```
3. Open frontend:
   - [http://localhost:3000](http://localhost:3000)

## Environment Variables (Backend)
Source: `HR APP BACKEND/.env.example`

| Variable | Description | Required in production |
|---|---|---|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint base URL. | Yes |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key for LLM/embedding calls. | Yes |
| `AZURE_OPENAI_API_VERSION` | Azure API version for request compatibility. | Yes |
| `AZURE_CHAT_DEPLOYMENT` | Primary Azure chat deployment name. | Yes |
| `AZURE_MINI_DEPLOYMENT` | Secondary/lighter Azure deployment. | Recommended |
| `GEMINI_API_KEY` | Gemini API key for Gemini-backed tasks. | Recommended |
| `GEMINI_MODEL` | Gemini chat model identifier. | Recommended |
| `GEMINI_EMBEDDING_MODEL` | Gemini embedding model identifier. | Recommended |
| `DATABASE_URL` | SQLAlchemy connection URL (`postgresql+asyncpg` in prod). | Yes |
| `SECRET_KEY` | JWT signing key; must be strong and non-placeholder. | Yes |
| `ALGORITHM` | JWT algorithm (default `HS256`). | Yes |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token TTL in minutes. | Yes |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token TTL in days. | Yes |
| `ENCRYPTION_KEY` | File/encryption key; must be strong and non-placeholder. | Yes |
| `APP_HOST` | Bind host (`0.0.0.0` required for production reachability). | Yes |
| `APP_PORT` | Backend bind port. | Yes |
| `APP_ENV` | Runtime mode (`development`/`production`). | Yes |
| `CORS_ORIGINS` | Allowed browser origins. Must not include localhost in production. | Yes |
| `FRONTEND_URL` | Canonical frontend URL used in links and auth flows. | Yes |
| `UPLOAD_DIR` | Backend upload directory path. | Yes |
| `MAX_FILE_SIZE_MB` | Max upload size in MB. | Yes |
| `ALLOWED_RESUME_EXTENSIONS` | Comma-separated allowed resume extensions. | Yes |
| `DEFAULT_RESUME_WEIGHT` | Default final-score resume weight. | Yes |
| `DEFAULT_QUIZ_WEIGHT` | Default final-score quiz weight. | Yes |
| `DEFAULT_PASS_THRESHOLD` | Default pass threshold for quiz/final scoring. | Yes |
| `QUIZ_DURATION_MINUTES` | Default assessment duration. | Yes |
| `QUIZ_TOTAL_QUESTIONS` | Total generated questions. | Yes |
| `QUIZ_EASY_COUNT` | Easy question count. | Yes |
| `QUIZ_MEDIUM_COUNT` | Medium question count. | Yes |
| `QUIZ_HARD_COUNT` | Hard question count. | Yes |
| `GROQ_API_KEY` | Optional Groq provider key (if enabled in workflows). | Optional |
| `SMTP_SERVER` | SMTP host for mail notifications/password reset. | Yes (if email flows enabled) |
| `SMTP_PORT` | SMTP port. | Yes (if email flows enabled) |
| `SMTP_USERNAME` | SMTP username. | Yes (if email flows enabled) |
| `SMTP_PASSWORD` | SMTP password/app password. | Yes (if email flows enabled) |
| `MLFLOW_TRACKING_URI` | MLflow tracking server URL. | Recommended |
| `MLFLOW_EXPERIMENT_NAME` | MLflow experiment namespace. | Recommended |
| `EVALS_ENABLED` | Enables/deactivates eval paths. | Optional |
| `ENABLE_METAFLOW` | Enables experimental Metaflow routes. | Optional |
| `REDIS_URL` | Redis URL for limiter/Harness dependencies. | Yes |
| `HARNESS_MOUNT_ENABLED` | Mount vendored Harness app under `/harness`. | Recommended |
| `HARNESS_ENVIRONMENT` | Harness runtime environment label. | Recommended |
| `HARNESS_ADAPTER_ENABLED` | Enables harness adapter layer. | Recommended |
| `HARNESS_EXECUTION_ENABLED` | Routes execution through harness first when true. | Optional |
| `HARNESS_TRACE_RECORDER_ENABLED` | Enables harness trace recorder integration. | Recommended |

## Production Deployment
1. Build images:
   ```bash
   docker build -t hr9-backend:latest "./HR APP BACKEND"
   docker build -t hr9-frontend:latest "./HR APP FRONTEND"
   ```
2. Push to your registry (example):
   ```bash
   docker tag hr9-backend:latest <registry>/hr9-backend:latest
   docker tag hr9-frontend:latest <registry>/hr9-frontend:latest
   docker push <registry>/hr9-backend:latest
   docker push <registry>/hr9-frontend:latest
   ```
3. Deploy:
   ```bash
   docker compose -f docker-compose.prod.yml up -d
   ```

## Running Tests
- Backend:
  ```bash
  cd "HR APP BACKEND"
  pytest
  ```
- Frontend:
  ```bash
  cd "HR APP FRONTEND"
  npm test
  ```

## Security Notes
- Rotate `SECRET_KEY`, `ENCRYPTION_KEY`, Azure/Gemini/provider API keys before production rollout.
- Restrict `CORS_ORIGINS` to real production domains only (no localhost/127.0.0.1).
- Dependency risk tracking note: `ragas` and `diskcache` have known CVEs tracked intentionally in dependency governance; monitor and patch per your security policy windows.

## Known Issues
- Historical docs/scripts may reference a misspelled `forntend/` directory; this repository currently uses `HR APP FRONTEND/`.
- Backup files (`*.bak`, `*.quickshare.bak`, `*.recovery.bak`) are now ignored and should not be shipped, but old local checkouts may still contain stale copies until cleaned.
