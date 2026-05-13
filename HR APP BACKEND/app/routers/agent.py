from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Request
from pydantic import ValidationError

from app.agents.graphs import build_resume_scoring_agents_graph
from app.config import settings
from app.models import User
from app.services.auth_service import require_hr

router = APIRouter(prefix="/agent", tags=["Agent"])
logger = logging.getLogger(__name__)


def _harness_base_url() -> str:
    port = int(getattr(settings, "APP_PORT", 8000) or 8000)
    return f"http://127.0.0.1:{port}/harness"


async def _send_harness_trace_record(
    *,
    request: Request,
    user: User,
    filename: str,
    score_result: dict,
) -> None:
    if not settings.HARNESS_TRACE_RECORDER_ENABLED:
        return

    payload = {
        "source": "agent.score-resume",
        "tenant_id": str(user.id),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "context": {
            "filename": filename,
            "resume_score": score_result.get("resume_score"),
            "tag": score_result.get("tag"),
            "confidence": score_result.get("confidence"),
        },
    }

    headers = {"Content-Type": "application/json"}
    auth_header = request.headers.get("authorization")
    if auth_header:
        headers["Authorization"] = auth_header

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.post(
                f"{_harness_base_url()}/traces",
                json=payload,
                headers=headers,
            )
        if resp.status_code >= 400:
            logger.warning(
                "Harness trace emit failed status=%s body=%s",
                resp.status_code,
                (resp.text or "")[:500],
            )
    except Exception as exc:
        logger.warning("Harness trace emit failed (non-fatal): %s", exc)


@router.post("/score-resume")
async def score_resume_with_agent(
    request: Request,
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

    await _send_harness_trace_record(
        request=request,
        user=user,
        filename=file.filename or "resume.pdf",
        score_result=score_result,
    )

    return score_result
