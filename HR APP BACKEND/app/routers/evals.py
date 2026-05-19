"""
Eval router - exposes HTTP endpoints to trigger and inspect LLM evaluations.

Endpoints:
  POST /evals/resume-parsing  -> evaluate parse quality (DeepEval + RAGAS)
  POST /evals/resume-scoring  -> evaluate scoring fairness (DeepEval + RAGAS)
  POST /evals/jd-generation   -> evaluate JD quality (DeepEval)
  POST /evals/full-pipeline   -> run all three in parallel
  GET  /evals/metrics         -> list available metrics per operation
  GET  /evals/history         -> user-level eval history
  GET  /evals/history/summary -> aggregated stats per operation for this user
  GET  /evals/ai-capability-report -> prompt quality, OCR quality, model-fit report
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings
from app.services.auth_service import require_admin, require_hr
from app.models import User
from app.evals.eval_hub import eval_hub
from app.services.ai_capability_report_service import build_ai_capability_report
from app.services.hr_inspector_service import build_hr_inspector_overview
from app.services.gemini_service import observe  # Real MLflow trace decorator
from app.services.langfuse_service import langfuse_context

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/evals", tags=["Evaluations"])


def _ensure_evals_enabled() -> None:
    if not settings.EVALS_ENABLED:
        raise HTTPException(status_code=503, detail="Evaluations are disabled")


# Request schemas

class ResumeParsingEvalRequest(BaseModel):
    resume_text: str = Field(..., description="Raw text extracted from the resume")
    parsed_output: dict[str, Any] = Field(..., description="Output of the AI resume parser")
    jd_text: str = Field(..., description="Job description text (used as RAGAS question)")


class ResumeScoringEvalRequest(BaseModel):
    resume_text: str = Field(...)
    jd_text: str = Field(...)
    scores: dict[str, Any] = Field(
        ...,
        example={"skill_score": 72, "experience_score": 65, "project_score": 58},
    )


class JDGenerationEvalRequest(BaseModel):
    user_input: str = Field(..., description="The brief the user provided")
    generated_jd: str = Field(..., description="The full JD text returned by the AI")


class FullPipelineEvalRequest(BaseModel):
    resume_text:   str = Field(...)
    parsed_output: dict[str, Any] = Field(...)
    jd_text:       str = Field(...)
    scores:        dict[str, Any] = Field(...)
    generated_jd:  str | None = Field(None)
    user_jd_input: str | None = Field(None)


# Endpoints

@router.post("/resume-parsing", summary="Evaluate resume parsing quality (DeepEval + RAGAS)")
@observe(name="eval/resume_parsing")
async def eval_resume_parsing(
    body: ResumeParsingEvalRequest,
    current_user: User = Depends(require_hr),
    db: AsyncSession = Depends(get_db),
):
    _ensure_evals_enabled()
    try:
        result = await eval_hub.run(
            operation="resume_parsing",
            user_id=current_user.id,
            resume_text=body.resume_text,
            parsed_output=body.parsed_output,
            jd_text=body.jd_text,
            db=db,
        )
        langfuse_context.update_current_trace(
            name="eval/resume_parsing",
            metadata={"passed": result.passed, "overall_score": result.overall_score},
        )
        return result.to_dict()
    except Exception as exc:
        logger.exception("Resume parsing eval failed")
        raise HTTPException(status_code=500, detail="An internal error occurred.") from exc


@router.post("/resume-scoring", summary="Evaluate AI resume scoring (DeepEval + RAGAS)")
@observe(name="eval/resume_scoring")
async def eval_resume_scoring(
    body: ResumeScoringEvalRequest,
    current_user: User = Depends(require_hr),
    db: AsyncSession = Depends(get_db),
):
    _ensure_evals_enabled()
    try:
        result = await eval_hub.run(
            operation="resume_scoring",
            user_id=current_user.id,
            resume_text=body.resume_text,
            jd_text=body.jd_text,
            scores=body.scores,
            db=db,
        )
        langfuse_context.update_current_trace(
            name="eval/resume_scoring",
            metadata={"passed": result.passed, "overall_score": result.overall_score},
        )
        return result.to_dict()
    except Exception as exc:
        logger.exception("Resume scoring eval failed")
        raise HTTPException(status_code=500, detail="An internal error occurred.") from exc


@router.post("/jd-generation", summary="Evaluate JD generation quality (DeepEval)")
@observe(name="eval/jd_generation")
async def eval_jd_generation(
    body: JDGenerationEvalRequest,
    current_user: User = Depends(require_hr),
    db: AsyncSession = Depends(get_db),
):
    _ensure_evals_enabled()
    try:
        result = await eval_hub.run(
            operation="jd_generation",
            user_id=current_user.id,
            user_input=body.user_input,
            generated_jd=body.generated_jd,
            db=db,
        )
        langfuse_context.update_current_trace(
            name="eval/jd_generation",
            metadata={"passed": result.passed, "overall_score": result.overall_score},
        )
        return result.to_dict()
    except Exception as exc:
        logger.exception("JD generation eval failed")
        raise HTTPException(status_code=500, detail="An internal error occurred.") from exc


@router.post("/full-pipeline", summary="Run all evaluations in parallel")
@observe(name="eval/full_pipeline")
async def eval_full_pipeline(
    body: FullPipelineEvalRequest,
    current_user: User = Depends(require_hr),
    db: AsyncSession = Depends(get_db),
):
    _ensure_evals_enabled()
    tasks = {
        "resume_parsing": eval_hub.run(
            operation="resume_parsing",
            user_id=current_user.id,
            resume_text=body.resume_text,
            parsed_output=body.parsed_output,
            jd_text=body.jd_text,
            db=db,
        ),
        "resume_scoring": eval_hub.run(
            operation="resume_scoring",
            user_id=current_user.id,
            resume_text=body.resume_text,
            jd_text=body.jd_text,
            scores=body.scores,
            db=db,
        ),
    }
    if body.generated_jd and body.user_jd_input:
        tasks["jd_generation"] = eval_hub.run(
            operation="jd_generation",
            user_id=current_user.id,
            user_input=body.user_jd_input,
            generated_jd=body.generated_jd,
            db=db,
        )
    try:
        results = dict(zip(tasks.keys(), await asyncio.gather(*tasks.values())))
        return {op: r.to_dict() for op, r in results.items()}
    except Exception as exc:
        logger.exception("Full pipeline eval failed")
        raise HTTPException(status_code=500, detail="An internal error occurred.") from exc


# User-level history

@router.get("/history", summary="User-level eval history")
@observe(name="eval/history_query")
async def get_eval_history(
    operation: str | None = Query(None, description="Filter by operation name"),
    limit:     int = Query(50, ge=1, le=200),
    offset:    int = Query(0, ge=0),
    current_user: User = Depends(require_hr),
    db: AsyncSession = Depends(get_db),
):
    _ensure_evals_enabled()
    """
    Returns the authenticated user's evaluation history, newest first.
    Each row includes scores from both DeepEval and RAGAS.
    """
    try:
        # FIX Finding 27: Eliminate string interpolation SQL hazard. Use parameterized static query.
        params: dict = {"uid": current_user.id, "limit": limit, "offset": offset, "op": operation}
        
        rows = await db.execute(
            text("""
                SELECT id, operation, overall_score, passed,
                       deepeval_json, ragas_json, latency_ms, evaluated_at
                FROM eval_results
                WHERE user_id = :uid AND (:op IS NULL OR operation = :op)
                ORDER BY evaluated_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        records = rows.mappings().all()
        return {
            "user_id":    current_user.id,
            "total":      len(records),
            "limit":      limit,
            "offset":     offset,
            "results": [
                {
                    "id":            r["id"],
                    "operation":     r["operation"],
                    "overall_score": r["overall_score"],
                    "passed":        r["passed"],
                    "latency_ms":    r["latency_ms"],
                    "evaluated_at":  r["evaluated_at"].isoformat() if r["evaluated_at"] else None,
                    "deepeval":      json.loads(r["deepeval_json"]) if r["deepeval_json"] else None,
                    "ragas":         json.loads(r["ragas_json"]) if r["ragas_json"] else None,
                }
                for r in records
            ],
        }
    except Exception as exc:
        logger.exception("eval history query failed")
        raise HTTPException(status_code=500, detail="An internal error occurred.") from exc


