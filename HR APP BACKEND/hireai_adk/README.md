# HIREAI ADK Sidecar

This sidecar adds a Google ADK orchestration agent without replacing the existing HIREAI backend. The agent calls HIREAI over HTTP using the existing A2A, artifact, audit, eval, and token-monitoring endpoints.

## Structure

```text
hireai_adk/
  .env.example
  requirements.txt
  hireai_screening_agent/
    __init__.py
    agent.py
    tools/
      __init__.py
      hireai_client.py
  tests/
    test_hireai_client.py
```

## Setup

```powershell
cd "D:\Shubham\HR APP\HR APP BACKEND\hireai_adk"
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
```

Fill `.env` with:

- `GOOGLE_API_KEY` for the ADK agent model.
- `ADK_MODEL_PROFILE`, default `screening_fast`.
- `HIREAI_BACKEND_URL`, usually `http://127.0.0.1:8000`.
- `HIREAI_A2A_SERVICE_TOKEN`, matching one token in backend `A2A_SERVICE_TOKENS`.
- Optional `HIREAI_ADMIN_AUTH_TOKEN` if you want token monitor or eval endpoints that require normal HR/admin auth.

## Local Run

Start the HIREAI backend first, then run:

```powershell
adk run hireai_screening_agent
```

For local visual debugging only:

```powershell
adk web --port 8081
```

Do not expose ADK Web in production. Production UI should go through the HIREAI backend, not directly to this sidecar.

## Example ADK Prompt

```text
Run resume screening for this candidate against this job description. Start the A2A task asynchronously, poll it, list artifacts, and summarize the result with matched skills, missing skills, score signals, artifact ids, and whether human review is needed.
```

## ADK Model Profiles

The sidecar keeps model selection centralized in `hireai_screening_agent/model_config.py`.

- `screening_fast`: default orchestration profile using `gemini-2.0-flash`.
- `screening_deep_review`: reserved for deeper audit/explanation summaries.
- `workflow_router`: reserved for routing decisions when deterministic graph routing is not enough.

`ADK_MODEL` overrides the selected profile model. HIREAI backend scoring remains the source of truth.

## A2A Discovery

The sidecar exposes HIREAI A2A discovery as ADK tools:

- `get_platform_agent_card`: reads the public `/.well-known/agent-card.json`.
- `list_a2a_agents`: reads `/a2a/agents` with the configured A2A bearer token.
- `get_a2a_agent_card`: reads `/a2a/agents/{agent_id}/card` before explaining or running agent-specific workflows.

Task execution still goes through HIREAI APIs only. The ADK sidecar does not read the database directly.

## Graph Workflow Phase

The sidecar includes a graph workflow spec in `hireai_screening_agent/workflow_specs.py` and an optional ADK 2.x builder in `hireai_screening_agent/graph_workflows.py`.

The resume screening graph is:

```text
START -> input_guard -> a2a_screening_task -> task_poll
task_poll -> artifact_fetch -> human_review_summary
task_poll -> audit_fetch -> human_review_summary
task_poll -> token_fetch -> human_review_summary
```

This is intentionally graph-shaped and explicit: scoring still runs in HIREAI, while ADK coordinates routing, polling, artifacts, audit, token/cost summary, and human-review output.

## Tests

```powershell
pytest tests
```

The tests mock the HTTP layer so they do not require the HIREAI backend to be running.
