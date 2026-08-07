# HireAI

AI recruitment platform — structured around a multi-agent scoring pipeline that evaluates resumes against job descriptions, generates adaptive technical assessments, and routes candidates through a recruiter review workflow.

Built this as a real alternative to keyword-matching ATS systems. The scoring engine uses LangGraph to orchestrate a graph of 15+ specialized agents — one for skills extraction, one for experience mapping, one for domain fit, one for deduplication via embeddings — and aggregates their outputs into a weighted score with full explainability. Each agent can be routed to a different model (GPT-4o for complex reasoning, GPT-4o-mini for fast parsing, o4-mini for structured output).

## What's inside

**Backend** — FastAPI with async SQLAlchemy, PostgreSQL (SQLite for local dev), JWT auth with bcrypt and token rotation, Redis-backed rate limiting with circuit breaker. The agent graph lives in `app/agents/` — `graphs.py` compiles 7 LangGraph workflows (resume screening, JD generation with embedding cache, quiz generation, full resume pipeline, quiz + code eval, candidate ranking, career tools). Specialized agents in `app/agents/specialized/` handle the actual work: file extraction, resume parsing, scoring, deduplication, embedding, ranking, quiz generation, code evaluation, cover letter generation, resume building, notifications, and recruiter copilot. The 80K-line scoring service in `app/services/scoring_service.py` does the heavy lifting — semantic skill matching, experience gap analysis, education scoring, and AI-augmented final scoring with structured reasoning.

**Frontend** — React 19 + TypeScript + Vite + Tailwind CSS v4 + Radix UI. Recruiter portal shows the candidate pipeline with bulk resume upload, JD management, analytics dashboards with Recharts, and a copilot chat. Candidate portal handles application flow, timed quizzes with anti-cheat controls, KYC document upload, resume enhancement tools, and cover letter generation.

**The scoring engine** — The core pipeline runs through `build_full_resume_pipeline_graph()`: file extraction, resume parsing, embedding generation, deduplication check (catches re-uploads via cosine similarity on embeddings), then multi-dimensional scoring. Scoring breaks down into must-have skill matching, good-to-have skill matching, experience range fit, education requirement matching, and an optional AI scoring pass that sends the parsed resume + JD to GPT-4o for a structured assessment with per-dimension reasoning. Results include matched/missing skills, a score breakdown, and a reasoning trace. Candidates get tagged into percentile-based cohorts (Strong / Medium / Needs Review) dynamically.

**Quiz system** — Auto-generates difficulty-tiered questions (easy/medium/hard split configurable per JD) using the JD skills as seed topics. Includes a code evaluation agent that can assess submitted code against problem statements. Anti-cheating controls on the frontend (tab-switch detection, timed sessions).

**Other notable bits** — A2A (agent-to-agent) protocol for inter-service calls, vendored HarnessAgent runtime for worker-mode agent execution, KYC document verification with AES-encrypted storage, Alembic migrations with startup schema drift detection, MLflow experiment tracking, Langfuse + DeepEval integration for LLM evaluation, Metaflow batch scoring pipeline (optional), and a full observability layer with request metrics, token budget monitoring, and runtime alerts.

## Stack

Python 3.11 · FastAPI · Pydantic v2 · SQLAlchemy (async) · Alembic · LangGraph · LangChain · Azure OpenAI (GPT-4o, GPT-4o-mini, o4-mini, text-embedding-3-small) · PostgreSQL · Redis · React 19 · TypeScript · Vite · Tailwind CSS v4 · Radix UI · Recharts · Docker Compose · Gunicorn

## Running it

### Backend

```bash
cd "HR APP BACKEND"
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example .env   # fill in your Azure OpenAI keys + Postgres connection
python -m alembic upgrade head
python run.py
```

### Frontend

```bash
cd "HR APP FRONTEND"
npm install
npm run dev
```

Or just `docker compose up --build` for the full stack.

Fill in `.env` — needs Azure OpenAI keys and a Postgres connection string. See `.env.example` for every variable.

## Data handling

This repository intentionally contains no candidate resumes, uploads, evaluation exports, or production-like data. Those files are ignored at the root; test coverage should use synthetic fixtures generated at test time. That keeps the project safe to clone, review, and share without treating applicant data as sample code.

## Author

Shubham Raut — [github.com/Shubham-raut-860](https://github.com/Shubham-raut-860)
