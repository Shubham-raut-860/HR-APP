# LangGraph Multi-Agent Architecture

This package converts the existing service layer into graph-addressable agents.
It intentionally reuses current functions instead of reimplementing business
logic.

## Service to Agent Map

- `document_intake_agent`: wraps `file_service` and `encryption_service`.
- `llm_extraction_agent`: wraps `gemini_service` / `azure_openai_service`.
- `resume_scoring_agent`: wraps `scoring_service` plus AI scoring calls.
- `quiz_agent`: wraps quiz generation, parsing, code evaluation, and scoring.
- `notification_agent`: wraps `notification_service` and `email_service`.
- `export_agent`: wraps `export_service` and `rendercv_service`.
- `observability_agent`: wraps `mlflow_service` and `langfuse_service`.
- `auth_policy_agent`: wraps `auth_service`.
- `cache_agent`: wraps `cache_service`.

## Initial Graphs

- `build_resume_screening_graph()`
  - `document_intake_agent` extracts resume text.
  - `resume_scoring_agent` calls the existing `_compute_resume_data_from_bytes`
    helper so scoring behavior stays identical.

- `build_jd_generation_graph()`
  - Builds the existing cache query.
  - Embeds it with `gemini_service.get_embedding`.
  - Checks `cache_service.get_cached_jd`.
  - Calls `gemini_service.generate_jd` only on cache miss.
  - Writes through `cache_service.cache_jd`.

- `build_quiz_generation_graph()`
  - Calls `gemini_service.generate_quiz_questions`.

- `build_candidate_tools_graph()`
  - Routes to existing resume enhancement or resume builder functions.

## Migration Rule

Routers should migrate by replacing local orchestration with:

```python
graph = build_jd_generation_graph()
state = await graph.ainvoke({...})
```

The service functions remain the source of truth.
