from __future__ import annotations

import logging
import os
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from app.agents.graphs import build_resume_scoring_agents_graph
from app.config import settings
from app.models import User
from app.services.auth_service import require_hr
from app.services.mlflow_service import mlflow_track_llm

router = APIRouter(prefix="/agent", tags=["Agent"])
logger = logging.getLogger(__name__)


async def _log_agent_score_to_mlflow(
    *,
    user: User,
    filename: str,
    score_result: dict,
) -> None:
    if not settings.HARNESS_TRACE_RECORDER_ENABLED:
        return
    if not (os.environ.get("MLFLOW_TRACKING_URI") or "").strip():
        return

    try:
        async with mlflow_track_llm(
            task_name="agent.score_resume",
            run_name=f"agent.score-resume.{str(user.id)[:8]}",
            tags={
                "component": "agent_router",
                "route": "/agent/score-resume",
            },
        ):
            import mlflow

            mlflow.log_param("filename", filename)
            mlflow.log_metric("resume_score", float(score_result.get("resume_score") or 0.0))
            mlflow.log_param("tag", str(score_result.get("tag") or ""))
            mlflow.log_param("confidence", str(score_result.get("confidence") or ""))
            reasoning = str(score_result.get("reasoning") or "")
            if reasoning:
                mlflow.log_text(reasoning, "agent_score_resume_reasoning.txt")
    except Exception as exc:
        logger.debug("MLflow agent trace non-fatal: %s", exc)


@router.post("/score-resume")
async def score_resume_with_agent(
    file: UploadFile = File(...),
    job_description: str = Form(...),
    user: User = Depends(require_hr),
):
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if not job_description.strip():
        raise HTTPException(status_code=400, detail="job_description is required")

    graph = build_resume_scoring_agents_graph()
    try:
        final_state = await graph.ainvoke(
            {
                "file_bytes": file_bytes,
                "job_description": job_description,
                "filename": file.filename or "resume.pdf",
            }
        )
    except (ValueError, ValidationError) as exc:
        logger.exception("Agent score-resume validation error")
        raise HTTPException(status_code=400, detail="Invalid request data") from exc
    except RuntimeError as exc:
        logger.exception("Agent score-resume domain error")
        raise HTTPException(status_code=422, detail="Unable to process resume for scoring") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Agent score-resume unexpected error")
        raise HTTPException(status_code=500, detail="Failed to score resume") from exc

    score_result = final_state.get("score_result")
    if score_result is None:
        logger.error("Agent score-resume returned no score_result")
        raise HTTPException(status_code=500, detail="Scoring pipeline returned no result")
    if not isinstance(score_result, dict):
        logger.error("Agent score-resume returned invalid score_result type: %s", type(score_result).__name__)
        raise HTTPException(status_code=500, detail="Scoring pipeline returned invalid result format")

    required_keys = ("resume_score",)
    missing_keys = [k for k in required_keys if k not in score_result]
    if missing_keys:
        logger.error("Agent score-resume returned incomplete score_result, missing keys: %s", missing_keys)
        raise HTTPException(status_code=422, detail="Incomplete scoring result")

    await _log_agent_score_to_mlflow(
        user=user,
        filename=file.filename or "resume.pdf",
        score_result=score_result,
    )

    return score_result
