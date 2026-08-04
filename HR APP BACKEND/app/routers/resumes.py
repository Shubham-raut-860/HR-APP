"""
Resumes router  upload, bulk-upload, pool management, candidate CRUD.
"""

from app.schemas import (
    CandidateOut, CandidateListOut, CandidatePipelineListOut, PoolMatchOut,
    MessageResponse, CandidateKycDocumentOut, CandidateHireApprovalUpdate, CandidateHireApprovalOut,
    CandidateKycInviteCreate, CandidateKycInviteOut, CandidateKycRecruiterStatusOut,
    AuditLogOut,
)
from app.config import settings
from app.services.mlflow_service import push_eval_to_mlflow as push_eval_to_langfuse  # MLflow replacement
from app.services.mlflow_service import mlflow_track_llm
from app.services.notification_service import push_notification, push_to_candidate_by_email
from app.services.langfuse_service import observe, langfuse_context
from app.services.auth_service import require_hr, log_action
from app.services.candidate_access_service import assert_bulk_candidate_access
from app.routers.resume_pool import ImportFromPoolRequest, import_from_pool_impl
from app.constants.scoring import (
    DEFAULT_SHORTLIST_THRESHOLD,
    MEDIUM_THRESHOLD,
    MAX_RESUME_EXPERIENCE_YEARS,
    SCORING_PASS_THRESHOLD,
    STRONG_SHORTLIST_THRESHOLD,
)
from app.constants.rate_limits import (
    AI_SCORING_RANKING_RATE_LIMIT,
    BULK_UPLOAD_RATE_LIMIT,
    SINGLE_FILE_UPLOAD_RATE_LIMIT,
)
from app.limiter import limiter
from app.models import (
    User, Candidate, JobDescription, NotificationType, UserRole,
    CandidateTag, AuditLog, BulkUploadJob, QuizAttempt, QuizStatus
)
from app.database import get_db, AsyncSessionLocal
from app.kyc_database import get_kyc_db
from app.kyc_models import (
    CandidateDocumentType,
    CandidateHireApproval,
    CandidateKycInvite,
    CandidateKycConsent,
    CandidateKycDocument,
    CandidateKycRetentionSchedule,
)
from pydantic import BaseModel
from typing import List, Literal, Optional
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload, load_only
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Request, Response, Header
import asyncio
import hashlib
import html
import json
import io
import logging
import math
import os
import re
import secrets
import tempfile
import time
from importlib import import_module
from datetime import datetime, timedelta, timezone
from uuid import uuid4

logger = logging.getLogger(__name__)

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
scoring_service = _LazyModule("app.services.scoring_service")
encryption_service = _LazyModule("app.services.encryption_service")
resume_fallback_parser = _LazyModule("app.services.resume_fallback_parser")
harness_agent_client = _LazyModule("app.services.harness_agent_client")


router = APIRouter(prefix="/resumes", tags=["Resumes"])
_KYC_DOC_TYPES: tuple[str, ...] = (
    "aadhaar",
    "pan",
    "employment_proof",
    "passport",
    "driving_license",
    "salary_slip",
    "offer_letter",
)
_KYC_MANDATORY_DOC_TYPES: tuple[str, ...] = ("aadhaar", "pan", "employment_proof")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _kyc_invite_token_hash(raw_token: str) -> str:
    return hashlib.sha256((raw_token or "").strip().encode("utf-8")).hexdigest()


def _build_candidate_kyc_magic_link(raw_token: str) -> str:
    base = (settings.FRONTEND_URL or "").strip().rstrip("/")
    if not base:
        base = "http://localhost:5173"
    return f"{base}/candidate/kyc-upload?token={raw_token}"

# Pipeline list endpoint intentionally omits heavy JSON/blob fields to keep
# recruiter list payloads small.
_CANDIDATE_LIST_LOAD_ONLY = (
    Candidate.id,
    Candidate.job_id,
    Candidate.user_id,
    Candidate.name,
    Candidate.email,
    Candidate.phone,
    Candidate.location,
    Candidate.normalized_skills,
    Candidate.experience_years,
    Candidate.skill_match_pct,
    Candidate.experience_match_pct,
    Candidate.resume_score,
    Candidate.tag,
    Candidate.quiz_score,
    Candidate.quiz_max,
    Candidate.quiz_pct,
    Candidate.final_score,
    Candidate.rank,
    Candidate.created_at,
    Candidate.is_archived,
)

# Master archive endpoint keeps richer fields used by export/archive workflows.
_CANDIDATE_ALL_DATA_LOAD_ONLY = (
    Candidate.id,
    Candidate.job_id,
    Candidate.user_id,
    Candidate.name,
    Candidate.email,
    Candidate.phone,
    Candidate.location,
    Candidate.skills,
    Candidate.normalized_skills,
    Candidate.experience_years,
    Candidate.education,
    Candidate.projects,
    Candidate.skill_match_pct,
    Candidate.experience_match_pct,
    Candidate.project_relevance_pct,
    Candidate.education_match_pct,
    Candidate.location_match_pct,
    Candidate.vector_similarity,
    Candidate.resume_score,
    Candidate.score_breakdown,
    Candidate.career_breaks,
    Candidate.tag,
    Candidate.quiz_score,
    Candidate.quiz_max,
    Candidate.quiz_pct,
    Candidate.final_score,
    Candidate.rank,
    Candidate.passed,
    Candidate.created_at,
    Candidate.is_archived,
)


_EMAIL_RE = re.compile(r"([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[A-Za-z]{2,})")
_PHONE_RE = re.compile(r"(\+\d[\d\s().-]{8,}\d)")
_EXP_RE = re.compile(r"(\d{1,2}(:\.\d+))\s*\+\s*(:years|yrs)", re.IGNORECASE)
_RUNTIME_RANK_ID_RE = re.compile(r"\[cid:([0-9a-fA-F-]{36})\]")
_BULK_JOB_STATUS: dict[str, dict] = {}
_BULK_STATUS_PRUNE_HANDLES: dict[str, asyncio.TimerHandle] = {}
_BULK_STATUS_TTL_SECONDS = 3600
_BULK_TERMINAL_STATUSES = {"completed", "failed"}
_BULK_ASYNC_JOB_SEMAPHORE = asyncio.Semaphore(max(1, int(settings.BULK_ASYNC_MAX_CONCURRENT_JOBS)))
_SHORTLIST_LOCKS: dict[str, asyncio.Lock] = {}
try:
    _ai_limit_raw = getattr(settings, "AI_CONCURRENT_REQUEST_LIMIT", 10)
    _ai_limit = int(_ai_limit_raw) if _ai_limit_raw is not None else 10
except (TypeError, ValueError):
    _ai_limit = 10
_AI_SEMAPHORE = asyncio.Semaphore(max(1, _ai_limit))
_gemini = gemini_service
_HARNESS_FALLBACK_LOG_LOCK = asyncio.Lock()
_HARNESS_FALLBACK_LOG_UNTIL: dict[str, float] = {}


def _is_harness_or_timeout_error(exc: Exception) -> bool:
    return isinstance(exc, asyncio.TimeoutError) or exc.__class__.__name__ == "HarnessAgentError"


def _is_harness_unavailable_error(exc: Exception) -> bool:
    return exc.__class__.__name__ == "HarnessAgentError" and str(getattr(exc, "status", "")) == "harness_unavailable"


def _ai_degraded_mode_active() -> bool:
    return bool(settings.AI_FAIL_FAST_ON_UNAVAILABLE and not gemini_service.is_realtime_ai_available())


async def _should_log_harness_fallback(agent_type: str, window_s: float = 10.0) -> bool:
    now = time.monotonic()
    async with _HARNESS_FALLBACK_LOG_LOCK:
        until = float(_HARNESS_FALLBACK_LOG_UNTIL.get(agent_type) or 0.0)
        if now >= until:
            _HARNESS_FALLBACK_LOG_UNTIL[agent_type] = now + max(2.0, float(window_s))
            return True
        return False


async def _run_resume_parser_with_fallback(
    *,
    text: str,
    auth_header: str | None = None,
) -> dict:
    parser_timeout_s = min(30.0, max(15.0, float(settings.AI_REQUEST_TIMEOUT_SECONDS) * 2.0))
    try:
        result = await asyncio.wait_for(
            harness_agent_client.run_agent(
                "resume_parser",
                {"text": text},
                auth_header,
                timeout_s=parser_timeout_s,
            ),
            timeout=parser_timeout_s,
        )
        if isinstance(result, dict) and isinstance(result.get("parsed_resume"), dict):
            return result["parsed_resume"]
        return result if isinstance(result, dict) else {}
    except Exception as runtime_exc:
        if not _is_harness_or_timeout_error(runtime_exc):
            raise
        if _is_harness_unavailable_error(runtime_exc):
            if await _should_log_harness_fallback("resume_parser"):
                logger.warning("Harness unavailable for resume_parser; using direct parser fallback: %s", runtime_exc)
            else:
                logger.debug("Harness unavailable for resume_parser; using direct parser fallback: %s", runtime_exc)
        else:
            logger.warning("Harness fallback resume_parser failed, using direct parser: %s", runtime_exc)
        return await asyncio.wait_for(_gemini.parse_resume(text), timeout=parser_timeout_s)


async def _run_embedding_with_fallback(
    *,
    text: str,
    auth_header: str | None = None,
) -> list:
    embedding_timeout_s = min(30.0, max(12.0, float(settings.AI_REQUEST_TIMEOUT_SECONDS) * 1.75))
    try:
        result = await asyncio.wait_for(
            harness_agent_client.run_agent(
                "embedding",
                {"text": text},
                auth_header,
                timeout_s=embedding_timeout_s,
            ),
            timeout=embedding_timeout_s,
        )
        if isinstance(result, dict):
            emb = result.get("embedding")
            if isinstance(emb, list):
                return emb
        return result if isinstance(result, list) else []
    except Exception as runtime_exc:
        if not _is_harness_or_timeout_error(runtime_exc):
            raise
        if _is_harness_unavailable_error(runtime_exc):
            if await _should_log_harness_fallback("embedding"):
                logger.warning("Harness unavailable for embedding; using direct embedding fallback: %s", runtime_exc)
            else:
                logger.debug("Harness unavailable for embedding; using direct embedding fallback: %s", runtime_exc)
        else:
            logger.warning("Harness fallback embedding failed, using direct embedding: %s", runtime_exc)
        return await asyncio.wait_for(_gemini.get_embedding(text), timeout=embedding_timeout_s)


async def _run_resume_scorer_with_fallback(
    *,
    parsed_resume: dict,
    job_title: str,
    exp_min: int,
    exp_max: int,
    must_have: list[str],
    good_to_have: list[str],
    description: str,
    auth_header: str | None = None,
) -> dict:
    scorer_timeout_s = min(30.0, max(15.0, float(settings.AI_REQUEST_TIMEOUT_SECONDS) * 2.0))
    try:
        result = await asyncio.wait_for(
            harness_agent_client.run_agent(
                "resume_scorer",
                {
                    "parsed_resume": parsed_resume,
                    "job_title": job_title,
                    "exp_min": exp_min,
                    "exp_max": exp_max,
                    "must_have": must_have,
                    "good_to_have": good_to_have,
                    "description": description,
                },
                auth_header,
                timeout_s=scorer_timeout_s,
            ),
            timeout=scorer_timeout_s,
        )
        if isinstance(result, dict) and isinstance(result.get("score_result"), dict):
            return result["score_result"]
        return result if isinstance(result, dict) else {}
    except Exception as runtime_exc:
        if not _is_harness_or_timeout_error(runtime_exc):
            raise
        if _is_harness_unavailable_error(runtime_exc):
            if await _should_log_harness_fallback("resume_scorer"):
                logger.warning("Harness unavailable for resume_scorer; using direct scorer fallback: %s", runtime_exc)
            else:
                logger.debug("Harness unavailable for resume_scorer; using direct scorer fallback: %s", runtime_exc)
        else:
            logger.warning("Harness fallback resume_scorer failed, using direct scorer: %s", runtime_exc)
        return await asyncio.wait_for(
            _gemini.score_resume_against_jd(
                parsed_resume=parsed_resume,
                job_title=job_title,
                exp_min=exp_min,
                exp_max=exp_max,
                must_have=must_have,
                good_to_have=good_to_have,
                description=description,
            ),
            timeout=scorer_timeout_s,
        )


async def _run_hr_email_draft_with_fallback(
    *,
    email_type: str,
    candidate_name: str,
    job_title: str,
    resume_score: float,
    quiz_score: float,
    auth_header: str | None = None,
) -> dict:
    try:
        result = await harness_agent_client.run_agent(
            "hr_email_draft",
            {
                "email_type": email_type,
                "candidate_name": candidate_name,
                "job_title": job_title,
                "resume_score": resume_score,
                "quiz_score": quiz_score,
            },
            auth_header,
        )
        if isinstance(result, dict) and isinstance(result.get("draft"), dict):
            return result["draft"]
        return result if isinstance(result, dict) else {}
    except Exception as runtime_exc:
        if not _is_harness_or_timeout_error(runtime_exc):
            raise
        logger.warning("Harness fallback hr_email_draft failed, using direct draft: %s", runtime_exc)
        return await gemini_service.generate_hr_email(
            email_type=email_type,
            candidate_name=candidate_name,
            job_title=job_title,
            resume_score=resume_score,
            quiz_score=quiz_score,
        )


def _job_has_meaningful_criteria(job: JobDescription) -> bool:
    has_skills = bool(job.must_have_skills or job.good_to_have_skills)
    desc = (job.description or "").strip()
    desc_alnum = re.sub(r"[^a-zA-Z0-9]+", "", desc)
    has_meaningful_desc = len(desc_alnum) >= 20 and any(ch.isalpha() for ch in desc)
    edu_req = str(getattr(job, "education_requirement", "") or "").strip().lower()
    has_edu_req = edu_req not in {"", "none", "null"}
    return has_skills or has_meaningful_desc or has_edu_req


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_bulk_job_status(run_id: str, **fields) -> None:
    current = _BULK_JOB_STATUS.get(run_id, {})
    merged = {**current, **fields}
    merged["updated_at"] = _now_iso()
    _BULK_JOB_STATUS[run_id] = merged
    _schedule_bulk_status_prune(run_id, merged)


def _parse_bulk_status_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_terminal_bulk_status(status: dict) -> bool:
    return str(status.get("status") or "").lower() in _BULK_TERMINAL_STATUSES


def _bulk_status_age_seconds(status: dict) -> float | None:
    terminal_at = _parse_bulk_status_time(status.get("completed_at") or status.get("updated_at"))
    if terminal_at is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - terminal_at).total_seconds())


def _prune_bulk_status_if_expired(run_id: str) -> None:
    status = _BULK_JOB_STATUS.get(run_id)
    if not status:
        _BULK_STATUS_PRUNE_HANDLES.pop(run_id, None)
        return

    age_s = _bulk_status_age_seconds(status)
    if _is_terminal_bulk_status(status) and age_s is not None and age_s >= _BULK_STATUS_TTL_SECONDS:
        _BULK_JOB_STATUS.pop(run_id, None)

    _BULK_STATUS_PRUNE_HANDLES.pop(run_id, None)


def _schedule_bulk_status_prune(run_id: str, status: dict) -> None:
    """Schedule in-memory bulk status cleanup once a terminal entry reaches TTL."""
    if run_id not in _BULK_JOB_STATUS:
        return
    if not _is_terminal_bulk_status(status):
        handle = _BULK_STATUS_PRUNE_HANDLES.pop(run_id, None)
        if handle and not handle.cancelled():
            handle.cancel()
        return

    age_s = _bulk_status_age_seconds(status)
    if age_s is not None and age_s >= _BULK_STATUS_TTL_SECONDS:
        _BULK_JOB_STATUS.pop(run_id, None)
        handle = _BULK_STATUS_PRUNE_HANDLES.pop(run_id, None)
        if handle and not handle.cancelled():
            handle.cancel()
        return

    delay = _BULK_STATUS_TTL_SECONDS if age_s is None else max(0.0, _BULK_STATUS_TTL_SECONDS - age_s)
    existing = _BULK_STATUS_PRUNE_HANDLES.get(run_id)
    if existing and not existing.cancelled():
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _BULK_STATUS_PRUNE_HANDLES[run_id] = loop.call_later(delay, _prune_bulk_status_if_expired, run_id)


async def _persist_bulk_job_status(run_id: str) -> None:
    """
    Persist async bulk-job status in DB so state survives process restarts and
    can be polled from any app instance.
    """
    snapshot = _BULK_JOB_STATUS.get(run_id)
    if not snapshot:
        return
    async with AsyncSessionLocal() as s:
        progress = snapshot.get("progress") if isinstance(snapshot.get("progress"), dict) else {}
        total = int(progress.get("total") or snapshot.get("requested_count") or 0)
        processed = int(progress.get("processed") or 0)
        failed = int(progress.get("failed_count") or snapshot.get("rejected_count") or 0)
        last_committed_batch = int(snapshot.get("last_committed_batch") or 0)
        error_summary = {
            "error": snapshot.get("error"),
            "failed_count": failed,
            "duplicate_count": int(progress.get("duplicate_count") or 0),
        }
        bulk_row = await s.get(BulkUploadJob, run_id)
        if bulk_row:
            bulk_row.status = str(snapshot.get("status") or bulk_row.status or "queued")
            bulk_row.job_id = snapshot.get("job_id")
            bulk_row.created_by = snapshot.get("owner_user_id")
            bulk_row.total = total
            bulk_row.processed = processed
            bulk_row.failed = failed
            bulk_row.last_committed_batch = last_committed_batch
            bulk_row.error_summary = error_summary
            bulk_row.details = dict(snapshot)
        else:
            s.add(
                BulkUploadJob(
                    id=run_id,
                    status=str(snapshot.get("status") or "queued"),
                    created_by=snapshot.get("owner_user_id"),
                    job_id=snapshot.get("job_id"),
                    total=total,
                    processed=processed,
                    failed=failed,
                    last_committed_batch=last_committed_batch,
                    error_summary=error_summary,
                    details=dict(snapshot),
                )
            )

        row = (await s.execute(
            select(AuditLog).where(
                AuditLog.action == "BULK_UPLOAD_ASYNC",
                AuditLog.resource == "bulk_upload",
                AuditLog.resource_id == run_id,
            )
        )).scalar_one_or_none()
        if row:
            row.details = dict(snapshot)
        else:
            s.add(AuditLog(
                user_id=snapshot.get("owner_user_id"),
                action="BULK_UPLOAD_ASYNC",
                resource="bulk_upload",
                resource_id=run_id,
                details=dict(snapshot),
            ))
        await s.commit()


