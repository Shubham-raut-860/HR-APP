# HarnessAgent Token Monitor Integration

Date: 2026-05-08

Reference source inspected:
- `C:\Users\Shubh\Downloads\Compressed\HarnessAgent-main.zip`
- Extracted at `D:\Shubham\HR APP\HR APP BACKEND\scratch\HarnessAgent-main`

## What was integrated

Instead of embedding the full HarnessAgent platform (Redis, Prometheus, workers, adapters),
we integrated the relevant monitoring pattern into the existing HR backend:

- Per-call token/cost capture from Azure OpenAI chat + embeddings
- Per-task token budgets and over-budget alerts
- Rolling in-memory usage analytics (recent events + hotspots + summary)
- HR-only API endpoints to inspect usage

## Files added/updated

- Added: `app/services/token_monitor_service.py`
- Added: `app/routers/token_monitor.py`
- Updated: `app/services/gemini_service.py` (records token usage)
- Updated: `app/config.py` (token monitor settings)
- Updated: `.env.example` (token monitor env vars)
- Updated: `app/main.py` (registers monitoring router)

## API endpoints

- `GET /monitoring/tokens/summary?window_minutes=60`
- `GET /monitoring/tokens/recent?limit=100`
- `GET /monitoring/tokens/hotspots?top_n=10&window_minutes=60`
- `GET /monitoring/tokens/budgets`

Additionally, harness pipeline endpoints now include per-run token deltas:
- `POST /harness/run`
- `POST /harness/pipeline/*`

Each response includes:
- `token_usage.calls`
- `token_usage.prompt_tokens`
- `token_usage.completion_tokens`
- `token_usage.total_tokens`
- `token_usage.total_cost_usd`
- `token_usage.budget_tokens`
- `token_usage.status` (`ok` or `over_budget`)

All endpoints require HR auth (`require_hr`).

## Notes

- This integration is dependency-light and production-safe for your current stack.
- If you later want full HarnessAgent observability (Redis + Prometheus + Grafana),
  we can add a phase-2 deployment profile without rewriting this interface.
