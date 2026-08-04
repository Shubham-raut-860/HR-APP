from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Candidate, JobDescription, User, UserRole


async def assert_bulk_candidate_access(
    db: AsyncSession,
    *,
    user: User,
    candidate_ids: list[str],
) -> None:
    """
    Ensure a non-admin HR user can mutate only candidates from their jobs or
    their own resume pool rows. Admin users are allowed across recruiters.
    """
    if not candidate_ids or user.role == UserRole.admin:
        return

    owned_job_ids = (
        await db.execute(select(JobDescription.id).where(JobDescription.created_by == user.id))
    ).scalars().all()

    unowned = (
        await db.execute(
            select(Candidate.id).where(
                Candidate.id.in_(candidate_ids),
                Candidate.job_id.isnot(None),
                Candidate.job_id.notin_(owned_job_ids),
            )
        )
    ).scalars().all()
    if unowned:
        raise HTTPException(
            status_code=403,
            detail="One or more candidates do not belong to your job postings",
        )

    unowned_pool = (
        await db.execute(
            select(Candidate.id).where(
                Candidate.id.in_(candidate_ids),
                Candidate.job_id.is_(None),
                or_(Candidate.user_id.is_(None), Candidate.user_id != user.id),
            )
        )
    ).scalars().all()
    if unowned_pool:
        raise HTTPException(
            status_code=403,
            detail="One or more pool candidates were not uploaded by you",
        )