@router.get("/history/summary", summary="Per-operation score summary for current user")
@observe(name="eval/summary_query")
async def get_eval_summary(
    current_user: User = Depends(require_hr),
    db: AsyncSession = Depends(get_db),
):
    _ensure_evals_enabled()
    """
    Returns aggregated eval stats per operation for the current user.
    Useful for user-facing dashboards: "Your JD generation quality: 0.74 avg"
    """
    try:
        rows = await db.execute(
            text("""
                SELECT
                    operation,
                    COUNT(*)              AS total_evals,
                    AVG(overall_score)    AS avg_score,
                    MIN(overall_score)    AS min_score,
                    MAX(overall_score)    AS max_score,
                    SUM(CASE WHEN passed THEN 1 ELSE 0 END) AS passed_count
                FROM eval_results
                WHERE user_id = :uid
                GROUP BY operation
                ORDER BY operation
            """),
            {"uid": current_user.id},
        )
        records = rows.mappings().all()
        return {
            "user_id": current_user.id,
            "summary": [
                {
                    "operation":    r["operation"],
                    "total_evals":  r["total_evals"],
                    "avg_score":    round(float(r["avg_score"] or 0), 4),
                    "min_score":    round(float(r["min_score"] or 0), 4),
                    "max_score":    round(float(r["max_score"] or 0), 4),
                    "pass_rate":    round(
                        int(r["passed_count"]) / int(r["total_evals"]), 4
                    ) if r["total_evals"] else 0,
                }
                for r in records
            ],
        }
    except Exception as exc:
        logger.exception("eval summary query failed")
        raise HTTPException(status_code=500, detail="An internal error occurred.") from exc


