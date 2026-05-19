from __future__ import annotations

import asyncio
import base64
import logging
import os
from importlib import import_module
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import ValidationError

from app.config import settings
from app.models import User
from app.services.auth_service import require_hr
from app.services.mlflow_service import mlflow_track_llm

router = APIRouter(prefix="/agent", tags=["Agent"])
logger = logging.getLogger(__name__)
_SCORE_RESUME_TIMEOUT_S = 105.0


class _LazyModule:
    def __init__(self, module_path: str):
        self._module_path = module_path
        self._module = None

    def _load(self):
        if self._module is None:
            self._module = import_module(self._module_path)
        return self._module

    def __getattr__(self, item):
        return getattr(self._load(), item)


gemini_service = _LazyModule("app.services.gemini_service")
file_service = _LazyModule("app.services.file_service")
resume_fallback_parser = _LazyModule("app.services.resume_fallback_parser")
scoring_service = _LazyModule("app.services.scoring_service")
harness_agent_client = _LazyModule("app.services.harness_agent_client")


def _is_harness_or_timeout_error(exc: Exception) -> bool:
    return isinstance(exc, asyncio.TimeoutError) or exc.__class__.__name__ == "HarnessAgentError"


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


async def _run_jd_parser_with_fallback(
    *,
    job_description: str,
    auth_header: str | None,
) -> dict:
    try:
        result = await harness_agent_client.run_agent(
            "jd_parser",
            {"doc_text": job_description},
            auth_header,
        )
        if isinstance(result, dict) and isinstance(result.get("parsed_job"), dict):
            return result["parsed_job"]
        return result if isinstance(result, dict) else {}
    except Exception as exc:
        if not _is_harness_or_timeout_error(exc):
            raise
        logger.warning("Harness fallback jd_parser failed, using direct parser: %s", exc)
        return await gemini_service.parse_jd_from_document(job_description)


async def _run_resume_pipeline_with_fallback(
    *,
    file_name: str,
    file_bytes: bytes,
    parsed_job: dict,
    auth_header: str | None,
) -> dict:
    try:
        return await harness_agent_client.run_agent(
            "resume_pipeline",
            {
                "filename": file_name,
                "file_bytes_b64": base64.b64encode(file_bytes).decode("utf-8"),
                "parsed_job": parsed_job,
            },
            auth_header,
            timeout_s=120.0,
        )
    except Exception as exc:
        if not _is_harness_or_timeout_error(exc):
            raise
        logger.warning("Harness fallback resume_pipeline failed, using direct scorer: %s", exc)
        extracted_text = await file_service.extract_text_from_bytes(file_name, file_bytes)
        parsed_resume = await gemini_service.parse_resume(extracted_text)
        score_result = await gemini_service.score_resume_against_jd(
            parsed_resume=parsed_resume,
            job_title=str(parsed_job.get("role") or parsed_job.get("title") or "Role"),
            exp_min=int(parsed_job.get("experience_min") or 0),
            exp_max=int(parsed_job.get("experience_max") or 5),
            must_have=list(parsed_job.get("must_have_skills") or []),
            good_to_have=list(parsed_job.get("good_to_have_skills") or []),
            description=str(parsed_job.get("description") or ""),
        )
        return {"score_result": score_result}


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

    auth_header = request.headers.get("authorization")
    file_name = file.filename or "resume.pdf"

    if settings.DATABASE_URL.startswith("sqlite"):
        text = await file_service.extract_text_from_bytes(file_name, file_bytes)
        parsed_resume = resume_fallback_parser.coerce_parsed_resume(None, text=text)
        skills = parsed_resume.get("normalized_skills") or []
        exp_years = float(parsed_resume.get("experience_years") or 0.0)
        # Deterministic local fallback score for sqlite runtime stability.
        resume_score = min(100.0, max(0.0, 35.0 + (len(skills) * 4.0) + (exp_years * 6.0)))
        return {
            "resume_score": round(resume_score, 2),
            "tag": scoring_service.assign_tag(resume_score).value,
            "confidence": "medium",
            "reasoning": "Scored via sqlite-safe deterministic fallback path.",
            "matched_must_have": [],
            "missing_must_have": [],
            "matched_good_to_have": [],
            "missing_good_to_have": [],
        }

    try:
        async def _run_scoring_workflow() -> dict:
            parsed_job = await _run_jd_parser_with_fallback(
                job_description=job_description,
                auth_header=auth_header,
            )
            return await _run_resume_pipeline_with_fallback(
                file_name=file_name,
                file_bytes=file_bytes,
                parsed_job=parsed_job,
                auth_header=auth_header,
            )

        pipeline_result = await asyncio.wait_for(
            _run_scoring_workflow(),
            timeout=_SCORE_RESUME_TIMEOUT_S,
        )
    except asyncio.TimeoutError as exc:
        logger.warning("Agent score-resume timed out for %s", file_name)
        raise HTTPException(
            status_code=503,
            detail="Resume scoring timed out. Please retry.",
        ) from exc
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

    score_result = pipeline_result.get("score_result") if isinstance(pipeline_result, dict) else None
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
        filename=file_name,
        score_result=score_result,
    )

    return score_result
