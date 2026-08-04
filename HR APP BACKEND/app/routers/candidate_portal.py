"""
Candidate Portal Router
-----------------------
Endpoints exclusively for users with role=candidate.

FIX LOG (original session):
  BUG-1  apply_with_vault_resume() called only rule-based compute_resume_score()
  BUG-2  apply_with_vault_resume() score_breakdown used wrong keys
  BUG-3  auto_send_quiz_to_shortlisted referenced UserRole.admin but UserRole was not imported
  BUG-4  get_my_feedback() quiz_max_score was hardcoded 36.0

FIX LOG (this session):
  BUG-1  POST /resume/enhance and POST /resume/build were each registered TWICE.
         FastAPI resolves routes in order â€” the second (stripped-down) definition
         shadowed the first (feature-rich) one, making vault/file paths permanently
         unreachable. Merged into a single endpoint per route, accepting both
         resume_id (vault) and resume_text (plain text) via JSON body.

  BUG-2  build_resume payload size guard used sys.getsizeof(str(body)) which
         measures CPython heap bytes, not content bytes. A 200 KB JSON payload
         routinely passed it. Fixed to len(json.dumps(body).encode("utf-8")).

  BUG-3  get_resume_fit_score() computed the preview score using the rule-based
         compute_resume_score(), while apply_with_vault_resume() uses the AI-
         override path. Candidates saw systematically different scores between
         preview and actual application. Fixed to use compute_resume_score_with_ai_override().

  BUG-5  build_candidate_resume() (the dead duplicate) used req.pop("target_role")
         which mutated the incoming dict and removed target_role before passing
         the body to build_resume_from_form(). Fixed in the merged endpoint by
         using body.target_role directly from the Pydantic model.
"""
from app.config import settings
from app.constants.versions import PARSER_VERSION
from app.services.notification_service import push_notification, push_to_candidate_by_email
from app.services.auth_service import require_candidate, require_hr, log_action
from app.services.candidate_coach_service import run_candidate_coach
from app.schemas import (
    CandidateOut, CandidatePortalOut, PublicJDOut,
    SkillFeedbackItem, StoredResumeOut,
    StoredResumeLabelUpdate,
    CandidateKycDocumentOut,
    CandidateKycChecklistOut,
    CandidateKycChecklistItem,
    CandidateKycConsentUpdate,
    CandidateKycConsentOut,
    CandidateKycMagicContextOut,
    CandidateKycMagicUploadOut,
)
from app.models import (
    User, Candidate, JobDescription, Quiz, QuizAttempt, QuizStatus, CandidateTag,
    UserRole, NotificationType,
    StoredResume,
)
from app.database import get_db, AsyncSessionLocal
from app.kyc_database import KycSessionLocal, get_kyc_db
from app.kyc_models import (
    CandidateDocumentStatus,
    CandidateDocumentType,
    CandidateHireApproval,
    CandidateKycConsent,
    CandidateKycDocument,
    CandidateKycInvite,
    CandidateKycRetentionSchedule,
)
from sqlalchemy.orm import selectinload, load_only
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, BackgroundTasks, Form, Request, Header, Response
# FIX Finding 20 & 26: Add rate limiting to public and expensive endpoints
from app.limiter import limiter
from typing import List, Optional
from datetime import datetime, timezone, timedelta
import asyncio
import hashlib
import json as _json
import logging
import os
import re
import secrets
from importlib import import_module

logger = logging.getLogger(__name__)


class CandidateCoachRequest(BaseModel):
    question: str = Field(
        default="Summarize my applications and recommend the next steps.",
        min_length=1,
        max_length=1000,
    )
    candidate_id: Optional[str] = Field(default=None, max_length=36)


class CandidateCoachResponse(BaseModel):
    answer: str
    headline: str
    recommendations: list[str]
    applications: list[dict]
    resumes: list[dict]
    risks: list[str]
    metrics: dict
    data_scope: str
    snapshot: dict


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


router = APIRouter(prefix="/candidate", tags=["Candidate Portal"])
# Keep interactive candidate routes bounded to reduce long-tail latency.
_CANDIDATE_APPLY_TIMEOUT_S = max(18.0, min(30.0, float(settings.AI_REQUEST_TIMEOUT_SECONDS) * 2.0))
_CANDIDATE_PRECHECK_TIMEOUT_S = max(12.0, min(24.0, float(settings.AI_REQUEST_TIMEOUT_SECONDS) * 1.5))
_CANDIDATE_AI_CALL_TIMEOUT_S = max(10.0, min(20.0, float(settings.AI_REQUEST_TIMEOUT_SECONDS) * 1.5))
_CANDIDATE_AI_ROUTE_TIMEOUT_S = max(12.0, min(24.0, float(settings.AI_REQUEST_TIMEOUT_SECONDS) * 1.75))
_KYC_MANDATORY_DOC_TYPES: tuple[str, ...] = ("aadhaar", "pan", "employment_proof")
_KYC_OPTIONAL_DOC_TYPES: tuple[str, ...] = (
    "passport",
    "driving_license",
    "salary_slip",
    "offer_letter",
)
_KYC_DOC_TYPES: tuple[str, ...] = _KYC_MANDATORY_DOC_TYPES + _KYC_OPTIONAL_DOC_TYPES
_KYC_DOC_LABELS: dict[str, str] = {
    "aadhaar": "Aadhaar Card",
    "pan": "PAN Card",
    "employment_proof": "Previous Employment Proof",
    "passport": "Passport",
    "driving_license": "Driving License",
    "salary_slip": "Salary Slip",
    "offer_letter": "Offer Letter",
}
_AADHAAR_NUMBER_RE = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_kyc_retention_days(value: int | None) -> int:
    if value is None:
        value = int(settings.KYC_DEFAULT_RETENTION_DAYS)
    return max(30, min(90, int(value)))


def _kyc_invite_token_hash(raw_token: str) -> str:
    return hashlib.sha256((raw_token or "").strip().encode("utf-8")).hexdigest()


def _build_candidate_kyc_magic_link(raw_token: str) -> str:
    base = (settings.FRONTEND_URL or "").strip().rstrip("/")
    if not base:
        raise HTTPException(status_code=500, detail="FRONTEND_URL is not configured")
    return f"{base}/candidate/kyc-upload?token={raw_token}"


def _build_quiz_magic_link(raw_token: str) -> str:
    base = (settings.FRONTEND_URL or "").strip().rstrip("/")
    if not base:
        raise HTTPException(status_code=500, detail="FRONTEND_URL is not configured")
    return f"{base}/take-quiz?token={raw_token}"


async def _cleanup_previous_kyc_file(path_str: str | None) -> None:
    import pathlib

    if not path_str:
        return
    try:
        upload_root = pathlib.Path(settings.UPLOAD_DIR).resolve()
        old_real = pathlib.Path(path_str).resolve()
        if upload_root in old_real.parents and old_real.exists():
            await asyncio.to_thread(old_real.unlink)
    except FileNotFoundError:
        return
    except Exception as cleanup_err:
        logger.warning("KYC old file cleanup skipped for %s: %s", path_str, cleanup_err)


async def _extract_text_for_kyc_scan(filename: str, content: bytes) -> str:
    try:
        return await asyncio.wait_for(
            file_service.extract_text_from_bytes(filename, content),
            timeout=8.0,
        )
    except Exception:
        return ""


def _assert_masked_aadhaar_policy(
    *,
    doc_type: str,
    require_masked_aadhaar: bool,
    aadhaar_masked_confirmed: bool,
    extracted_text: str,
) -> None:
    if doc_type != "aadhaar" or not require_masked_aadhaar:
        return
    if not aadhaar_masked_confirmed:
        raise HTTPException(
            status_code=422,
            detail="Masked Aadhaar confirmation is required before upload.",
        )
    if extracted_text and _AADHAAR_NUMBER_RE.search(extracted_text):
        raise HTTPException(
            status_code=422,
            detail="Unmasked Aadhaar number detected. Upload a masked Aadhaar copy.",
        )


async def purge_expired_kyc_documents_once() -> int:
    """Delete expired KYC documents and retention rows in small bounded batches."""
    import pathlib

    now = _utc_now()
    purged = 0
    async with KycSessionLocal() as kyc_db:
        schedules = (await kyc_db.execute(
            select(CandidateKycRetentionSchedule)
            .where(CandidateKycRetentionSchedule.delete_after <= now)
            .order_by(CandidateKycRetentionSchedule.delete_after.asc())
            .limit(100)
        )).scalars().all()
        if not schedules:
            return 0

        upload_root = pathlib.Path(settings.UPLOAD_DIR).resolve()
        for schedule in schedules:
            doc = (await kyc_db.execute(
                select(CandidateKycDocument).where(CandidateKycDocument.id == schedule.document_id)
            )).scalar_one_or_none()
            if doc and doc.file_path:
                try:
                    doc_path = pathlib.Path(doc.file_path).resolve()
                    if upload_root in doc_path.parents and doc_path.exists():
                        await asyncio.to_thread(doc_path.unlink)
                except FileNotFoundError:
                    pass
                except Exception as file_err:
                    logger.warning("KYC retention file delete skipped for %s: %s", doc.file_path, file_err)
                await kyc_db.delete(doc)
                purged += 1
            await kyc_db.delete(schedule)

        await kyc_db.commit()
    return purged


def _is_harness_or_timeout_error(exc: Exception) -> bool:
    return isinstance(exc, asyncio.TimeoutError) or exc.__class__.__name__ == "HarnessAgentError"


def _new_quiz_token_pair() -> tuple[str, str]:
    raw_token = secrets.token_urlsafe(32)
    return raw_token, QuizAttempt.hash_access_token(raw_token)


async def _notify_candidate_shortlist_post_commit(
    *,
    candidate_email: str,
    candidate_id: str,
    jd_title: str,
    quiz_link: str,
) -> None:
    async with AsyncSessionLocal() as notif_db:
        await push_to_candidate_by_email(
            notif_db,
            candidate_email,
            title=f"Shortlisted: Next step for {jd_title}",
            message=(
                f"You have been shortlisted for {jd_title}. "
                f"Please complete the assessment here: {quiz_link}"
            ),
            ntype=NotificationType.system,
            related_id=candidate_id,
        )
        await notif_db.commit()


# â”€â”€â”€ Private helper â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async def _run_quiz_generation(
    *,
    request: Request | None,
    jd_text: str,
    skills: list[str],
    easy: int,
    medium: int,
    hard: int,
) -> list[dict]:
    try:
        auth_header = request.headers.get("authorization") if request else None
        result = await asyncio.wait_for(
            harness_agent_client.run_agent(
                "quiz_generator",
                {
                    "jd_text": jd_text,
                    "skills": skills,
                    "easy": easy,
                    "medium": medium,
                    "hard": hard,
                },
                auth_header,
                timeout_s=_CANDIDATE_AI_CALL_TIMEOUT_S,
            ),
            timeout=_CANDIDATE_AI_CALL_TIMEOUT_S,
        )
        if isinstance(result, dict):
            questions = result.get("questions")
            if isinstance(questions, list):
                return questions
        return result if isinstance(result, list) else []
    except Exception as runtime_exc:
        if not _is_harness_or_timeout_error(runtime_exc):
            raise
        logger.warning("Harness fallback quiz_generator failed, using direct generator: %s", runtime_exc)
        return await asyncio.wait_for(
            gemini_service.generate_quiz_questions(
                jd_text=jd_text,
                skills=skills,
                easy=easy,
                medium=medium,
                hard=hard,
            ),
            timeout=_CANDIDATE_AI_CALL_TIMEOUT_S,
        )


async def _run_parse_resume(
    *,
    request: Request | None,
    resume_text: str,
) -> dict:
    try:
        auth_header = request.headers.get("authorization") if request else None
        result = await asyncio.wait_for(
            harness_agent_client.run_agent(
                "resume_parser",
                {"text": resume_text},
                auth_header,
                timeout_s=_CANDIDATE_AI_CALL_TIMEOUT_S,
            ),
            timeout=_CANDIDATE_AI_CALL_TIMEOUT_S,
        )
        if isinstance(result, dict) and isinstance(result.get("parsed_resume"), dict):
            return result["parsed_resume"]
        return result if isinstance(result, dict) else {}
    except Exception as runtime_exc:
        if not _is_harness_or_timeout_error(runtime_exc):
            raise
        logger.warning("Harness fallback resume_parser failed, using direct parser: %s", runtime_exc)
        return await asyncio.wait_for(
            gemini_service.parse_resume(resume_text),
            timeout=_CANDIDATE_AI_CALL_TIMEOUT_S,
        )


async def _run_get_embedding(
    *,
    request: Request | None,
    text: str,
) -> list:
    try:
        auth_header = request.headers.get("authorization") if request else None
        result = await asyncio.wait_for(
            harness_agent_client.run_agent(
                "embedding",
                {"text": text},
                auth_header,
                timeout_s=_CANDIDATE_AI_CALL_TIMEOUT_S,
            ),
            timeout=_CANDIDATE_AI_CALL_TIMEOUT_S,
        )
        if isinstance(result, dict):
            embedding = result.get("embedding")
            if isinstance(embedding, list):
                return embedding
        return result if isinstance(result, list) else []
    except Exception as runtime_exc:
        if not _is_harness_or_timeout_error(runtime_exc):
            raise
        logger.warning("Harness fallback embedding failed, using direct embedding: %s", runtime_exc)
        return await asyncio.wait_for(
            gemini_service.get_embedding(text),
            timeout=_CANDIDATE_AI_CALL_TIMEOUT_S,
        )


