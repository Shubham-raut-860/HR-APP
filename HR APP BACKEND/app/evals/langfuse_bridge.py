"""
Langfuse ↔ DeepEval bridge.

After a DeepEval evaluation completes, call `push_to_langfuse()` to attach
each metric's score to the active Langfuse trace.  This creates a unified
view in Langfuse where you can see both the LLM call telemetry AND the
evaluation quality scores side by side.

Usage (inside an @observe-decorated function):

    from app.evals.langfuse_bridge import push_eval_to_langfuse

    parsed = await gemini_service.parse_resume(text)
    eval_result = await evaluator.evaluate_resume_parsing(text, parsed)
    push_eval_to_langfuse(eval_result)

The function is a no-op if:
  - Langfuse is not installed / configured
  - There is no active trace in the current context
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.evals.deepeval_service import EvalResult

logger = logging.getLogger(__name__)

# BUG #3 FIX: Langfuse() was being instantiated fresh on every push_eval_to_langfuse()
# call, opening a new HTTP connection each time.  Use a module-level singleton instead.
_lf_client = None


def _get_langfuse_client():
    global _lf_client
    if _lf_client is None:
        try:
            from langfuse import Langfuse
            _lf_client = Langfuse()
        except Exception as _lf_exc:
            import logging as _lfl
            _lfl.getLogger(__name__).warning(
                "Langfuse observability disabled - init failed: %s. "
                "Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY to enable.",
                _lf_exc,
            )
    return _lf_client


def push_eval_to_langfuse(result: "EvalResult", trace_id: str | None = None) -> None:
    """
    Post all metric scores from a DeepEval EvalResult to the current Langfuse trace.

    Args:
        result:   The EvalResult returned by DeepEvalService.evaluate_*().
        trace_id: Optional explicit trace ID. If None, uses the current
                  active trace from langfuse_context (requires @observe wrapper).
    """
    try:
        from langfuse.decorators import langfuse_context

        lf = _get_langfuse_client()
        if lf is None:
            logger.debug("Langfuse not installed - skipping score push.")
            return

        # Resolve trace_id — prefer explicit, fall back to active context
        tid = trace_id or langfuse_context.get_current_trace_id()
        if not tid:
            logger.debug("push_eval_to_langfuse: no active trace - scores not pushed.")
            return

        for metric in result.metrics:
            try:
                lf.score(
                    trace_id=tid,
                    name=f"deepeval/{result.operation}/{metric.name.lower().replace(' ', '_')}",
                    value=metric.score,
                    comment=(
                        f"threshold={metric.threshold} | passed={metric.passed} | "
                        f"{metric.reason[:200] if metric.reason else ''}"
                    ),
                )
            except Exception as score_err:
                logger.warning(
                    "Failed to push metric '%s' to Langfuse: %s", metric.name, score_err
                )

        # Also push an aggregate overall score for quick dashboard filtering
        try:
            lf.score(
                trace_id=tid,
                name=f"deepeval/{result.operation}/overall",
                value=result.overall_score,
                comment=f"passed={result.passed} | latency={result.latency_ms:.0f}ms",
            )
        except Exception as agg_err:
            logger.warning("Failed to push aggregate score to Langfuse: %s", agg_err)

        logger.debug(
            "Pushed %d metric scores to Langfuse trace %s (operation=%s).",
            len(result.metrics), tid, result.operation,
        )

    except ImportError:
        logger.debug("Langfuse not installed - skipping score push.")
    except Exception as exc:
        # Never let observability failures crash the main request path
        logger.warning("push_eval_to_langfuse error (non-fatal): %s", exc)
