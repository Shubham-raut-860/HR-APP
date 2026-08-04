"""
EvalHub — single unified evaluation interface for Jobora.

Merges DeepEval (primary) + RAGAS (RAG metrics) + MLflow (score sink)
into ONE call site. Callers never import from individual libraries.

Architecture:
  ┌─────────────────────────────────────────────────────────────┐
  │                        EvalHub                              │
  │                                                             │
  │  ┌──────────────┐   ┌──────────────┐   ┌────────────────┐  │
  │  │  DeepEval    │   │    RAGAS     │   │    MLflow      │  │
  │  │  (9 metrics) │   │  (4 metrics) │   │  (score sink)  │  │
  │  │  GEval       │   │  Faithfulns  │   │  per-metric    │  │
  │  │  Hallucn     │   │  AnsRelevncy │   │  metrics on    │  │
  │  │  AnswerRel   │   │  CtxPrecisn  │   │  active run    │  │
  │  │  DAGMetric   │   │  CtxRecall   │   │                │  │
  │  └──────────────┘   └──────────────┘   └────────────────┘  │
  │           │                 │                   ▲           │
  │           └────────┬────────┘                   │           │
  │                    ▼                             │           │
  │          ┌─────────────────┐          push_eval_to_mlflow │
  │          │  UnifiedResult  │ ──────────────────►│           │
  │          └─────────────────┘                               │
  └─────────────────────────────────────────────────────────────┘

User-level tracking:
  Every eval result is also written to the eval_results table in the DB,
  keyed by user_id + operation + timestamp. This powers per-user dashboards
  and trend reports accessible via GET /evals/history.

Usage:
    from app.evals.eval_hub import eval_hub

    result = await eval_hub.run(
        operation="resume_parsing",
        user_id=current_user.id,
        resume_text=text,
        parsed_output=parsed,
        jd_text=jd.full_text,
        db=db,                   # for user-level storage
    )

    result = await eval_hub.run(
        operation="resume_scoring",
        user_id=current_user.id,
        resume_text=text,
        jd_text=jd.full_text,
        scores=ai_scores,
        db=db,
    )

    result = await eval_hub.run(
        operation="jd_generation",
        user_id=current_user.id,
        user_input=prompt,
        generated_jd=jd_text,
        db=db,
    )
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ─── Unified result ───────────────────────────────────────────────────────────

@dataclass
class UnifiedEvalResult:
    operation:      str
    user_id:        str
    passed:         bool
    overall_score:  float
    deepeval:       dict | None = None   # EvalResult.to_dict()
    ragas:          dict | None = None   # RagasResult.to_dict()
    latency_ms:     float = 0.0
    evaluated_at:   str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "operation":     self.operation,
            "user_id":       self.user_id,
            "passed":        self.passed,
            "overall_score": round(self.overall_score, 4),
            "latency_ms":    round(self.latency_ms, 1),
            "evaluated_at":  self.evaluated_at,
            "deepeval":      self.deepeval,
            "ragas":         self.ragas,
        }


# ─── EvalHub ─────────────────────────────────────────────────────────────────

class EvalHub:
    """
    Single entry point for all evaluations. Runs DeepEval + RAGAS in parallel,
    pushes results to Langfuse, and persists per-user history to the DB.
    """

    def __init__(self):
        from app.evals.deepeval_service import evaluator as _deepeval
        from app.evals.ragas_service import ragas_evaluator as _ragas
        self._deepeval = _deepeval
        self._ragas = _ragas
        logger.info("EvalHub ready (DeepEval + RAGAS + MLflow).")

    async def run(
        self,
        *,
        operation:      str,
        user_id:        str,
        db=None,                         # AsyncSession — for user-level storage
        trace_id:       str | None = None,
        # resume_parsing args
        resume_text:    str | None = None,
        parsed_output:  dict | None = None,
        # resume_scoring args
        jd_text:        str | None = None,
        scores:         dict | None = None,
        # jd_generation args
        user_input:     str | None = None,
        generated_jd:   str | None = None,
    ) -> UnifiedEvalResult:
        """
        Run all applicable metrics for the given operation in parallel.

        operation must be one of: resume_parsing | resume_scoring | jd_generation
        """
        t0 = time.perf_counter()

        deepeval_task = self._run_deepeval(
            operation=operation,
            resume_text=resume_text,
            parsed_output=parsed_output,
            jd_text=jd_text,
            scores=scores,
            user_input=user_input,
            generated_jd=generated_jd,
        )
        ragas_task = self._run_ragas(
            operation=operation,
            resume_text=resume_text,
            parsed_output=parsed_output,
            jd_text=jd_text,
            scores=scores,
        )

        deepeval_result, ragas_result = await asyncio.gather(
            deepeval_task, ragas_task, return_exceptions=True
        )

        # Safely unwrap (gather with return_exceptions returns Exception objects on failure)
        deepeval_dict = None
        ragas_dict = None
        deepeval_score = 0.0
        ragas_score = 0.0
        deepeval_failed = False
        ragas_failed = False

        if isinstance(deepeval_result, Exception):
            deepeval_failed = True
            logger.error("DeepEval task raised: %s", deepeval_result)
            deepeval_dict = {
                "operation": operation,
                "passed": False,
                "overall_score": 0.0,
                "latency_ms": 0.0,
                "error": "service_unavailable",
                "metrics": [
                    {
                        "name": "service_unavailable",
                        "score": 0.0,
                        "passed": False,
                        "threshold": 1.0,
                        "reason": "service_unavailable",
                    }
                ],
            }
        elif deepeval_result is not None:
            deepeval_dict = deepeval_result.to_dict()
            deepeval_score = deepeval_result.overall_score

        if isinstance(ragas_result, Exception):
            ragas_failed = True
            logger.error("RAGAS task raised: %s", ragas_result)
            ragas_dict = {
                "library": "ragas",
                "passed": False,
                "metrics": {},
                "latency_ms": 0.0,
                "error": "service_unavailable",
            }
        elif ragas_result is not None:
            ragas_dict = ragas_result.to_dict()
            ragas_score = (
                sum(ragas_result.metrics.values()) / len(ragas_result.metrics)
                if ragas_result.metrics else 0.0
            )

        # Weighted overall — RAGAS only available for parsing/scoring
        if ragas_dict and ragas_dict.get("metrics"):
            overall = (deepeval_score * 0.6) + (ragas_score * 0.4)
        else:
            overall = deepeval_score

        deepeval_passed = bool(
            (not deepeval_failed)
            and (deepeval_result is not None)
            and (not isinstance(deepeval_result, Exception))
            and deepeval_result.passed
        )
        if operation in {"resume_parsing", "resume_scoring"}:
            ragas_passed = bool(
                (not ragas_failed)
                and (ragas_result is not None)
                and (not isinstance(ragas_result, Exception))
                and ragas_result.passed
            )
        else:
            ragas_passed = True

        passed = deepeval_passed and ragas_passed

        latency_ms = (time.perf_counter() - t0) * 1000

        result = UnifiedEvalResult(
            operation=operation,
            user_id=user_id,
            passed=passed,
            overall_score=overall,
            deepeval=deepeval_dict,
            ragas=ragas_dict,
            latency_ms=latency_ms,
        )

        # Push to MLflow (awaited so failures are visible to caller/logs)
        await self._push_mlflow(result, deepeval_result, ragas_result)

        # Persist user-level history to DB (awaited so failures surface)
        if db is not None:
            await self._persist(result, db)

        return result

    # ── DeepEval dispatch ─────────────────────────────────────────────────────

    async def _run_deepeval(self, *, operation: str, **kwargs):
        try:
            if operation == "resume_parsing":
                return await self._deepeval.evaluate_resume_parsing(
                    resume_text=kwargs["resume_text"],
                    parsed_output=kwargs["parsed_output"],
                )
            elif operation == "resume_scoring":
                return await self._deepeval.evaluate_resume_scoring(
                    resume_text=kwargs["resume_text"],
                    jd_text=kwargs["jd_text"],
                    scores=kwargs["scores"],
                )
            elif operation == "jd_generation":
                return await self._deepeval.evaluate_jd_generation(
                    user_input=kwargs["user_input"],
                    generated_jd=kwargs["generated_jd"],
                )
            raise ValueError(f"Unsupported eval operation: {operation}")
        except Exception as exc:
            logger.error("DeepEval dispatch error (%s): %s", operation, exc, exc_info=True)
            raise

    # ── RAGAS dispatch ────────────────────────────────────────────────────────

    async def _run_ragas(self, *, operation: str, **kwargs):
        try:
            if operation == "resume_parsing":
                return await self._ragas.evaluate_resume_parsing(
                    resume_text=kwargs["resume_text"],
                    parsed_output=kwargs["parsed_output"],
                    jd_text=kwargs["jd_text"],
                )
            elif operation == "resume_scoring":
                return await self._ragas.evaluate_resume_scoring(
                    resume_text=kwargs["resume_text"],
                    jd_text=kwargs["jd_text"],
                    scores=kwargs["scores"],
                )
            # jd_generation has no RAGAS equivalent (not a RAG operation)
            return None
        except Exception as exc:
            logger.error("RAGAS dispatch error (%s): %s", operation, exc, exc_info=True)
            raise

    # ── MLflow push ──────────────────────────────────────────────────────────────────────

    async def _push_mlflow(self, result: UnifiedEvalResult, deepeval_result, ragas_result):
        try:
            from app.services.mlflow_service import push_eval_to_mlflow, push_ragas_to_mlflow
            if deepeval_result and not isinstance(deepeval_result, Exception):
                push_eval_to_mlflow(deepeval_result)
            if ragas_result and not isinstance(ragas_result, Exception) and ragas_result.metrics:
                push_ragas_to_mlflow(result.operation, ragas_result.metrics)
        except Exception as exc:
            logger.error("MLflow push failed: %s", exc, exc_info=True)
            raise

    # ── DB persistence ────────────────────────────────────────────────────────

    async def _persist(self, result: UnifiedEvalResult, db):
        """
        Write eval result to the eval_results table for user-level tracking.
        """
        try:
            from sqlalchemy import text
            await db.execute(
                text("""
                    INSERT INTO eval_results
                        (user_id, operation, overall_score, passed,
                         deepeval_json, ragas_json, latency_ms, evaluated_at)
                    VALUES
                        (:user_id, :operation, :overall_score, :passed,
                         :deepeval_json, :ragas_json, :latency_ms, :evaluated_at)
                """),
                {
                    # BUG #6 FIX: user_id may be a UUID object; VARCHAR(36) needs a plain str.
                    "user_id":       str(result.user_id),
                    "operation":     result.operation,
                    "overall_score": result.overall_score,
                    "passed":        result.passed,
                    "deepeval_json": json.dumps(result.deepeval) if result.deepeval else None,
                    "ragas_json":    json.dumps(result.ragas) if result.ragas else None,
                    "latency_ms":    result.latency_ms,
                    "evaluated_at":  result.evaluated_at,
                },
            )
            await db.commit()
        except Exception as exc:
            logger.error("eval_results persistence failed: %s", exc, exc_info=True)
            raise

    async def run_summary(self, user_id: str, db, days: int = 7) -> dict:
        """
        Return a rolling aggregate of eval scores for the given user.

        Useful for programmatic dashboarding (e.g. nightly report scripts)
        without going through the HTTP layer.

        Returns:
            {
                "user_id": "...",
                "window_days": 7,
                "by_operation": [
                    {"operation": "resume_parsing", "total": 34, "avg_score": 0.82, "pass_rate": 0.91},
                    ...
                ]
            }
        """
        from sqlalchemy import text
        try:
            rows = await db.execute(
                text("""
                    SELECT
                        operation,
                        COUNT(*)              AS total,
                        AVG(overall_score)    AS avg_score,
                        SUM(CASE WHEN passed THEN 1 ELSE 0 END) AS passed_count
                    FROM eval_results
                    WHERE user_id = :uid
                      AND evaluated_at >= NOW() - INTERVAL '1 day' * :days
                    GROUP BY operation
                    ORDER BY operation
                """),
                {"uid": str(user_id), "days": days},
            )
            records = rows.mappings().all()
            by_op = [
                {
                    "operation":  r["operation"],
                    "total":      int(r["total"]),
                    "avg_score":  round(float(r["avg_score"] or 0), 4),
                    "pass_rate":  round(int(r["passed_count"]) / int(r["total"]), 4)
                    if r["total"] else 0.0,
                }
                for r in records
            ]
        except Exception as exc:
            logger.debug("run_summary DB error (non-fatal): %s", exc)
            by_op = []

        return {"user_id": str(user_id), "window_days": days, "by_operation": by_op}


# ─── Singleton ────────────────────────────────────────────────────────────────
eval_hub = EvalHub()