async def _run_resume_scorer(
    *,
    request: Request | None,
    parsed_resume: dict,
    job_title: str,
    exp_min: int,
    exp_max: int,
    must_have: list[str],
    good_to_have: list[str],
    description: str,
) -> dict:
    try:
        auth_header = request.headers.get("authorization") if request else None
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
                timeout_s=_CANDIDATE_AI_CALL_TIMEOUT_S,
            ),
            timeout=_CANDIDATE_AI_CALL_TIMEOUT_S,
        )
        if isinstance(result, dict) and isinstance(result.get("score_result"), dict):
            return result["score_result"]
        return result if isinstance(result, dict) else {}
    except Exception as runtime_exc:
        if not _is_harness_or_timeout_error(runtime_exc):
            raise
        logger.warning("Harness fallback resume_scorer failed, using direct scorer: %s", runtime_exc)
        return await asyncio.wait_for(
            gemini_service.score_resume_against_jd(
                parsed_resume=parsed_resume,
                job_title=job_title,
                exp_min=exp_min,
                exp_max=exp_max,
                must_have=must_have,
                good_to_have=good_to_have,
                description=description,
            ),
            timeout=_CANDIDATE_AI_CALL_TIMEOUT_S,
        )


async def _run_enhance_resume(
    *,
    request: Request | None,
    resume_text: str,
    job_title: str,
    must_have: list[str],
    good_to_have: list[str],
    job_description: str,
    current_score: float,
    missing_skills: list[str],
) -> dict:
    try:
        auth_header = request.headers.get("authorization") if request else None
        result = await asyncio.wait_for(
            harness_agent_client.run_agent(
                "resume_enhancer",
                {
                    "resume_text": resume_text,
                    "job_title": job_title,
                    "must_have": must_have,
                    "good_to_have": good_to_have,
                    "description": job_description,
                    "parsed_resume": {},
                },
                auth_header,
                timeout_s=_CANDIDATE_AI_CALL_TIMEOUT_S,
            ),
            timeout=_CANDIDATE_AI_CALL_TIMEOUT_S,
        )
        if isinstance(result, dict) and isinstance(result.get("enhancement_result"), dict):
            return result["enhancement_result"]
        return result if isinstance(result, dict) else {}
    except Exception as runtime_exc:
        if not _is_harness_or_timeout_error(runtime_exc):
            raise
        logger.warning("Harness fallback resume_enhancer failed, using direct enhancer: %s", runtime_exc)
        return await asyncio.wait_for(
            gemini_service.enhance_resume(
                resume_text=resume_text,
                job_title=job_title,
                must_have=must_have,
                good_to_have=good_to_have,
                job_description=job_description,
                current_score=current_score,
                missing_skills=missing_skills,
            ),
            timeout=_CANDIDATE_AI_CALL_TIMEOUT_S,
        )


async def _run_build_resume(
    *,
    request: Request | None,
    candidate_data: dict,
    target_role: str,
) -> dict:
    try:
        auth_header = request.headers.get("authorization") if request else None
        result = await asyncio.wait_for(
            harness_agent_client.run_agent(
                "resume_builder",
                {
                    "candidate_data": candidate_data,
                    "target_role": target_role,
                },
                auth_header,
                timeout_s=_CANDIDATE_AI_CALL_TIMEOUT_S,
            ),
            timeout=_CANDIDATE_AI_CALL_TIMEOUT_S,
        )
        if isinstance(result, dict) and isinstance(result.get("built_resume"), dict):
            return result["built_resume"]
        return result if isinstance(result, dict) else {}
    except Exception as runtime_exc:
        if not _is_harness_or_timeout_error(runtime_exc):
            raise
        logger.warning("Harness fallback resume_builder failed, using direct builder: %s", runtime_exc)
        return await asyncio.wait_for(
            gemini_service.build_resume_from_form(
                candidate_data=candidate_data,
                target_role=target_role,
            ),
            timeout=_CANDIDATE_AI_CALL_TIMEOUT_S,
        )


async def _run_cover_letter(
    *,
    request: Request | None,
    candidate_name: str,
    exp_years: float,
    skills: list,
    work_history: list,
    education: list,
    company_name: str,
    job_title: str,
    must_have: list[str],
    job_description: str,
) -> dict:
    try:
        auth_header = request.headers.get("authorization") if request else None
        result = await asyncio.wait_for(
            harness_agent_client.run_agent(
                "cover_letter",
                {
                    "candidate_name": candidate_name,
                    "exp_years": exp_years,
                    "skills": skills,
                    "work_history": work_history,
                    "education": education,
                    "company_name": company_name,
                    "job_title": job_title,
                    "must_have": must_have,
                    "description": job_description,
                },
                auth_header,
                timeout_s=_CANDIDATE_AI_CALL_TIMEOUT_S,
            ),
            timeout=_CANDIDATE_AI_CALL_TIMEOUT_S,
        )
        if isinstance(result, dict) and isinstance(result.get("cover_letter"), dict):
            return result["cover_letter"]
        return result if isinstance(result, dict) else {}
    except Exception as runtime_exc:
        if not _is_harness_or_timeout_error(runtime_exc):
            raise
        logger.warning("Harness fallback cover_letter failed, using direct generator: %s", runtime_exc)
        return await asyncio.wait_for(
            gemini_service.generate_cover_letter(
                candidate_name=candidate_name,
                exp_years=exp_years,
                skills=skills,
                work_history=work_history,
                education=education,
                company_name=company_name,
                job_title=job_title,
                must_have=must_have,
                job_description=job_description,
            ),
            timeout=_CANDIDATE_AI_CALL_TIMEOUT_S,
        )


async def _run_career_analysis(
    *,
    request: Request | None,
    candidate_name: str,
    exp_years: float,
    skills: list,
    work_history: list,
    education: list,
    career_breaks: list,
    target_role: str,
) -> dict:
    try:
        auth_header = request.headers.get("authorization") if request else None
        result = await asyncio.wait_for(
            harness_agent_client.run_agent(
                "career_analyst",
                {
                    "candidate_name": candidate_name,
                    "experience_years": exp_years,
                    "skills": skills,
                    "work_history": work_history,
                    "education": education,
                    "career_breaks": career_breaks,
                    "target_role": target_role,
                },
                auth_header,
                timeout_s=_CANDIDATE_AI_CALL_TIMEOUT_S,
            ),
            timeout=_CANDIDATE_AI_CALL_TIMEOUT_S,
        )
        if isinstance(result, dict) and isinstance(result.get("career_analysis"), dict):
            return result["career_analysis"]
        return result if isinstance(result, dict) else {}
    except Exception as runtime_exc:
        if not _is_harness_or_timeout_error(runtime_exc):
            raise
        logger.warning("Harness fallback career_analyst failed, using direct analysis: %s", runtime_exc)
        return await asyncio.wait_for(
            gemini_service.analyze_career_path(
                candidate_name=candidate_name,
                exp_years=exp_years,
                skills=skills,
                work_history=work_history,
                education=education,
                career_breaks=career_breaks,
                target_role=target_role,
            ),
            timeout=_CANDIDATE_AI_CALL_TIMEOUT_S,
        )

def _company_info(hr_user) -> dict:
    _DEFAULT_BIO = (
        "We are an innovative company actively looking for top talent. "
        "Apply to our open roles to learn more about our mission and culture!"
    )
    company_name = "Your Company"
    company_bio = _DEFAULT_BIO
    company_blog = ""

    if hr_user:
        prefs = hr_user.preferences or {}
        company_name = (
            prefs.get("companyName") or prefs.get("company_name")
            or hr_user.full_name or company_name
        )
        company_bio = (
            hr_user.bio or prefs.get("companyBio") or prefs.get("company_bio")
            or company_bio
        )
        company_blog = prefs.get("companyWebsite") or prefs.get("company_website") or company_blog

    return {"company": company_name, "company_bio": company_bio, "company_blog": company_blog}


def _public_jd_payload(jd: JobDescription, hr_user: User | None) -> dict:
    """Candidate-facing JD payload without internal heavy fields."""
    payload = {
        "id": jd.id,
        "title": jd.title,
        "role": jd.role,
        "location": jd.location,
        "employment_type": jd.employment_type,
        "experience_min": jd.experience_min,
        "experience_max": jd.experience_max,
        "must_have_skills": jd.must_have_skills or [],
        "good_to_have_skills": jd.good_to_have_skills or [],
        "description": jd.description,
        "salary_range": jd.salary_range,
        "created_at": jd.created_at,
    }
    payload.update(_company_info(hr_user))
    return payload


def _ensure_resume_text_quality(text: str, *, context: str) -> None:
    """Reject unreadable/near-empty resume content early to avoid garbage scoring."""
    cleaned = (text or "").strip()
    alpha = sum(1 for ch in cleaned if ch.isalpha())
    alnum = sum(1 for ch in cleaned if ch.isalnum())
    if alpha < 30 or alnum < 80:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Could not extract enough readable text from the resume ({context}). "
                "Please upload a clearer PDF/DOCX or higher-quality scan."
            ),
        )


def _jd_has_meaningful_criteria(jd: JobDescription) -> bool:
    has_skills = bool(jd.must_have_skills or jd.good_to_have_skills)
    desc = (jd.description or "").strip()
    desc_alnum = "".join(ch for ch in desc if ch.isalnum())
    has_meaningful_desc = len(desc_alnum) >= 20 and any(ch.isalpha() for ch in desc)
    edu_req = str(getattr(jd, "education_requirement", "") or "").strip().lower()
    has_edu_req = edu_req not in {"", "none", "null"}
    return has_skills or has_meaningful_desc or has_edu_req


def _fallback_mock_questions(skills: list[str], *, total: int = 10) -> list[dict]:
    """Deterministic mock-test fallback when AI question generation is unavailable."""
    base_skills = [s for s in skills if isinstance(s, str) and s.strip()] or [
        "Problem Solving",
        "APIs",
        "Databases",
        "Testing",
        "System Design",
    ]
    questions: list[dict] = []
    for idx in range(max(1, total)):
        skill = base_skills[idx % len(base_skills)]
        prompt = f"Which practice is most reliable for {skill} in production software?"
        options = [
            "Use repeatable validation, testing, and monitoring",
            "Skip validation and rely on manual checks only",
            "Avoid logs to reduce any overhead",
            "Delay all error handling until after release",
        ]
        questions.append({
            "question_text": prompt,
            "options": options,
            "correct_answer": 0,
            "difficulty": "medium",
            "skill_tag": skill,
            "weight": 2,
        })
    return questions


async def _insert_application_atomic(
    db: AsyncSession,
    candidate_values: dict,
) -> Candidate | None:
    """
    Atomically insert one candidate application.
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
        raise RuntimeError(f"Unsupported database dialect for atomic apply insert: {dialect}")

    inserted_id = (await db.execute(stmt)).scalar_one_or_none()
    if inserted_id is None:
        return None
    return await db.get(Candidate, inserted_id)


def _resume_cache_is_current(stored: StoredResume) -> bool:
    if settings.DATABASE_URL.startswith("sqlite"):
        return (
            stored.parse_version == PARSER_VERSION
            and bool(stored.normalized_skills)
        )
    return (
        stored.parse_version == PARSER_VERSION
        and bool(stored.normalized_skills)
        and bool(stored.embedding)
    )


def _application_status(candidate: Candidate) -> str:
    breakdown = candidate.score_breakdown or {}
    if isinstance(breakdown, dict) and breakdown.get("application_status") == "withdrawn":
        return "withdrawn"
    return "active"


def _apply_stored_resume_parse_cache(
    stored: StoredResume,
    parsed: dict,
    embedding: list,
    *,
    file_hash: str | None = None,
) -> None:
    stored.normalized_skills = parsed.get("normalized_skills", [])
    stored.skills = parsed.get("skills", [])
    stored.experience_years = float(parsed.get("experience_years") or 0.0)
    stored.skill_years = parsed.get("skill_years") or {}
    stored.projects = parsed.get("projects", [])
    stored.work_experience = parsed.get("work_experience", [])
    stored.education = parsed.get("education", [])
    stored.career_breaks = parsed.get("career_breaks", [])
    stored.parsed_location = parsed.get("location")
    stored.parsed_name = parsed.get("name")
    stored.parsed_email = parsed.get("email")
    stored.parsed_phone = parsed.get("phone")
    stored.summary = parsed.get("summary")
    stored.embedding = embedding or []
    if file_hash is not None:
        stored.file_hash = file_hash
    stored.parse_version = PARSER_VERSION


# â”€â”€â”€ Public â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/jobs", response_model=List[PublicJDOut])
@limiter.limit("60/minute")
async def list_public_jobs(
    request: Request,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint â€” any visitor can browse active job listings."""
    jobs_query = (
        select(JobDescription)
        .options(
            load_only(
                JobDescription.id,
                JobDescription.title,
                JobDescription.role,
                JobDescription.location,
                JobDescription.employment_type,
                JobDescription.experience_min,
                JobDescription.experience_max,
                JobDescription.must_have_skills,
                JobDescription.good_to_have_skills,
                JobDescription.description,
                JobDescription.salary_range,
                JobDescription.created_at,
                JobDescription.created_by,
            ),
        )
        .where(JobDescription.is_active == True)
        .order_by(JobDescription.created_at.desc())
        .offset(skip).limit(limit)
    )
    jobs = (await db.execute(jobs_query)).scalars().all()

    creator_ids = [jd.created_by for jd in jobs if jd.created_by]
    hr_map: dict[str, User] = {}
    if creator_ids:
        hr_rows = (await db.execute(
            select(User)
            .options(
                load_only(
                    User.id,
                    User.full_name,
                    User.bio,
                    User.preferences,
                )
            )
            .where(User.id.in_(creator_ids))
        )).scalars().all()
        hr_map = {u.id: u for u in hr_rows}

    return [_public_jd_payload(jd, hr_map.get(jd.created_by)) for jd in jobs]


