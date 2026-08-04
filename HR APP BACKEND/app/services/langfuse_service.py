"""
Optional Langfuse observability adapter.

MLflow and the internal token monitor are the default observability path for
HIREAI. Langfuse is opt-in via LANGFUSE_ENABLED=true. When disabled, or when the
SDK is unavailable, this module exports no-op shims so importers keep working.
"""
from __future__ import annotations

import functools
import logging
from typing import Any, Callable, TypeVar

from app.config import settings

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def _noop_observe(
    func: F | None = None,
    *,
    name: str | None = None,
    as_type: str | None = None,
    capture_input: bool = True,
    capture_output: bool = True,
    transform_to_string: Callable[[Any], str] | None = None,
    **kwargs: Any,
):
    def decorator(f: F) -> F:
        @functools.wraps(f)
        async def wrapper(*args: Any, **inner_kwargs: Any):
            return await f(*args, **inner_kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator(func) if func is not None else decorator


class _NoopLangfuseContext:
    def update_current_trace(self, **kwargs: Any) -> None:
        return None

    def update_current_observation(self, **kwargs: Any) -> None:
        return None

    def get_current_trace_id(self) -> None:
        return None


observe = _noop_observe
langfuse_context = _NoopLangfuseContext()

if settings.LANGFUSE_ENABLED:
    try:
        from langfuse.decorators import (  # type: ignore[assignment]  # noqa: F401
            langfuse_context as _real_langfuse_context,
            observe as _real_observe,
        )

        observe = _real_observe
        langfuse_context = _real_langfuse_context
        logger.info("Langfuse tracing enabled.")
    except ImportError:
        logger.warning(
            "LANGFUSE_ENABLED=true but the langfuse package is not installed; "
            "falling back to no-op tracing."
        )
else:
    logger.debug("Langfuse tracing disabled by LANGFUSE_ENABLED=false.")


class _NoopTracker:
    class _Run:
        class info:
            run_id = ""

    def start_run(self, run_name: str = "") -> "_NoopTracker._Run":
        return self._Run()

    def end_run(self, run_id: str, status: str = "FINISHED") -> None:
        return None

    def log_llm_metrics(
        self,
        run_id: str,
        model: str,
        temperature: float,
        latency: float,
        tokens: dict | None = None,
    ) -> None:
        return None


tracker = _NoopTracker()
