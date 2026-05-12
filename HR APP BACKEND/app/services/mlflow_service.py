"""
MLflow observability service — replaces Langfuse.

Populates the following MLflow UI sections:
  ✅ Traces        — mlflow.openai.autolog() + @mlflow.trace decorator
  ✅ Sessions      — every trace tagged with a session_id (per HTTP request)
  ✅ Evaluation Runs — mlflow.evaluate() with DeepEval/RAGAS as custom evaluators
  ✅ Judges        — custom Python evaluator functions registered via mlflow.evaluate
  ✅ Datasets      — mlflow.data.from_pandas() logged with mlflow.log_input()
  ✅ Prompts       — prompt text stored via mlflow.log_text (Prompt Registry)
  ✅ Runs          — all eval runs appear in the Runs tab
  ✅ Models        — Azure OpenAI endpoint registered as pyfunc model
  ✅ Registered Models — mlflow.register_model() for the chat model

  ⚠️  Agent versions — N/A (requires LangGraph agents)
  ⚠️  AI Gateway     — Enterprise MLflow feature, not on local server
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.evals.deepeval_service import EvalResult

logger = logging.getLogger(__name__)

# ─── Singleton state ──────────────────────────────────────────────────────────

_mlflow_available = False
_experiment_id: str | None = None
_model_registered = False


def _init_mlflow() -> bool:
    """Init MLflow tracking, autolog, and register the chat model once."""
    global _mlflow_available, _experiment_id, _model_registered
    try:
        import mlflow
        import os
        from app.config import settings

        # Prevent MLflow from blocking the local process if the tracking server is down
        os.environ["MLFLOW_TRACKING_REQUEST_TIMEOUT"] = "3"
        os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"] = "3"

        mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
        experiment = mlflow.set_experiment(settings.MLFLOW_EXPERIMENT_NAME)
        _experiment_id = experiment.experiment_id

        # ── 1. OpenAI autolog → populates Traces tab automatically ────────────
        try:
            mlflow.openai.autolog()
        except AttributeError:
            logger.debug("mlflow.openai autolog not available in this build")

        _mlflow_available = True
        logger.info(
            "✅ MLflow tracing enabled → %s  (experiment: '%s')",
            settings.MLFLOW_TRACKING_URI,
            settings.MLFLOW_EXPERIMENT_NAME,
        )

        # ── 2. Log system prompts → populates Prompts section ─────────────────
        _register_prompts()

        # ── 3. Register the Azure OpenAI model → Registered Models tab ────────
        if not _model_registered:
            _register_azure_model()
            _model_registered = True

        return True

    except Exception as exc:
        logger.warning(
            "⚠️  MLflow not available (%s). "
            "Start server: mlflow server --host 127.0.0.1 --port 5000",
            exc,
        )
        return False


# ─── 2. Prompt Registry ───────────────────────────────────────────────────────

def _register_prompts() -> None:
    """
    Log HireAI system prompts to MLflow so they appear in the Prompts section.
    Each prompt is stored as a text artifact under a dedicated prompt run.
    """
    try:
        import mlflow

        prompts = {
            "resume_parse_prompt": _get_resume_parse_prompt_text(),
            "resume_score_prompt": _get_resume_score_prompt_text(),
            "jd_generation_prompt": _get_jd_generation_prompt_text(),
        }

        with mlflow.start_run(
            run_name="prompt_registry",
            experiment_id=_experiment_id,
            tags={"type": "prompt_registry", "source": "hireai"},
        ):
            for name, text in prompts.items():
                mlflow.log_text(text, f"prompts/{name}.txt")
                # Also log as param for quick preview in UI
                mlflow.log_param(f"prompt_{name}_length", len(text))
            logger.info("✅ Prompts logged to MLflow (Prompts section populated).")

    except Exception as exc:
        logger.debug("Prompt registration non-fatal: %s", exc)


def _get_resume_parse_prompt_text() -> str:
    try:
        from app.services.gemini_service import RESUME_PARSE_PROMPT
        return RESUME_PARSE_PROMPT
    except Exception:
        return "Resume parse prompt — import failed"


def _get_resume_score_prompt_text() -> str:
    try:
        from app.services.gemini_service import SCORE_RESUME_PROMPT
        return SCORE_RESUME_PROMPT
    except Exception:
        return "Resume score prompt — import failed"


def _get_jd_generation_prompt_text() -> str:
    try:
        # FIX Finding 29: Use JD_PARSE_PROMPT since JD_GENERATION_PROMPT is dynamically built now
        from app.services.gemini_service import JD_PARSE_PROMPT
        return JD_PARSE_PROMPT
    except Exception:
        return "JD parse prompt — import failed"


# ─── 3. Registered Models ─────────────────────────────────────────────────────

def _register_azure_model() -> None:
    """
    Register the Azure OpenAI chat endpoint as an MLflow model so it appears
    in the Models and Registered Models tabs.
    Uses mlflow.openai model flavor.
    """
    try:
        import mlflow
        from app.config import settings
        from mlflow.models.signature import ModelSignature
        from mlflow.types.schema import Schema, ColSpec

        signature = ModelSignature(
            inputs=Schema([ColSpec("string", "prompt")]),
            outputs=Schema([ColSpec("string", "response")]),
        )

        with mlflow.start_run(
            run_name="hireai_azure_openai_registration",
            experiment_id=_experiment_id,
            tags={"type": "model_registration", "source": "hireai"},
        ) as run:
            mlflow.log_params({
                "model_type":    "azure_openai_chat",
                "deployment":    settings.AZURE_CHAT_DEPLOYMENT,
                "api_version":   settings.AZURE_OPENAI_API_VERSION,
                "endpoint":      settings.AZURE_OPENAI_ENDPOINT,
                "max_tokens":    "4000",
            })

            model_info = mlflow.openai.log_model(
                model="chat.completions",
                task="chat.completions",
                artifact_path="hireai_chat_model",
                messages=[
                    {"role": "system",  "content": "You are an HR AI assistant."},
                    {"role": "user",    "content": "{prompt}"},
                ],
                signature=signature,
            )

            # Register for the Registered Models tab
            try:
                mlflow.register_model(
                    model_uri=model_info.model_uri,
                    name="HireAI-AzureOpenAI-Chat",
                )
                logger.info("✅ Azure OpenAI model registered → Registered Models tab.")
            except Exception as reg_exc:
                logger.debug("Model already registered or registry error: %s", reg_exc)

    except Exception as exc:
        logger.debug("Model registration non-fatal: %s", exc)


# ─── 4. Session Tracking ──────────────────────────────────────────────────────

def get_or_create_session_id(request_id: str | None = None) -> str:
    """
    Return a session ID for the current request. Use this to group
    all traces from a single HTTP request into one MLflow Session.
    """
    return request_id or str(uuid.uuid4())


def tag_trace_with_session(session_id: str, user_id: int | None = None) -> None:
    """
    Set session-level tags on the active MLflow trace so that
    all spans from this request appear together in the Sessions tab.
    """
    if not _mlflow_available:
        return
    try:
        import mlflow
        mlflow.set_tags({
            "mlflow.session.id": session_id,
            "hireai.user_id":    str(user_id) if user_id else "anonymous",
        })
    except Exception as exc:
        logger.debug("Session tag error (non-fatal): %s", exc)


# ─── 5. Async LLM span context manager ───────────────────────────────────────

@asynccontextmanager
async def mlflow_track_llm(
    task_name: str,
    run_name: str | None = None,
    tags: dict | None = None,
    session_id: str | None = None,
    user_id: int | None = None,
):
    """
    Async context manager: wraps any LLM call in an MLflow nested run.
    Tags the run with session_id → populates Sessions tab.
    """
    if not _mlflow_available:
        yield None
        return

    try:
        import mlflow

        sid = session_id or str(uuid.uuid4())
        t0 = time.perf_counter()
        run_tags = {
            "task":              task_name,
            "source":            "hireai",
            "mlflow.session.id": sid,
            **({"hireai.user_id": str(user_id)} if user_id else {}),
            **(tags or {}),
        }

        with mlflow.start_run(
            run_name=run_name or task_name,
            experiment_id=_experiment_id,
            nested=True,
            tags=run_tags,
        ) as run:
            try:
                mlflow.log_param("task_name", task_name)
                mlflow.log_param("session_id", sid)
                yield run
            finally:
                latency_ms = (time.perf_counter() - t0) * 1000
                try:
                    mlflow.log_metric("latency_ms", round(latency_ms, 2))
                except Exception:
                    pass
    except Exception as exc:
        logger.debug("MLflow tracing error (non-fatal): %s", exc)
        yield None


# ─── 6. Evaluation Runs + Datasets + Judges ──────────────────────────────────

def run_mlflow_evaluation(
    operation: str,
    eval_data: list[dict],
    run_name: str | None = None,
) -> None:
    """
    Run mlflow.evaluate() with our custom HireAI judge functions.
    Populates: Evaluation runs, Judges, Datasets, Runs tabs.

    Args:
        operation:  'resume_parsing' | 'resume_scoring' | 'jd_generation'
        eval_data:  List of dicts with keys: 'inputs', 'ground_truth', 'outputs'
        run_name:   Optional run name for the UI.
    """
    if not _mlflow_available:
        return

    try:
        import mlflow
        import pandas as pd

        df = pd.DataFrame(eval_data)
        dataset = mlflow.data.from_pandas(
            df,
            name=f"hireai_{operation}_dataset",
            targets="ground_truth",
        )

        # Build custom evaluator functions per operation
        evaluators = _build_evaluators(operation)

        with mlflow.start_run(
            run_name=run_name or f"eval_{operation}",
            experiment_id=_experiment_id,
            tags={
                "type":      "evaluation_run",
                "operation": operation,
                "source":    "hireai",
            },
        ):
            mlflow.log_input(dataset, context="evaluation")
            mlflow.log_param("operation", operation)
            mlflow.log_param("eval_sample_count", len(eval_data))

            results = mlflow.evaluate(
                data=df,
                targets="ground_truth",
                predictions="outputs",
                extra_metrics=evaluators,
                evaluator_config={"col_mapping": {"inputs": "inputs"}},
            )

            logger.info(
                "✅ MLflow evaluation run complete for '%s': %s",
                operation,
                results.metrics,
            )
            return results

    except Exception as exc:
        logger.warning("run_mlflow_evaluation error (non-fatal): %s", exc)
        return None


def _build_evaluators(operation: str) -> list:
    """
    Build mlflow.metrics.make_metric() custom judge functions for each operation.
    These appear as 'Judges' in the MLflow Evaluation Runs tab.
    """
    try:
        import mlflow

        metrics = []

        def _completeness_judge(predictions, targets, metrics_):
            """Judge: Is the output complete and non-empty?"""
            scores = []
            for pred in predictions:
                if pred and len(str(pred)) > 50:
                    scores.append(1.0)
                elif pred and len(str(pred)) > 10:
                    scores.append(0.6)
                else:
                    scores.append(0.0)
            import numpy as np
            return mlflow.metrics.MetricValue(
                scores=scores,
                aggregate_results={"mean": float(np.mean(scores))},
            )

        def _relevance_judge(predictions, targets, metrics_):
            """Judge: Does the output contain expected keywords from ground truth?"""
            scores = []
            for pred, gt in zip(predictions, targets):
                pred_str = str(pred).lower()
                gt_str = str(gt).lower()
                gt_words = set(gt_str.split()) - {"the", "a", "is", "in", "of"}
                if not gt_words:
                    scores.append(0.5)
                    continue
                hits = sum(1 for w in gt_words if w in pred_str)
                scores.append(round(hits / len(gt_words), 2))
            import numpy as np
            return mlflow.metrics.MetricValue(
                scores=scores,
                aggregate_results={"mean": float(np.mean(scores))},
            )

        metrics.append(
            mlflow.metrics.make_metric(
                eval_fn=_completeness_judge,
                greater_is_better=True,
                name="hireai_completeness",
                long_name=f"HireAI Output Completeness ({operation})",
            )
        )
        metrics.append(
            mlflow.metrics.make_metric(
                eval_fn=_relevance_judge,
                greater_is_better=True,
                name="hireai_relevance",
                long_name=f"HireAI Output Relevance ({operation})",
            )
        )

        # Add operation-specific metrics
        if operation == "resume_scoring":
            def _score_range_judge(predictions, targets, metrics_):
                """Judge: Are scores within valid 0-100 range?"""
                import json
                import numpy as np
                scores = []
                for pred in predictions:
                    try:
                        if isinstance(pred, str):
                            pred = json.loads(pred)
                        vals = [v for v in (pred or {}).values() if isinstance(v, (int, float))]
                        in_range = all(0 <= v <= 100 for v in vals)
                        scores.append(1.0 if in_range else 0.0)
                    except Exception:
                        scores.append(0.5)
                return mlflow.metrics.MetricValue(
                    scores=scores,
                    aggregate_results={"mean": float(np.mean(scores))},
                )

            metrics.append(
                mlflow.metrics.make_metric(
                    eval_fn=_score_range_judge,
                    greater_is_better=True,
                    name="hireai_score_range_validity",
                    long_name="HireAI Score Range Validity (0-100)",
                )
            )

        return metrics

    except Exception as exc:
        logger.debug("Evaluator build error (non-fatal): %s", exc)
        return []


# ─── 7. Push DeepEval eval results to MLflow ─────────────────────────────────

def push_eval_to_mlflow(result: "EvalResult", run_id: str | None = None) -> None:
    """Log all DeepEval metric scores to the active MLflow run."""
    if not _mlflow_available:
        return

    try:
        import mlflow

        def _log():
            mlflow.log_metric(f"{result.operation}/overall_score", round(result.overall_score, 4))
            mlflow.log_metric(f"{result.operation}/passed",        float(result.passed))
            mlflow.log_metric(f"{result.operation}/latency_ms",    round(result.latency_ms, 2))
            for metric in result.metrics:
                safe = metric.name.lower().replace(" ", "_")
                mlflow.log_metric(f"{result.operation}/{safe}",        round(metric.score, 4))
                mlflow.log_metric(f"{result.operation}/{safe}_passed", float(metric.passed))

        if run_id:
            with mlflow.start_run(run_id=run_id, nested=True):
                _log()
        else:
            _log()

    except Exception as exc:
        logger.warning("push_eval_to_mlflow error (non-fatal): %s", exc)


# ─── 8. Push RAGAS metric dict to MLflow ─────────────────────────────────────

def push_ragas_to_mlflow(operation: str, metrics: dict[str, float]) -> None:
    """Log a RAGAS metrics dict (name → score) to the active MLflow run."""
    if not _mlflow_available or not metrics:
        return

    try:
        import mlflow
        for name, score in metrics.items():
            safe = name.lower().replace(" ", "_")
            mlflow.log_metric(f"ragas/{operation}/{safe}", round(float(score), 4))
    except Exception as exc:
        logger.warning("push_ragas_to_mlflow error (non-fatal): %s", exc)


# ─── 9. Back-compat: LLMTracker shim ─────────────────────────────────────────

class LLMTracker:
    """Backward-compatible shim — old callers using tracker.start_run() still work."""

    def start_run(self, run_name: str = ""):
        class _Run:
            class info:
                run_id = ""
        if not _mlflow_available:
            return _Run()
        try:
            import mlflow
            run = mlflow.start_run(
                run_name=run_name or "hireai_llm_call",
                experiment_id=_experiment_id,
            )

            class _Info:
                run_id = run.info.run_id

            class _Active:
                info = _Info()
            return _Active()
        except Exception:
            return _Run()

    def end_run(self, run_id: str, status: str = "FINISHED") -> None:
        if _mlflow_available and run_id:
            try:
                import mlflow
                mlflow.end_run(status=status)
            except Exception:
                pass

    def log_llm_metrics(self, run_id: str, model: str, temperature: float,
                        latency: float, tokens: dict | None = None) -> None:
        if not _mlflow_available or not run_id:
            return
        try:
            import mlflow
            mlflow.log_param("model", model)
            mlflow.log_param("temperature", temperature)
            mlflow.log_metric("latency_seconds", round(latency, 4))
            if tokens:
                mlflow.log_metric("prompt_tokens",     tokens.get("prompt_tokens", 0))
                mlflow.log_metric("completion_tokens", tokens.get("completion_tokens", 0))
                mlflow.log_metric("total_tokens",      tokens.get("total_tokens", 0))
        except Exception as exc:
            logger.debug("LLMTracker.log_llm_metrics error: %s", exc)


_tracker_instance: LLMTracker | None = None


def get_tracker() -> LLMTracker:
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = LLMTracker()
    return _tracker_instance


class _LazyTrackerProxy:
    def __getattr__(self, name: str):
        return getattr(get_tracker(), name)


tracker = _LazyTrackerProxy()

# ─── Run init ─────────────────────────────────────────────────────────────────
# AUTO-INIT REMOVED: Initializing MLflow during module import blocks the
# uvicorn reloader and can hang the entire server if the tracking URI
# is unreachable. Initialization is now triggered explicitly by the
# app lifespan hook in app/main.py.
