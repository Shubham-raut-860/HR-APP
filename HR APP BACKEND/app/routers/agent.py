from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from app.agents.graphs import build_resume_scoring_agents_graph
from app.models import User
from app.services.auth_service import require_hr

router = APIRouter(prefix="/agent", tags=["Agent"])
logger = logging.getLogger(__name__)


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

    return score_result
