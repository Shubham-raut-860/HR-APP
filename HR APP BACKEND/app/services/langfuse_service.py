"""
Langfuse observability service (SDK v3 / OpenTelemetry-based).

The modern Langfuse SDK wraps the OpenAI client directly — no manual trace/generation
calls needed. Just use `from langfuse.openai import AsyncAzureOpenAI` in gemini_service.py
and every completion is auto-traced.

For grouping multiple LLM calls under a single parent trace (e.g. the full resume pipeline),
decorate the top-level async function with @observe and call
langfuse_context.update_current_trace() to set name/user_id/metadata.

Exports:
  observe                → decorator that creates a parent trace span
  langfuse_context       → update trace metadata from inside a decorated function
  tracker                → back-compat no-op shim
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ─── Re-export the decorator API ──────────────────────────────────────────────
# These are used by resumes.py (and any other router) to wrap pipeline functions.

try:
    from langfuse.decorators import observe, langfuse_context  # noqa: F401
    logger.debug("Langfuse decorator API imported successfully.")
except ImportError:
    logger.warning(
        "⚠️  langfuse package not installed — run `pip install langfuse` to enable tracing."
    )

    # Provide no-op fallbacks so the app starts cleanly without the package.
    import functools

    def observe(func=None, *, name=None, as_type=None, capture_input=True,  # type: ignore[misc]
                capture_output=True, transform_to_string=None, **kwargs):
        def decorator(f):
            @functools.wraps(f)
            async def wrapper(*a, **kw):
                # PII Masking Note: The native Langfuse SDK's observer automatically captures input/output.
                # In production, PII masking should be implemented using Langfuse SDK data masking callbacks 
                # or modifying capture_input=False explicitly where PII is passed.
                return await f(*a, **kw)
            return wrapper
        return decorator(func) if func is not None else decorator

    class _NoopLangfuseContext:
        def update_current_trace(self, **kwargs): pass
        def update_current_observation(self, **kwargs): pass
        def get_current_trace_id(self): return None

    langfuse_context = _NoopLangfuseContext()  # type: ignore[assignment]


# ─── Back-compat shim ─────────────────────────────────────────────────────────
# Any code that still does `from langfuse_service import tracker` keeps working.

class _NoopTracker:
    class _Run:
        class info:
            run_id = ""

    def start_run(self, run_name: str = "") -> "_NoopTracker._Run":
        return self._Run()

    def end_run(self, run_id: str, status: str = "FINISHED") -> None:
        pass

    def log_llm_metrics(self, run_id: str, model: str, temperature: float,
                        latency: float, tokens: dict | None = None) -> None:
        pass


tracker = _NoopTracker()