async def _load_bulk_job_status(run_id: str, db: AsyncSession) -> dict | None:
    bulk_row = await db.get(BulkUploadJob, run_id)
    if bulk_row is not None:
        if isinstance(bulk_row.details, dict):
            _BULK_JOB_STATUS[run_id] = dict(bulk_row.details)
            return _BULK_JOB_STATUS[run_id]
        payload = {
            "id": bulk_row.id,
            "status": bulk_row.status,
            "job_id": bulk_row.job_id,
            "owner_user_id": bulk_row.created_by,
            "progress": {
                "processed": bulk_row.processed,
                "total": bulk_row.total,
                "failed_count": bulk_row.failed,
            },
            "last_committed_batch": bulk_row.last_committed_batch,
            "error": (bulk_row.error_summary or {}).get("error"),
            "updated_at": bulk_row.updated_at.isoformat() if bulk_row.updated_at else None,
            "created_at": bulk_row.created_at.isoformat() if bulk_row.created_at else None,
        }
        _BULK_JOB_STATUS[run_id] = payload
        return payload

    row = (await db.execute(
        select(AuditLog).where(
            AuditLog.action == "BULK_UPLOAD_ASYNC",
            AuditLog.resource == "bulk_upload",
            AuditLog.resource_id == run_id,
        )
    )).scalar_one_or_none()
    if row and isinstance(row.details, dict):
        _BULK_JOB_STATUS[run_id] = dict(row.details)
        return _BULK_JOB_STATUS[run_id]
    in_mem = _BULK_JOB_STATUS.get(run_id)
    if in_mem:
        try:
            await _persist_bulk_job_status(run_id)
        except Exception as exc:
            logger.debug("Best-effort bulk status persistence failed for %s: %s", run_id, exc)
    return in_mem