@router.get("/jobs/{job_id}", response_model=PublicJDOut)
@limiter.limit("60/minute")
async def get_public_job(request: Request, job_id: str, db: AsyncSession = Depends(get_db)):
    job_query = (
        select(JobDescription)
        .options(
            load_only(
                JobDescription.id,
                JobDescription.title,
                JobDescription.role,
                JobDescription.location,
                JobDescription.employment_type,
                JobDescription.experience_min,
                JobDescription.experience_max,
                JobDescription.must_have_skills,
                JobDescription.good_to_have_skills,
                JobDescription.description,
                JobDescription.salary_range,
                JobDescription.created_at,
                JobDescription.is_active,
                JobDescription.created_by,
            ),
        )
        .where(JobDescription.id == job_id)
    )
    jd = (await db.execute(job_query)).scalar_one_or_none()
    if not jd or not jd.is_active:
        raise HTTPException(status_code=404, detail="Job not found")

    hr_user = None
    if jd.created_by:
        hr_user = (await db.execute(
            select(User)
            .options(
                load_only(
                    User.id,
                    User.full_name,
                    User.bio,
                    User.preferences,
                )
            )
            .where(User.id == jd.created_by)
        )).scalar_one_or_none()

    return _public_jd_payload(jd, hr_user)


# â”€â”€â”€ Apply to job (fresh file upload) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/apply/{job_id}", response_model=CandidateOut, status_code=201)
@limiter.limit("10/minute")
async def apply_to_job(
    request: Request,
    job_id: str,
    file: UploadFile = File(...),
    career_breaks: Optional[str] = Form(None),
    x_idempotency_key: Optional[str] = Header(default=None, alias="X-Idempotency-Key"),
    response: Response = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    from app.routers.resumes import _compute_resume_data_from_bytes

    jd = (await db.execute(select(JobDescription).where(JobDescription.id == job_id))).scalar_one_or_none()
    if not jd or not jd.is_active:
        raise HTTPException(status_code=404, detail="Job not found or closed")

    idem_key = (x_idempotency_key or "").strip()
    if idem_key:
        existing_app = (await db.execute(
            select(Candidate).where(Candidate.job_id == job_id, Candidate.user_id == user.id)
        )).scalar_one_or_none()
        if existing_app:
            response.status_code = 200
            return existing_app


    import os
    _raw_ext = os.path.splitext(file.filename or "")[1].lower()
    if _raw_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=422, detail=f"File type '{_raw_ext or '(none)'}' is not allowed.")

    _MAX_UPLOAD = settings.MAX_FILE_SIZE_MB * 1024 * 1024  # from config
    # FIX Finding 12: use bytearray to avoid O(nÂ²) byte concatenation
    _buf = bytearray()
    while _chunk := await file.read(1024 * 1024):
        _buf.extend(_chunk)
        if len(_buf) > _MAX_UPLOAD:
            raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_FILE_SIZE_MB} MB limit.")
    content = bytes(_buf)
    import io as _io
    file.file = _io.BytesIO(content)
    await file.seek(0)

    text, _ = await file_service.extract_text(file)
    _ensure_resume_text_quality(text, context="job application upload")

    manual_cbs = []
    if career_breaks:
        import json as _json2
        try:
            manual_cbs = _json2.loads(career_breaks)
        except (ValueError, TypeError) as exc:
            logger.warning("Invalid career_breaks payload for candidate apply: %s", exc)
            raise HTTPException(
                status_code=422,
                detail="career_breaks must be valid JSON.",
            ) from exc

    try:
        data = await asyncio.wait_for(
            _compute_resume_data_from_bytes(
                file.filename or "resume.pdf", content, text, jd,
                cached_candidate=None,
                user_email=user.email,
                auth_header=request.headers.get("authorization"),
                manual_career_breaks=manual_cbs,
                fast_mode=settings.DATABASE_URL.startswith("sqlite"),
            ),
            timeout=_CANDIDATE_APPLY_TIMEOUT_S,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=503,
            detail="Application processing is taking longer than expected. Please retry in a moment.",
        ) from exc

    # Keep account-linked applications bound to the authenticated user email so
    # downstream invite/notification delivery resolves to the active account.
    final_email = user.email or data.get("email")
    
    # FIX: Prevent 500 IntegrityError when the parsed email already exists for this job under a different user_id
    email_conflict = (await db.execute(
        select(Candidate).where(Candidate.job_id == job_id, Candidate.email == final_email)
    )).scalars().first()
    if email_conflict:
        raise HTTPException(status_code=409, detail=f"An application with the email {final_email} already exists for this job.")

    candidate_values = {
        **data,
        "user_id": user.id,
        "name": data.get("name") or user.full_name,
        "email": final_email,
    }
    candidate = await _insert_application_atomic(db, candidate_values)
    if candidate is None:
        if idem_key:
            existing_app = (await db.execute(
                select(Candidate).where(Candidate.job_id == job_id, Candidate.user_id == user.id)
            )).scalar_one_or_none()
            if existing_app:
                response.status_code = 200
                return existing_app
        raise HTTPException(status_code=409, detail="You have already applied to this job")

    quiz_attempt: QuizAttempt | None = None
    quiz_raw_token: Optional[str] = None
    if candidate.tag in (CandidateTag.strong, CandidateTag.medium):
        quiz = (await db.execute(
            select(Quiz).where(Quiz.job_id == jd.id, Quiz.is_active == True)
            .order_by(Quiz.created_at.desc())
        )).scalars().first()
        if quiz:
            quiz_raw_token, quiz_token_hash = _new_quiz_token_pair()
            quiz_attempt = QuizAttempt(
                quiz_id=quiz.id,
                candidate_id=candidate.id,
                token_hash=quiz_token_hash,
                token_expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            )
            db.add(quiz_attempt)

    await db.flush()
    await log_action(db, user.id, "CANDIDATE_APPLY", "candidate", candidate.id,
                     details={"job_id": job_id, "tag": candidate.tag.value if candidate.tag else None})
    await db.commit()
    await db.refresh(candidate)
    if quiz_attempt and candidate.email and quiz_raw_token:
        try:
            quiz_link = _build_quiz_magic_link(quiz_raw_token)
            await _notify_candidate_shortlist_post_commit(
                candidate_email=candidate.email,
                candidate_id=candidate.id,
                jd_title=jd.title,
                quiz_link=quiz_link,
            )
        except Exception as notify_err:
            logger.warning("Shortlist notification send failed for candidate %s: %s", candidate.id, notify_err)
    return candidate


