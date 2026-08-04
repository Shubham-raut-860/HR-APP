from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Candidate, CandidateTag, JobDescription, Quiz, QuizAttempt, QuizStatus, User
from app.services.multi_agent_runtime import hr_multi_agent_runtime


def _score_value(candidate: Candidate) -> float:
    for value in (candidate.final_score, candidate.resume_score, candidate.quiz_pct):
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return 0.0


def _tag_key(tag: Any) -> str:
    value = getattr(tag, "value", tag)
    return str(value or "untagged").strip().lower()


def _candidate_public_row(candidate: Candidate, job_title: str | None = None) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "name": candidate.name or "Candidate",
        "job_id": candidate.job_id,
        "job_title": job_title,
        "tag": getattr(candidate.tag, "value", candidate.tag),
        "resume_score": round(float(candidate.resume_score or 0), 1),
        "quiz_pct": round(float(candidate.quiz_pct or 0), 1) if candidate.quiz_pct is not None else None,
        "final_score": round(float(candidate.final_score or _score_value(candidate)), 1),
        "rank": candidate.rank,
        "passed": candidate.passed,
        "skills": list(candidate.normalized_skills or candidate.skills or [])[:8],
    }


async def build_recruiter_pipeline_snapshot(
    db: AsyncSession,
    *,
    user: User,
    job_id: str | None = None,
) -> dict[str, Any]:
    job_stmt = select(JobDescription).where(JobDescription.created_by == user.id)
    if job_id:
        job_stmt = job_stmt.where(JobDescription.id == job_id)
    jobs = list((await db.execute(job_stmt.order_by(JobDescription.created_at.desc()))).scalars().all())

    if job_id and not jobs:
        owned_job = (await db.execute(
            select(JobDescription.id).where(JobDescription.id == job_id)
        )).scalar_one_or_none()
        if owned_job:
            raise HTTPException(status_code=403, detail="You do not have access to this job")
        raise HTTPException(status_code=404, detail="Job not found")

    job_ids = [job.id for job in jobs]
    job_title_by_id = {job.id: job.title for job in jobs}
    candidates: list[Candidate] = []
    quizzes: list[Quiz] = []
    attempts: list[QuizAttempt] = []
    if job_ids:
        candidates = list((await db.execute(
            select(Candidate)
            .where(Candidate.job_id.in_(job_ids))
            .where(Candidate.is_archived.is_(False))
            .order_by(Candidate.created_at.desc())
        )).scalars().all())
        quizzes = list((await db.execute(
            select(Quiz).where(Quiz.job_id.in_(job_ids))
        )).scalars().all())
        quiz_ids = [quiz.id for quiz in quizzes]
        if quiz_ids:
            attempts = list((await db.execute(
                select(QuizAttempt).where(QuizAttempt.quiz_id.in_(quiz_ids))
            )).scalars().all())

    by_job: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        if candidate.job_id:
            by_job[candidate.job_id].append(candidate)

    quiz_ids_by_job: dict[str, list[str]] = defaultdict(list)
    for quiz in quizzes:
        if quiz.job_id:
            quiz_ids_by_job[quiz.job_id].append(quiz.id)

    completed_quiz_ids = {
        attempt.quiz_id
        for attempt in attempts
        if attempt.status == QuizStatus.submitted and attempt.quiz_id
    }
    completed_attempts = sum(1 for attempt in attempts if attempt.status == QuizStatus.submitted)
    tag_counts = Counter(_tag_key(candidate.tag) for candidate in candidates)
    active_jobs = sum(1 for job in jobs if bool(job.is_active))

    job_rows: list[dict[str, Any]] = []
    risks: list[str] = []
    for job in jobs:
        job_candidates = by_job.get(job.id, [])
        job_tag_counts = Counter(_tag_key(candidate.tag) for candidate in job_candidates)
        job_quiz_ids = quiz_ids_by_job.get(job.id, [])
        completed_for_job = len([quiz_id for quiz_id in job_quiz_ids if quiz_id in completed_quiz_ids])
        if job.is_active and not job_candidates:
            risks.append(f"{job.title} is active but has no candidates yet.")
        if job_candidates and not job_quiz_ids:
            risks.append(f"{job.title} has candidates but no assessment generated.")
        if job_tag_counts.get("untagged", 0):
            risks.append(f"{job.title} has {job_tag_counts['untagged']} untagged candidate(s).")
        job_rows.append(
            {
                "id": job.id,
                "title": job.title,
                "role": job.role,
                "is_active": bool(job.is_active),
                "candidate_count": len(job_candidates),
                "strong_candidates": job_tag_counts.get("strong", 0),
                "medium_candidates": job_tag_counts.get("medium", 0),
                "rejected_candidates": job_tag_counts.get("reject", 0),
                "untagged_candidates": job_tag_counts.get("untagged", 0),
                "quiz_count": len(job_quiz_ids),
                "completed_assessments": completed_for_job,
            }
        )

    top_candidates = sorted(candidates, key=_score_value, reverse=True)[:10]
    return {
        "data_scope": "recruiter_owned",
        "recruiter_id": str(user.id),
        "job_filter": job_id,
        "metrics": {
            "total_jobs": len(jobs),
            "active_jobs": active_jobs,
            "total_candidates": len(candidates),
            "strong_candidates": tag_counts.get("strong", 0),
            "medium_candidates": tag_counts.get("medium", 0),
            "rejected_candidates": tag_counts.get("reject", 0),
            "untagged_candidates": tag_counts.get("untagged", 0),
            "quiz_count": len(quizzes),
            "assessment_attempts": len(attempts),
            "completed_assessments": completed_attempts,
        },
        "jobs": job_rows,
        "top_candidates": [
            _candidate_public_row(candidate, job_title_by_id.get(candidate.job_id or ""))
            for candidate in top_candidates
        ],
        "risks": risks[:10],
    }


async def run_recruiter_copilot(
    db: AsyncSession,
    *,
    user: User,
    question: str,
    job_id: str | None = None,
) -> dict[str, Any]:
    snapshot = await build_recruiter_pipeline_snapshot(db, user=user, job_id=job_id)
    result = await hr_multi_agent_runtime.run_recruiter_copilot(
        snapshot=snapshot,
        question=question,
        timeout_s=min(10.0, float(getattr(settings, "AGENT_MAX_TIMEOUT_SECONDS", 90.0))),
    )
    return {
        **result,
        "snapshot": {
            "metrics": snapshot["metrics"],
            "jobs": snapshot["jobs"],
            "data_scope": snapshot["data_scope"],
        },
    }
