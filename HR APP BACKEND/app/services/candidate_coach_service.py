from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import Candidate, QuizAttempt, QuizStatus, StoredResume, User
from app.services.multi_agent_runtime import hr_multi_agent_runtime


def _round_optional(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def _application_status(candidate: Candidate) -> str:
    breakdown = candidate.score_breakdown if isinstance(candidate.score_breakdown, dict) else {}
    status = str(breakdown.get("application_status") or "").strip().lower()
    return status if status in {"active", "withdrawn"} else "active"


def _candidate_row(candidate: Candidate, attempt: QuizAttempt | None) -> dict[str, Any]:
    job = candidate.job
    return {
        "candidate_id": candidate.id,
        "job_id": candidate.job_id,
        "job_title": job.title if job else "Unknown job",
        "job_role": job.role if job else None,
        "application_status": _application_status(candidate),
        "tag": getattr(candidate.tag, "value", candidate.tag),
        "resume_score": _round_optional(candidate.resume_score),
        "quiz_pct": _round_optional(candidate.quiz_pct),
        "final_score": _round_optional(candidate.final_score),
        "rank": candidate.rank,
        "passed": candidate.passed,
        "quiz_status": attempt.status.value if attempt else None,
        "skills": list(candidate.normalized_skills or candidate.skills or [])[:8],
    }


def _resume_row(resume: StoredResume) -> dict[str, Any]:
    return {
        "id": resume.id,
        "label": resume.label,
        "original_filename": resume.original_filename,
        "is_default": bool(resume.is_default),
        "uploaded_at": resume.uploaded_at.isoformat() if resume.uploaded_at else None,
        "experience_years": _round_optional(resume.experience_years),
        "skills": list(resume.normalized_skills or resume.skills or [])[:8],
        "summary": (resume.summary or "")[:600] if resume.summary else None,
        "is_parsed": bool(resume.normalized_skills or resume.skills or resume.summary),
    }


async def build_candidate_coach_snapshot(
    db: AsyncSession,
    *,
    user: User,
    candidate_id: str | None = None,
) -> dict[str, Any]:
    candidate_stmt = (
        select(Candidate)
        .options(selectinload(Candidate.job))
        .where(Candidate.user_id == user.id)
        .order_by(Candidate.created_at.desc())
    )
    if candidate_id:
        candidate_stmt = candidate_stmt.where(Candidate.id == candidate_id)

    candidates = list((await db.execute(candidate_stmt)).scalars().all())

    if candidate_id and not candidates:
        exists = (await db.execute(select(Candidate.id).where(Candidate.id == candidate_id))).scalar_one_or_none()
        if exists:
            raise HTTPException(status_code=403, detail="Not your application")
        raise HTTPException(status_code=404, detail="Application not found")

    candidate_ids = [candidate.id for candidate in candidates]
    attempts: list[QuizAttempt] = []
    if candidate_ids:
        attempts = list((await db.execute(
            select(QuizAttempt)
            .where(QuizAttempt.candidate_id.in_(candidate_ids))
            .order_by(QuizAttempt.created_at.desc())
        )).scalars().all())

    latest_attempt_by_candidate: dict[str, QuizAttempt] = {}
    for attempt in attempts:
        latest_attempt_by_candidate.setdefault(attempt.candidate_id, attempt)

    resumes = list((await db.execute(
        select(StoredResume)
        .where(StoredResume.user_id == user.id)
        .order_by(StoredResume.uploaded_at.desc())
    )).scalars().all())

    application_rows = [
        _candidate_row(candidate, latest_attempt_by_candidate.get(candidate.id))
        for candidate in candidates
    ]
    resume_rows = [_resume_row(resume) for resume in resumes]

    active_applications = sum(1 for candidate in candidates if _application_status(candidate) == "active")
    pending_assessments = sum(
        1 for attempt in latest_attempt_by_candidate.values()
        if attempt.status in (QuizStatus.pending, QuizStatus.in_progress)
    )
    completed_assessments = sum(
        1 for attempt in latest_attempt_by_candidate.values()
        if attempt.status == QuizStatus.submitted
    )
    shortlisted = sum(1 for candidate in candidates if str(getattr(candidate.tag, "value", candidate.tag) or "").lower() == "strong")
    rejected = sum(1 for candidate in candidates if str(getattr(candidate.tag, "value", candidate.tag) or "").lower() == "reject")

    risks: list[str] = []
    if not resumes:
        risks.append("No resume is saved in your vault yet.")
    if candidates and pending_assessments:
        risks.append(f"{pending_assessments} assessment(s) still need completion.")
    if candidates and not any(candidate.final_score is not None for candidate in candidates):
        risks.append("Some applications do not have final scoring yet.")

    return {
        "data_scope": "candidate_owned",
        "candidate_user_id": str(user.id),
        "candidate_filter": candidate_id,
        "metrics": {
            "total_applications": len(candidates),
            "active_applications": active_applications,
            "withdrawn_applications": len(candidates) - active_applications,
            "shortlisted_applications": shortlisted,
            "rejected_applications": rejected,
            "pending_assessments": pending_assessments,
            "completed_assessments": completed_assessments,
            "vault_resumes": len(resumes),
        },
        "applications": application_rows,
        "resumes": resume_rows,
        "risks": risks[:10],
    }


async def run_candidate_coach(
    db: AsyncSession,
    *,
    user: User,
    question: str,
    candidate_id: str | None = None,
) -> dict[str, Any]:
    snapshot = await build_candidate_coach_snapshot(db, user=user, candidate_id=candidate_id)
    result = await hr_multi_agent_runtime.run_candidate_coach(
        snapshot=snapshot,
        question=question,
        timeout_s=min(10.0, float(getattr(settings, "AGENT_MAX_TIMEOUT_SECONDS", 90.0))),
    )
    return {
        **result,
        "snapshot": {
            "metrics": snapshot["metrics"],
            "applications": snapshot["applications"],
            "resumes": snapshot["resumes"],
            "data_scope": snapshot["data_scope"],
        },
    }