async def recover_stale_bulk_upload_jobs(grace_minutes: int = 15) -> int:
    """
    Mark queued/running bulk jobs as failed after restart when they are stale.
    This prevents permanent "running" states after process rotation/crash.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(1, int(grace_minutes)))
    recovered = 0

    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                select(BulkUploadJob).where(
                    BulkUploadJob.status.in_(["queued", "running"]),
                    BulkUploadJob.updated_at < cutoff,
                )
            )
        ).scalars().all()
        if not rows:
            return 0

        for row in rows:
            details = dict(row.details or {})
            details["status"] = "failed"
            details["completed_at"] = _now_iso()
            details["error"] = "recovered_from_restart"
            details["updated_at"] = _now_iso()

            progress = details.get("progress") if isinstance(details.get("progress"), dict) else {}
            progress["failed_count"] = max(
                int(progress.get("failed_count") or 0),
                int(row.failed or 0),
            )
            details["progress"] = progress

            temp_paths = details.get("temp_paths")
            if isinstance(temp_paths, list):
                for path in temp_paths:
                    try:
                        os.unlink(str(path))
                    except FileNotFoundError:
                        continue
                    except Exception as exc:
                        logger.warning("Failed to cleanup stale temp file %s: %s", path, exc)

            row.status = "failed"
            row.failed = int(progress.get("failed_count") or row.failed or 0)
            row.error_summary = {
                "error": "recovered_from_restart",
                "failed_count": row.failed,
            }
            row.details = details
            _BULK_JOB_STATUS[row.id] = details
            recovered += 1

        await s.commit()

    if recovered:
        logger.warning("Recovered %d stale bulk upload jobs after restart.", recovered)
    return recovered


def _normalize_skill_token(skill: str) -> str:
    return re.sub(r"\s+", " ", (skill or "").strip().lower())


def _jd_signature_hash(job: JobDescription) -> str:
    """
    Stable hash of scoring-relevant JD fields used for cache provenance.
    """
    import json as _json

    payload = _json.dumps(
        {
            "title": job.title or "",
            "role": job.role or "",
            "description": job.description or "",
            "location": job.location or "",
            "employment_type": job.employment_type or "",
            "education_requirement": job.education_requirement or "",
            "salary_range": job.salary_range or "",
            "must": sorted(job.must_have_skills or []),
            "good": sorted(job.good_to_have_skills or []),
            "exp_min": job.experience_min,
            "exp_max": job.experience_max,
            "resume_weight": job.resume_weight,
            "quiz_weight": job.quiz_weight,
            "pass_threshold": job.pass_threshold,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _fast_parse_resume_text(text: str, job: JobDescription | None = None) -> dict:
    """
    Fast, regex-based parser used for BULK_FAST_MODE.
    This avoids per-resume LLM parse calls and is intended for near-instant
    recruiter feedback while still producing usable shortlist signals.
    """
    jd_skills = []
    if job is not None:
        jd_skills = list(job.must_have_skills or []) + list(job.good_to_have_skills or [])
    return resume_fallback_parser.fast_parse_resume_text(text, jd_skills=jd_skills)


def _coerce_parsed_resume_payload(
    parsed: dict | None,
    text: str,
    job: JobDescription | None,
) -> dict:
    jd_skills = []
    if job is not None:
        jd_skills = list(job.must_have_skills or []) + list(job.good_to_have_skills or [])
    return resume_fallback_parser.coerce_parsed_resume(parsed, text=text, jd_skills=jd_skills)


def _job_candidate_score(c: Candidate) -> float:
    return float(c.final_score if c.final_score is not None else (c.resume_score or 0.0))


def _quantile_from_sorted(values_asc: list[float], q: float) -> float:
    if not values_asc:
        return 0.0
    if len(values_asc) == 1:
        return float(values_asc[0])
    q = min(1.0, max(0.0, q))
    idx = int(math.ceil(q * (len(values_asc) - 1)))
    return float(values_asc[idx])


def _extract_runtime_rank_candidate_id(candidate_name: str | None) -> str | None:
    if not candidate_name:
        return None
    match = _RUNTIME_RANK_ID_RE.search(str(candidate_name))
    if not match:
        return None
    return match.group(1)


def _build_runtime_rank_payload(
    *,
    job: JobDescription,
    candidates: list[Candidate],
) -> tuple[dict[str, object], list[dict[str, object]], dict[str, Candidate]]:
    jd_payload: dict[str, object] = {
        "title": job.title or job.role or "Job",
        "required_skills": list(job.must_have_skills or []),
        "experience_min": float(job.experience_min or 0),
        "experience_max": float(job.experience_max or 0),
        "description": job.description or "",
    }

    ranked_candidates_payload: list[dict[str, object]] = []
    id_to_candidate: dict[str, Candidate] = {}
    for candidate in candidates:
        candidate_id = str(candidate.id)
        display_name = str(candidate.name or "Candidate").strip() or "Candidate"
        payload_name = f"{display_name} [cid:{candidate_id}]"
        skills = candidate.normalized_skills or candidate.skills or []
        summary = (candidate.raw_resume_text or "").strip()
        ranked_candidates_payload.append(
            {
                "name": payload_name,
                "skills": [str(skill) for skill in skills if skill],
                "experience_years": float(candidate.experience_years or 0.0),
                "resume_score": float(candidate.resume_score or 0.0),
                "final_score": float(candidate.final_score) if candidate.final_score is not None else None,
                "summary": summary[:1200],
            }
        )
        id_to_candidate[candidate_id] = candidate
    return jd_payload, ranked_candidates_payload, id_to_candidate


async def _recompute_job_rank_and_tags(
    db: AsyncSession,
    job: JobDescription,
    *,
    strong_threshold: float | None = None,
    medium_threshold: float | None = None,
    auth_header: str | None = None,
) -> None:
    """
    Re-rank and re-tag candidates for a job with cohort-relative thresholds.
    This keeps shortlist quality stable and prevents universal "Strong" inflation.
    """
    candidates = (await db.execute(
        select(Candidate).where(
            Candidate.job_id == job.id,
            Candidate.is_archived == False,
        )
    )).scalars().all()
    if not candidates:
        return

    candidates_sorted = sorted(candidates, key=_job_candidate_score, reverse=True)
    ranking_source = "score_fallback"
    runtime_error: str | None = None

    try:
        jd_payload, candidate_payload, id_to_candidate = _build_runtime_rank_payload(
            job=job,
            candidates=candidates,
        )
        ranking_result = await harness_agent_client.run_agent(
            "candidate_ranker",
            {
                "jd": jd_payload,
                "candidates": candidate_payload,
                "use_lyzr": True,
            },
            auth_header,
        )
        if isinstance(ranking_result, dict) and isinstance(ranking_result.get("ranking_result"), dict):
            ranking_result = ranking_result["ranking_result"]
        ranked_rows = ranking_result.get("results")
        if isinstance(ranked_rows, list) and ranked_rows:
            ordered_runtime: list[Candidate] = []
            seen_ids: set[str] = set()
            for row in ranked_rows:
                if not isinstance(row, dict):
                    continue
                candidate_id = _extract_runtime_rank_candidate_id(row.get("candidate_name"))
                if not candidate_id or candidate_id in seen_ids:
                    continue
                matched_candidate = id_to_candidate.get(candidate_id)
                if matched_candidate is None:
                    continue
                ordered_runtime.append(matched_candidate)
                seen_ids.add(candidate_id)

            if ordered_runtime:
                for fallback_candidate in candidates_sorted:
                    fallback_id = str(fallback_candidate.id)
                    if fallback_id not in seen_ids:
                        ordered_runtime.append(fallback_candidate)
                candidates_sorted = ordered_runtime
                ranking_source = str(ranking_result.get("source") or "harness")
    except Exception as runtime_exc:
        if not _is_harness_or_timeout_error(runtime_exc):
            raise
        runtime_error = str(runtime_exc)
        logger.warning(
            "Harness ranking failed for job %s, using score fallback: %s",
            job.id,
            runtime_exc,
        )
    except Exception as exc:
        runtime_error = str(exc)
        logger.warning(
            "Unexpected runtime ranking failure for job %s, using score fallback: %s",
            job.id,
            exc,
        )

    scores_desc = [_job_candidate_score(c) for c in candidates_sorted]
    scores_asc = sorted(scores_desc)

    use_forced_thresholds = strong_threshold is not None and medium_threshold is not None
    if use_forced_thresholds:
        strong_t = float(strong_threshold)
        medium_t = float(medium_threshold)
        use_dynamic = False
    else:
        use_dynamic = settings.DYNAMIC_TAGGING_ENABLED and len(candidates_sorted) >= int(settings.DYNAMIC_TAG_MIN_COHORT)
        if use_dynamic:
            strong_t = max(
                float(settings.DYNAMIC_STRONG_FLOOR),
                _quantile_from_sorted(scores_asc, float(settings.DYNAMIC_STRONG_PERCENTILE)),
            )
            medium_t = max(
                float(settings.DYNAMIC_MEDIUM_FLOOR),
                _quantile_from_sorted(scores_asc, float(settings.DYNAMIC_MEDIUM_PERCENTILE)),
            )
            if medium_t >= strong_t:
                medium_t = max(float(settings.DYNAMIC_MEDIUM_FLOOR), strong_t - 0.1)
        else:
            strong_t = STRONG_SHORTLIST_THRESHOLD
            medium_t = SCORING_PASS_THRESHOLD

    n = len(candidates_sorted)
    for idx, c in enumerate(candidates_sorted):
        score = scores_desc[idx]
        c.rank = idx + 1
        c.tag = scoring_service.assign_tag(score, strong=strong_t, medium=medium_t)
        if c.final_score is not None:
            c.passed = bool(c.final_score >= float(job.pass_threshold))

        breakdown = dict(c.score_breakdown or {})
        breakdown["ranking"] = {
            "rank": c.rank,
            "cohort_size": n,
            "score": round(score, 2),
            "percentile": round((1 - (idx / max(1, n - 1))) * 100, 2) if n > 1 else 100.0,
            "strong_threshold": round(strong_t, 2),
            "medium_threshold": round(medium_t, 2),
            "dynamic_thresholds": use_dynamic,
            "ranking_source": ranking_source,
            "runtime_method": "harness_agent_client.run_agent(candidate_ranker)",
        }
        if runtime_error:
            breakdown["ranking"]["ranking_runtime_error"] = runtime_error
        c.score_breakdown = breakdown


def _log_worker_error(message: str, filename: str, err: Exception) -> None:
    """
    Log async worker failures without spurious "NoneType: None" trace lines.
    `asyncio.gather(..., return_exceptions=True)` returns Exception objects
    outside an active `except` block, so `exc_info=True` is incorrect there.
    """
    if isinstance(err, HTTPException):
        logger.error(message, filename, err)
        return
    logger.error(message, filename, err, exc_info=(type(err), err, err.__traceback__))


def _maybe_decrypt_bulk_upload_content(filename: str, ext: str, content: bytes) -> bytes:
    """
    Early handling for accidentally uploaded encrypted internal artifacts.
    Mirrors file_service behavior so we fail fast during read batching, before
    expensive text extraction and scoring.
    """
    if ext == ".txt" or len(content) < 32 or not encryption_service.looks_like_internal_ciphertext(content):
        return content

    decrypted = encryption_service.try_decrypt_file(content)
    if decrypted is not None:
        logger.warning(
            "Detected encrypted upload artifact for %s during bulk read; auto-decrypted before parsing.",
            filename,
        )
        return decrypted

    raise HTTPException(
        status_code=422,
        detail=(
            "Uploaded file appears to be an encrypted internal storage copy "
            "(from uploads/resumes), not an original resume document. "
            "Please upload the original source file."
        ),
    )

#  Pydantic models 


class EmailDraftRequest(BaseModel):
    email_type: str


class EmailSendRequest(BaseModel):
    subject: str
    body: str
    interview_at: Optional[datetime] = None
    meeting_link: Optional[str] = None
    interview_note: Optional[str] = None


class BulkDeleteRequest(BaseModel):
    candidate_ids: list[str]


class CandidateUpdate(BaseModel):
    # Accept both legacy lowercase and canonical title-case values.
    tag: Optional[Literal["Strong", "Medium", "Reject", "strong", "medium", "reject"]] = None

#  Helpers 


def _sha256(content: bytes) -> str:
    """Compute SHA-256 hex digest of file bytes. Used for duplicate detection."""
    return hashlib.sha256(content).hexdigest()


def _precheck_content_length(headers_obj, max_bytes: int) -> None:
    """
    Fast-path size rejection before buffering whole payload into memory.
    Uses per-part content-length when available.
    """
    if not headers_obj:
        return
    raw_len = None
    try:
        raw_len = headers_obj.get("content-length")
    except Exception:
        raw_len = None
    if not raw_len:
        return
    try:
        hinted = int(raw_len)
    except (TypeError, ValueError):
        return
    if hinted > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {settings.MAX_FILE_SIZE_MB}MB)",
        )


def _normalize_candidate_tag(tag: str | None) -> str | None:
    if tag is None:
        return None
    mapping = {
        "strong": "Strong",
        "medium": "Medium",
        "reject": "Reject",
    }
    return mapping.get(tag.strip().lower(), tag)


async def _existing_hashes(
    db: AsyncSession,
    hashes: list[str],
    *,
    owner_user_id: str | None = None,
) -> set[str]:
    """
    Return the subset of hashes that already exist in the candidate POOL
    (job_id IS NULL). Scoped to pool so that uploading the same resume to
    a different job is not incorrectly blocked.

    BUG 5 FIX: the original version had no job_id filter, so a resume
    previously uploaded to Job A would be rejected when added to the pool.
    """
    if not hashes:
        return set()
    filters = [
        Candidate.file_hash.in_(hashes),
        Candidate.job_id.is_(None),
    ]
    if owner_user_id:
        filters.append(Candidate.user_id == str(owner_user_id))
    rows = (await db.execute(select(Candidate.file_hash).where(*filters))).scalars().all()
    return set(rows)


async def _existing_pool_emails(
    db: AsyncSession,
    emails: list[str],
    *,
    owner_user_id: str | None = None,
) -> set[str]:
    """
    Return the subset of emails that already exist in the candidate pool (job_id IS NULL).
    Used for email-level dedup so the same person can't appear twice in the pool
    even if they upload different file versions (different SHA-256 but same person).
    """
    if not emails:
        return set()
    clean = [e.lower().strip() for e in emails if e]
    if not clean:
        return set()
    filters = [
        Candidate.job_id.is_(None),
        func.lower(Candidate.email).in_(clean),
    ]
    if owner_user_id:
        filters.append(Candidate.user_id == str(owner_user_id))
    rows = (await db.execute(select(Candidate.email).where(*filters))).scalars().all()
    return {r.lower() for r in rows if r}


async def _existing_job_emails(db: AsyncSession, job_id: str, emails: list[str]) -> set[str]:
    """
    Return the subset of emails that already exist for a specific job_id.

    FIX: This was missing  bulk uploads only deduped by file hash, so if the
    same person uploaded two slightly different versions of their resume (or the
    same file with a different name) both would slip through. Krishnaraj Panwar
    appearing twice in the candidates list is caused exactly by this bug.
    """
    if not emails:
        return set()
    clean = [e.lower().strip() for e in emails if e]
    if not clean:
        return set()
    from sqlalchemy import func
    rows = (await db.execute(
        select(Candidate.email).where(
            Candidate.job_id == job_id,
            func.lower(Candidate.email).in_(clean),
        )
    )).scalars().all()
    return {r.lower() for r in rows if r}


async def _assert_job_owner(job_id: str, user: User, db: AsyncSession) -> JobDescription:
    job = (await db.execute(
        select(JobDescription).where(JobDescription.id == job_id)
    )).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job description not found")
    if user.role != UserRole.admin and job.created_by != user.id:
        raise HTTPException(status_code=403, detail="You do not have access to this job posting")
    return job


async def _assert_candidate_owner(candidate_id: str, user: User, db: AsyncSession) -> Candidate:
    c = (await db.execute(
        select(Candidate).where(Candidate.id == candidate_id)
    )).scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if user.role != UserRole.admin:
        if c.job_id is None:
            if c.user_id is None:
                raise HTTPException(
                    status_code=403, detail="Pool candidate has no owner  access denied")
            if c.user_id != user.id:
                raise HTTPException(
                    status_code=403, detail="Pool candidate belongs to another user")
        else:
            jd_check = (await db.execute(
                select(JobDescription).where(
                    JobDescription.id == c.job_id,
                    JobDescription.created_by == user.id,
                )
            )).scalar_one_or_none()
            if not jd_check:
                raise HTTPException(
                    status_code=403, detail="You do not have access to this candidate")
    return c


async def _assert_recruiter_kyc_access(
    *,
    candidate: Candidate,
    recruiter_user_id: str,
    kyc_db: AsyncSession,
) -> None:
    if not candidate.user_id or not candidate.job_id:
        raise HTTPException(status_code=422, detail="KYC access requires a job-linked candidate profile")
    if candidate.tag not in (CandidateTag.strong, CandidateTag.medium):
        raise HTTPException(status_code=403, detail="Candidate is not shortlisted")

    approval = (await kyc_db.execute(
        select(CandidateHireApproval).where(
            CandidateHireApproval.candidate_id == candidate.id,
            CandidateHireApproval.candidate_user_id == candidate.user_id,
            CandidateHireApproval.recruiter_user_id == recruiter_user_id,
            CandidateHireApproval.job_id == candidate.job_id,
        )
    )).scalar_one_or_none()
    if not approval or not bool(approval.approved) or approval.revoked_at is not None:
        raise HTTPException(status_code=403, detail="Recruiter hire approval is required before KYC access")

    consent = (await kyc_db.execute(
        select(CandidateKycConsent).where(
            CandidateKycConsent.candidate_id == candidate.id,
            CandidateKycConsent.candidate_user_id == candidate.user_id,
            CandidateKycConsent.recruiter_user_id == recruiter_user_id,
            CandidateKycConsent.job_id == candidate.job_id,
        )
    )).scalar_one_or_none()
    if not consent or not bool(consent.granted) or consent.revoked_at is not None:
        raise HTTPException(status_code=403, detail="Candidate consent is required before KYC access")


async def _enriched_candidate_out(candidate: Candidate, db: AsyncSession) -> CandidateOut:
    """
    Build a sanitized response model for candidate detail views without mutating
    ORM state. This keeps GET /resumes/{id} strictly read-only and avoids
    accidental autoflush UPDATEs during serialization.
    """
    job = None
    if candidate.job_id:
        job = await db.get(JobDescription, candidate.job_id)

    raw_text = ""
    if candidate.raw_resume_text:
        try:
            raw_text = encryption_service.decrypt_text(candidate.raw_resume_text) or ""
        except Exception as exc:
            logger.warning("Candidate profile enrichment decrypt failed for %s: %s", candidate.id, exc)

    parsed_seed = {
        "name": candidate.name,
        "email": candidate.email,
        "phone": candidate.phone,
        "location": candidate.location,
        "skills": candidate.skills or [],
        "normalized_skills": candidate.normalized_skills or [],
        "experience_years": candidate.experience_years or 0.0,
        "education": candidate.education or [],
        "projects": candidate.projects or [],
        "work_experience": candidate.work_experience or [],
        "career_breaks": candidate.career_breaks or [],
        "skill_years": candidate.skill_years or {},
    }
    def _structured_density(payload: dict) -> int:
        return (
            len(payload.get("work_experience") or [])
            + len(payload.get("projects") or [])
            + len(payload.get("career_breaks") or [])
        )

    enriched = _coerce_parsed_resume_payload(parsed_seed, raw_text, job)

    # Recover from legacy rows where raw_resume_text stored only a short summary,
    # causing empty project/work sections in detail view. We keep GET read-only:
    # parse from file on-demand and return enriched data without mutating DB state.
    if (
        _structured_density(enriched) == 0
        and candidate.resume_path
        and os.path.exists(candidate.resume_path)
    ):
        try:
            decrypted_file = await asyncio.to_thread(
                encryption_service.decrypt_file_from_path,
                candidate.resume_path,
            )
            source_name = os.path.basename(candidate.resume_path) or "resume.pdf"
            full_text = await file_service.extract_text_from_bytes(source_name, decrypted_file)
            if full_text.strip():
                from_file = _coerce_parsed_resume_payload(parsed_seed, full_text, job)
                if _structured_density(from_file) > 0:
                    enriched = from_file
        except Exception as exc:
            logger.warning(
                "Candidate detail enrichment fallback-from-file failed for %s: %s",
                candidate.id,
                exc,
            )

    payload = CandidateOut.model_validate(candidate).model_dump()
    payload["skills"] = enriched.get("skills") or payload.get("skills") or []
    payload["normalized_skills"] = enriched.get("normalized_skills") or payload.get("normalized_skills") or []
    payload["education"] = enriched.get("education") or payload.get("education") or []
    payload["projects"] = enriched.get("projects") or payload.get("projects") or []
    payload["work_experience"] = enriched.get("work_experience") or payload.get("work_experience") or []
    payload["career_breaks"] = enriched.get("career_breaks") or payload.get("career_breaks") or []
    payload["skill_years"] = enriched.get("skill_years") or payload.get("skill_years") or {}
    return CandidateOut(**payload)


async def _insert_application_atomic(
    db: AsyncSession,
    candidate_values: dict,
) -> Candidate | None:
    """
    Atomically insert a candidate application row.
    Returns None when (user_id, job_id) already exists.
    """
    dialect = db.get_bind().dialect.name
    conflict_where = and_(Candidate.user_id.isnot(None), Candidate.job_id.isnot(None))
    if dialect == "postgresql":
        stmt = (
            pg_insert(Candidate)
            .values(**candidate_values)
            .on_conflict_do_nothing(
                index_elements=[Candidate.user_id, Candidate.job_id],
                index_where=conflict_where,
            )
            .returning(Candidate.id)
        )
    elif dialect == "sqlite":
        stmt = (
            sqlite_insert(Candidate)
            .values(**candidate_values)
            .on_conflict_do_nothing(
                index_elements=["user_id", "job_id"],
                index_where=conflict_where,
            )
            .returning(Candidate.id)
        )
    else:
        raise RuntimeError(f"Unsupported database dialect for atomic application insert: {dialect}")

    inserted_id = (await db.execute(stmt)).scalar_one_or_none()
    if inserted_id is None:
        return None
    return await db.get(Candidate, inserted_id)


async def _insert_pool_candidate_atomic(
    db: AsyncSession,
    candidate_values: dict,
) -> Candidate | None:
    """
    Atomically insert a pool candidate.
    Returns None when the per-user pool unique index rejects a duplicate.
    """
    dialect = db.get_bind().dialect.name
    conflict_where = and_(
        Candidate.job_id.is_(None),
        Candidate.user_id.isnot(None),
        Candidate.email.isnot(None),
    )
    # Keep conflict target aligned with the existing partial unique index
    # (email, user_id) where job_id IS NULL.
    conflict_elements = [Candidate.email, Candidate.user_id]

    if dialect == "postgresql":
        stmt = (
            pg_insert(Candidate)
            .values(**candidate_values)
            .on_conflict_do_nothing(
                index_elements=conflict_elements,
                index_where=conflict_where,
            )
            .returning(Candidate.id)
        )
    elif dialect == "sqlite":
        # SQLite can reject partial-index ON CONFLICT targets depending on
        # runtime version and index metadata; use an explicit flush path here.
        candidate = Candidate(**candidate_values)
        db.add(candidate)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            return None
        return candidate
    else:
        raise RuntimeError(f"Unsupported database dialect for atomic pool insert: {dialect}")

    inserted_id = (await db.execute(stmt)).scalar_one_or_none()
    if inserted_id is None:
        return None
    return await db.get(Candidate, inserted_id)

#  Core resume processing 


async def _compute_resume_data(
    file: UploadFile,
    job: JobDescription,
    user_email: str | None = None,
    auth_header: str | None = None,
) -> dict:
    text, content = await file_service.extract_text(file)
    return await _compute_resume_data_from_bytes(
        file.filename or "resume.pdf",
        content,
        text,
        job,
        user_email=user_email,
        auth_header=auth_header,
    )


_background_tasks: set[asyncio.Task] = set()
__all__ = ["router", "_background_tasks"]


@observe(name="resume_pipeline")
async def _compute_resume_data_from_bytes(
    filename: str, content: bytes, text: str, job: JobDescription,
    cached_candidate: "Candidate | None" = None,
    user_email: str | None = None,
    auth_header: str | None = None,
    pre_parsed_data: dict | None = None,
    manual_career_breaks: list | None = None,
    fast_mode: bool = False,
) -> dict:
    """
    Core scoring pipeline  accepts pre-read bytes and extracted text.

    @observe creates a Langfuse parent trace automatically. Every LLM call inside
    (parse_resume, get_embedding, score_resume) appears as a child span grouped
    under this trace in the Langfuse UI.

    Steps:
      0. AI score cache check (skip LLM if same file_hash+job_id already scored)
      1. Parse resume (LLM) + get embedding + save file  concurrent via gather
      2. Rule-based scores (always; used as AI fallback)
      3. AI scoring  skipped on cache hit, falls back to rule-based on error
      4. Final composite score (tier-aware weights)
    """
    file_hash = _sha256(content)
    fast_mode = bool(fast_mode)
    if not fast_mode and _ai_degraded_mode_active():
        fast_mode = True
        logger.warning(
            "[DEGRADED-MODE] AI backend unavailable. Using fast parser + deterministic scoring for %s",
            filename,
        )

    #  Tag the Langfuse trace with useful metadata 
    try:
        langfuse_context.update_current_trace(
            user_id=user_email,
            metadata={
                "filename": filename,
                "job_id": str(job.id),
                "job_title": job.title,
                "file_hash": file_hash[:12],
            },
        )
    except Exception as exc:
        logger.debug("Langfuse trace metadata update failed (non-fatal): %s", exc)

    #  Step 0: AI Score Cache 
    # BUG 3 FIX: cache key must cover all scoring-relevant JD context.
    jd_hash = _jd_signature_hash(job)

    # If the same file has already been scored against this same JD version,
    # restore the stored AI result and skip the expensive LLM call entirely.
    cached_ai_scores: dict | None = None
    if (
        settings.AI_SCORE_CACHE_ENABLED
        and cached_candidate is not None
        and cached_candidate.score_breakdown
        and cached_candidate.score_breakdown.get("ai_score_used") is True
        and cached_candidate.file_hash == file_hash
        and cached_candidate.score_breakdown.get("jd_hash") == jd_hash
    ):
        bd = cached_candidate.score_breakdown
        cached_ai_scores = {
            "skill_score":          bd.get("ai_skill_score", 50),
            "experience_score":     bd.get("ai_experience_score", 50),
            "project_score":        bd.get("ai_project_score", 50),
            "matched_must_have":    bd.get("matched_must_have", []),
            "missing_must_have":    bd.get("missing_must_have", []),
            "matched_good_to_have": bd.get("matched_good_to_have", []),
            "missing_good_to_have":  bd.get("missing_good_to_have", []),
            "reasoning":            bd.get("reasoning", ""),
            "domain_fit":           bd.get("domain_fit", "exact"),
            "seniority_match":      bd.get("seniority_match", "exact"),
            "hire_recommendation":  bd.get("hire_recommendation", "maybe"),
            "red_flags":            bd.get("red_flags", []),
            "standout_factors":     bd.get("standout_factors", []),
            "confidence":           bd.get("confidence", "medium"),
        }
        logger.info("[AI Score CACHE HIT] %s (hash=%s)  skipping LLM call",
                    filename, file_hash[:8])

    #  Step 1: Parse + embed + save file (concurrent) 
    async def _get_parsed():
        if pre_parsed_data is not None:
            return _coerce_parsed_resume_payload(pre_parsed_data, text, job)
        if fast_mode:
            return _coerce_parsed_resume_payload(None, text, job)
        try:
            async with _AI_SEMAPHORE:
                parsed_data = await _run_resume_parser_with_fallback(
                    text=text,
                    auth_header=auth_header,
                )
            if isinstance(parsed_data, dict):
                return _coerce_parsed_resume_payload(parsed_data, text, job)
            logger.warning(
                "[WARN] Unexpected parsed resume payload type for %s: %s. Falling back to fast parser.",
                filename, type(parsed_data).__name__,
            )
            return _coerce_parsed_resume_payload(None, text, job)
        except Exception as parse_err:
            logger.warning(
                "[WARN] AI resume parsing failed for %s (%s). Falling back to fast parser.",
                filename, parse_err,
            )
            return _coerce_parsed_resume_payload(None, text, job)

    async def _get_embedding():
        if fast_mode:
            return []
        async with _AI_SEMAPHORE:
            return await _run_embedding_with_fallback(
                text=text[:12000],
                auth_header=auth_header,
            )

    parsed, resume_embedding, resume_path = await asyncio.gather(
        _get_parsed(),
        _get_embedding(),
        file_service.save_file(content, filename),
        return_exceptions=True,
    )

    if isinstance(resume_embedding, Exception):
        logger.warning("[WARN] Embedding failed for %s: %s", filename, resume_embedding)
        resume_embedding = []

    if isinstance(resume_path, Exception):
        # FIX 3: A failed file save must NOT silently produce a ghost candidate
        # (a scored DB row with no physical file). Re-raise so the caller records
        # this as a processing failure and the candidate is not persisted.
        logger.error(
            "[ERROR] save_file failed for %s  aborting candidate save: %s",
            filename, resume_path,
        )
        raise RuntimeError(
            f"Resume file could not be saved for '{filename}': {resume_path}"
        ) from resume_path

    if isinstance(parsed, Exception):
        # BUG #16 FIX (MEDIUM): Explicitly re-raise parsed exceptions from
        # asyncio.gather with a clean error message. Previously, the code would
        # proceed and call parsed.get("name") which raised a confusing
        # AttributeError (e.g., "'ValueError' object has no attribute 'get'").
        logger.error(
            "[ERROR] Resume parsing failed for %s: %s", filename, parsed,
            exc_info=parsed,
        )
        if not isinstance(resume_embedding, list):
            logger.warning(
                "[WARN] Embedding also failed for %s (suppressed by parse error): %s", filename, resume_embedding)
        raise RuntimeError(
            f"Resume parsing failed for '{filename}': {parsed}"
        ) from parsed

    exp_years = float(parsed.get("experience_years") or 0.0)
    skill_years = parsed.get("skill_years") or {}

    #  Step 2: Rule-based specialists (parallel fan-out for lower latency)
    normalized_skills = parsed.get("normalized_skills", [])
    projects = parsed.get("projects", [])
    education_rows = parsed.get("education", [])
    location_value = parsed.get("location")

    def _calc_skill() -> float:
        return scoring_service.skill_match_score(
            normalized_skills,
            job.must_have_skills or [],
            job.good_to_have_skills or [],
        )

    def _calc_exp() -> float:
        return scoring_service.experience_match_score(
            exp_years,
            job.experience_min,
            job.experience_max,
            skill_years,
            job.must_have_skills or [],
        )

    def _calc_proj() -> float:
        return scoring_service.project_relevance_score(
            projects,
            job.must_have_skills or [],
            job.good_to_have_skills or [],
            exp_years,
        )

    def _calc_edu() -> float:
        return scoring_service.education_match_score(
            education_rows,
            experience_years=exp_years,
            jd_description=job.description or "",
            jd_must_have=job.must_have_skills or [],
            # ISSUE 7 FIX: pass LLM-extracted value when available; scoring_service
            # will skip regex detection and use it directly.
            jd_education_requirement=getattr(job, "education_requirement", None),
        )

    def _calc_loc() -> float:
        return scoring_service.location_match_score(location_value, job.location)

    rule_skill_pct, rule_exp_pct, rule_proj_pct, edu_pct, loc_pct = await asyncio.gather(
        asyncio.to_thread(_calc_skill),
        asyncio.to_thread(_calc_exp),
        asyncio.to_thread(_calc_proj),
        asyncio.to_thread(_calc_edu),
        asyncio.to_thread(_calc_loc),
    )

    critical_missing_count = sum(
        1
        for skill in (job.must_have_skills or [])
        if not scoring_service.semantic_skill_match(skill, normalized_skills)
    )

    try:
        vec_sim = scoring_service.cosine_similarity(resume_embedding, job.embedding or [])
    except ValueError as vec_err:
        logger.warning("Vector similarity degraded during scoring for job %s: %s", job.id, vec_err)
        vec_sim = 0.0
    vector_available = bool(resume_embedding) and bool(job.embedding or [])

    #  Step 3: AI scoring (skipped on cache hit) 
    ai_scores: dict | None = cached_ai_scores
    if ai_scores is None and settings.AI_SCORING_ENABLED and not fast_mode:
        try:
            async with _AI_SEMAPHORE:
                ai_scores = await _run_resume_scorer_with_fallback(
                    parsed_resume=parsed,
                    job_title=job.title,
                    exp_min=job.experience_min,
                    exp_max=job.experience_max,
                    must_have=job.must_have_skills or [],
                    good_to_have=job.good_to_have_skills or [],
                    description=job.description or "",
                    auth_header=auth_header,
                )
            logger.info(
                "[AI Score NEW] %s  skill=%s exp=%s proj=%s tier=%s",
                filename,
                ai_scores.get("skill_score"),
                ai_scores.get("experience_score"),
                ai_scores.get("project_score"),
                scoring_service.detect_candidate_tier(exp_years),
            )
        except Exception as ai_err:
            logger.warning(
                "[AI Score FAIL] %s  rule-based fallback. Error: %s",
                filename, ai_err,
            )

    #  Step 4: Final composite score (tier-aware weights) 
    has_jd_criteria = _job_has_meaningful_criteria(job)
    phase_b_weights, phase_b_bias, phase_b_meta = scoring_service.build_phase_b_calibration(
        experience_years=exp_years,
        job_title=job.title,
        job_role=job.role,
        jd_description=job.description or "",
        jd_must_have=job.must_have_skills or [],
        jd_good_to_have=job.good_to_have_skills or [],
        exp_min=job.experience_min,
        exp_max=job.experience_max,
    )

    resume_score, skill_pct, exp_pct, proj_pct = (
        scoring_service.compute_resume_score_with_ai_override(
            ai_scores=ai_scores,
            education_pct=edu_pct,
            vector_sim=vec_sim,
            location_pct=loc_pct,
            experience_years=exp_years,
            rule_skill_pct=rule_skill_pct,
            rule_exp_pct=rule_exp_pct,
            rule_proj_pct=rule_proj_pct,
            critical_missing_count=critical_missing_count,
            has_jd_skills=has_jd_criteria,
            total_must_have_count=len(job.must_have_skills or []),
            vector_available=vector_available,
            calibrated_weights=phase_b_weights,
            score_bias_points=phase_b_bias,
            phase_c_enabled=bool(settings.PHASE_C_SCORING_ENABLED),
            ai_confidence=str((ai_scores or {}).get("confidence", "")),
            jd_signal_strength=phase_b_meta.get("jd_signal_strength"),
            required_skills=job.must_have_skills or [],
            work_experience=parsed.get("work_experience", []),
            skill_years=skill_years,
        )
    )

    tag = scoring_service.assign_tag(resume_score)

    #  Build score_breakdown for UI + next cache read 
    ai = ai_scores or {}
    score_breakdown = {
        "ai_score_used":        ai_scores is not None,
        # Raw AI component scores  stored so cache reads can reconstruct them
        "ai_skill_score":       ai.get("skill_score"),
        "ai_experience_score":  ai.get("experience_score"),
        "ai_project_score":     ai.get("project_score"),
        # JD match details (shown in UI)
        "matched_must_have":    ai.get("matched_must_have", []),
        "missing_must_have":    ai.get("missing_must_have", []),
        "matched_good_to_have": ai.get("matched_good_to_have", []),
        "missing_good_to_have":  ai.get("missing_good_to_have", []),
        "reasoning":            ai.get("reasoning", ""),
        "domain_fit":           ai.get("domain_fit", "exact"),
        "seniority_match":      ai.get("seniority_match", "exact"),
        "hire_recommendation":  ai.get("hire_recommendation", "maybe"),
        "red_flags":            ai.get("red_flags", []),
        "standout_factors":     ai.get("standout_factors", []),
        "confidence":           ai.get("confidence", "medium"),
        # Rule-based scores kept for comparison/debugging
        "rule_based": {
            "skill_pct": round(rule_skill_pct, 1),
            "exp_pct":   round(rule_exp_pct, 1),
            "proj_pct":  round(rule_proj_pct, 1),
        },
        # Tier used for weighting
        "candidate_tier": scoring_service.detect_candidate_tier(exp_years),
        # Cache provenance flag
        "from_cache": cached_ai_scores is not None,
        "fast_mode": bool(fast_mode),
        "degraded_mode": bool(fast_mode and _ai_degraded_mode_active()),
        "ocr_truncated": "[SYSTEM: OCR_TRUNCATED]" in text,
        "phase_b_calibration": phase_b_meta,
        "phase_c_applied": bool(settings.PHASE_C_SCORING_ENABLED),
        # BUG 3 FIX: store JD content hash so future cache reads can detect
        # stale scores caused by JD edits (new skills, changed exp range).
        "jd_hash": jd_hash,
    }

    result = dict(
        file_hash=file_hash,
        job_id=job.id,
        name=parsed.get("name"),
        email=parsed.get("email"),
        phone=parsed.get("phone"),
        location=parsed.get("location"),
        skills=parsed.get("skills", []),
        normalized_skills=parsed.get("normalized_skills", []),
        experience_years=exp_years,
        education=parsed.get("education", []),
        projects=parsed.get("projects", []),
        work_experience=parsed.get("work_experience", []),
        career_breaks=(manual_career_breaks or []) + parsed.get("career_breaks", []),
        skill_years=skill_years,
        # BUG-8 FIX: parse_resume uses text[:40_000]; storing only 15k means
        # the bottom ~25k chars (later work history, contact details) are silently
        # lost. Stored text is now consistent with what the LLM actually processed.
        raw_resume_text=encryption_service.encrypt_text(text[:40000]),
        resume_path=resume_path,
        embedding=resume_embedding,
        skill_match_pct=skill_pct,
        experience_match_pct=exp_pct,
        project_relevance_pct=proj_pct,
        education_match_pct=edu_pct,
        location_match_pct=loc_pct,
        vector_similarity=vec_sim,
        resume_score=resume_score,
        # Keep an authoritative score even before quiz attempts so ranking/analytics
        # never depend on nullable fields for non-quiz workflows.
        final_score=resume_score,
        score_breakdown=score_breakdown,
        tag=tag,
    )

    #  Finalize Langfuse trace 
    #  Update the Langfuse trace output 
    #  DeepEval: fire-and-forget background eval 
    #  CRITICAL FIX: DeepEval uses LLM-as-a-judge (another massive LLM call).
    # Previously this was `await`-ed inline  100 resumes = 100 concurrent eval
    # LLM calls that blocked the HTTP response for minutes and exhausted Azure
    # OpenAI TPM limits. Now runs as a background task that doesn't block the
    # upload pipeline or consume the response budget.
    _job_desc = job.description or ""
    _job_must_have = list(job.must_have_skills or [])
    _ai_skill = ai.get("skill_score", 50)
    _ai_exp = ai.get("experience_score", 50)
    _ai_proj = ai.get("project_score", 50)

    async def _background_deepeval(fname: str, txt: str, desc: str, must_have: list, sk_score: float, ex_score: float, pr_score: float):
        try:
            jd_text_for_eval = desc + " Required skills: " + ", ".join(must_have)
            _deepeval_evaluator = import_module("app.evals.deepeval_service").evaluator
            _eval_result = await _deepeval_evaluator.evaluate_resume_scoring(
                resume_text=txt[:3000],
                jd_text=jd_text_for_eval,
                scores={
                    "skill_score":      sk_score,
                    "experience_score": ex_score,
                    "project_score":    pr_score,
                },
            )
            push_eval_to_langfuse(_eval_result)
            logger.info(
                "[DeepEval] %s  overall=%.2f passed=%s",
                fname, _eval_result.overall_score, _eval_result.passed,
            )
        except Exception as _eval_err:
            logger.debug("DeepEval scoring eval skipped (non-fatal): %s", _eval_err)

    if settings.EVALS_ENABLED and not fast_mode:
        task = asyncio.create_task(_background_deepeval(
            filename, text, _job_desc, _job_must_have, _ai_skill, _ai_exp, _ai_proj
        ))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    try:
        langfuse_context.update_current_observation(output={
            "resume_score": round(resume_score, 2),
            "hire_recommendation": ai.get("hire_recommendation", "n/a"),
            "candidate_tier": score_breakdown.get("candidate_tier"),
            "from_cache": score_breakdown.get("from_cache", False),
        })
    except Exception as trace_exc:
        logger.debug("Langfuse observation update skipped (non-fatal): %s", trace_exc)

    return result


@observe(name="pool_resume_parse")
async def _compute_pool_resume_data_from_bytes(
    filename: str, content: bytes, text: str,
    user_email: str | None = None,
    auth_header: str | None = None,
    pre_parsed_data: dict | None = None,
) -> dict:
    """Pool upload  no job, no scoring. @observe creates a Langfuse trace for the parse step."""
    file_hash = _sha256(content)

    try:
        langfuse_context.update_current_trace(
            user_id=user_email,
            metadata={"filename": filename, "file_hash": file_hash[:12]},
        )
    except Exception as exc:
        logger.debug("Langfuse pool trace metadata update failed (non-fatal): %s", exc)

    async def _get_pool_parsed():
        if pre_parsed_data:
            return resume_fallback_parser.coerce_parsed_resume(pre_parsed_data, text=text)
        if _ai_degraded_mode_active():
            return resume_fallback_parser.coerce_parsed_resume(None, text=text)
        try:
            parsed = await _run_resume_parser_with_fallback(
                text=text,
                auth_header=auth_header,
            )
            return resume_fallback_parser.coerce_parsed_resume(parsed, text=text)
        except Exception as parse_err:
            logger.warning(
                "[WARN] Pool AI parse failed for %s (%s). Falling back to fast parser.",
                filename, parse_err,
            )
            return resume_fallback_parser.coerce_parsed_resume(None, text=text)

    parsed, resume_path = await asyncio.gather(
        _get_pool_parsed(),
        file_service.save_file(content, filename),
        return_exceptions=True,
    )

    if isinstance(resume_path, Exception):
        logger.error(
            "[ERROR] Pool save_file failed for %s - aborting candidate save: %s",
            filename,
            resume_path,
        )
        raise RuntimeError(
            f"Resume file could not be saved for '{filename}': {resume_path}"
        ) from resume_path

    if isinstance(parsed, Exception):
        raise parsed

    return dict(
        file_hash=file_hash,
        job_id=None,
        name=parsed.get("name"), email=parsed.get("email"), phone=parsed.get("phone"),
        skills=parsed.get("skills", []), normalized_skills=parsed.get("normalized_skills", []),
        experience_years=float(parsed.get("experience_years") or 0.0),
        education=parsed.get("education", []), projects=parsed.get("projects", []),
        location=parsed.get("location"),
        work_experience=parsed.get("work_experience", []),
        career_breaks=parsed.get("career_breaks", []),
        skill_years=parsed.get("skill_years") or {},
        score_breakdown={"ocr_truncated": "[SYSTEM: OCR_TRUNCATED]" in text},
        raw_resume_text=encryption_service.encrypt_text(text[:40000]),
        resume_path=resume_path, embedding=[],
        skill_match_pct=0.0, experience_match_pct=0.0, project_relevance_pct=0.0,
        education_match_pct=0.0, vector_similarity=0.0,
        # FIX: use 0.0 (float) not 0 (int) for type consistency with the Float column
        resume_score=0.0, tag=None,
    )

#  Static routes (before any /{candidate_id} routes) 


@router.post("/upload", status_code=201)
@limiter.limit(SINGLE_FILE_UPLOAD_RATE_LIMIT)
async def upload_resume(
    request: Request,
    response: Response,
    job_id: str = Form(...),
    file: UploadFile = File(...),
    x_idempotency_key: Optional[str] = Header(default=None, alias="X-Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    job = await _assert_job_owner(job_id, user, db)

    # FIX 8: Validate extension against allowlist BEFORE reading file content.
    # Without this, an attacker uploads resume.html  stored  served back as
    # text/html  stored XSS. ALLOWED_RESUME_EXTENSIONS was defined in config
    # but never enforced here.
    _raw_ext = os.path.splitext(file.filename or "")[1].lower()
    if _raw_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=422,
            detail=(
                f"File type '{_raw_ext or '(none)'}' is not allowed. "
                f"Accepted: {', '.join(settings.allowed_extensions_list)}"
            ),
        )

    _max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    _precheck_content_length(file.headers, _max_bytes)
    _precheck_content_length(request.headers, _max_bytes)

    content_arr = bytearray()
    while chunk := await file.read(1024 * 1024):
        content_arr.extend(chunk)
        if len(content_arr) > _max_bytes:
            raise HTTPException(status_code=413, detail=f"File too large (max {settings.MAX_FILE_SIZE_MB}MB)")
    raw_content = bytes(content_arr)
    text, content = await file_service.extract_text_normalised_from_bytes(
        file.filename or "resume.pdf",
        raw_content,
    )
    file_hash = _sha256(content)
    idem_key = (x_idempotency_key or "").strip()

    # Single query: check for duplicate AND serve as AI score cache lookup.
    # Previously this was two identical queries  the first raised 409 if a row
    # was found, so the second always returned None (cache was never populated).
    # Now we fetch the full row once; raise 409 on dup; pass None as cached_row
    # (no prior same-job upload can exist after the 409 guard, by definition).
    existing_for_job = (await db.execute(
        select(Candidate).where(
            Candidate.file_hash == file_hash,
            Candidate.job_id == job_id,
        )
    )).scalar_one_or_none()
    if existing_for_job:
        if idem_key:
            response.status_code = 200
            return CandidateOut.model_validate(existing_for_job)
        raise HTTPException(
            status_code=409,
            detail="This resume has already been uploaded for this job (duplicate content detected)."
        )
    # cached_row is always None here (the 409 guard above would have fired if one
    # existed). Keep the variable for the _compute_resume_data_from_bytes signature.
    cached_row = None

    degraded_mode = _ai_degraded_mode_active()
    if degraded_mode:
        response.headers["X-AI-Degraded-Mode"] = "1"

    upload_slo_s = max(1.0, float(settings.RECRUITER_UPLOAD_SLO_MS) / 1000.0)
    try:
        data = await asyncio.wait_for(
            _compute_resume_data_from_bytes(
                file.filename or "resume.pdf",
                content,
                text,
                job,
                cached_candidate=cached_row,
                user_email=user.email,
                auth_header=request.headers.get("authorization"),
                fast_mode=degraded_mode,
            ),
            timeout=upload_slo_s,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Resume processing exceeded recruiter upload SLO. "
                "Retry in degraded mode or use async bulk upload."
            ),
        ) from exc

    # BUG 2 FIX: email-level dedup for single upload (same as bulk-upload).
    # A candidate who tweaks their PDF filename or reformats their resume will
    # get a different file hash but the same email  they'd appear twice without this.
    if data.get("email"):
        dup_emails = await _existing_job_emails(db, job_id, [data["email"]])
        if data["email"].lower().strip() in dup_emails:
            if idem_key:
                existing_by_email = (await db.execute(
                    select(Candidate).where(
                        Candidate.job_id == job_id,
                        Candidate.email == data["email"].lower().strip(),
                    )
                )).scalar_one_or_none()
                if existing_by_email:
                    response.status_code = 200
                    return CandidateOut.model_validate(existing_by_email)
            raise HTTPException(
                status_code=409,
                detail=f"A candidate with email {data['email']} is already uploaded for this job. "
                "Delete the existing entry before re-uploading."
            )

    # Candidate application uniqueness (uq_application_user_job) is meant for
    # candidate self-apply flows. Recruiter pipeline uploads must allow many
    # candidates per job, so do not set recruiter user_id on job candidates.
    candidate = Candidate(**data, user_id=None)
    try:
        db.add(candidate)
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A candidate with the same email already exists for this job.",
        ) from exc
    await _recompute_job_rank_and_tags(
        db,
        job,
        auth_header=request.headers.get("authorization"),
    )
    await log_action(db, user.id, "UPLOAD_RESUME", "candidate", candidate.id)
    await db.commit()
    await db.refresh(candidate)
    return CandidateOut.model_validate(candidate)


@router.post("/upload-pool", status_code=201)
@limiter.limit(SINGLE_FILE_UPLOAD_RATE_LIMIT)
async def upload_pool_single(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    x_idempotency_key: Optional[str] = Header(default=None, alias="X-Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    _raw_ext = os.path.splitext(file.filename or "")[1].lower()
    if _raw_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=422,
            detail=f"File type '{_raw_ext or '(none)'}' is not allowed.",
        )
    try:
        _max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
        _precheck_content_length(file.headers, _max_bytes)
        _precheck_content_length(request.headers, _max_bytes)
        content_arr = bytearray()
        while chunk := await file.read(1024 * 1024):
            content_arr.extend(chunk)
            if len(content_arr) > _max_bytes:
                raise HTTPException(status_code=413, detail=f"File too large (max {settings.MAX_FILE_SIZE_MB}MB)")
        raw_content = bytes(content_arr)
        text, content = await file_service.extract_text_normalised_from_bytes(
            file.filename or "resume.pdf",
            raw_content,
        )
    except HTTPException:
        # Preserve specific parser/file-service errors (e.g., encrypted storage blob uploads).
        raise
    except Exception:
        logger.exception("Pool upload read/extract failed for file %s", file.filename)
        raise HTTPException(status_code=422, detail="Could not read file.")

    # FIX: check for duplicate on single pool upload for consistency with bulk
    file_hash = _sha256(content)
    idem_key = (x_idempotency_key or "").strip()
    existing_hashes = await _existing_hashes(db, [file_hash], owner_user_id=str(user.id))
    if file_hash in existing_hashes:
        if idem_key:
            existing_pool = (await db.execute(
                select(Candidate).where(
                    Candidate.user_id == str(user.id),
                    Candidate.job_id.is_(None),
                    Candidate.file_hash == file_hash,
                )
            )).scalar_one_or_none()
            if existing_pool:
                response.status_code = 200
                return CandidateOut.model_validate(existing_pool)
        raise HTTPException(
            status_code=409,
            detail="This resume has already been uploaded (duplicate file detected)."
        )

    # Email-level dedup: parse first to get email, then check pool
    data = await _compute_pool_resume_data_from_bytes(
        file.filename or "resume.pdf",
        content,
        text,
        user_email=user.email,
        auth_header=request.headers.get("authorization"),
    )

    if data.get("email"):
        dup_emails = await _existing_pool_emails(db, [data["email"]], owner_user_id=str(user.id))
        if data["email"].lower().strip() in dup_emails:
            if idem_key:
                existing_pool_by_email = (await db.execute(
                    select(Candidate).where(
                        Candidate.user_id == str(user.id),
                        Candidate.job_id.is_(None),
                        Candidate.email == data["email"].lower().strip(),
                    )
                )).scalar_one_or_none()
                if existing_pool_by_email:
                    response.status_code = 200
                    return CandidateOut.model_validate(existing_pool_by_email)
            raise HTTPException(
                status_code=409,
                detail=f"A resume from {data['email']} already exists in the pool. "
                "Delete the existing entry before re-uploading."
            )

    normalized_email = (str(data.get("email") or "").strip().lower() or None)
    candidate_values = {**data, "user_id": user.id, "email": normalized_email}
    try:
        candidate = await _insert_pool_candidate_atomic(db, candidate_values)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A resume with the same email already exists in your pool.",
        ) from exc
    if candidate is None:
        raise HTTPException(
            status_code=409,
            detail="A resume with the same email already exists in your pool.",
        )
    await log_action(db, user.id, "UPLOAD_RESUME_POOL", "candidate", candidate.id)
    await db.commit()
    await db.refresh(candidate)
    return CandidateOut.model_validate(candidate)


@router.post("/upload-bulk", status_code=201)
@limiter.limit(BULK_UPLOAD_RATE_LIMIT)
async def upload_bulk_resumes(
    request: Request,
    response: Response,
    job_id: str = Form(...),
    files: List[UploadFile] = File(...),
    file_ids: List[str] = Form(default=[]),
    progress_run_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    """Bulk resume upload for a specific job with deduplication."""
    _bulk_started_at = time.perf_counter()
    max_bulk_files = max(1, int(settings.BULK_UPLOAD_MAX_FILES))
    if len(files) > max_bulk_files:
        raise HTTPException(status_code=422, detail=f"Max {max_bulk_files} files per bulk upload")

    job = await _assert_job_owner(job_id, user, db)

    client_ids = list(file_ids) if file_ids else [
        f.filename or f"file_{i}" for i, f in enumerate(files)]
    while len(client_ids) < len(files):
        client_ids.append(f"file_{len(client_ids)}")
    client_ids = client_ids[:len(files)]

    # FIX (Placebo RAM Batching OOM): The original code called raw_files.extend(_batch_raw)
    # then del _batch_raw, which did nothing  extend() copies object references into
    # raw_files so bytes stayed alive. With 50010 MB PDFs that is ~5 GB in RAM before
    # any AI processing starts, guaranteeing an OOM crash in standard containers.
    #
    # Real fix: read  validate  extract  dedup  score each batch IN-PLACE.
    # Only lightweight metadata (text strings, small dicts) accumulate across batches.
    # Heavy bytes buffers are explicitly deleted after extraction within each batch.

    _READ_BATCH = 50
    _file_pairs = list(zip(files, client_ids))
    resume_from_batch = 0
    if progress_run_id:
        prior = _BULK_JOB_STATUS.get(progress_run_id, {})
        resume_from_batch = int((prior or {}).get("last_committed_batch") or 0)

    already_uploaded: set[str] = set()
    existing_emails_for_job: set[str] = set()
    seen_emails_this_batch: set[str] = set()

    read_failures: list[dict] = []
    extract_failures: list[dict] = []
    skipped_duplicates: list[dict] = []
    ai_failures: list[dict] = []
    success_records: list[dict] = []
    last_committed_batch = 0

    async def _publish_progress(status: str = "running", *, last_committed_batch: int | None = None) -> None:
        if not progress_run_id:
            return
        processed = (
            len(success_records)
            + len(read_failures)
            + len(extract_failures)
            + len(ai_failures)
            + len(skipped_duplicates)
        )
        _set_bulk_job_status(
            progress_run_id,
            status=status,
            last_committed_batch=(
                int(last_committed_batch)
                if last_committed_batch is not None
                else int((_BULK_JOB_STATUS.get(progress_run_id, {}) or {}).get("last_committed_batch") or 0)
            ),
            progress={
                "processed": processed,
                "total": len(files),
                "success_count": len(success_records),
                "failed_count": len(read_failures) + len(extract_failures) + len(ai_failures),
                "duplicate_count": len(skipped_duplicates),
            },
        )
        await _persist_bulk_job_status(progress_run_id)

    await _publish_progress("running", last_committed_batch=last_committed_batch)

    bulk_fast_mode = bool(settings.BULK_FAST_MODE or _ai_degraded_mode_active())
    if bulk_fast_mode and not bool(settings.BULK_FAST_MODE):
        logger.warning(
            "[DEGRADED-MODE] Forcing deterministic bulk mode for job=%s because AI backend is unavailable.",
            job_id,
        )

    extract_sem = asyncio.Semaphore(max(1, int(settings.BULK_EXTRACT_CONCURRENCY)))
    _parse_sem = asyncio.Semaphore(max(1, int(settings.BULK_PARSE_CONCURRENCY)))
    _score_sem = asyncio.Semaphore(max(1, int(settings.BULK_SCORE_CONCURRENCY)))
    _hash_to_cached: dict[str, Candidate] = {}

    async def _extract_one(fname: str, content: bytes) -> str:
        async with extract_sem:
            return await file_service.extract_text_from_bytes(fname, content)

    async def _parse_one(text: str) -> dict:
        async with _parse_sem:
            if bulk_fast_mode:
                return _coerce_parsed_resume_payload(None, text, job)
            try:
                parsed = await _run_resume_parser_with_fallback(
                    text=text,
                    auth_header=request.headers.get("authorization"),
                )
                return _coerce_parsed_resume_payload(parsed, text, job)
            except Exception as exc:
                logger.warning(
                    "[WARN] Bulk pre-parse fell back to fast parser due to AI error: %s",
                    exc,
                )
                return _coerce_parsed_resume_payload(None, text, job)

    async def _score_one(fname: str, content: bytes, text: str, pre_parsed: dict) -> dict:
        async with _score_sem:
            h = _sha256(content)
            return await _compute_resume_data_from_bytes(
                fname,
                content,
                text,
                job,
                cached_candidate=_hash_to_cached.get(h),
                user_email=user.email,
                auth_header=request.headers.get("authorization"),
                pre_parsed_data=pre_parsed,
                fast_mode=bulk_fast_mode,
            )

    for batch_no, _bi in enumerate(range(0, len(_file_pairs), _READ_BATCH), start=1):
        if batch_no <= resume_from_batch:
            continue
        _batch_pairs = _file_pairs[_bi: _bi + _READ_BATCH]

        #  Step 1: read bytes + validate extension 
        _batch_buf: list[tuple[str, bytes, str]] = []
        for f, cid in _batch_pairs:
            _raw_ext = os.path.splitext(f.filename or "")[1].lower()
            if _raw_ext not in settings.allowed_extensions_list:
                read_failures.append({
                    "filename": f.filename, "file_id": cid,
                    "error": f"File type '{_raw_ext or '(none)'}' is not allowed",
                })
                continue
            try:
                _max_bytes = int(settings.MAX_FILE_SIZE_BYTES)
                _precheck_content_length(getattr(f, "headers", None), _max_bytes)
                _chunk_size = 4 * 1024 * 1024
                content_arr = bytearray()
                oversized = False
                while chunk := await f.read(_chunk_size):
                    content_arr.extend(chunk)
                    if len(content_arr) > _max_bytes:
                        read_failures.append({
                            "filename": f.filename,
                            "file_id": cid,
                            "warning": f"Skipped: file exceeds {settings.MAX_FILE_SIZE_MB}MB limit",
                        })
                        oversized = True
                        break
                if oversized:
                    continue
                content = bytes(content_arr)
                content = _maybe_decrypt_bulk_upload_content(f.filename or "resume.pdf", _raw_ext, content)
                _batch_buf.append((f.filename or "resume.pdf", content, cid))
            except Exception as e:
                if isinstance(e, HTTPException):
                    read_failures.append({"filename": f.filename, "file_id": cid, "error": str(e.detail)})
                else:
                    logger.exception("Bulk upload read failed for %s", f.filename)
                    read_failures.append({"filename": f.filename, "file_id": cid, "error": "Failed to read file."})

        if not _batch_buf:
            continue

        #  Step 2: hash dedup scoped to this job 
        _batch_hashes = {cid: _sha256(content) for _, content, cid in _batch_buf}
        _new_hashes = [h for h in _batch_hashes.values() if h not in already_uploaded]
        if _new_hashes:
            _dup_rows = (await db.execute(
                select(Candidate.file_hash).where(
                    Candidate.file_hash.in_(_new_hashes),
                    Candidate.job_id == job_id,
                )
            )).scalars().all()
            already_uploaded.update(_dup_rows)

        _dedup_buf: list[tuple[str, bytes, str]] = []
        for fname, content, cid in _batch_buf:
            h = _batch_hashes[cid]
            if h in already_uploaded:
                skipped_duplicates.append(
                    {"filename": fname, "file_id": cid, "reason": "already_uploaded"})
            else:
                _dedup_buf.append((fname, content, cid))
                already_uploaded.add(h)
        del _batch_buf  # release raw bytes for duplicates immediately

        if not _dedup_buf:
            continue

        #  Step 3: text extraction (concurrent within batch) 
        _extract_results = await asyncio.gather(
            *[_extract_one(fname, content) for fname, content, _ in _dedup_buf],
            return_exceptions=True,
        )

        _text_buf: list[tuple[str, bytes, str, str]] = []
        for (fname, content, cid), result in zip(_dedup_buf, _extract_results):
            if isinstance(result, Exception):
                _log_worker_error("[ERROR] Text extraction failed for %s: %s", fname, result)
                extract_failures.append({"filename": fname, "file_id": cid, "error": str(result)})
            else:
                _text_buf.append((fname, content, result, cid))
        del _dedup_buf

        if not _text_buf:
            continue

        #  Step 4: warm cross-job AI-score cache for this batch 
        _batch_content_hashes = [_sha256(c) for _, c, _, _ in _text_buf]
        _cached_rows = (await db.execute(
            select(Candidate).where(
                Candidate.file_hash.in_(_batch_content_hashes),
                Candidate.job_id.isnot(None),
                Candidate.score_breakdown.isnot(None),
            )
        )).scalars().all()
        for _crow in sorted(_cached_rows, key=lambda r: r.resume_score or 0):
            if _crow.file_hash:
                _hash_to_cached[_crow.file_hash] = _crow

        #  Step 5: cheap parse  email dedup BEFORE expensive scoring 
        _parse_results = await asyncio.gather(
            *[_parse_one(text) for _, _, text, _ in _text_buf],
            return_exceptions=True,
        )

        _new_emails_in_batch = [
            r.get("email") for r in _parse_results
            if not isinstance(r, Exception) and r.get("email")
        ]
        if _new_emails_in_batch:
            _job_email_rows = await _existing_job_emails(db, job_id, _new_emails_in_batch)
            existing_emails_for_job.update(_job_email_rows)

        _scoreable: list[tuple[str, bytes, str, str]] = []
        _scoreable_parsed: list[dict] = []
        for (fname, content, text, cid), _parsed in zip(_text_buf, _parse_results):
            if isinstance(_parsed, Exception):
                _log_worker_error("[ERROR] Pre-parse failed for %s: %s", fname, _parsed)
                ai_failures.append({"filename": fname, "file_id": cid, "error": str(_parsed)})
                continue
            _email_key = (_parsed.get("email") or "").lower().strip()
            if _email_key and (
                _email_key in existing_emails_for_job
                or _email_key in seen_emails_this_batch
            ):
                skipped_duplicates.append({
                    "filename": fname, "file_id": cid,
                    "reason": "duplicate_email",
                    "email": _parsed.get("email"),
                })
                continue
            _scoreable.append((fname, content, text, cid))
            _scoreable_parsed.append(_parsed)
            if _email_key:
                seen_emails_this_batch.add(_email_key)
        del _text_buf

        if not _scoreable:
            continue

        #  Step 6: full AI scoring (concurrent within batch) 
        _ai_results = await asyncio.gather(
            *[_score_one(fname, content, text, pre_parsed)
              for (fname, content, text, _cid), pre_parsed in zip(_scoreable, _scoreable_parsed)],
            return_exceptions=True,
        )

        # Step 7: persist with per-row savepoints so one bad row does not roll
        # back all valid rows in the same batch.
        for (fname, _content, _text, cid), result in zip(_scoreable, _ai_results):
            if isinstance(result, Exception):
                _log_worker_error("[ERROR] AI processing failed for %s: %s", fname, result)
                ai_failures.append({"filename": fname, "file_id": cid, "error": str(result)})
                continue
            try:
                async with db.begin_nested():
                    candidate = Candidate(**result, user_id=None)
                    db.add(candidate)
                    await db.flush()
                    await log_action(db, user.id, "UPLOAD_RESUME", "candidate", candidate.id)
                    success_records.append(
                        {"filename": fname, "file_id": cid, "candidate_id": candidate.id}
                    )
            except IntegrityError as exc:
                logger.warning("Skipping invalid/duplicate candidate row for %s: %s", fname, exc)
                ai_failures.append(
                    {"filename": fname, "file_id": cid, "error": "Duplicate or invalid candidate row."}
                )
            except Exception as exc:
                logger.error("DB save failed for %s: %s", fname, exc)
                ai_failures.append({"filename": fname, "file_id": cid, "error": f"DB save failed: {exc}"})

        await db.commit()
        last_committed_batch = batch_no

        del _scoreable, _scoreable_parsed, _ai_results  # release before next batch
        await _publish_progress("running", last_committed_batch=last_committed_batch)

    if success_records:
        await _recompute_job_rank_and_tags(
            db,
            job,
            auth_header=request.headers.get("authorization"),
        )
        await db.commit()

    all_failures = read_failures + extract_failures + ai_failures
    await _publish_progress("completed", last_committed_batch=last_committed_batch)
    if all_failures or skipped_duplicates:
        # Mixed/failed bulk outcomes should not be reported as plain "201 Created".
        response.status_code = 207
    elapsed_ms = (time.perf_counter() - _bulk_started_at) * 1000.0
    if elapsed_ms > settings.RECRUITER_BULK_API_SLO_MS:
        logger.warning(
            "Bulk upload exceeded SLO: %.0fms > %dms",
            elapsed_ms,
            settings.RECRUITER_BULK_API_SLO_MS,
        )

    return {
        "orchestrator": "native",
        "degraded_mode": bool(bulk_fast_mode),
        "success": success_records,
        "failed": all_failures,
        "skipped_duplicates": skipped_duplicates,
        "success_count": len(success_records),
        "failed_count": len(all_failures),
        "duplicate_count": len(skipped_duplicates),
    }


@router.post("/upload-bulk-async", status_code=202)
@limiter.limit(BULK_UPLOAD_RATE_LIMIT)
async def upload_bulk_resumes_async(
    request: Request,
    job_id: str = Form(...),
    files: List[UploadFile] = File(...),
    file_ids: List[str] = Form(default=[]),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    """
    Non-blocking bulk upload mode for recruiter UX.
    Returns immediately with an async job id and processes in background.
    """
    max_bulk_files = max(1, int(settings.MAX_BULK_FILES))
    if len(files) > max_bulk_files:
        raise HTTPException(status_code=413, detail=f"Max {max_bulk_files} files per bulk upload")

    await _assert_job_owner(job_id, user, db)

    run_id = str(uuid4())
    client_ids = list(file_ids) if file_ids else [f.filename or f"file_{i}" for i, f in enumerate(files)]
    while len(client_ids) < len(files):
        client_ids.append(f"file_{len(client_ids)}")
    client_ids = client_ids[:len(files)]

    accepted: list[tuple[str, str, str]] = []
    intake_rejected: list[dict] = []
    for f, cid in zip(files, client_ids):
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext not in settings.allowed_extensions_list:
            intake_rejected.append({"filename": f.filename, "file_id": cid, "error": f"File type '{ext or '(none)'}' is not allowed"})
            continue
        try:
            max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
            _precheck_content_length(getattr(f, "headers", None), max_bytes)
            content_arr = bytearray()
            while chunk := await f.read(1024 * 1024):
                content_arr.extend(chunk)
                if len(content_arr) > max_bytes:
                    raise ValueError(f"File exceeds {settings.MAX_FILE_SIZE_MB}MB limit")
            content = bytes(content_arr)
            content = _maybe_decrypt_bulk_upload_content(f.filename or "resume.pdf", ext, content)
            file_service.validate_file_magic(content, ext)
            suffix = ext if ext else ".tmp"
            temp_path = ""
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_fp:
                    temp_fp.write(content)
                    temp_path = temp_fp.name
            except Exception:
                if temp_path:
                    try:
                        os.unlink(temp_path)
                    except FileNotFoundError:
                        pass
                raise
            accepted.append((f.filename or "resume.pdf", temp_path, cid))
        except Exception as e:
            if isinstance(e, HTTPException):
                intake_rejected.append({"filename": f.filename, "file_id": cid, "error": str(e.detail)})
            else:
                logger.exception("Bulk async intake failed for %s", f.filename)
                intake_rejected.append({"filename": f.filename, "file_id": cid, "error": "Failed to read file."})

    if not accepted:
        raise HTTPException(status_code=422, detail={"message": "No valid files accepted for processing", "failed": intake_rejected})

    user_id = str(user.id)
    user_email = str(user.email or "")
    user_role = user.role
    temp_paths = [path for _fname, path, _cid in accepted]

    _set_bulk_job_status(
        run_id,
        id=run_id,
        type="bulk_upload",
        status="queued",
        job_id=job_id,
        owner_user_id=user_id,
        requested_count=len(files),
        accepted_count=len(accepted),
        rejected_count=len(intake_rejected),
        rejected=intake_rejected[:100],
        created_at=_now_iso(),
        started_at=None,
        completed_at=None,
        result=None,
        error=None,
        progress={
            "processed": 0,
            "total": len(files),
            "success_count": 0,
            "failed_count": len(intake_rejected),
            "duplicate_count": 0,
        },
        last_committed_batch=0,
        temp_paths=temp_paths,
    )
    await _persist_bulk_job_status(run_id)

    async def _runner() -> None:
        _set_bulk_job_status(run_id, status="queued")
        await _persist_bulk_job_status(run_id)
        temp_uploads = []

        class _TempUploadFile:
            def __init__(self, filename: str, path: str):
                self.filename = filename
                self._path = path
                self._file = None
                self._closed = False

            async def read(self, size: int = -1) -> bytes:
                if self._closed:
                    return b""
                if self._file is None:
                    self._file = open(self._path, "rb")
                chunk = self._file.read(size)
                if chunk:
                    return chunk
                self.close()
                return b""

            def close(self) -> None:
                if self._closed:
                    return
                self._closed = True
                if self._file is not None:
                    try:
                        self._file.close()
                    except Exception:
                        pass
                    self._file = None
                try:
                    os.unlink(self._path)
                except FileNotFoundError:
                    pass
                except Exception as exc:
                    logger.warning("Failed to delete temp bulk upload file %s: %s", self._path, exc)

        try:
            async with _BULK_ASYNC_JOB_SEMAPHORE:
                _set_bulk_job_status(run_id, status="running", started_at=_now_iso())
                await _persist_bulk_job_status(run_id)

                temp_uploads = [_TempUploadFile(filename=fname, path=path) for fname, path, _cid in accepted]
                star_file_ids = [cid for _fname, _content, cid in accepted]

                class _TaskUser:
                    id = user_id
                    email = user_email
                    role = user_role

                async with AsyncSessionLocal() as task_db:
                    resp = Response()
                    bulk_upload_handler = getattr(upload_bulk_resumes, "__wrapped__", upload_bulk_resumes)
                    result = await bulk_upload_handler(
                        request=request,
                        response=resp,
                        job_id=job_id,
                        files=temp_uploads,
                        file_ids=star_file_ids,
                        progress_run_id=run_id,
                        db=task_db,
                        user=_TaskUser(),
                    )
                    await task_db.commit()

            _set_bulk_job_status(
                run_id,
                status="completed",
                completed_at=_now_iso(),
                temp_paths=[],
                result={
                    "http_status": resp.status_code,
                    "summary": result,
                },
            )
            await _persist_bulk_job_status(run_id)
        except Exception as exc:
            logger.error("Async bulk upload failed: run_id=%s error=%s", run_id, exc, exc_info=exc)
            _set_bulk_job_status(
                run_id,
                status="failed",
                completed_at=_now_iso(),
                error=str(exc),
                temp_paths=[],
            )
            await _persist_bulk_job_status(run_id)
        finally:
            for temp_upload in temp_uploads:
                temp_upload.close()
            for temp_path in temp_paths:
                try:
                    os.unlink(temp_path)
                except FileNotFoundError:
                    continue
                except Exception as exc:
                    logger.warning("Failed to cleanup temp bulk file %s: %s", temp_path, exc)

    try:
        task = asyncio.create_task(_runner())
    except Exception:
        for temp_path in temp_paths:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                continue
            except Exception:
                pass
        raise
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {
        "run_id": run_id,
        "job_id": job_id,
        "status": "started",
        "orchestrator": "native",
        "max_concurrent_jobs": max(1, int(settings.BULK_ASYNC_MAX_CONCURRENT_JOBS)),
        "accepted_count": len(accepted),
        "rejected_count": len(intake_rejected),
        "poll_url": f"/resumes/upload-bulk-async/{run_id}",
    }


@router.get("/upload-bulk-async/{run_id}")
async def get_bulk_upload_async_status(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    data = await _load_bulk_job_status(run_id, db)
    if not data:
        raise HTTPException(status_code=404, detail="Async bulk job not found")
    owner_user_id = str(data.get("owner_user_id") or "")
    if user.role != UserRole.admin and owner_user_id and owner_user_id != str(user.id):
        raise HTTPException(status_code=403, detail="You do not have access to this async bulk job")
    if user.role != UserRole.admin and data.get("job_id"):
        await _assert_job_owner(str(data["job_id"]), user, db)
    # Prevent unbounded in-memory growth: terminal async job statuses are cached
    # for up to 1 hour, then pruned from _BULK_JOB_STATUS.
    _schedule_bulk_status_prune(run_id, data)
    return data


@router.post("/upload-bulk-pool", status_code=201)
@limiter.limit(BULK_UPLOAD_RATE_LIMIT)
async def upload_bulk_pool(
    request: Request,
    response: Response,
    files: List[UploadFile] = File(...),
    file_ids: List[str] = Form(default=[]),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    """Bulk-upload resumes into the general candidate pool (no job attached)."""
    max_bulk_files = max(1, int(settings.BULK_UPLOAD_MAX_FILES))
    if len(files) > max_bulk_files:
        raise HTTPException(status_code=422, detail=f"Max {max_bulk_files} files per bulk upload")

    client_ids = list(file_ids) if file_ids else [
        f.filename or f"file_{i}" for i, f in enumerate(files)]
    while len(client_ids) < len(files):
        client_ids.append(f"file_{len(client_ids)}")
    client_ids = client_ids[:len(files)]

    # FIX (Placebo RAM Batching OOM  pool variant): same root cause as upload_bulk.
    # raw_files.extend() kept all bytes alive; del _batch_raw did nothing.
    # Fix: process each batch in-place; delete bytes after extraction.

    _READ_BATCH = 50
    _file_pairs = list(zip(files, client_ids))

    already_uploaded: set[str] = set()
    # BUG-3 FIX: email dedup now happens inside each batch (see Step 3.5 below)
    # so we track seen emails incrementally rather than post-loop.
    seen_emails_global: set[str] = set()  # emails seen across ALL batches
    read_failures: list[dict] = []
    extract_failures: list[dict] = []
    skipped_duplicates: list[dict] = []
    ai_failures: list[dict] = []
    success_records: list[dict] = []
    bulk_fast_mode = bool(settings.BULK_FAST_MODE or _ai_degraded_mode_active())
    if bulk_fast_mode and not bool(settings.BULK_FAST_MODE):
        logger.warning(
            "[DEGRADED-MODE] Forcing deterministic pool bulk mode because AI backend is unavailable."
        )

    extract_sem = asyncio.Semaphore(max(1, int(settings.BULK_EXTRACT_CONCURRENCY)))
    ai_sem = asyncio.Semaphore(max(1, int(settings.BULK_PARSE_CONCURRENCY)))

    async def _pool_extract(fname: str, content: bytes) -> str:
        async with extract_sem:
            return await file_service.extract_text_from_bytes(fname, content)

    async def _cheap_parse(text: str) -> dict:
        """BUG-3 FIX: cheap parse to extract email BEFORE expensive AI scoring."""
        async with ai_sem:
            if bulk_fast_mode:
                return resume_fallback_parser.coerce_parsed_resume(None, text=text)
            try:
                parsed = await _run_resume_parser_with_fallback(
                    text=text,
                    auth_header=request.headers.get("authorization"),
                )
                return resume_fallback_parser.coerce_parsed_resume(parsed, text=text)
            except Exception as exc:
                logger.warning(
                    "[WARN] Pool pre-parse fell back to fast parser due to AI error: %s",
                    exc,
                )
                return resume_fallback_parser.coerce_parsed_resume(None, text=text)

    async def _pool_score(fname: str, content: bytes, text: str, pre_parsed: dict | None) -> dict:
        async with ai_sem:
            return await _compute_pool_resume_data_from_bytes(
                fname,
                content,
                text,
                user_email=user.email,
                auth_header=request.headers.get("authorization"),
                pre_parsed_data=pre_parsed or None,
            )

    for _bi in range(0, len(_file_pairs), _READ_BATCH):
        _batch_pairs = _file_pairs[_bi: _bi + _READ_BATCH]

        #  Step 1: read + validate 
        _batch_buf: list[tuple[str, bytes, str]] = []
        for f, cid in _batch_pairs:
            _raw_ext = os.path.splitext(f.filename or "")[1].lower()
            if _raw_ext not in settings.allowed_extensions_list:
                read_failures.append({
                    "filename": f.filename, "file_id": cid,
                    "error": f"File type '{_raw_ext or '(none)'}' is not allowed",
                })
                continue
            try:
                _max_bytes = int(settings.MAX_FILE_SIZE_BYTES)
                _precheck_content_length(getattr(f, "headers", None), _max_bytes)
                _chunk_size = 4 * 1024 * 1024
                content_arr = bytearray()
                oversized = False
                while chunk := await f.read(_chunk_size):
                    content_arr.extend(chunk)
                    if len(content_arr) > _max_bytes:
                        read_failures.append({
                            "filename": f.filename,
                            "file_id": cid,
                            "warning": f"Skipped: file exceeds {settings.MAX_FILE_SIZE_MB}MB limit",
                        })
                        oversized = True
                        break
                if oversized:
                    continue
                content = bytes(content_arr)
                content = _maybe_decrypt_bulk_upload_content(f.filename or "resume.pdf", _raw_ext, content)
                file_service.validate_file_magic(content, _raw_ext)
                _batch_buf.append((f.filename or "resume.pdf", content, cid))
            except Exception as e:
                if isinstance(e, HTTPException):
                    read_failures.append({"filename": f.filename, "file_id": cid, "error": str(e.detail)})
                else:
                    logger.exception("Bulk pool read failed for %s", f.filename)
                    read_failures.append({"filename": f.filename, "file_id": cid, "error": "Failed to read file."})

        if not _batch_buf:
            continue

        #  Step 2: hash dedup (global for pool  no job scope) 
        _batch_hashes = {cid: _sha256(content) for _, content, cid in _batch_buf}
        _new_hashes = [h for h in _batch_hashes.values() if h not in already_uploaded]
        if _new_hashes:
            _existing = await _existing_hashes(db, _new_hashes, owner_user_id=str(user.id))
            already_uploaded.update(_existing)

        _dedup_buf: list[tuple[str, bytes, str]] = []
        for fname, content, cid in _batch_buf:
            h = _batch_hashes[cid]
            if h in already_uploaded:
                skipped_duplicates.append(
                    {"filename": fname, "file_id": cid, "reason": "duplicate_file"})
            else:
                _dedup_buf.append((fname, content, cid))
                already_uploaded.add(h)
        del _batch_buf

        if not _dedup_buf:
            continue

        #  Step 3: extract text 
        _extr = await asyncio.gather(
            *[_pool_extract(fname, content) for fname, content, _ in _dedup_buf],
            return_exceptions=True,
        )

        _text_buf: list[tuple[str, bytes, str, str]] = []
        for (fname, content, cid), result in zip(_dedup_buf, _extr):
            if isinstance(result, Exception):
                _log_worker_error("[ERROR] Pool extract failed for %s: %s", fname, result)
                extract_failures.append({"filename": fname, "file_id": cid, "error": str(result)})
            else:
                _text_buf.append((fname, content, result, cid))
        del _dedup_buf

        if not _text_buf:
            continue

        #  Step 3.5: Cheap parse for email dedup (BUG-3 FIX) 
        # Parse resumes cheaply to extract emails BEFORE spending LLM budget on
        # AI scoring. Duplicates caught here skip _pool_score entirely, saving
        # Azure OpenAI API calls and disk writes for already-known candidates.
        _parsed_results = await asyncio.gather(
            *[_cheap_parse(text) for _, _, text, _ in _text_buf],
            return_exceptions=True,
        )

        _score_buf: list[tuple[str, bytes, str, str]] = []
        _score_buf_parsed: list[dict | None] = []  # BUG-NEW-1 FIX: carry parse result to avoid re-parse
        # fetch existing emails for this batch from DB
        _batch_emails = [
            r.get("email") for r in _parsed_results
            if not isinstance(r, Exception) and r.get("email")
        ]
        _db_existing_emails = await _existing_pool_emails(
            db,
            _batch_emails,
            owner_user_id=str(user.id),
        )

        for (fname, content, text, cid), parsed in zip(_text_buf, _parsed_results):
            if isinstance(parsed, Exception):
                # parse failed  still try full AI scoring (it re-parses internally)
                _score_buf.append((fname, content, text, cid))
                _score_buf_parsed.append(None)
                continue
            email_key = (parsed.get("email") or "").lower().strip()
            if email_key and (email_key in _db_existing_emails or email_key in seen_emails_global):
                skipped_duplicates.append({
                    "filename": fname, "file_id": cid,
                    "reason": "duplicate_email",
                    "email": parsed.get("email"),
                })
            else:
                _score_buf.append((fname, content, text, cid))
                _score_buf_parsed.append(parsed)  # BUG-NEW-1 FIX: pass cached parse
                if email_key:
                    seen_emails_global.add(email_key)
        del _text_buf

        if not _score_buf:
            continue

        #  Step 4: AI score (only non-duplicate candidates) 
        # BUG-NEW-1 FIX: pass pre_parsed so _compute_pool_resume_data_from_bytes skips re-parse
        _scored = await asyncio.gather(
            *[_pool_score(fname, content, text, pre_parsed)
              for (fname, content, text, _cid), pre_parsed in zip(_score_buf, _score_buf_parsed)],
            return_exceptions=True,
        )

        for (fname, _content, _text, cid), result in zip(_score_buf, _scored):
            if isinstance(result, Exception):
                _log_worker_error("[ERROR] Pool AI failed for %s: %s", fname, result)
                ai_failures.append({"filename": fname, "file_id": cid, "error": str(result)})
            else:
                try:
                    candidate = await _insert_pool_candidate_atomic(
                        db,
                        {**result, "user_id": user.id},
                    )
                    if candidate is None:
                        skipped_duplicates.append(
                            {"filename": fname, "file_id": cid, "reason": "duplicate_email"}
                        )
                        await db.rollback()
                        continue
                    await log_action(db, user.id, "UPLOAD_RESUME_POOL", "candidate", candidate.id)
                    await db.commit()
                    success_records.append({"filename": fname, "file_id": cid,
                                           "candidate_id": candidate.id})
                except Exception as e:
                    await db.rollback()
                    logger.error("DB save failed for %s: %s", fname, e)
                    ai_failures.append({"filename": fname, "file_id": cid,
                                       "error": f"DB save failed: {e}"})
        del _score_buf

    all_failures = read_failures + extract_failures + ai_failures
    if all_failures or skipped_duplicates:
        # Mixed/failed bulk outcomes should not be reported as plain "201 Created".
        response.status_code = 207

    return {
        "degraded_mode": bool(bulk_fast_mode),
        "success": success_records,
        "failed": all_failures,
        "skipped_duplicates": skipped_duplicates,
        "success_count": len(success_records),
        "failed_count": len(all_failures),
        "duplicate_count": len(skipped_duplicates),
    }


@router.get("/pool-matches", response_model=List[PoolMatchOut])
async def get_pool_matches(
    job_id: str,
    min_score: float = 0.0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    job = await _assert_job_owner(job_id, user, db)

    # BUG 2 FIX: the original query fetched ALL pool candidates (job_id IS NULL)
    # regardless of who uploaded them, exposing every other HR user's pool resumes.
    # Admins may see everything; HR users only see pool candidates they uploaded.
    # BUG 8 FIX: original query had no LIMIT  at 50k candidates this would
    # exhaust memory. Hard-cap at 2000 rows sorted by recency for safety.
    # NOTE: Do NOT pre-filter by resume_score here  pool candidates are stored
    # with resume_score=0.0 (no JD to score against at upload time). Filtering
    # by score would exclude the entire pool. Dynamic scoring happens below.
    pool_query = (
        select(Candidate)
        .where(Candidate.job_id.is_(None))
        .order_by(Candidate.created_at.desc())
        .limit(2000)
    )
    if user.role != UserRole.admin:
        pool_query = pool_query.where(Candidate.user_id == user.id)
    pool = (await db.execute(pool_query)).scalars().all()

    results = []
    for c in pool:
        skill_pct = scoring_service.skill_match_score(
            c.normalized_skills or [], job.must_have_skills or [], job.good_to_have_skills or [])
        exp_years = float(c.experience_years or 0)
        skill_years_c = getattr(c, 'skill_years', None) or {}
        exp_pct = scoring_service.experience_match_score(
            exp_years, job.experience_min, job.experience_max, skill_years_c, job.must_have_skills or [])
        proj_pct = scoring_service.project_relevance_score(
            c.projects or [], job.must_have_skills or [], job.good_to_have_skills or [], exp_years)
        edu_pct = scoring_service.education_match_score(
            c.education or [],
            experience_years=exp_years,
            jd_description=job.description or "",
            jd_must_have=job.must_have_skills or [],
            jd_education_requirement=getattr(job, "education_requirement", None),
        )
        loc_pct = scoring_service.location_match_score(getattr(c, "location", None), job.location)
        try:
            vec_sim = scoring_service.cosine_similarity(c.embedding or [], job.embedding or [])
        except ValueError as vec_err:
            logger.warning("Vector similarity degraded during pool import for candidate %s: %s", c.id, vec_err)
            vec_sim = 0.0

        # FIX: Pool candidates have embedding=[]  vec_sim=0.0. The vector weight
        # still occupies the denominator, deflating pool scores by ~5% vs post-import.
        # Renormalize weights excluding vector when embedding is unavailable.
        has_embedding = bool(c.embedding)
        phase_b_weights, phase_b_bias, phase_b_meta = scoring_service.build_phase_b_calibration(
            experience_years=exp_years,
            job_title=job.title,
            job_role=job.role,
            jd_description=job.description or "",
            jd_must_have=job.must_have_skills or [],
            jd_good_to_have=job.good_to_have_skills or [],
            exp_min=job.experience_min,
            exp_max=job.experience_max,
        )
        missing_must_count = sum(
            1
            for skill in (job.must_have_skills or [])
            if not scoring_service.semantic_skill_match(skill, c.normalized_skills or [])
        )
        score, _, _, _ = scoring_service.compute_resume_score_with_ai_override(
            ai_scores=None,
            education_pct=edu_pct,
            vector_sim=vec_sim,
            location_pct=loc_pct,
            experience_years=exp_years,
            rule_skill_pct=skill_pct,
            rule_exp_pct=exp_pct,
            rule_proj_pct=proj_pct,
            critical_missing_count=missing_must_count,
            has_jd_skills=_job_has_meaningful_criteria(job),
            total_must_have_count=len(job.must_have_skills or []),
            vector_available=has_embedding and bool(job.embedding or []),
            calibrated_weights=phase_b_weights,
            score_bias_points=phase_b_bias,
            phase_c_enabled=bool(settings.PHASE_C_SCORING_ENABLED),
            ai_confidence=None,
            jd_signal_strength=phase_b_meta.get("jd_signal_strength"),
            required_skills=job.must_have_skills or [],
            work_experience=c.work_experience or [],
            skill_years=skill_years_c,
        )
        score = round(score, 2)
        tag = scoring_service.assign_tag(score)

        if score < min_score:
            continue

        results.append(PoolMatchOut(
            id=c.id, name=c.name, email=c.email, phone=c.phone,
            skills=c.skills or [], normalized_skills=c.normalized_skills or [],
            experience_years=float(c.experience_years or 0),
            computed_resume_score=round(score, 2),
            computed_skill_match_pct=round(skill_pct, 2),
            computed_experience_match_pct=round(exp_pct, 2),
            computed_tag=tag,
        ))

    results.sort(key=lambda r: r.computed_resume_score, reverse=True)
    return results


@router.post("/import-from-pool", response_model=dict)
@limiter.limit(AI_SCORING_RANKING_RATE_LIMIT)
async def import_from_pool(
    request: Request,
    body: ImportFromPoolRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    # Concurrency is preserved in resume_pool.import_from_pool_impl via asyncio.gather.
    return await import_from_pool_impl(
        request=request,
        body=body,
        db=db,
        user=user,
        logger=logger,
        assert_job_owner=_assert_job_owner,
        jd_signature_hash=_jd_signature_hash,
        job_has_meaningful_criteria=_job_has_meaningful_criteria,
        recompute_job_rank_and_tags=_recompute_job_rank_and_tags,
    )


# --- Aggregate stats (dashboard summary  no full rows returned) ---
class PipelineStats(BaseModel):
    total_candidates: int
    shortlisted: int
    hired: int
    tested: int        # has a quiz_score
    final_ranked: int  # has a final_score
    avg_quiz_score: Optional[float]


@router.get("/stats", response_model=PipelineStats)
async def get_pipeline_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    """
    Lightweight aggregate counts used by the Dashboard summary cards and
    hiring funnel chart. Returns only numbers  no candidate rows  so it
    never transmits embeddings, score breakdowns, or work_experience blobs
    regardless of how many candidates exist.
    """
    from sqlalchemy import and_ as _and, func as _func, or_ as _or
    from sqlalchemy.exc import OperationalError

    # Build ownership filters (scoped per HR user or all for admin).
    ownership_filters = []
    if user.role != UserRole.admin:
        owned = select(JobDescription.id).where(JobDescription.created_by == user.id)
        ownership_filters.append(
            _or(
                Candidate.job_id.in_(owned),
                _and(Candidate.job_id.is_(None), Candidate.user_id == user.id),
            )
        )

    # is_archived requires migrate_all.py to have been run.
    # Try with the filter first; if the column doesn't exist yet (OperationalError
    # on SQLite, or ProgrammingError on PostgreSQL) fall back to no archive filter
    # so the endpoint never returns a 500 due to a missing migration.
    archive_filter_candidates = [Candidate.is_archived == False]
    try:
        await db.execute(
            select(_func.count(Candidate.id)).where(*archive_filter_candidates)
        )
    except (OperationalError, Exception) as _col_check_err:
        if "no such column" in str(_col_check_err).lower() or \
           "column" in str(_col_check_err).lower():
            archive_filter_candidates = []   # column missing  skip the filter
        # else re-raise genuine DB errors
        else:
            raise

    active_filters = ownership_filters + archive_filter_candidates

    def _count(*extra_where):
        return select(_func.count(Candidate.id)).where(*active_filters, *extra_where)

    total = (await db.execute(_count())).scalar_one()
    shortlisted = (
        await db.execute(_count(Candidate.tag.in_([CandidateTag.strong, CandidateTag.medium])))
    ).scalar_one()
    hired = 0  # "Hired" is not a CandidateTag value; remove or track separately
    tested = (await db.execute(_count(Candidate.quiz_score.isnot(None)))).scalar_one()
    final_ranked = (await db.execute(_count(Candidate.final_score.isnot(None)))).scalar_one()

    avg_row = (await db.execute(
        select(
            _func.avg(
                (QuizAttempt.raw_score * 100.0) / _func.nullif(QuizAttempt.max_score, 0)
            )
        )
        .join(Candidate, Candidate.id == QuizAttempt.candidate_id)
        .where(
            *active_filters,
            QuizAttempt.status == QuizStatus.submitted,
            QuizAttempt.raw_score.isnot(None),
            QuizAttempt.max_score.isnot(None),
            QuizAttempt.max_score > 0,
        )
    )).scalar_one()
    avg_quiz = round(float(avg_row), 1) if avg_row is not None else None

    return PipelineStats(
        total_candidates=total,
        shortlisted=shortlisted,
        hired=hired,
        tested=tested,
        final_ranked=final_ranked,
        avg_quiz_score=avg_quiz,
    )


@router.get("/audit-trail", response_model=List[AuditLogOut])
async def get_recruiter_audit_trail(
    limit: int = Query(default=50, ge=1, le=200),
    resource: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    query = (
        select(AuditLog)
        .where(AuditLog.user_id == user.id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    if resource:
        query = query.where(AuditLog.resource == resource)
    return (await db.execute(query)).scalars().all()


@router.get("/all-data", response_model=List[CandidateListOut])
async def get_all_data(
    search: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    """
    Master resume database  returns EVERY candidate ever uploaded (active AND
    archived). Ownership: admins see everything; HR users see candidates from
    their own jobs plus pool candidates they uploaded.

    BUG 8 FIX: uses CandidateListOut instead of CandidateOut to avoid returning
    embedding vectors (~6 KB each) and work_experience blobs in bulk list responses.
    """
    from sqlalchemy import and_, or_
    if user.role == UserRole.admin:
        query = select(Candidate).options(load_only(*_CANDIDATE_ALL_DATA_LOAD_ONLY))
    else:
        owned_job_ids = select(JobDescription.id).where(JobDescription.created_by == user.id)
        pool_owned_filter = and_(
            Candidate.job_id.is_(None),
            Candidate.user_id == user.id,
        )
        query = select(Candidate).options(load_only(*_CANDIDATE_ALL_DATA_LOAD_ONLY)).where(
            or_(
                Candidate.job_id.in_(owned_job_ids),
                pool_owned_filter,
            )
        )
    if search:
        # FIX 6: Escape SQL LIKE metacharacters before wrapping in wildcards.
        # An unescaped "%%%%%" forces a catastrophic full-table scan.
        # "_%__%_" causes backtracking that can stall the DB for seconds.
        _search_escaped = (
            search.lower()
            .replace("\\", "\\\\")   # escape backslash first
            .replace("%", "\\%")          # then percent wildcard
            .replace("_", "\\_")          # then single-char wildcard
        )
        search_like = f"%{_search_escaped}%"
        from sqlalchemy import func
        query = query.where(
            or_(
                func.lower(func.coalesce(Candidate.name, "")).like(search_like, escape="\\"),
                func.lower(func.coalesce(Candidate.email, "")).like(search_like, escape="\\"),
            )
        )
    query = query.offset(skip).limit(limit).order_by(Candidate.created_at.desc())
    return (await db.execute(query)).scalars().all()


@router.get("/", response_model=List[CandidatePipelineListOut])
async def list_candidates(
    job_id: Optional[str] = None,
    tag: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    query = select(Candidate).options(load_only(*_CANDIDATE_LIST_LOAD_ONLY))
    if user.role != UserRole.admin:
        from sqlalchemy import and_, or_
        owned_job_ids = select(JobDescription.id).where(JobDescription.created_by == user.id)
        query = query.where(
            or_(
                Candidate.job_id.in_(owned_job_ids),
                and_(Candidate.job_id.is_(None), Candidate.user_id == user.id),
            )
        )
    if job_id:
        if user.role != UserRole.admin:
            await _assert_job_owner(job_id, user, db)
        query = query.where(Candidate.job_id == job_id)
    if tag:
        normalized_tag = CandidateTag._missing_(tag) if isinstance(tag, str) else tag
        if normalized_tag is None:
            raise HTTPException(status_code=422, detail="Invalid tag. Use Strong, Medium, or Reject.")
        query = query.where(Candidate.tag == normalized_tag)
    # BUG-5 FIX: is_archived == False excludes rows where is_archived IS NULL
    # (all records created before add_is_archived_migration.py ran). Those candidates
    # silently disappear from the pipeline view. Include NULL rows explicitly.
    from sqlalchemy import or_ as _or_archived
    query = query.where(_or_archived(Candidate.is_archived == False, Candidate.is_archived.is_(None)))
    from sqlalchemy import func as _func_order
    query = query.offset(skip).limit(limit).order_by(
        _func_order.coalesce(Candidate.final_score, Candidate.resume_score, 0.0).desc()
    )
    return (await db.execute(query)).scalars().all()


@router.post("/shortlist", response_model=MessageResponse)
@limiter.limit(AI_SCORING_RANKING_RATE_LIMIT)
async def run_shortlisting(
    request: Request,
    job_id: str,
    strong_threshold: float = STRONG_SHORTLIST_THRESHOLD,
    medium_threshold: float = MEDIUM_THRESHOLD,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    job = await _assert_job_owner(job_id, user, db)
    lock = _SHORTLIST_LOCKS.setdefault(job_id, asyncio.Lock())
    if lock.locked():
        return {"message": "Ranking already in progress for this job. Please wait."}

    async with lock:
        candidates = (await db.execute(
            select(Candidate).where(
                Candidate.job_id == job_id,
                Candidate.is_archived == False,
            )
        )).scalars().all()
        await _recompute_job_rank_and_tags(
            db,
            job,
            strong_threshold=strong_threshold,
            medium_threshold=medium_threshold,
            auth_header=request.headers.get("authorization"),
        )
        await log_action(db, user.id, "RUN_SHORTLISTING", "job_description", job_id)
        await db.commit()
        return {"message": f"Shortlisting complete for {len(candidates)} candidates"}


class BulkArchiveRequest(BaseModel):
    candidate_ids: list[str]


@router.post("/bulk-archive")
@limiter.limit(BULK_UPLOAD_RATE_LIMIT)
async def bulk_archive_candidates(
    request: Request,
    body: BulkArchiveRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    """
    Soft-remove candidates from the active pipeline by setting is_archived=True.
    Archived candidates remain permanently visible in GET /resumes/all-data.
    """
    from sqlalchemy import update as sql_update
    if not body.candidate_ids:
        return {"message": "No candidates provided", "archived": 0}

    try:
        await assert_bulk_candidate_access(db, user=user, candidate_ids=body.candidate_ids)

        result = await db.execute(
            sql_update(Candidate)
            .where(Candidate.id.in_(body.candidate_ids))
            .values(is_archived=True)
        )
        archived_count = result.rowcount
        await log_action(db, user.id, "ARCHIVE_CANDIDATES", "candidate",
                         details={"count": archived_count, "ids": body.candidate_ids[:10]})
        await db.commit()
        return {"message": f"Archived {archived_count} candidate(s) to master database", "archived": archived_count}
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to archive candidates.")


@router.post("/bulk-restore")
@limiter.limit(BULK_UPLOAD_RATE_LIMIT)
async def bulk_restore_candidates(
    request: Request,
    body: BulkArchiveRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    """Restore previously archived candidates back to the active pipeline."""
    from sqlalchemy import update as sql_update
    if not body.candidate_ids:
        return {"message": "No candidates provided", "restored": 0}

    try:
        await assert_bulk_candidate_access(db, user=user, candidate_ids=body.candidate_ids)

        result = await db.execute(
            sql_update(Candidate)
            .where(Candidate.id.in_(body.candidate_ids))
            .values(is_archived=False)
        )
        restored_count = result.rowcount
        await log_action(db, user.id, "RESTORE_CANDIDATES", "candidate",
                         details={"count": restored_count, "ids": body.candidate_ids[:10]})
        await db.commit()
        return {"message": f"Restored {restored_count} candidate(s) to active pipeline", "restored": restored_count}
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to restore candidates.")


@router.post("/bulk-delete")
@limiter.limit(BULK_UPLOAD_RATE_LIMIT)
async def bulk_delete_candidates(
    request: Request,
    body: BulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    from sqlalchemy import delete, func
    if not body.candidate_ids:
        return {"message": "No candidates provided"}

    _CHUNK = 500
    try:
        await assert_bulk_candidate_access(db, user=user, candidate_ids=body.candidate_ids)

        from app.models import QuizAttempt

        # Collect resume file paths before DB deletion for cleanup after commit
        paths_to_delete = set((await db.execute(
            select(Candidate.resume_path).where(
                Candidate.id.in_(body.candidate_ids),
                Candidate.resume_path.isnot(None),
            )
        )).scalars().all())
        path_usage_counts: dict[str, int] = {}
        if paths_to_delete:
            usage_rows = (await db.execute(
                select(Candidate.resume_path, func.count(Candidate.id))
                .where(
                    Candidate.resume_path.in_(paths_to_delete),
                    Candidate.id.notin_(body.candidate_ids),
                )
                .group_by(Candidate.resume_path)
            )).all()
            path_usage_counts = {str(path): int(count or 0) for path, count in usage_rows if path}
        upload_dir = os.path.realpath(settings.UPLOAD_DIR)
        safe_paths_to_unlink: list[str] = []
        for path in paths_to_delete:
            real = os.path.realpath(path)
            if real.startswith(upload_dir + os.sep) and os.path.exists(real):
                usage_count = path_usage_counts.get(path, 0)
                if usage_count and usage_count > 0:
                    continue
                safe_paths_to_unlink.append(real)

        for i in range(0, len(body.candidate_ids), _CHUNK):
            chunk = body.candidate_ids[i: i + _CHUNK]
            await db.execute(delete(QuizAttempt).where(QuizAttempt.candidate_id.in_(chunk)))
            await db.execute(delete(Candidate).where(Candidate.id.in_(chunk)))
        await db.commit()

        # FIX Finding 5: delete physical files AFTER DB commit succeeds
        # to prevent data loss if the commit fails and rolls back
        for real in safe_paths_to_unlink:
            try:
                os.unlink(real)
            except OSError as e:
                logger.warning("Could not delete resume file %s: %s", real, e)

        return {"message": f"Successfully deleted {len(body.candidate_ids)} candidates"}
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete candidates.")


@router.post("/jobs/{job_id}/refresh-jd-similarity")
@limiter.limit(AI_SCORING_RANKING_RATE_LIMIT)
async def refresh_job_jd_similarity(
    request: Request,
    job_id: str,
    limit: int = Query(200, ge=1, le=2000),
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    """
    Backfill candidate embeddings and vector_similarity for one job.

    Intended for candidates previously processed in degraded/fast mode, where
    resume embeddings were skipped and JD similarity stayed at 0.
    """
    job = await _assert_job_owner(job_id, user, db)

    if _ai_degraded_mode_active():
        raise HTTPException(
            status_code=503,
            detail="AI is currently in degraded mode. Retry similarity refresh once AI is healthy.",
        )

    if not (job.embedding or []):
        raise HTTPException(
            status_code=422,
            detail="Job embedding is missing. Recreate or re-parse the job before refreshing JD similarity.",
        )

    # Fail fast when embeddings are unavailable, instead of returning a long
    # list of per-candidate failures.
    async with _AI_SEMAPHORE:
        probe_embedding = await _run_embedding_with_fallback(
            text="jd similarity refresh health check",
            auth_header=request.headers.get("authorization"),
        )
    if not probe_embedding:
        raise HTTPException(
            status_code=503,
            detail="Embedding service is currently unavailable. Retry when AI connectivity is restored.",
        )

    from sqlalchemy import or_ as _or_archived

    filters = [Candidate.job_id == job.id]
    if not include_archived:
        filters.append(_or_archived(Candidate.is_archived == False, Candidate.is_archived.is_(None)))

    candidates = (await db.execute(
        select(Candidate)
        .where(*filters)
        .order_by(Candidate.created_at.desc())
        .limit(limit)
    )).scalars().all()

    processed = 0
    updated = 0
    skipped_no_text = 0
    failed = 0
    failed_candidates: list[dict[str, str]] = []

    for c in candidates:
        processed += 1

        try:
            if not c.raw_resume_text:
                skipped_no_text += 1
                continue

            resume_text = encryption_service.decrypt_text(c.raw_resume_text) or ""
            if not resume_text.strip():
                skipped_no_text += 1
                continue

            async with _AI_SEMAPHORE:
                resume_embedding = await _run_embedding_with_fallback(
                    text=resume_text[:12000],
                    auth_header=request.headers.get("authorization"),
                )
            if not resume_embedding:
                failed += 1
                failed_candidates.append({
                    "candidate_id": str(c.id),
                    "reason": "embedding_unavailable",
                })
                continue

            c.embedding = resume_embedding
            try:
                c.vector_similarity = scoring_service.cosine_similarity(resume_embedding, job.embedding or [])
            except ValueError as vec_err:
                logger.warning("Vector similarity degraded during recompute for candidate %s: %s", c.id, vec_err)
                c.vector_similarity = 0.0

            breakdown = dict(c.score_breakdown or {})
            breakdown["jd_similarity_refreshed_at"] = _now_iso()
            # Candidate was successfully refreshed against live AI.
            breakdown["fast_mode"] = False
            breakdown["degraded_mode"] = False
            c.score_breakdown = breakdown
            updated += 1
        except Exception as exc:
            failed += 1
            failed_candidates.append({
                "candidate_id": str(c.id),
                "reason": str(exc)[:200],
            })

    await log_action(
        db,
        user.id,
        "REFRESH_JD_SIMILARITY",
        "job_description",
        job_id,
        details={
            "processed": processed,
            "updated": updated,
            "skipped_no_text": skipped_no_text,
            "failed": failed,
            "include_archived": include_archived,
            "limit": limit,
        },
    )
    await db.commit()

    return {
        "message": "JD similarity refresh completed",
        "job_id": job_id,
        "processed": processed,
        "updated": updated,
        "skipped_no_text": skipped_no_text,
        "failed": failed,
        "failed_candidates": failed_candidates[:25],
    }


#  Dynamic /{candidate_id} routes (must come after all static routes) 

@router.get("/{candidate_id}", response_model=CandidateOut)
async def get_candidate(
    candidate_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    candidate = await _assert_candidate_owner(candidate_id, user, db)
    return await _enriched_candidate_out(candidate, db)


@router.patch("/{candidate_id}", response_model=CandidateOut)
async def update_candidate(
    request: Request,
    candidate_id: str,
    body: CandidateUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    c = await _assert_candidate_owner(candidate_id, user, db)
    old_tag = c.tag

    updates = body.model_dump(exclude_unset=True)
    if "tag" in updates:
        updates["tag"] = _normalize_candidate_tag(updates.get("tag"))

    for field, value in updates.items():
        if hasattr(c, field):
            setattr(c, field, value)
    await db.flush()
    if c.job_id:
        job = await db.get(JobDescription, c.job_id)
        if job is not None:
            await _recompute_job_rank_and_tags(
                db,
                job,
                auth_header=request.headers.get("authorization"),
            )

    new_tag = c.tag
    if new_tag and new_tag != old_tag:
        tag_messages = {
            "Strong": (" Candidate marked Strong", "Great news! Your application has been marked as Strong by the hiring team."),
            "Medium": (" Candidate marked Medium", "Your application is under review by the hiring team."),
            "Reject": (" Candidate marked Reject", "The hiring team has updated your application status."),
        }
        hr_title, cand_msg = tag_messages.get(
            (new_tag.value if hasattr(new_tag, "value") else str(new_tag)).capitalize(),
            ("Status updated", "Your application status was updated.")
        )
        try:
            await push_notification(
                db, user.id,
                title=hr_title,
                message=f"{html.escape(c.name or 'Candidate')}  Resume score: {c.resume_score:.1f}%",
                ntype=NotificationType.tag_updated,
                related_id=candidate_id,
            )
            if c.email:
                await push_to_candidate_by_email(
                    db, c.email,
                    title="Your application status was updated",
                    message=cand_msg,
                    ntype=NotificationType.tag_updated,
                    related_id=c.job_id,
                )
        except Exception as notif_err:
            logger.warning("Non-fatal notification error during tag update: %s", notif_err)

    await db.commit()
    await db.refresh(c)
    return c


@router.post("/{candidate_id}/hire-approval", response_model=CandidateHireApprovalOut)
async def set_hire_approval(
    candidate_id: str,
    body: CandidateHireApprovalUpdate,
    db: AsyncSession = Depends(get_db),
    kyc_db: AsyncSession = Depends(get_kyc_db),
    user: User = Depends(require_hr),
):
    candidate = await _assert_candidate_owner(candidate_id, user, db)
    if not candidate.user_id or not candidate.job_id:
        raise HTTPException(status_code=422, detail="Hire approval requires a job-linked candidate profile")
    if candidate.tag not in (CandidateTag.strong, CandidateTag.medium):
        raise HTTPException(status_code=422, detail="Only shortlisted candidates can be marked approved to hire")

    existing = (await kyc_db.execute(
        select(CandidateHireApproval).where(
            CandidateHireApproval.candidate_id == candidate.id,
            CandidateHireApproval.candidate_user_id == candidate.user_id,
            CandidateHireApproval.recruiter_user_id == user.id,
            CandidateHireApproval.job_id == candidate.job_id,
        )
    )).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if existing:
        existing.approved = bool(body.approved)
        existing.approved_at = now if body.approved else existing.approved_at
        existing.revoked_at = None if body.approved else now
        target = existing
    else:
        target = CandidateHireApproval(
            candidate_id=candidate.id,
            candidate_user_id=candidate.user_id,
            recruiter_user_id=user.id,
            job_id=candidate.job_id,
            approved=bool(body.approved),
            approved_at=(now if body.approved else None),
            revoked_at=(None if body.approved else now),
        )
        kyc_db.add(target)

    await kyc_db.commit()
    await kyc_db.refresh(target)
    return CandidateHireApprovalOut(
        candidate_id=target.candidate_id,
        recruiter_user_id=target.recruiter_user_id,
        job_id=target.job_id,
        approved=bool(target.approved),
        approved_at=target.approved_at,
        revoked_at=target.revoked_at,
        updated_at=target.updated_at,
    )


@router.post("/{candidate_id}/kyc-invite", response_model=CandidateKycInviteOut)
async def create_candidate_kyc_invite(
    candidate_id: str,
    body: CandidateKycInviteCreate,
    db: AsyncSession = Depends(get_db),
    kyc_db: AsyncSession = Depends(get_kyc_db),
    user: User = Depends(require_hr),
):
    candidate = await _assert_candidate_owner(candidate_id, user, db)
    if not candidate.user_id or not candidate.job_id:
        raise HTTPException(status_code=422, detail="KYC invite requires a job-linked candidate profile")
    if candidate.tag not in (CandidateTag.strong, CandidateTag.medium):
        raise HTTPException(status_code=422, detail="KYC invite is allowed only for shortlisted candidates")

    approval = (await kyc_db.execute(
        select(CandidateHireApproval).where(
            CandidateHireApproval.candidate_id == candidate.id,
            CandidateHireApproval.candidate_user_id == candidate.user_id,
            CandidateHireApproval.recruiter_user_id == user.id,
            CandidateHireApproval.job_id == candidate.job_id,
        )
    )).scalar_one_or_none()
    if not approval or not bool(approval.approved) or approval.revoked_at is not None:
        raise HTTPException(status_code=422, detail="Approve to hire before sending KYC upload link")

    now = _utc_now()
    prior_active = (await kyc_db.execute(
        select(CandidateKycInvite).where(
            CandidateKycInvite.candidate_id == candidate.id,
            CandidateKycInvite.candidate_user_id == candidate.user_id,
            CandidateKycInvite.recruiter_user_id == user.id,
            CandidateKycInvite.job_id == candidate.job_id,
            CandidateKycInvite.used_at.is_(None),
            CandidateKycInvite.revoked_at.is_(None),
            CandidateKycInvite.expires_at > now,
        )
    )).scalars().all()
    for old_invite in prior_active:
        old_invite.revoked_at = now

    raw_token = secrets.token_urlsafe(36)
    token_hash = _kyc_invite_token_hash(raw_token)
    expires_minutes = int(body.expires_minutes or settings.KYC_MAGIC_LINK_EXPIRE_MINUTES)
    expires_minutes = max(5, min(1440, expires_minutes))
    retention_days = int(body.retention_days or settings.KYC_DEFAULT_RETENTION_DAYS)
    retention_days = max(30, min(90, retention_days))

    invite = CandidateKycInvite(
        candidate_id=candidate.id,
        candidate_user_id=candidate.user_id,
        recruiter_user_id=user.id,
        job_id=candidate.job_id,
        token_hash=token_hash,
        purpose=(body.purpose or "").strip() or "Identity verification for final hiring decision.",
        access_scope=(body.access_scope or "").strip() or (
            "Only the assigned recruiter and authorized hiring operations reviewer."
        ),
        retention_days=retention_days,
        require_masked_aadhaar=bool(body.require_masked_aadhaar),
        legal_hold_required=bool(body.legal_hold_required),
        expires_at=now + timedelta(minutes=expires_minutes),
    )
    kyc_db.add(invite)
    await kyc_db.commit()
    await kyc_db.refresh(invite)

    kyc_link = _build_candidate_kyc_magic_link(raw_token)
    jd = await db.get(JobDescription, candidate.job_id)
    safe_job_title = (jd.title if jd else "your application").strip()
    notif_message = (
        f"You are in the final verification stage for {safe_job_title}. "
        f"Upload KYC documents using your one-time secure link: {kyc_link}"
    )
    if candidate.user_id:
        await push_notification(
            db,
            candidate.user_id,
            title="Secure KYC Upload Link",
            message=notif_message,
            ntype=NotificationType.system,
            related_id=candidate.id,
        )
    if candidate.email:
        await push_to_candidate_by_email(
            db,
            candidate.email,
            title="Secure KYC Upload Link",
            message=notif_message,
            ntype=NotificationType.system,
            related_id=candidate.id,
        )
    await db.commit()

    await log_action(
        db,
        user.id,
        "CREATE_KYC_MAGIC_LINK",
        "candidate",
        candidate.id,
        details={
            "candidate_id": candidate.id,
            "job_id": candidate.job_id,
            "expires_minutes": expires_minutes,
            "retention_days": retention_days,
            "require_masked_aadhaar": bool(body.require_masked_aadhaar),
            "legal_hold_required": bool(body.legal_hold_required),
        },
    )
    await db.commit()

    return CandidateKycInviteOut(
        invite_id=invite.id,
        candidate_id=invite.candidate_id,
        recruiter_user_id=invite.recruiter_user_id,
        job_id=invite.job_id,
        upload_url=kyc_link,
        expires_at=invite.expires_at,
        retention_days=int(invite.retention_days),
        require_masked_aadhaar=bool(invite.require_masked_aadhaar),
        legal_hold_required=bool(invite.legal_hold_required),
        purpose=invite.purpose,
        access_scope=invite.access_scope,
    )


@router.get("/{candidate_id}/kyc-documents", response_model=list[CandidateKycRecruiterStatusOut])
async def list_candidate_kyc_documents(
    candidate_id: str,
    db: AsyncSession = Depends(get_db),
    kyc_db: AsyncSession = Depends(get_kyc_db),
    user: User = Depends(require_hr),
):
    candidate = await _assert_candidate_owner(candidate_id, user, db)
    await _assert_recruiter_kyc_access(
        candidate=candidate,
        recruiter_user_id=user.id,
        kyc_db=kyc_db,
    )
    docs = (await kyc_db.execute(
        select(CandidateKycDocument)
        .where(CandidateKycDocument.user_id == candidate.user_id)
        .order_by(CandidateKycDocument.updated_at.desc())
    )).scalars().all()
    if not docs:
        return []
    schedules = (await kyc_db.execute(
        select(CandidateKycRetentionSchedule).where(
            CandidateKycRetentionSchedule.document_id.in_([doc.id for doc in docs])
        )
    )).scalars().all()
    retention_by_doc_id = {row.document_id: row.delete_after for row in schedules}
    return [
        CandidateKycRecruiterStatusOut(
            doc_type=doc.doc_type.value,
            status=doc.status.value,
            uploaded_at=doc.uploaded_at,
            updated_at=doc.updated_at,
            review_note=doc.review_note,
            retention_expires_at=retention_by_doc_id.get(doc.id),
        )
        for doc in docs
    ]


@router.get("/{candidate_id}/kyc-documents/{doc_type}/download")
async def download_candidate_kyc_document(
    candidate_id: str,
    doc_type: str,
    db: AsyncSession = Depends(get_db),
    kyc_db: AsyncSession = Depends(get_kyc_db),
    user: User = Depends(require_hr),
):
    import pathlib

    if not bool(settings.KYC_RECRUITER_RAW_ACCESS_ENABLED):
        raise HTTPException(
            status_code=403,
            detail=(
                "Raw KYC document download is disabled by policy. "
                "Recruiters can view verification status only."
            ),
        )

    normalized_doc_type = (doc_type or "").strip().lower()
    if normalized_doc_type not in _KYC_DOC_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported doc type '{doc_type}'. Use one of: {', '.join(_KYC_DOC_TYPES)}",
        )

    candidate = await _assert_candidate_owner(candidate_id, user, db)
    await _assert_recruiter_kyc_access(
        candidate=candidate,
        recruiter_user_id=user.id,
        kyc_db=kyc_db,
    )

    row = (await kyc_db.execute(
        select(CandidateKycDocument).where(
            CandidateKycDocument.user_id == candidate.user_id,
            CandidateKycDocument.doc_type == CandidateDocumentType(normalized_doc_type),
        )
    )).scalar_one_or_none()
    if not row or not row.file_path:
        raise HTTPException(status_code=404, detail="Document not found")

    path = pathlib.Path(row.file_path).resolve()
    upload_root = pathlib.Path(settings.UPLOAD_DIR).resolve()
    if upload_root not in path.parents and path != upload_root:
        raise HTTPException(status_code=403, detail="Access to this file is not permitted")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Document file not found")

    encrypted_size = await asyncio.to_thread(lambda: path.stat().st_size)
    if encrypted_size > settings.MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_FILE_SIZE_MB} MB limit.")

    try:
        decrypted_bytes = await asyncio.to_thread(encryption_service.decrypt_file_from_path, str(path))
    except encryption_service.DecryptionError:
        raise HTTPException(
            status_code=422,
            detail="Document decryption failed. File encryption key mismatch or corruption.",
        )

    ext = os.path.splitext(row.original_filename or "")[1] or ".pdf"
    mime_map = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }
    media_type = mime_map.get(ext.lower(), "application/octet-stream")
    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "", f"{normalized_doc_type}_document") + ext
    return Response(
        content=decrypted_bytes,
        media_type=media_type,
        headers={
            "Content-Disposition": f'inline; filename="{safe_name}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.get("/{candidate_id}/resume-file")
async def download_resume(
    candidate_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    import re
    from fastapi.responses import Response

    c = await _assert_candidate_owner(candidate_id, user, db)
    if not c.resume_path or not os.path.exists(c.resume_path):
        raise HTTPException(status_code=404, detail="Resume file not found")

    upload_dir = os.path.realpath(settings.UPLOAD_DIR)
    real_resume_path = os.path.realpath(c.resume_path)
    if not real_resume_path.startswith(upload_dir + os.sep) and real_resume_path != upload_dir:
        raise HTTPException(status_code=403, detail="Access to this file is not permitted")

    ext = os.path.splitext(c.resume_path)[1] or ".pdf"
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "",
                       (c.name or "Candidate").replace(" ", "_")) + f"_Resume{ext}"

    try:
        decrypted_bytes = await asyncio.to_thread(encryption_service.decrypt_file_from_path, c.resume_path)
    except encryption_service.DecryptionError:
        raise HTTPException(
            status_code=422, detail="Resume decryption failed. File encryption key mismatch or corruption.")
    # BUG-7 FIX: serving all files as octet-stream forces a browser download
    # instead of inline view for PDFs. Map extension to correct MIME type.
    _MIME_TYPES = {
        ".pdf":  "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc":  "application/msword",
        ".png":  "image/png",
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".tiff": "image/tiff",
        ".tif":  "image/tiff",
        ".bmp":  "image/bmp",
        ".gif":  "image/gif",
    }
    mime_type = _MIME_TYPES.get(ext.lower(), "application/octet-stream")
    return Response(
        content=decrypted_bytes,
        media_type=mime_type,
        headers={
            "Content-Disposition": f'inline; filename="{safe_name}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.post("/{candidate_id}/draft-email")
async def draft_candidate_email(
    request: Request,
    candidate_id: str,
    body: EmailDraftRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    c = await _assert_candidate_owner(candidate_id, user, db)
    jd = (await db.execute(select(JobDescription).where(JobDescription.id == c.job_id))).scalar_one_or_none()
    email_type = (body.email_type or "invite").strip().lower()
    candidate_name = c.name or "Candidate"
    job_title = jd.title if jd else "Software Engineer"
    try:
        email_data = await _run_hr_email_draft_with_fallback(
            email_type=email_type,
            candidate_name=candidate_name,
            job_title=job_title,
            resume_score=float(c.resume_score or 0.0),
            quiz_score=c.quiz_score or 0.0,
            auth_header=request.headers.get("authorization"),
        )
        return email_data
    except Exception:
        logger.exception("Failed to draft email via AI for candidate_id=%s", candidate_id)
        if email_type == "reject":
            return {
                "subject": f"Update on your application for {job_title}",
                "body": (
                    f"Hi {candidate_name},\n\n"
                    f"Thank you for your interest in the {job_title} role. "
                    "After careful consideration, we will not be moving forward at this time.\n\n"
                    "We appreciate your time and wish you the best in your job search."
                ),
            }
        if email_type == "offer":
            return {
                "subject": f"Next steps for {job_title}",
                "body": (
                    f"Hi {candidate_name},\n\n"
                    f"We were impressed by your profile for the {job_title} role. "
                    "We would like to move forward with the next stage.\n\n"
                    "Please reply with your availability for a follow-up discussion."
                ),
            }
        return {
            "subject": f"Invitation to proceed with your application for {job_title}",
            "body": (
                f"Hi {candidate_name},\n\n"
                f"Thank you for applying to the {job_title} role. "
                "We would like to proceed with the next step in the process.\n\n"
                "Please check your portal for the next instructions."
            ),
        }


@router.post("/{candidate_id}/send-email")
async def send_candidate_email(
    candidate_id: str,
    body: EmailSendRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    c = await _assert_candidate_owner(candidate_id, user, db)
    if not c.email:
        raise HTTPException(400, "Candidate email missing")
    from app.services.email_service import send_email, EmailSendError
    # FIX Finding 35: Catch email failures so we don't return 500 or commit notifications
    try:
        await asyncio.to_thread(send_email, c.email, body.subject, body.body)
    except EmailSendError:
        logger.exception("Email provider rejected send for candidate %s", candidate_id)
        raise HTTPException(status_code=400, detail="Email dispatch failed. Please verify SMTP settings.")
    except Exception as e:
        logger.error(f"Unexpected error sending email: {e}")
        raise HTTPException(status_code=500, detail="Email dispatch failed. Please try again later.")
    await push_notification(
        db, user.id,
        title=f"Email sent to {html.escape(c.name or c.email or 'Candidate')}",
        message=f"Subject: {body.subject}",
        ntype=NotificationType.email_sent,
        related_id=candidate_id,
    )
    await push_to_candidate_by_email(
        db, c.email,
        title=f"New message from HR: {body.subject}",
        message="You received an email from the hiring team. Check your inbox for details.",
        ntype=NotificationType.email_sent,
        related_id=c.job_id,
    )
    if body.interview_at or (body.meeting_link or "").strip():
        interview_details = {
            "candidate_id": candidate_id,
            "job_id": c.job_id,
            "interview_at": body.interview_at.isoformat() if body.interview_at else None,
            "meeting_link": (body.meeting_link or "").strip() or None,
            "note": (body.interview_note or "").strip() or None,
        }
        await log_action(
            db,
            user.id,
            "SCHEDULE_INTERVIEW",
            "candidate",
            candidate_id,
            details=interview_details,
        )
        await push_to_candidate_by_email(
            db,
            c.email,
            title="Interview details shared",
            message="The recruiter shared interview schedule details. Check your email for the time and meeting link.",
            ntype=NotificationType.system,
            related_id=c.job_id,
        )
    await db.commit()
    return {"message": "Email dispatched"}


@router.get("/{candidate_id}/quiz-result")
async def get_candidate_quiz_result(
    candidate_id: str,
    db: AsyncSession = Depends(get_db),
    kyc_db: AsyncSession = Depends(get_kyc_db),
    user: User = Depends(require_hr),
):
    """Return the latest submitted quiz attempt for a candidate.

    Secured by _assert_candidate_owner  only the HR user who owns the JD
    (or an admin) can access this endpoint.
    """
    from app.models import QuizAttempt, QuizStatus, Quiz

    c = await _assert_candidate_owner(candidate_id, user, db)
    await _assert_recruiter_kyc_access(
        candidate=c,
        recruiter_user_id=user.id,
        kyc_db=kyc_db,
    )

    # Fetch the most recent *submitted* attempt for this candidate
    attempt_res = await db.execute(
        select(QuizAttempt)
        .options(selectinload(QuizAttempt.quiz))
        .where(
            QuizAttempt.candidate_id == candidate_id,
            QuizAttempt.status == QuizStatus.submitted,
        )
        .order_by(QuizAttempt.submitted_at.desc())
        .limit(1)
    )
    attempt = attempt_res.scalar_one_or_none()

    if not attempt:
        # Check if there's a pending/in-progress attempt
        any_attempt_res = await db.execute(
            select(QuizAttempt)
            .where(QuizAttempt.candidate_id == candidate_id)
            .order_by(QuizAttempt.created_at.desc())
            .limit(1)
        )
        any_attempt = any_attempt_res.scalar_one_or_none()
        if any_attempt:
            raise HTTPException(
                status_code=404,
                detail=f"Quiz not yet submitted (current status: {any_attempt.status.value})",
            )
        raise HTTPException(status_code=404, detail="No quiz assigned to this candidate")

    max_score = attempt.max_score or 0
    raw_score = attempt.raw_score or 0
    percentage = round((raw_score / max_score) * 100, 2) if max_score > 0 else 0.0

    return {
        "attempt_id": attempt.id,
        "candidate_id": candidate_id,
        "candidate_name": c.name,
        "quiz_title": attempt.quiz.title if attempt.quiz else "Technical Assessment",
        "status": attempt.status.value,
        "raw_score": raw_score,
        "max_score": max_score,
        "percentage": percentage,
        "passed": c.passed,
        "tab_switches": attempt.tab_switches or 0,
        "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
        "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
        "skill_breakdown": attempt.skill_breakdown or {},
        "difficulty_breakdown": attempt.difficulty_breakdown or {},
    }