# â”€â”€â”€ Candidate: My applications â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/coach", response_model=CandidateCoachResponse)
async def candidate_coach(
    body: CandidateCoachRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    result = await run_candidate_coach(
        db,
        user=user,
        question=body.question.strip(),
        candidate_id=body.candidate_id,
    )
    await log_action(
        db,
        user.id,
        "CANDIDATE_COACH_ASK",
        "candidate",
        body.candidate_id or user.id,
        details={"data_scope": result.get("data_scope", "candidate_owned")},
    )
    await db.commit()
    return result


@router.get("/my-applications", response_model=List[CandidateOut])
async def my_applications(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    rows = (await db.execute(
        select(Candidate)
        .where(Candidate.user_id == user.id)
        .order_by(Candidate.created_at.desc())
        .offset(skip).limit(limit)
    )).scalars().all()
    return rows


@router.post("/applications/{candidate_id}/withdraw")
async def withdraw_application(
    candidate_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    candidate = (await db.execute(
        select(Candidate)
        .options(selectinload(Candidate.job))
        .where(Candidate.id == candidate_id)
    )).scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Application not found")
    if candidate.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your application")
    if not candidate.job_id:
        raise HTTPException(status_code=400, detail="Only job applications can be withdrawn")

    now = datetime.now(timezone.utc)
    already_withdrawn = _application_status(candidate) == "withdrawn"
    if not already_withdrawn:
        breakdown = dict(candidate.score_breakdown or {})
        breakdown.update({
            "application_status": "withdrawn",
            "withdrawn_at": now.isoformat(),
            "withdrawn_by": "candidate",
        })
        candidate.score_breakdown = breakdown
        candidate.is_archived = True

        pending_attempts = (await db.execute(
            select(QuizAttempt).where(
                QuizAttempt.candidate_id == candidate.id,
                QuizAttempt.status.in_([QuizStatus.pending, QuizStatus.in_progress]),
            )
        )).scalars().all()
        for attempt in pending_attempts:
            attempt.status = QuizStatus.timed_out

        await log_action(
            db,
            user.id,
            "CANDIDATE_WITHDRAW_APPLICATION",
            "candidate",
            candidate.id,
            details={"job_id": candidate.job_id},
        )

    await db.commit()

    if not already_withdrawn and candidate.job and candidate.job.created_by:
        try:
            async with AsyncSessionLocal() as notif_db:
                await push_notification(
                    notif_db,
                    candidate.job.created_by,
                    title="Application withdrawn",
                    message=f"{candidate.name or user.full_name or 'A candidate'} withdrew from {candidate.job.title}.",
                    ntype=NotificationType.system,
                    related_id=candidate.id,
                )
                await notif_db.commit()
        except Exception as notify_err:
            logger.warning("Withdraw notification failed for candidate %s: %s", candidate.id, notify_err)

    return {
        "message": "Application withdrawn",
        "candidate_id": candidate.id,
        "application_status": "withdrawn",
        "already_withdrawn": already_withdrawn,
    }


# â”€â”€â”€ Candidate: Detailed feedback for one application â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/feedback/{candidate_id}", response_model=CandidatePortalOut)
async def get_my_feedback(
    candidate_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    candidate = (await db.execute(
        select(Candidate)
        .options(selectinload(Candidate.job))
        .where(Candidate.id == candidate_id)
    )).scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Application not found")
    if candidate.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your application")

    jd = candidate.job
    candidate_skills = list(candidate.normalized_skills or [])
    skill_feedback: List[SkillFeedbackItem] = []

    for skill in (jd.must_have_skills or []):
        has_it = scoring_service.semantic_skill_match(skill, candidate_skills)
        skill_feedback.append(SkillFeedbackItem(
            skill=skill, required=True, candidate_has=has_it, importance="Critical",
            suggestion="" if has_it else f"Add hands-on experience with {skill}. Consider a project or certification.",
        ))

    for skill in (jd.good_to_have_skills or []):
        has_it = scoring_service.semantic_skill_match(skill, candidate_skills)
        skill_feedback.append(SkillFeedbackItem(
            skill=skill, required=False, candidate_has=has_it, importance="Nice to have",
            suggestion="" if has_it else f"Familiarity with {skill} would strengthen your profile.",
        ))

    # BUG-4 FIX: default None until an actual quiz is assigned
    quiz_status: Optional[str] = None
    quiz_token: Optional[str] = None
    quiz_max_score: Optional[float] = None

    attempt = (await db.execute(
        select(QuizAttempt)
        .where(QuizAttempt.candidate_id == candidate.id)
        .order_by(QuizAttempt.created_at.desc())
    )).scalars().first()
    if attempt:
        quiz_status = attempt.status.value
        quiz_max_score = attempt.max_score
        if attempt.status in (QuizStatus.pending, QuizStatus.in_progress):
            # Raw quiz tokens are only available at creation/resend time. Read-only
            # candidate views must not rotate token_hash and invalidate sent links.
            quiz_token = None

    return CandidatePortalOut(
        candidate_id=candidate.id,
        job_id=jd.id,
        job_title=jd.title,
        job_role=jd.role,
        resume_score=round(candidate.resume_score, 2),
        skill_match_pct=round(candidate.skill_match_pct, 2),
        experience_match_pct=round(candidate.experience_match_pct, 2),
        project_relevance_pct=round(candidate.project_relevance_pct, 2),
        education_match_pct=round(candidate.education_match_pct, 2),
        tag=candidate.tag.value if candidate.tag else None,
        quiz_score=candidate.quiz_score,
        quiz_max_score=quiz_max_score,
        final_score=candidate.final_score,
        passed=candidate.passed,
        rank=candidate.rank,
        skill_feedback=skill_feedback,
        quiz_status=quiz_status,
        quiz_token=quiz_token,
    )


# â”€â”€â”€ Candidate: All results across all applications â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/results")
async def get_my_results(
    skip: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    candidates = (await db.execute(
        select(Candidate)
        .options(selectinload(Candidate.job))
        .where(Candidate.user_id == user.id)
        .order_by(Candidate.created_at.desc())
        .offset(skip).limit(50)
    )).scalars().all()

    candidate_ids = [c.id for c in candidates]
    attempts_raw = (await db.execute(
        select(QuizAttempt)
        .where(QuizAttempt.candidate_id.in_(candidate_ids))
        .order_by(QuizAttempt.created_at.desc())
    )).scalars().all()

    attempt_map: dict[str, QuizAttempt] = {}
    for att in attempts_raw:
        if att.candidate_id not in attempt_map:
            attempt_map[att.candidate_id] = att

    results = []
    for c in candidates:
        attempt = attempt_map.get(c.id)
        hr_tag = c.tag.value if c.tag else None
        reveal_decision = hr_tag is not None

        results.append({
            "candidate_id":   c.id,
            "job_id":         c.job_id,
            "job_title":      c.job.title if c.job else "Unknown",
            "application_status": _application_status(c),
            # Canonical field name for frontend/date sorting.
            "created_at":     c.created_at,
            # Backward-compatible alias for older clients.
            "applied_at":     c.created_at,
            "tag":            hr_tag,
            "resume_score":   round(c.resume_score, 2),
            "quiz_score":     c.quiz_score,
            "quiz_max_score": attempt.max_score if attempt else None,
            "final_score":    round(c.final_score, 2) if c.final_score is not None else None,
            "passed":         c.passed if reveal_decision else None,
            "rank":           c.rank,
            "quiz_status":    attempt.status.value if attempt else None,
        })

    return results


# â”€â”€â”€ HR: Auto-send quiz when quiz is generated â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/internal/auto-send-quiz/{job_id}", include_in_schema=False)
async def auto_send_quiz_to_shortlisted(
    job_id: str,
    quiz_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    if user.role != UserRole.admin:
        jd_check = (await db.execute(
            select(JobDescription).where(
                JobDescription.id == job_id,
                JobDescription.created_by == user.id,
            )
        )).scalar_one_or_none()
        if not jd_check:
            raise HTTPException(
                status_code=403, detail="You do not have access to this job posting")

    candidates = (await db.execute(
        select(Candidate).where(
            Candidate.job_id == job_id,
            Candidate.tag.in_([CandidateTag.strong, CandidateTag.medium]),
            Candidate.user_id.isnot(None),
        )
    )).scalars().all()

    already_sent = {
        r for r in (await db.execute(
            select(QuizAttempt.candidate_id).where(QuizAttempt.quiz_id == quiz_id)
        )).scalars().all()
    }

    created = 0
    for c in candidates:
        if c.id in already_sent:
            continue
        db.add(
            QuizAttempt(
                quiz_id=quiz_id,
                candidate_id=c.id,
                token_hash=QuizAttempt.hash_access_token(secrets.token_urlsafe(32)),
                token_expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            )
        )
        created += 1

    await db.flush()
    await db.commit()
    return {"message": f"Quiz tokens created for {created} portal candidates"}


# â”€â”€â”€ Candidate: Get Pending Quiz â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/quiz")
async def get_my_pending_quiz(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    attempts = (await db.execute(
        select(QuizAttempt)
        .options(selectinload(QuizAttempt.quiz))
        .where(
            QuizAttempt.candidate_id.in_(
                select(Candidate.id).where(Candidate.user_id == user.id)
            ),
            QuizAttempt.status.in_([QuizStatus.pending, QuizStatus.in_progress]),
        )
        .order_by(QuizAttempt.created_at.desc())
    )).scalars().all()

    if not attempts:
        return {"pending": False, "attempts": []}

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    valid_attempts = []
    timed_out_count = 0

    for a in attempts:
        if a.status == QuizStatus.in_progress and a.started_at:
            started = (
                a.started_at if a.started_at.tzinfo is not None
                else a.started_at.replace(tzinfo=timezone.utc)
            )
            if (now - started).total_seconds() / 60 > (a.quiz.duration_minutes + 2):
                a.status = QuizStatus.timed_out
                a.submitted_at = now  # FIX-8: Ensure submitted_at is never null on timeout
                timed_out_count += 1
                continue

        if a.token_expires_at:
            expires_utc = (
                a.token_expires_at
                if a.token_expires_at.tzinfo is not None
                else a.token_expires_at.replace(tzinfo=timezone.utc)
            )
            if now > expires_utc:
                a.status = QuizStatus.timed_out
                if not a.submitted_at:
                    a.submitted_at = now
                timed_out_count += 1
                continue

        valid_attempts.append(a)

    if timed_out_count > 0:
        await db.flush()
        await db.commit()

    if not valid_attempts:
        return {"pending": False, "attempts": []}

    return {
        "pending": True,
        "attempts": [
            {
                "attempt_id":       a.id,
                "quiz_id":          a.quiz_id,
                "quiz_title":       a.quiz.title,
                "duration_minutes": a.quiz.duration_minutes,
                "status":           a.status.value,
                "token":            None,
                "started_at":       a.started_at,
            }
            for a in valid_attempts
        ],
    }


# â”€â”€â”€ Candidate: AI Mock Test Generator â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/mock-test")
@limiter.limit("20/minute")
async def generate_mock_test(
    request: Request,
    context: Optional[str] = Query(default=None, max_length=1000),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    latest = (await db.execute(
        select(Candidate).where(Candidate.user_id == user.id).order_by(Candidate.created_at.desc())
    )).scalars().first()

    skills: list[str]
    jd_text = "General Technical Interview Preparation"
    if context and context.strip():
        # Support topic-only mock tests even when the candidate has never applied.
        raw = context.strip()[:300]
        topic = raw
        if "Topic:" in raw:
            topic = raw.split("Topic:", 1)[1].split(".", 1)[0].strip() or raw
        skills = [topic]
        jd_text = f"Topic-focused interview preparation: {topic}"
    elif latest:
        skills = latest.normalized_skills or latest.skills or ["General Software Engineering"]
    else:
        skills = ["General Software Engineering"]

    try:
        questions_data = await _run_quiz_generation(
            request=request,
            jd_text=jd_text,
            skills=skills[:8],
            easy=4, medium=4, hard=2,
        )
        if not isinstance(questions_data, list) or not questions_data:
            logger.warning("[mock-test] AI returned empty/invalid payload; using fallback set")
            questions_data = _fallback_mock_questions(skills[:8], total=10)
    except Exception as exc:
        logger.exception("[mock-test] AI generation failed; serving fallback questions")
        questions_data = _fallback_mock_questions(skills[:8], total=10)

    return [
        {
            "question":      q["question_text"],
            "options":       q["options"],
            "correctAnswer": (
                q["options"][q["correct_answer"]]
                if isinstance(q.get("correct_answer"), int) and q["options"]
                else (q["options"][0] if q["options"] else "")
            ),
        }
        for q in questions_data
    ]


# â”€â”€â”€ Candidate: AI Resume Pre-Evaluation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/evaluate-resume/{job_id}")
@limiter.limit("5/minute")
async def evaluate_resume_precheck(
    request: Request,
    job_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    from app.routers.resumes import _compute_resume_data_from_bytes

    jd = (await db.execute(select(JobDescription).where(JobDescription.id == job_id))).scalar_one_or_none()
    if not jd or not jd.is_active:
        raise HTTPException(status_code=404, detail="Job not found")

    import os
    _raw_ext = os.path.splitext(file.filename or "")[1].lower()
    if _raw_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=422, detail=f"File type '{_raw_ext or '(none)'}' is not allowed.")

    _MAX_UPLOAD = settings.MAX_FILE_SIZE_MB * 1024 * 1024  # from config
    _buf = bytearray()
    while _chunk := await file.read(1024 * 1024):
        _buf.extend(_chunk)
        if len(_buf) > _MAX_UPLOAD:
            raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_FILE_SIZE_MB} MB limit.")
    content = bytes(_buf)
    text = await file_service.extract_text_from_bytes(file.filename or "resume", content)

    try:
        data = await asyncio.wait_for(
            _compute_resume_data_from_bytes(
                file.filename or "resume", content, text, jd,
                cached_candidate=None,
                auth_header=request.headers.get("authorization"),
            ),
            timeout=_CANDIDATE_PRECHECK_TIMEOUT_S,
        )
    except asyncio.TimeoutError as exc:
        logger.warning("[evaluate-resume] scoring timed out for %s", file.filename)
        raise HTTPException(
            status_code=503,
            detail="Resume evaluation timed out. Please try again.",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[evaluate-resume] AI scoring failed: %s", exc)
        raise HTTPException(status_code=503, detail="AI scoring unavailable. Please try again.")

    return {
        "match_score":    data.get("resume_score", 0.0),
        "score_breakdown": data.get("score_breakdown", {}),
        "missing_skills": data.get("score_breakdown", {}).get("missing_must_have", []),
        "matched_skills": data.get("score_breakdown", {}).get("matched_must_have", []),
        "career_breaks": data.get("career_breaks", []) or [],
    }


# â”€â”€â”€ Resume Vault â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/my-resumes", response_model=list[StoredResumeOut])
async def list_stored_resumes(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    rows = (await db.execute(
        select(StoredResume)
        .where(StoredResume.user_id == user.id)
        .order_by(StoredResume.is_default.desc(), StoredResume.uploaded_at.desc())
    )).scalars().all()
    return rows


@router.post("/my-resumes", response_model=StoredResumeOut, status_code=201)
async def upload_stored_resume(
    request: Request,
    file: UploadFile = File(...),
    label: str = "My Resume",
    set_as_default: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    """Upload a new resume to the vault. Up to 5 resumes per candidate."""
    import os as _os
    _raw_ext = _os.path.splitext(file.filename or "")[1].lower()
    if _raw_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=422,
            detail=f"File type '{_raw_ext or '(none)'}' is not allowed. Accepted: {', '.join(settings.allowed_extensions_list)}",
        )

    from sqlalchemy import func as _func
    existing_count = (await db.execute(
        select(_func.count(StoredResume.id))
        .where(StoredResume.user_id == user.id)
        .with_for_update()
    )).scalar() or 0
    if existing_count >= 5:
        raise HTTPException(
            status_code=400, detail="You can store up to 5 resumes. Delete one before uploading a new one.")

    _MAX_UPLOAD = settings.MAX_FILE_SIZE_MB * 1024 * 1024  # from config
    _buf = bytearray()
    while _chunk := await file.read(1024 * 1024):
        _buf.extend(_chunk)
        if len(_buf) > _MAX_UPLOAD:
            raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_FILE_SIZE_MB} MB limit.")
    content = bytes(_buf)
    file_hash = hashlib.sha256(content).hexdigest()

    dup = (await db.execute(
        select(StoredResume.id).where(
            StoredResume.user_id == user.id,
            StoredResume.file_hash == file_hash,
        )
    )).scalar_one_or_none()
    if dup:
        raise HTTPException(
            status_code=409, detail="This resume file is already in your vault (duplicate detected).")

    try:
        text = await file_service.extract_text_from_bytes(file.filename or "resume", content)
    except HTTPException as exc:
        logger.warning("Vault upload text extraction failed for %s: %s", file.filename, exc.detail)
        text = ""
    _ensure_resume_text_quality(text, context="resume vault upload")
    try:
        resume_path = await file_service.save_file(content, file.filename or "resume")
    except RuntimeError as exc:
        logger.error("Vault upload file save failed for %s: %s", file.filename, exc)
        raise HTTPException(
            status_code=503,
            detail="Resume storage is temporarily unavailable. Please try again shortly.",
        ) from exc
    file_size_kb = max(1, len(content) // 1024)

    parsed, embedding = {}, []
    if text.strip():
        if settings.DATABASE_URL.startswith("sqlite"):
            parsed = resume_fallback_parser.coerce_parsed_resume(None, text=text)
            embedding = []
        else:
            try:
                parsed, embedding = await asyncio.gather(
                    _run_parse_resume(request=request, resume_text=text),
                    _run_get_embedding(request=request, text=text[:6000]),
                    return_exceptions=True,
                )
                if isinstance(parsed, Exception):
                    logger.warning("Resume parse failed on vault upload: %s", parsed)
                    parsed = resume_fallback_parser.coerce_parsed_resume(None, text=text)
                elif isinstance(parsed, dict):
                    parsed = resume_fallback_parser.coerce_parsed_resume(parsed, text=text)
                else:
                    parsed = resume_fallback_parser.coerce_parsed_resume(None, text=text)
                if isinstance(embedding, Exception):
                    logger.warning("Embedding failed on vault upload: %s", embedding)
                    embedding = []
            except Exception as exc:
                logger.error("AI processing failed on vault upload: %s", exc)
                parsed, embedding = resume_fallback_parser.coerce_parsed_resume(None, text=text), []

    is_first = existing_count == 0
    if set_as_default or is_first:
        from sqlalchemy import update as _update
        await db.execute(
            _update(StoredResume).where(StoredResume.user_id == user.id).values(is_default=False)
        )

    stored = StoredResume(
        user_id=user.id,
        label=label[:255],
        original_filename=file.filename or "resume",
        resume_path=resume_path,
        file_hash=file_hash,
        file_size_kb=file_size_kb,
        is_default=set_as_default or is_first,
        parsed_name=parsed.get("name"),
        parsed_email=parsed.get("email"),
        parsed_phone=parsed.get("phone"),
        parsed_location=parsed.get("location"),
        skills=parsed.get("skills", []),
        normalized_skills=parsed.get("normalized_skills", []),
        experience_years=float(parsed.get("experience_years") or 0.0),
        education=parsed.get("education", []),
        projects=parsed.get("projects", []),
        work_experience=parsed.get("work_experience", []),
        career_breaks=parsed.get("career_breaks", []),
        skill_years=parsed.get("skill_years") or {},
        embedding=embedding,
        summary=parsed.get("summary"),
        parse_version=PARSER_VERSION,
    )
    db.add(stored)
    await db.commit()
    await db.refresh(stored)
    return stored


@router.patch("/my-resumes/{resume_id}", response_model=StoredResumeOut)
@limiter.limit("30/minute")
async def update_stored_resume(
    request: Request,
    resume_id: str,
    body: StoredResumeLabelUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    stored = (await db.execute(
        select(StoredResume).where(StoredResume.id == resume_id, StoredResume.user_id == user.id)
    )).scalar_one_or_none()
    if not stored:
        raise HTTPException(status_code=404, detail="Resume not found")

    if body.label is not None:
        stored.label = body.label[:255]

    # FIX Finding 22: also handle is_default=False
    if body.is_default is True:
        from sqlalchemy import update as _update
        await db.execute(
            _update(StoredResume).where(StoredResume.user_id == user.id).values(is_default=False)
        )
        stored.is_default = True
    elif body.is_default is False:
        stored.is_default = False

    await db.commit()
    await db.refresh(stored)
    return stored


@router.delete("/my-resumes/{resume_id}", status_code=204)
async def delete_stored_resume(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    import os
    stored = (await db.execute(
        select(StoredResume).where(StoredResume.id == resume_id, StoredResume.user_id == user.id)
    )).scalar_one_or_none()
    if not stored:
        raise HTTPException(status_code=404, detail="Resume not found")

    was_default = stored.is_default

    try:
        if stored.resume_path and os.path.exists(stored.resume_path):
            import pathlib as _pl
            _upload_dir = _pl.Path(settings.UPLOAD_DIR).resolve()
            _real = _pl.Path(stored.resume_path).resolve()
            # CRIT-1 FIX: use pathlib containment â€” os.sep is OS-specific and
            # breaks when Windows paths are stored in a Linux Docker container.
            if _upload_dir in _real.parents or _real == _upload_dir:
                os.remove(stored.resume_path)
    except FileNotFoundError:
        # Already removed by another process or cleanup job.
        pass
    except Exception as exc:
        logger.error("Failed to remove stored resume file %s: %s", stored.resume_path, exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to delete resume file from storage. Please retry.",
        ) from exc

    await db.delete(stored)
    await db.flush()

    if was_default:
        next_stored = (await db.execute(
            select(StoredResume)
            .where(StoredResume.user_id == user.id)
            .order_by(StoredResume.uploaded_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        if next_stored:
            next_stored.is_default = True

    await db.commit()
    return None


@router.get("/my-resumes/{resume_id}/download")
async def download_stored_resume(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    import os
    import re
    from fastapi.responses import Response

    stored = (await db.execute(
        select(StoredResume).where(StoredResume.id == resume_id, StoredResume.user_id == user.id)
    )).scalar_one_or_none()
    if not stored or not os.path.exists(stored.resume_path):
        raise HTTPException(status_code=404, detail="Resume file not found")

    import pathlib
    _upload_dir = pathlib.Path(settings.UPLOAD_DIR).resolve()
    _real = pathlib.Path(stored.resume_path).resolve()
    # CRIT-1 FIX: pathlib containment check â€” cross-platform, no os.sep dependency.
    if _upload_dir not in _real.parents and _real != _upload_dir:
        raise HTTPException(status_code=403, detail="Access to this file is not permitted")

    ext = os.path.splitext(stored.resume_path)[1] or ".pdf"
    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "", stored.label.replace(" ", "_")) + ext

    encrypted_size = await asyncio.to_thread(lambda: _real.stat().st_size)
    if encrypted_size > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_FILE_SIZE_MB} MB limit.")
    try:
        decrypted = await asyncio.to_thread(encryption_service.decrypt_file_from_path, str(_real))
    except encryption_service.DecryptionError:
        raise HTTPException(
            status_code=422,
            detail="Resume decryption failed. File encryption key mismatch or corruption.",
        )

    return Response(
        content=decrypted,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'inline; filename="{safe_name}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


# Candidate KYC Documents (separate DB)
@router.get("/my-kyc-documents", response_model=list[CandidateKycDocumentOut])
async def list_kyc_documents(
    kyc_db: AsyncSession = Depends(get_kyc_db),
    user: User = Depends(require_candidate),
):
    docs = (await kyc_db.execute(
        select(CandidateKycDocument)
        .where(CandidateKycDocument.user_id == user.id)
        .order_by(CandidateKycDocument.updated_at.desc())
    )).scalars().all()
    return docs


@router.get("/my-kyc-checklist", response_model=CandidateKycChecklistOut)
async def get_kyc_checklist(
    kyc_db: AsyncSession = Depends(get_kyc_db),
    user: User = Depends(require_candidate),
):
    docs = (await kyc_db.execute(
        select(CandidateKycDocument).where(CandidateKycDocument.user_id == user.id)
    )).scalars().all()
    doc_map = {d.doc_type.value: d for d in docs}
    items: list[CandidateKycChecklistItem] = []
    for doc_type in _KYC_DOC_TYPES:
        row = doc_map.get(doc_type)
        items.append(
            CandidateKycChecklistItem(
                doc_type=doc_type,
                label=_KYC_DOC_LABELS.get(doc_type, doc_type),
                mandatory=doc_type in _KYC_MANDATORY_DOC_TYPES,
                uploaded=row is not None,
                status=(row.status.value if row else None),
                updated_at=(row.updated_at if row else None),
            )
        )
    return CandidateKycChecklistOut(
        all_mandatory_uploaded=all(item.uploaded for item in items if item.mandatory),
        items=items,
    )


@router.post("/kyc-consent/{candidate_id}", response_model=CandidateKycConsentOut)
async def set_kyc_consent(
    candidate_id: str,
    body: CandidateKycConsentUpdate,
    db: AsyncSession = Depends(get_db),
    kyc_db: AsyncSession = Depends(get_kyc_db),
    user: User = Depends(require_candidate),
):
    candidate = (await db.execute(
        select(Candidate).where(Candidate.id == candidate_id, Candidate.user_id == user.id)
    )).scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Application not found")
    if not candidate.job_id:
        raise HTTPException(status_code=422, detail="Consent requires a job-linked application")

    job = await db.get(JobDescription, candidate.job_id)
    recruiter_user_id = (job.created_by if job else None)
    if not recruiter_user_id:
        raise HTTPException(status_code=422, detail="Recruiter owner not found for this application")

    existing = (await kyc_db.execute(
        select(CandidateKycConsent).where(
            CandidateKycConsent.candidate_id == candidate.id,
            CandidateKycConsent.candidate_user_id == user.id,
            CandidateKycConsent.recruiter_user_id == recruiter_user_id,
            CandidateKycConsent.job_id == candidate.job_id,
        )
    )).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if existing:
        existing.granted = bool(body.granted)
        existing.granted_at = now if body.granted else existing.granted_at
        existing.revoked_at = None if body.granted else now
        target = existing
    else:
        target = CandidateKycConsent(
            candidate_id=candidate.id,
            candidate_user_id=user.id,
            recruiter_user_id=recruiter_user_id,
            job_id=candidate.job_id,
            granted=bool(body.granted),
            granted_at=(now if body.granted else None),
            revoked_at=(None if body.granted else now),
        )
        kyc_db.add(target)

    await kyc_db.commit()
    await kyc_db.refresh(target)
    return CandidateKycConsentOut(
        candidate_id=target.candidate_id,
        recruiter_user_id=target.recruiter_user_id,
        job_id=target.job_id,
        granted=bool(target.granted),
        granted_at=target.granted_at,
        revoked_at=target.revoked_at,
        updated_at=target.updated_at,
    )


@router.get("/kyc-consents", response_model=list[CandidateKycConsentOut])
async def list_kyc_consents(
    kyc_db: AsyncSession = Depends(get_kyc_db),
    user: User = Depends(require_candidate),
):
    rows = (await kyc_db.execute(
        select(CandidateKycConsent)
        .where(CandidateKycConsent.candidate_user_id == user.id)
        .order_by(CandidateKycConsent.updated_at.desc())
    )).scalars().all()
    return [
        CandidateKycConsentOut(
            candidate_id=row.candidate_id,
            recruiter_user_id=row.recruiter_user_id,
            job_id=row.job_id,
            granted=bool(row.granted),
            granted_at=row.granted_at,
            revoked_at=row.revoked_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.get("/kyc-magic/context", response_model=CandidateKycMagicContextOut)
async def get_kyc_magic_context(
    token: str = Query(..., min_length=20, max_length=2048),
    kyc_db: AsyncSession = Depends(get_kyc_db),
):
    normalized_token = (token or "").strip()
    invite = (await kyc_db.execute(
        select(CandidateKycInvite).where(
            CandidateKycInvite.token_hash == _kyc_invite_token_hash(normalized_token)
        )
    )).scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="KYC invite is invalid or expired")
    now = _utc_now()
    if invite.revoked_at is not None:
        raise HTTPException(status_code=410, detail="This KYC invite is no longer active")
    if invite.used_at is not None:
        raise HTTPException(status_code=410, detail="This KYC invite has already been used")
    if _as_utc(invite.expires_at) <= now:
        raise HTTPException(status_code=410, detail="This KYC invite has expired")

    return CandidateKycMagicContextOut(
        valid=True,
        invite_id=invite.id,
        candidate_id=invite.candidate_id,
        job_id=invite.job_id,
        expires_at=invite.expires_at,
        purpose=invite.purpose,
        access_scope=invite.access_scope,
        retention_days=int(invite.retention_days),
        require_masked_aadhaar=bool(invite.require_masked_aadhaar),
        legal_hold_required=bool(invite.legal_hold_required),
        allowed_doc_types=list(_KYC_DOC_TYPES),
        mandatory_doc_types=list(_KYC_MANDATORY_DOC_TYPES),
    )


@router.post("/kyc-magic/upload", response_model=CandidateKycMagicUploadOut, status_code=201)
async def upload_kyc_documents_with_magic_link(
    token: str = Form(..., min_length=20),
    consent_given: bool = Form(...),
    consent_purpose_ack: str = Form("", max_length=512),
    consent_access_ack: str = Form("", max_length=512),
    consent_retention_ack_days: int = Form(..., ge=30, le=3650),
    aadhaar_masked_confirmed: bool = Form(False),
    doc_types: list[str] = Form(...),
    files: list[UploadFile] = File(...),
    kyc_db: AsyncSession = Depends(get_kyc_db),
):
    normalized_token = (token or "").strip()
    if not consent_given:
        raise HTTPException(status_code=422, detail="Explicit consent is required before KYC upload")
    if not (consent_purpose_ack or "").strip():
        raise HTTPException(status_code=422, detail="Consent purpose acknowledgement is required")
    if not (consent_access_ack or "").strip():
        raise HTTPException(status_code=422, detail="Consent access acknowledgement is required")
    if not doc_types or not files:
        raise HTTPException(status_code=422, detail="At least one document is required")
    if len(doc_types) != len(files):
        raise HTTPException(status_code=422, detail="Each uploaded file must include a matching doc_type")
    provided_types = {(value or "").strip().lower() for value in doc_types}
    missing_mandatory = [d for d in _KYC_MANDATORY_DOC_TYPES if d not in provided_types]
    if missing_mandatory:
        raise HTTPException(
            status_code=422,
            detail=f"Missing mandatory documents: {', '.join(missing_mandatory)}",
        )

    invite = (await kyc_db.execute(
        select(CandidateKycInvite).where(
            CandidateKycInvite.token_hash == _kyc_invite_token_hash(normalized_token)
        )
    )).scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="KYC invite is invalid or expired")

    now = _utc_now()
    if invite.revoked_at is not None:
        raise HTTPException(status_code=410, detail="This KYC invite is no longer active")
    if invite.used_at is not None:
        raise HTTPException(status_code=410, detail="This KYC invite has already been used")
    if _as_utc(invite.expires_at) <= now:
        raise HTTPException(status_code=410, detail="This KYC invite has expired")

    if int(consent_retention_ack_days) < int(invite.retention_days):
        raise HTTPException(status_code=422, detail="Retention acknowledgement does not match invite policy")

    existing_consent = (await kyc_db.execute(
        select(CandidateKycConsent).where(
            CandidateKycConsent.candidate_id == invite.candidate_id,
            CandidateKycConsent.candidate_user_id == invite.candidate_user_id,
            CandidateKycConsent.recruiter_user_id == invite.recruiter_user_id,
            CandidateKycConsent.job_id == invite.job_id,
        )
    )).scalar_one_or_none()
    if existing_consent:
        existing_consent.granted = True
        existing_consent.granted_at = now
        existing_consent.revoked_at = None
        consent_row = existing_consent
    else:
        consent_row = CandidateKycConsent(
            candidate_id=invite.candidate_id,
            candidate_user_id=invite.candidate_user_id,
            recruiter_user_id=invite.recruiter_user_id,
            job_id=invite.job_id,
            granted=True,
            granted_at=now,
            revoked_at=None,
        )
        kyc_db.add(consent_row)

    saved_docs: list[CandidateKycDocument] = []
    retention_days = _normalize_kyc_retention_days(int(invite.retention_days))
    for raw_doc_type, file in zip(doc_types, files):
        normalized_doc_type = (raw_doc_type or "").strip().lower()
        if normalized_doc_type not in _KYC_DOC_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported doc type '{raw_doc_type}'. Use one of: {', '.join(_KYC_DOC_TYPES)}",
            )
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in settings.kyc_allowed_extensions_list:
            raise HTTPException(
                status_code=422,
                detail=f"File type '{ext or '(none)'}' is not allowed for KYC documents.",
            )
        max_size = settings.MAX_FILE_SIZE_BYTES
        buffer = bytearray()
        while chunk := await file.read(1024 * 1024):
            buffer.extend(chunk)
            if len(buffer) > max_size:
                raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_FILE_SIZE_MB} MB limit.")
        content = bytes(buffer)
        if not content:
            raise HTTPException(status_code=422, detail="Uploaded file is empty.")
        await asyncio.to_thread(file_service.validate_file_magic, content, ext)

        extracted_text = await _extract_text_for_kyc_scan(
            file.filename or f"{normalized_doc_type}{ext or '.pdf'}",
            content,
        )
        _assert_masked_aadhaar_policy(
            doc_type=normalized_doc_type,
            require_masked_aadhaar=bool(invite.require_masked_aadhaar),
            aadhaar_masked_confirmed=bool(aadhaar_masked_confirmed),
            extracted_text=extracted_text,
        )

        file_hash = hashlib.sha256(content).hexdigest()
        saved_path = await file_service.save_file(
            content,
            file.filename or f"{normalized_doc_type}.pdf",
            subfolder=f"candidate_docs/{invite.candidate_user_id}",
        )
        size_kb = max(1, len(content) // 1024)
        existing_doc = (await kyc_db.execute(
            select(CandidateKycDocument).where(
                CandidateKycDocument.user_id == invite.candidate_user_id,
                CandidateKycDocument.doc_type == CandidateDocumentType(normalized_doc_type),
            )
        )).scalar_one_or_none()

        if existing_doc:
            old_path = existing_doc.file_path
            existing_doc.original_filename = file.filename or existing_doc.original_filename
            existing_doc.file_path = saved_path
            existing_doc.file_hash = file_hash
            existing_doc.file_size_kb = size_kb
            existing_doc.status = CandidateDocumentStatus.uploaded
            existing_doc.review_note = None
            doc_row = existing_doc
            if old_path and old_path != saved_path:
                await _cleanup_previous_kyc_file(old_path)
        else:
            doc_row = CandidateKycDocument(
                user_id=invite.candidate_user_id,
                doc_type=CandidateDocumentType(normalized_doc_type),
                original_filename=file.filename or f"{normalized_doc_type}{ext or '.pdf'}",
                file_path=saved_path,
                file_hash=file_hash,
                file_size_kb=size_kb,
                status=CandidateDocumentStatus.uploaded,
            )
            kyc_db.add(doc_row)
            await kyc_db.flush()

        if not invite.legal_hold_required:
            delete_after = now + timedelta(days=retention_days)
            retention = (await kyc_db.execute(
                select(CandidateKycRetentionSchedule).where(
                    CandidateKycRetentionSchedule.document_id == doc_row.id
                )
            )).scalar_one_or_none()
            if retention:
                retention.delete_after = delete_after
            else:
                kyc_db.add(
                    CandidateKycRetentionSchedule(
                        document_id=doc_row.id,
                        delete_after=delete_after,
                    )
                )

        saved_docs.append(doc_row)

    invite.used_at = now
    invite.consent_granted_at = now
    await kyc_db.commit()
    for row in saved_docs:
        await kyc_db.refresh(row)

    return CandidateKycMagicUploadOut(
        message="KYC documents uploaded securely via consented one-time link",
        uploaded_count=len(saved_docs),
        retention_days=retention_days,
        invite_consumed=True,
        documents=[CandidateKycDocumentOut.model_validate(row) for row in saved_docs],
    )


@router.post("/my-kyc-documents/{doc_type}", response_model=CandidateKycDocumentOut, status_code=201)
async def upload_kyc_document(
    doc_type: str,
    file: UploadFile = File(...),
    kyc_db: AsyncSession = Depends(get_kyc_db),
    user: User = Depends(require_candidate),
):
    _ = (doc_type, file, kyc_db, user)
    raise HTTPException(
        status_code=403,
        detail=(
            "Direct KYC upload is disabled. "
            "Use the one-time secure KYC link shared after shortlist/pre-offer."
        ),
    )


@router.get("/my-kyc-documents/{doc_type}/download")
async def download_kyc_document(
    doc_type: str,
    kyc_db: AsyncSession = Depends(get_kyc_db),
    user: User = Depends(require_candidate),
):
    import os
    import pathlib
    import re
    from fastapi.responses import Response

    normalized_doc_type = (doc_type or "").strip().lower()
    if normalized_doc_type not in _KYC_DOC_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported doc type '{doc_type}'. Use one of: {', '.join(_KYC_DOC_TYPES)}",
        )

    row = (await kyc_db.execute(
        select(CandidateKycDocument).where(
            CandidateKycDocument.user_id == user.id,
            CandidateKycDocument.doc_type == CandidateDocumentType(normalized_doc_type),
        )
    )).scalar_one_or_none()
    if not row or not row.file_path:
        raise HTTPException(status_code=404, detail="Document not found")

    doc_path = pathlib.Path(row.file_path)
    if not doc_path.exists():
        raise HTTPException(status_code=404, detail="Document file not found")
    upload_root = pathlib.Path(settings.UPLOAD_DIR).resolve()
    resolved = doc_path.resolve()
    if upload_root not in resolved.parents and resolved != upload_root:
        raise HTTPException(status_code=403, detail="Access to this file is not permitted")

    encrypted_size = await asyncio.to_thread(lambda: resolved.stat().st_size)
    if encrypted_size > settings.MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_FILE_SIZE_MB} MB limit.")
    try:
        decrypted = await asyncio.to_thread(encryption_service.decrypt_file_from_path, str(resolved))
    except encryption_service.DecryptionError:
        raise HTTPException(
            status_code=422,
            detail="Document decryption failed. File encryption key mismatch or corruption.",
        )

    ext = os.path.splitext(row.original_filename or "")[1] or ".pdf"
    safe_label = _KYC_DOC_LABELS.get(normalized_doc_type, normalized_doc_type).replace(" ", "_")
    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "", safe_label) + ext

    return Response(
        content=decrypted,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'inline; filename="{safe_name}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )

# â”€â”€â”€ Apply with vault resume â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/apply-with-vault/{job_id}", response_model=CandidateOut, status_code=201)
async def apply_with_vault_resume(
    request: Request,
    job_id: str,
    resume_id: str,
    x_idempotency_key: Optional[str] = Header(default=None, alias="X-Idempotency-Key"),
    response: Response = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    jd = (await db.execute(select(JobDescription).where(JobDescription.id == job_id))).scalar_one_or_none()
    if not jd or not jd.is_active:
        raise HTTPException(status_code=404, detail="Job not found or closed")

    idem_key = (x_idempotency_key or "").strip()
    if idem_key:
        existing_app = (await db.execute(
            select(Candidate).where(Candidate.job_id == job_id, Candidate.user_id == user.id)
        )).scalar_one_or_none()
        if existing_app:
            response.status_code = 200
            return existing_app

    stored = (await db.execute(
        select(StoredResume).where(StoredResume.id == resume_id, StoredResume.user_id == user.id)
    )).scalar_one_or_none()
    if not stored:
        raise HTTPException(status_code=404, detail="Stored resume not found")

    has_cache = _resume_cache_is_current(stored)

    if has_cache:
        exp_years = float(stored.experience_years or 0.0)
        skill_yrs = stored.skill_years or {}
        normalized_skills = stored.normalized_skills or []
        projects = stored.projects or []
        education = stored.education or []
        location = stored.parsed_location
        resume_embedding = stored.embedding or []
        file_hash = stored.file_hash or ""
        work_experience = stored.work_experience or []
        career_breaks = stored.career_breaks or []
        summary = stored.summary or ""
        raw_text_for_store = summary[:5000]
        # Prefer storing full extracted text when source file is still available.
        # Fallback to summary only if read/decrypt/extract fails.
        if stored.resume_path:
            try:
                file_bytes = await asyncio.to_thread(
                    encryption_service.decrypt_file_from_path,
                    stored.resume_path,
                )
                extracted_text = await file_service.extract_text_from_bytes(
                    stored.original_filename,
                    file_bytes,
                )
                if extracted_text:
                    raw_text_for_store = extracted_text[:40000]
            except Exception as _raw_text_err:
                logger.warning(
                    "[vault-apply] full raw text refresh failed for %s: %s; using summary fallback",
                    stored.id, _raw_text_err,
                )
    else:
        import os
        if not os.path.exists(stored.resume_path):
            raise HTTPException(status_code=404, detail="Resume file missing from storage")

        # FIX Finding 8 & 9: use direct decrypted bytes path
        import pathlib
        encrypted_size = await asyncio.to_thread(lambda: pathlib.Path(stored.resume_path).stat().st_size)
        # HIGH-1 FIX: use settings instead of hardcoded 5 MB
        if encrypted_size > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_FILE_SIZE_MB} MB limit.")
        try:
            file_bytes = await asyncio.to_thread(
                encryption_service.decrypt_file_from_path,
                stored.resume_path,
            )
        except encryption_service.DecryptionError:
            raise HTTPException(
                status_code=422,
                detail="Resume decryption failed. File encryption key mismatch or corruption.",
            )
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        class _VaultFileStub:
            """
            UploadFile-compatible minimal adapter used only by vault-apply.
            Keeps file_service contract explicit and prevents ad-hoc attribute errors.
            """

            def __init__(self, filename: str, content: bytes):
                import mimetypes

                self.filename = filename or "resume.pdf"
                self.content_type = mimetypes.guess_type(self.filename)[0] or "application/octet-stream"
                self.headers = {"content-length": str(len(content))}
                self._content = content
                self._consumed = False

            async def read(self) -> bytes:
                if self._consumed:
                    return b""
                self._consumed = True
                return self._content

        vault_file = _VaultFileStub(stored.original_filename or "resume.pdf", file_bytes)
        text, _ = await file_service.extract_text(vault_file)
        _ensure_resume_text_quality(text, context="stored resume re-parse")
        parsed: dict = {}
        resume_embedding: list = []
        if settings.DATABASE_URL.startswith("sqlite"):
            parsed = resume_fallback_parser.coerce_parsed_resume(None, text=text)
            resume_embedding = []
        else:
            parsed_res, embedding_res = await asyncio.gather(
                _run_parse_resume(request=request, resume_text=text),
                _run_get_embedding(request=request, text=text[:6000]),
                return_exceptions=True,
            )
            if isinstance(parsed_res, Exception):
                logger.warning("[vault-apply] parse_resume unavailable; using stored fallback fields: %s", parsed_res)
                parsed = resume_fallback_parser.coerce_parsed_resume(None, text=text)
            else:
                parsed = resume_fallback_parser.coerce_parsed_resume(
                    parsed_res if isinstance(parsed_res, dict) else None,
                    text=text,
                )
            if isinstance(embedding_res, Exception):
                logger.warning("[vault-apply] embedding unavailable; using zero vector similarity: %s", embedding_res)
                resume_embedding = []
            else:
                resume_embedding = embedding_res or []

        _apply_stored_resume_parse_cache(
            stored,
            parsed if isinstance(parsed, dict) else {},
            resume_embedding,
            file_hash=file_hash,
        )
        # FIX Finding 24: Commit parsing cache immediately so it's not lost if AI scoring throws exception
        await db.commit()

        exp_years = float(stored.experience_years or 0.0)
        skill_yrs = stored.skill_years or {}
        normalized_skills = stored.normalized_skills or []
        projects = stored.projects or []
        education = stored.education or []
        location = stored.parsed_location
        work_experience = stored.work_experience or []
        career_breaks = stored.career_breaks or []
        summary = stored.summary or ""
        raw_text_for_store = text[:40000]  # BUG-NEW-13 FIX: full extracted text, not just summary

    rule_skill_pct = scoring_service.skill_match_score(
        normalized_skills, jd.must_have_skills or [], jd.good_to_have_skills or [])
    # BUG-NEW-2 FIX: compute critical_missing_count so the penalty multiplier in
    # compute_resume_score_with_ai_override matches the HR-upload path (resumes.py:339).
    critical_missing_count = sum(
        1 for skill in (jd.must_have_skills or [])
        if not scoring_service.semantic_skill_match(skill, normalized_skills)
    )
    rule_exp_pct = scoring_service.experience_match_score(
        exp_years, jd.experience_min, jd.experience_max, skill_yrs, jd.must_have_skills or [])
    rule_proj_pct = scoring_service.project_relevance_score(
        projects, jd.must_have_skills or [], jd.good_to_have_skills or [], exp_years)
    edu_pct = scoring_service.education_match_score(
        education, experience_years=exp_years,
        jd_description=jd.description or "", jd_must_have=jd.must_have_skills or [],
        jd_education_requirement=getattr(jd, "education_requirement", None),
    )
    loc_pct = scoring_service.location_match_score(location, jd.location)
    try:
        vec_sim = scoring_service.cosine_similarity(resume_embedding, jd.embedding or [])
    except ValueError as vec_err:
        logger.warning("Vector similarity degraded for candidate preview: %s", vec_err)
        vec_sim = 0.0

    _jd_content = _json.dumps({
        "must": sorted(jd.must_have_skills or []), "good": sorted(jd.good_to_have_skills or []),
        "exp_min": jd.experience_min, "exp_max": jd.experience_max,
    }, sort_keys=True)
    # FIX Finding 18: Use SHA-256 instead of truncated MD5
    jd_hash = hashlib.sha256(_jd_content.encode()).hexdigest()[:16]

    ai_scores: dict | None = None
    if not settings.DATABASE_URL.startswith("sqlite"):
        try:
            ai_scores = await _run_resume_scorer(
                request=request,
                parsed_resume={
                    "name": stored.parsed_name if has_cache else None,
                    "email": stored.parsed_email if has_cache else None,
                    "location": location, "experience_years": exp_years,
                    "skills": stored.skills or normalized_skills,
                    "normalized_skills": normalized_skills, "skill_years": skill_yrs,
                    "work_experience": work_experience, "projects": projects, "education": education,
                },
                job_title=jd.title,
                exp_min=jd.experience_min,
                exp_max=jd.experience_max,
                must_have=jd.must_have_skills or [],
                good_to_have=jd.good_to_have_skills or [],
                description=jd.description or "",
            )
        except Exception as ai_err:
            logger.warning(
                "[vault-apply] AI scoring failed for %s - rule-based fallback: %s", stored.label, ai_err)

    has_jd_criteria = _jd_has_meaningful_criteria(jd)
    phase_b_weights, phase_b_bias, phase_b_meta = scoring_service.build_phase_b_calibration(
        experience_years=exp_years,
        job_title=jd.title,
        job_role=jd.role,
        jd_description=jd.description or "",
        jd_must_have=jd.must_have_skills or [],
        jd_good_to_have=jd.good_to_have_skills or [],
        exp_min=jd.experience_min,
        exp_max=jd.experience_max,
    )

    resume_score, used_skill_pct, used_exp_pct, used_proj_pct = (
        scoring_service.compute_resume_score_with_ai_override(
            ai_scores=ai_scores, education_pct=edu_pct, vector_sim=vec_sim,
            location_pct=loc_pct, experience_years=exp_years,
            rule_skill_pct=rule_skill_pct, rule_exp_pct=rule_exp_pct, rule_proj_pct=rule_proj_pct,
            critical_missing_count=critical_missing_count,  # BUG-NEW-2 FIX
            has_jd_skills=has_jd_criteria,
            total_must_have_count=len(jd.must_have_skills or []),
            vector_available=bool(resume_embedding) and bool(jd.embedding or []),
            calibrated_weights=phase_b_weights,
            score_bias_points=phase_b_bias,
            phase_c_enabled=bool(settings.PHASE_C_SCORING_ENABLED),
            ai_confidence=str((ai_scores or {}).get("confidence", "")),
            jd_signal_strength=phase_b_meta.get("jd_signal_strength"),
            required_skills=jd.must_have_skills or [],
            work_experience=work_experience,
            skill_years=skill_yrs,
        )
    )

    tag = scoring_service.assign_tag(resume_score)
    ai = ai_scores or {}
    score_breakdown = {
        "ai_score_used": ai_scores is not None,
        "ai_skill_score": ai.get("skill_score"), "ai_experience_score": ai.get("experience_score"),
        "ai_project_score": ai.get("project_score"),
        "matched_must_have": ai.get("matched_must_have", []),
        "missing_must_have": ai.get("missing_must_have", []),
        "matched_good_to_have": ai.get("matched_good_to_have", []),
        "missing_good_to_have": ai.get("missing_good_to_have", []),
        "reasoning": ai.get("reasoning", ""), "domain_fit": ai.get("domain_fit", "exact"),
        "seniority_match": ai.get("seniority_match", "exact"),
        "hire_recommendation": ai.get("hire_recommendation", "maybe"),
        "red_flags": ai.get("red_flags", []), "standout_factors": ai.get("standout_factors", []),
        "confidence": ai.get("confidence", "medium"),
        "rule_based": {
            "skill_pct": round(rule_skill_pct, 1),
            "exp_pct": round(rule_exp_pct, 1),
            "proj_pct": round(rule_proj_pct, 1),
        },
        "candidate_tier": scoring_service.detect_candidate_tier(exp_years),
        "from_vault": True, "from_cache": has_cache,
        "phase_b_calibration": phase_b_meta,
        "phase_c_applied": bool(settings.PHASE_C_SCORING_ENABLED),
        "jd_hash": jd_hash,
    }

    # Use authenticated account email as canonical contact for portal-bound
    # applications; parsed resume email can differ and break account notifications.
    final_email = user.email or (stored.parsed_email if has_cache else None)
    
    # FIX: Prevent 500 IntegrityError when the parsed email already exists for this job under a different user_id
    email_conflict = (await db.execute(
        select(Candidate).where(Candidate.job_id == job_id, Candidate.email == final_email)
    )).scalars().first()
    if email_conflict:
        raise HTTPException(status_code=409, detail=f"An application with the email {final_email} already exists for this job.")

    candidate_values = {
        "job_id": jd.id,
        "user_id": user.id,
        "file_hash": file_hash,
        "name": (stored.parsed_name if has_cache else None) or user.full_name,
        "email": final_email,
        "phone": (stored.parsed_phone if has_cache else None),
        "skills": stored.skills or [],
        "normalized_skills": normalized_skills,
        "experience_years": exp_years,
        "education": education,
        "projects": projects,
        "work_experience": work_experience,
        "career_breaks": career_breaks,
        "skill_years": skill_yrs,
        "location": location,
        "raw_resume_text": encryption_service.encrypt_text(raw_text_for_store) if raw_text_for_store else "",
        "resume_path": stored.resume_path,
        "embedding": resume_embedding,
        "skill_match_pct": used_skill_pct,
        "experience_match_pct": used_exp_pct,
        "project_relevance_pct": used_proj_pct,
        "education_match_pct": edu_pct,
        "location_match_pct": loc_pct,
        "vector_similarity": vec_sim,
        "resume_score": resume_score,
        "final_score": resume_score,
        "tag": tag,
        "score_breakdown": score_breakdown,
    }
    candidate = await _insert_application_atomic(db, candidate_values)
    if candidate is None:
        if idem_key:
            existing_app = (await db.execute(
                select(Candidate).where(Candidate.job_id == job_id, Candidate.user_id == user.id)
            )).scalar_one_or_none()
            if existing_app:
                response.status_code = 200
                return existing_app
        raise HTTPException(status_code=409, detail="You have already applied to this job")

    quiz_attempt: QuizAttempt | None = None
    quiz_raw_token: Optional[str] = None
    if tag in (CandidateTag.strong, CandidateTag.medium):
        quiz = (await db.execute(
            select(Quiz).where(Quiz.job_id == jd.id, Quiz.is_active == True)
            .order_by(Quiz.created_at.desc())
        )).scalars().first()
        if quiz:
            quiz_raw_token, quiz_token_hash = _new_quiz_token_pair()
            quiz_attempt = QuizAttempt(
                quiz_id=quiz.id,
                candidate_id=candidate.id,
                token_hash=quiz_token_hash,
                token_expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            )
            db.add(quiz_attempt)

    await db.flush()
    await log_action(db, user.id, "CANDIDATE_APPLY_VAULT", "candidate", candidate.id,
                     details={"job_id": job_id, "stored_resume_id": resume_id, "tag": tag.value if tag else None})
    await db.commit()
    await db.refresh(candidate)
    if quiz_attempt and candidate.email and quiz_raw_token:
        try:
            quiz_link = _build_quiz_magic_link(quiz_raw_token)
            await _notify_candidate_shortlist_post_commit(
                candidate_email=candidate.email,
                candidate_id=candidate.id,
                jd_title=jd.title,
                quiz_link=quiz_link,
            )
        except Exception as notify_err:
            logger.warning("Vault shortlist notification send failed for candidate %s: %s", candidate.id, notify_err)
    return candidate


# â”€â”€â”€ Resume Fit Score Preview (no write) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/resume-fit/{job_id}")
async def get_resume_fit_score(
    request: Request,
    job_id: str,
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    """Returns a fit score for a stored resume vs a JD (no application created).

    BUG-3 FIX: Previously used compute_resume_score() (rule-based only) while the
    actual application pipeline uses compute_resume_score_with_ai_override(). This
    caused systematic score discrepancies â€” candidates saw a different number in
    preview vs what they received after applying. Now uses the same scoring path.
    The AI call is skipped here (cached_candidate=None, ai_scores=None passed as
    None to the override function) so rule-based weights are used, but the weight
    distribution now matches the apply path exactly.
    """
    import os

    jd = (await db.execute(select(JobDescription).where(JobDescription.id == job_id))).scalar_one_or_none()
    if not jd or not jd.is_active:
        raise HTTPException(status_code=404, detail="Job not found or closed")

    stored = (await db.execute(
        select(StoredResume).where(StoredResume.id == resume_id, StoredResume.user_id == user.id)
    )).scalar_one_or_none()
    if not stored:
        raise HTTPException(status_code=404, detail="Stored resume not found")

    has_cache = _resume_cache_is_current(stored)

    if has_cache:
        normalized_skills = stored.normalized_skills or []
        exp_years = float(stored.experience_years or 0.0)
        skill_yrs = stored.skill_years or {}
        projects = stored.projects or []
        education = stored.education or []
        location = stored.parsed_location
        resume_embedding = stored.embedding or []
    else:
        logger.info("Cache miss for StoredResume %s - re-parsing", stored.id)
        if not os.path.exists(stored.resume_path):
            raise HTTPException(status_code=404, detail="Resume file missing from storage")

        import pathlib
        encrypted_size = await asyncio.to_thread(lambda: pathlib.Path(stored.resume_path).stat().st_size)
        # HIGH-1 FIX: use settings instead of hardcoded 5 MB
        if encrypted_size > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_FILE_SIZE_MB} MB limit.")
        try:
            file_bytes = await asyncio.to_thread(
                encryption_service.decrypt_file_from_path,
                stored.resume_path,
            )
        except encryption_service.DecryptionError:
            raise HTTPException(
                status_code=422,
                detail="Resume decryption failed. File encryption key mismatch or corruption.",
            )
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        text = await file_service.extract_text_from_bytes(
            stored.original_filename,
            file_bytes,
        )
        _ensure_resume_text_quality(text, context="resume-fit preview re-parse")
        if settings.DATABASE_URL.startswith("sqlite"):
            parsed = resume_fallback_parser.coerce_parsed_resume(None, text=text)
            resume_embedding = []
        else:
            parsed, resume_embedding = await asyncio.gather(
                _run_parse_resume(request=request, resume_text=text),
                _run_get_embedding(request=request, text=text[:6000]),
                return_exceptions=True,
            )
            if isinstance(parsed, Exception):
                parsed = resume_fallback_parser.coerce_parsed_resume(None, text=text)
            elif isinstance(parsed, dict):
                parsed = resume_fallback_parser.coerce_parsed_resume(parsed, text=text)
            else:
                parsed = resume_fallback_parser.coerce_parsed_resume(None, text=text)
            if isinstance(resume_embedding, Exception):
                resume_embedding = []

        _apply_stored_resume_parse_cache(
            stored,
            parsed if isinstance(parsed, dict) else {},
            resume_embedding if isinstance(resume_embedding, list) else [],
            file_hash=file_hash,
        )
        await db.commit()

        normalized_skills = stored.normalized_skills or []
        exp_years = float(stored.experience_years or 0.0)
        skill_yrs = stored.skill_years or {}
        projects = stored.projects or []
        education = stored.education or []
        location = stored.parsed_location
        resume_embedding = stored.embedding or []

    rule_skill_pct = scoring_service.skill_match_score(
        normalized_skills, jd.must_have_skills or [], jd.good_to_have_skills or [])
    rule_exp_pct = scoring_service.experience_match_score(
        exp_years, jd.experience_min, jd.experience_max, skill_yrs, jd.must_have_skills or [])
    rule_proj_pct = scoring_service.project_relevance_score(
        projects, jd.must_have_skills or [], jd.good_to_have_skills or [], exp_years)
    edu_pct = scoring_service.education_match_score(
        education, experience_years=exp_years,
        jd_description=jd.description or "", jd_must_have=jd.must_have_skills or [],
        jd_education_requirement=getattr(jd, "education_requirement", None),
    )
    loc_pct = scoring_service.location_match_score(location, jd.location)
    try:
        vec_sim = scoring_service.cosine_similarity(resume_embedding, jd.embedding or [])
    except ValueError as vec_err:
        logger.warning("Vector similarity degraded for candidate apply flow: %s", vec_err)
        vec_sim = 0.0

    # BUG-3 FIX: use the same override function as the apply path (ai_scores=None
    # means pure rule-based weights are applied, but the tier-based weight distribution
    # is now identical to what the candidate will receive after applying).
    has_jd_criteria = _jd_has_meaningful_criteria(jd)
    phase_b_weights, phase_b_bias, phase_b_meta = scoring_service.build_phase_b_calibration(
        experience_years=exp_years,
        job_title=jd.title,
        job_role=jd.role,
        jd_description=jd.description or "",
        jd_must_have=jd.must_have_skills or [],
        jd_good_to_have=jd.good_to_have_skills or [],
        exp_min=jd.experience_min,
        exp_max=jd.experience_max,
    )

    resume_score, _, _, _ = scoring_service.compute_resume_score_with_ai_override(
        ai_scores=None,
        education_pct=edu_pct, vector_sim=vec_sim, location_pct=loc_pct,
        experience_years=exp_years,
        rule_skill_pct=rule_skill_pct, rule_exp_pct=rule_exp_pct, rule_proj_pct=rule_proj_pct,
        critical_missing_count=sum(
            1
            for skill in (jd.must_have_skills or [])
            if not scoring_service.semantic_skill_match(skill, normalized_skills)
        ),
        has_jd_skills=has_jd_criteria,
        total_must_have_count=len(jd.must_have_skills or []),
        vector_available=bool(resume_embedding) and bool(jd.embedding or []),
        calibrated_weights=phase_b_weights,
        score_bias_points=phase_b_bias,
        phase_c_enabled=bool(settings.PHASE_C_SCORING_ENABLED),
        ai_confidence=None,
        jd_signal_strength=phase_b_meta.get("jd_signal_strength"),
        required_skills=jd.must_have_skills or [],
        work_experience=stored.work_experience or [],
        skill_years=skill_yrs,
    )
    tag = scoring_service.assign_tag(resume_score)

    missing_must = [s for s in (jd.must_have_skills or [])
                    if not scoring_service.semantic_skill_match(s, normalized_skills)]
    matched_must = [s for s in (jd.must_have_skills or [])
                    if scoring_service.semantic_skill_match(s, normalized_skills)]

    return {
        "resume_score":             round(resume_score, 1),
        "skill_match_pct":          round(rule_skill_pct, 1),
        "experience_match_pct":     round(rule_exp_pct, 1),
        "project_relevance_pct":    round(rule_proj_pct, 1),
        "education_match_pct":      round(edu_pct, 1),
        "tag":                      tag.value if hasattr(tag, "value") else str(tag),
        "matched_must_have":        matched_must,
        "missing_must_have":        missing_must,
        "job_title":                jd.title,
        "resume_label":             stored.label,
        "from_cache":               has_cache,
    }


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# AI Career Tool Endpoints
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

class EnhanceResumeRequest(BaseModel):
    job_id: str
    resume_id: Optional[str] = None   # use a vault resume
    resume_text: Optional[str] = None  # or paste raw text


@router.post("/resume/enhance")
async def enhance_resume(
    request: Request,
    body: EnhanceResumeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    """
    AI-powered resume enhancement against a specific JD.

    BUG-1 FIX: This endpoint was registered twice. The second (stripped-down)
    definition shadowed the first, making vault/file paths permanently unreachable
    and removing the path-traversal guard. Merged into a single endpoint that
    accepts JSON with optional resume_id (vault) or resume_text (plain text).

    Supply exactly one of:
    - resume_id: use a resume already stored in the vault
    - resume_text: paste raw resume text directly

    Returns enhanced summary, bullet rewrites, keyword additions,
    ATS tips, and an estimated score after improvements.
    """
    if not body.resume_id and not body.resume_text:
        raise HTTPException(
            status_code=422, detail="Provide either resume_id (vault) or resume_text.")

    jd = (await db.execute(select(JobDescription).where(JobDescription.id == body.job_id))).scalar_one_or_none()
    if not jd or not jd.is_active:
        raise HTTPException(status_code=404, detail="Job not found or closed")

    parse_degraded = False
    parse_degraded_reason = ""

    if body.resume_id:
        stored = (await db.execute(
            select(StoredResume).where(StoredResume.id ==
                                       body.resume_id, StoredResume.user_id == user.id)
        )).scalar_one_or_none()
        if not stored:
            raise HTTPException(status_code=404, detail="Stored resume not found")

        import os
        import pathlib as _pathlib
        if not stored.resume_path or not os.path.exists(stored.resume_path):
            raise HTTPException(status_code=404, detail="Resume file missing from storage")

        # CRIT-1 FIX: pathlib containment check â€” cross-platform, no os.sep dependency.
        _upload_dir_p = _pathlib.Path(settings.UPLOAD_DIR).resolve()
        _real_p = _pathlib.Path(stored.resume_path).resolve()
        if _upload_dir_p not in _real_p.parents and _real_p != _upload_dir_p:
            raise HTTPException(status_code=403, detail="Access to this file is not permitted")

        encrypted_size = await asyncio.to_thread(lambda: _real_p.stat().st_size)
        # HIGH-1 FIX: use settings instead of hardcoded 5 MB
        if encrypted_size > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_FILE_SIZE_MB} MB limit.")
        try:
            file_bytes = await asyncio.to_thread(encryption_service.decrypt_file_from_path, str(_real_p))
        except encryption_service.DecryptionError:
            raise HTTPException(
                status_code=422,
                detail="Resume decryption failed. File encryption key mismatch or corruption.",
            )

        resume_text = await file_service.extract_text_from_bytes(
            stored.original_filename,
            file_bytes,
        )
        normalized_skills = stored.normalized_skills or []

    else:
        resume_text = body.resume_text
        try:
            parsed = await _run_parse_resume(request=request, resume_text=resume_text)
            parsed = resume_fallback_parser.coerce_parsed_resume(
                parsed if isinstance(parsed, dict) else None,
                text=resume_text,
            )
            normalized_skills = parsed.get("normalized_skills", [])
        except Exception as exc:
            logger.warning("Resume parse failed during enhance preview, using fast fallback: %s", exc)
            parse_degraded = True
            parse_degraded_reason = str(exc)
            normalized_skills = resume_fallback_parser.fast_parse_resume_text(
                resume_text
            ).get("normalized_skills", [])

    current_score = scoring_service.skill_match_score(
        normalized_skills, jd.must_have_skills or [], jd.good_to_have_skills or []
    )
    missing_skills = [
        s for s in (jd.must_have_skills or [])
        if not scoring_service.semantic_skill_match(s, normalized_skills)
    ]

    try:
        enhancement = await _run_enhance_resume(
            request=request,
            resume_text=resume_text,
            job_title=jd.title,
            must_have=jd.must_have_skills or [],
            good_to_have=jd.good_to_have_skills or [],
            job_description=jd.description or "",
            current_score=current_score,
            missing_skills=missing_skills,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[resume/enhance] AI enhancement failed: %s", exc)
        raise HTTPException(
            status_code=503, detail="AI enhancement service unavailable. Please try again.")

    return {
        "job_title":               jd.title,
        "current_skill_match_pct": round(current_score, 1),
        "missing_must_have":       missing_skills,
        "parser_degraded":         parse_degraded,
        "parser_degraded_reason":  parse_degraded_reason if parse_degraded else None,
        **enhancement,
    }


class BuildResumeRequest(BaseModel):
    target_role: str = ""
    # Structured format (preferred)
    personal_info: Optional[dict] = None
    work_experience: Optional[list] = None
    education: Optional[list] = None
    skills: Optional[list] = None
    projects: Optional[list] = None
    certifications: Optional[list] = None
    summary: Optional[str] = None
    # Simple text format (from the quick-build form)
    experience_summary: Optional[str] = None
    skills_list: Optional[str] = None
    education_summary: Optional[str] = None


@router.post("/resume/build")
async def build_resume(
    request: Request,
    body: BuildResumeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    """
    AI-generate a complete structured resume from either:
    - Structured input: personal_info, work_experience[], education[], skills[], projects[]
    - Quick text input: experience_summary, skills_list, education_summary (plain strings)

    BUG-1 FIX: was registered twice; second definition shadowed the first.
    BUG-2 FIX: payload size check now uses json.dumps byte length, not sys.getsizeof.
    BUG-5 FIX: target_role is now read from body.target_role (Pydantic field) so it
               is never accidentally removed before being passed to the AI function.
    """
    has_structured = bool(body.personal_info or body.work_experience)
    has_simple = bool(body.experience_summary or body.skills_list)
    if not has_structured and not has_simple:
        raise HTTPException(
            status_code=422,
            detail="Provide at least one of: personal_info/work_experience (structured) or experience_summary/skills_list (quick form).",
        )

    # BUG-2 FIX: correct byte-length check
    candidate_data = body.model_dump(exclude_none=True, exclude={"target_role"})
    if len(_json.dumps(candidate_data).encode("utf-8")) > 50_000:
        raise HTTPException(status_code=413, detail="Request payload too large (max 50 KB)")

    try:
        # BUG-5 FIX: target_role comes from body.target_role â€” never mutated
        built_resume = await _run_build_resume(
            request=request,
            candidate_data=candidate_data,
            target_role=body.target_role,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[resume/build] AI resume build failed: %s", exc)
        raise HTTPException(
            status_code=503, detail="AI resume builder unavailable. Please try again.")

    return {
        "target_role": body.target_role,
        "resume":      built_resume,
        "usage_tip":   "Use the export button to download as PDF, or copy the 'resume' object into your preferred editor.",
    }


# â”€â”€â”€ Cover Letter Generator â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/cover-letter/{job_id}")
async def generate_cover_letter(
    request: Request,
    job_id: str,
    resume_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    jd = (await db.execute(select(JobDescription).where(JobDescription.id == job_id))).scalar_one_or_none()
    if not jd or not jd.is_active:
        raise HTTPException(status_code=404, detail="Job not found or closed")

    hr_user = (await db.execute(select(User).where(User.id == jd.created_by))).scalar_one_or_none()
    company_name = _company_info(hr_user).get("company", "the company")

    if resume_id:
        stored = (await db.execute(
            select(StoredResume).where(StoredResume.id ==
                                       resume_id, StoredResume.user_id == user.id)
        )).scalar_one_or_none()
        if not stored:
            raise HTTPException(status_code=404, detail="Stored resume not found")
        candidate_name = stored.parsed_name or user.full_name
        exp_years = float(stored.experience_years or 0.0)
        skills = stored.skills or stored.normalized_skills or []
        work_history = stored.work_experience or []
        education = stored.education or []
    else:
        latest = (await db.execute(
            select(Candidate).where(Candidate.user_id == user.id, Candidate.job_id ==
                                    job_id).order_by(Candidate.created_at.desc()).limit(1)
        )).scalars().first()
        if not latest:
            latest = (await db.execute(
                select(Candidate).where(Candidate.user_id == user.id).order_by(
                    Candidate.created_at.desc()).limit(1)
            )).scalars().first()
        if not latest:
            raise HTTPException(
                status_code=400, detail="No profile found. Apply to a job first or provide a resume_id.")
        candidate_name = latest.name or user.full_name
        exp_years = float(latest.experience_years or 0.0)
        skills = latest.skills or latest.normalized_skills or []
        work_history = latest.work_experience or []
        education = latest.education or []

    try:
        cover_letter = await _run_cover_letter(
            request=request,
            candidate_name=candidate_name, exp_years=exp_years,
            skills=skills, work_history=work_history, education=education,
            company_name=company_name, job_title=jd.title,
            must_have=jd.must_have_skills or [], job_description=jd.description or "",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[cover-letter] AI generation failed: %s", exc)
        raise HTTPException(
            status_code=503, detail="Cover letter generation unavailable. Please try again.")

    return {"job_title": jd.title, "company": company_name, **cover_letter}


# â”€â”€â”€ Career Analysis â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/career-analysis")
async def get_career_analysis(
    request: Request,
    target_role: Optional[str] = Query(default=None),
    resume_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    if resume_id:
        stored = (await db.execute(
            select(StoredResume).where(StoredResume.id ==
                                       resume_id, StoredResume.user_id == user.id)
        )).scalar_one_or_none()
        if not stored:
            raise HTTPException(status_code=404, detail="Stored resume not found")
        candidate_name = stored.parsed_name or user.full_name
        exp_years = float(stored.experience_years or 0.0)
        skills = stored.normalized_skills or stored.skills or []
        work_history = stored.work_experience or []
        education = stored.education or []
        career_breaks = stored.career_breaks or []
    else:
        latest = (await db.execute(
            select(Candidate).where(Candidate.user_id == user.id).order_by(
                Candidate.created_at.desc()).limit(1)
        )).scalars().first()
        if not latest:
            raise HTTPException(
                status_code=400, detail="No profile found. Apply to a job first or upload a resume via the vault.")
        candidate_name = latest.name or user.full_name
        exp_years = float(latest.experience_years or 0.0)
        skills = latest.normalized_skills or latest.skills or []
        work_history = latest.work_experience or []
        education = latest.education or []
        career_breaks = latest.career_breaks or []

    if not skills and not work_history:
        raise HTTPException(
            status_code=400, detail="Insufficient profile data. Please upload a detailed resume first.")

    try:
        analysis = await _run_career_analysis(
            request=request,
            candidate_name=candidate_name, exp_years=exp_years,
            skills=skills, work_history=work_history, education=education,
            career_breaks=career_breaks, target_role=target_role or "",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[career-analysis] AI analysis failed: %s", exc)
        raise HTTPException(
            status_code=503, detail="Career analysis unavailable. Please try again.")

    return {
        "candidate_name":    candidate_name,
        "experience_years":  round(exp_years, 1),
        "target_role":       target_role,
        **analysis,
    }


# â”€â”€â”€ Resume PDF Generation (RenderCV) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class GeneratePDFRequest(BaseModel):
    resume: dict          # Full structured resume JSON from build_resume_from_form
    theme: Optional[str] = "classic"  # RenderCV theme


@router.post("/resume/generate-pdf")
async def generate_resume_pdf(
    body: GeneratePDFRequest,
    user: User = Depends(require_candidate),
):
    """
    Convert a structured resume JSON into a professional PDF using RenderCV.
    Returns the PDF as a binary file download.

    Supported themes: classic, engineering, sb2nov, moderncv
    """
    from app.services.rendercv_service import generate_pdf_from_resume
    from fastapi.responses import Response

    allowed_themes = {"classic", "engineering", "sb2nov", "moderncv"}
    theme = (body.theme or "classic").lower()
    if theme not in allowed_themes:
        theme = "classic"

    try:
        pdf_bytes = await generate_pdf_from_resume(body.resume, theme=theme)
    except RuntimeError as exc:
        logger.exception("[generate-resume-pdf] failed")
        raise HTTPException(
            status_code=503,
            detail="An internal error occurred."
        )

    candidate_name = (body.resume.get("contact") or {}).get("name") or "resume"
    safe_name = "".join(c for c in candidate_name if c.isalnum() or c in "_ ").replace(" ", "_")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}_resume.pdf"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


# â”€â”€â”€ Parse Existing Resume for Builder Pre-Fill â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/resume/parse-for-builder")
async def parse_resume_for_builder(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    """
    Upload an existing resume/document/image and extract structured data that can
    be used to pre-populate the Resume Builder form.

    Returns the same schema as build_resume_from_form so the frontend can
    directly populate all form fields.
    """
    import os as _os
    _raw_ext = _os.path.splitext(file.filename or "")[1].lower()
    if _raw_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=422,
            detail=f"File type '{_raw_ext or '(none)'}' is not allowed. Accepted: {', '.join(settings.allowed_extensions_list)}",
        )

    _MAX_UPLOAD = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    _content_arr = bytearray()
    while _chunk := await file.read(1024 * 1024):
        _content_arr.extend(_chunk)
        if len(_content_arr) > _MAX_UPLOAD:
            raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_FILE_SIZE_MB} MB limit.")
    content = bytes(_content_arr)

    text = await file_service.extract_text_from_bytes(file.filename or "resume", content)
    if not text or not text.strip():
        raise HTTPException(
            status_code=422,
            detail="Could not extract readable text from this file. For images/scans, upload a clearer file (front-facing, good lighting).",
        )

    try:
        parsed = await _run_parse_resume(request=request, resume_text=text)
        parsed = resume_fallback_parser.coerce_parsed_resume(
            parsed if isinstance(parsed, dict) else None,
            text=text,
        )
    except Exception as exc:
        logger.error("[parse-for-builder] parse_resume failed: %s", exc)
        parsed = resume_fallback_parser.coerce_parsed_resume(None, text=text)

    # Map the parsed resume back into the builder schema so frontend
    # can directly inject it into form state
    work_exp = []
    for job in (parsed.get("work_experience") or []):
        achievements = job.get("achievements") or []
        if not achievements and job.get("skills"):
            achievements = [f"Worked with {', '.join(job['skills'][:5])}"]
        work_exp.append({
            "company": job.get("company") or "",
            "role": job.get("role") or "",
            "start_date": job.get("start_date") or "",
            "end_date": job.get("end_date") or "Present",
            "bullets": achievements if isinstance(achievements, list) else [achievements],
            "location": "",
        })

    education = []
    for edu in (parsed.get("education") or []):
        education.append({
            "degree": edu.get("degree") or "",
            "institution": edu.get("institute") or edu.get("institution") or "",
            "year": edu.get("year") or "",
            "gpa": edu.get("gpa"),
            "highlights": [],
        })

    all_skills = parsed.get("skills") or parsed.get("normalized_skills") or []
    skills_grouped = {
        "languages": [],
        "frameworks": [],
        "databases": [],
        "tools": [],
        "cloud": [],
        "other": all_skills,
    }

    projects = []
    for proj in (parsed.get("projects") or []):
        projects.append({
            "title": proj.get("title") or "",
            "description": proj.get("description") or "",
            "technologies": proj.get("skills") or [],
            "link": "",
        })

    return {
        "contact": {
            "name": parsed.get("name") or "",
            "email": parsed.get("email") or "",
            "phone": parsed.get("phone") or "",
            "location": parsed.get("location") or "",
            "linkedin": "",
            "github": "",
        },
        "summary": parsed.get("summary") or "",
        "skills": skills_grouped,
        "work_experience": work_exp,
        "education": education,
        "projects": projects,
        "certifications": [],
        "ats_keywords": parsed.get("normalized_skills") or [],
        "_meta": {
            "experience_years": float(parsed.get("experience_years") or 0),
            "parsed_from_file": file.filename,
        },
    }



