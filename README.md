# HireAI

Recruitment platform that uses a LangGraph multi-agent pipeline to automate resume screening, candidate scoring, and quiz generation. Built with FastAPI (Python) on the backend and React + TypeScript on the frontend, running on Azure OpenAI.

## How it works

Recruiters post job descriptions and upload resumes (bulk or single). The backend runs a graph of 15+ specialized agents — each one handles a specific task like parsing resumes, extracting JD requirements, scoring candidates against those requirements, generating quizzes, or ranking applicants. Agents are orchestrated through LangGraph with per-agent model routing (GPT-4o for complex tasks, GPT-4o-mini for fast ones, o4-mini for reasoning).

Candidates get their own portal where they take timed quizzes (auto-generated, difficulty-tiered), upload KYC documents, and track their application status.

## What's in here

- Multi-agent scoring engine with LangGraph (resume parser, JD parser, scoring, ranking, deduplication, quiz gen, code eval, career analyst, cover letter gen, resume builder, recruiter copilot, notifications, embeddings, file extraction)
- Bulk resume processing — async pipeline with configurable concurrency, OCR support for scanned PDFs/images
- Quiz system — easy/medium/hard questions generated per JD, with anti-cheating controls
- Dynamic candidate tagging — percentile-based cohort labels (Strong / Medium / Needs Review)
- JWT auth with bcrypt, access/refresh token rotation, invite-code registration
- Rate limiting with Redis, circuit breaker pattern, token budget monitoring
- KYC document verification with encrypted storage
- A2A protocol for agent-to-agent service calls
- DeepEval + Langfuse + RAGAS integration for LLM eval

## Stack

**Backend:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy (async), Alembic, Redis
**Frontend:** React 19, TypeScript, Vite, Tailwind CSS v4, Radix UI, Recharts
**AI:** LangGraph, LangChain, Azure OpenAI (GPT-4o, GPT-4o-mini, o4-mini), text-embedding-3-small
**Infra:** Docker Compose, Gunicorn, PostgreSQL (prod) / SQLite (dev)

## Running locally

### Backend

```bash
cd "HR APP BACKEND"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example .env   # fill in your Azure OpenAI keys
python -m alembic upgrade head
python run.py
```

### Frontend

```bash
cd "HR APP FRONTEND"
npm install
npm run dev
```

Or just `docker compose up --build` if you want the full stack.

## Config

Copy `.env.example` to `.env` and fill in your credentials. All config is through environment variables — see the example file for the full list.