@router.get("/metrics", summary="List available evaluation metrics by library")
async def list_metrics(current_user: User = Depends(require_hr)):
    _ensure_evals_enabled()
    return {
        "libraries": ["deepeval", "ragas"],
        "resume_parsing": {
            "deepeval": [
                {"name": "Extraction Completeness", "type": "GEval",               "threshold": 0.6},
                {"name": "Field Accuracy",           "type": "GEval",               "threshold": 0.7},
                {"name": "Hallucination",             "type": "HallucinationMetric", "threshold": 0.2},
            ],
            "ragas": [
                {"name": "faithfulness",       "threshold": 0.5},
                {"name": "answer_relevancy",   "threshold": 0.5},
                {"name": "context_precision",  "threshold": 0.5},
            ],
        },
        "resume_scoring": {
            "deepeval": [
                {"name": "Scoring Fairness",      "type": "GEval",    "threshold": 0.65},
                {"name": "Scoring Consistency",   "type": "GEval",    "threshold": 0.60},
                {"name": "Score Range Validity",  "type": "DAGMetric", "threshold": 0.50},
            ],
            "ragas": [
                {"name": "faithfulness",     "threshold": 0.5},
                {"name": "answer_relevancy", "threshold": 0.5},
                {"name": "context_recall",   "threshold": 0.5},
            ],
        },
        "jd_generation": {
            "deepeval": [
                {"name": "Answer Relevancy", "type": "AnswerRelevancyMetric", "threshold": 0.7},
                {"name": "JD Completeness",  "type": "GEval",                 "threshold": 0.7},
                {"name": "JD Clarity",       "type": "GEval",                 "threshold": 0.65},
            ],
            "ragas": "N/A - JD generation is not a RAG operation",
        },
    }


@router.get("/ai-capability-report", summary="Prompt/OCR/model fit report for current HR user")
@observe(name="eval/ai_capability_report")
async def ai_capability_report(
    window_minutes: int = Query(1440, ge=15, le=10080),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _ensure_evals_enabled()
    try:
        return await build_ai_capability_report(
            db=db,
            user_id=str(current_user.id),
            window_minutes=int(window_minutes),
        )
    except Exception as exc:
        logger.exception("ai capability report failed")
        raise HTTPException(status_code=500, detail="An internal error occurred.") from exc


@router.get("/hr-inspector", summary="Unified HR inspector overview (harness + traces + model fit + readiness)")
@observe(name="eval/hr_inspector")
async def hr_inspector_overview(
    window_minutes: int = Query(1440, ge=15, le=10080),
    run_limit: int = Query(20, ge=1, le=100),
    trace_limit: int = Query(8, ge=1, le=25),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _ensure_evals_enabled()
    try:
        return await build_hr_inspector_overview(
            db=db,
            user_id=str(current_user.id),
            window_minutes=int(window_minutes),
            run_limit=int(run_limit),
            trace_limit=int(trace_limit),
        )
    except Exception as exc:
        logger.exception("hr inspector overview failed")
        raise HTTPException(status_code=500, detail="An internal error occurred.") from exc
