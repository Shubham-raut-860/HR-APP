from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.services.auth_service import log_action, require_hr
from app.services.recruiter_copilot_service import run_recruiter_copilot

router = APIRouter(prefix="/recruiter-copilot", tags=["Recruiter Copilot"])


class RecruiterCopilotRequest(BaseModel):
    question: str = Field(
        default="Summarize my hiring pipeline and recommend next actions.",
        max_length=1000,
    )
    job_id: str | None = Field(default=None, max_length=36)


class RecruiterCopilotResponse(BaseModel):
    answer: str
    headline: str
    recommendations: list[str]
    focus_jobs: list[dict[str, Any]]
    top_candidates: list[dict[str, Any]]
    risks: list[str]
    metrics: dict[str, Any]
    data_scope: str
    snapshot: dict[str, Any]


@router.post("/ask", response_model=RecruiterCopilotResponse)
async def ask_recruiter_copilot(
    body: RecruiterCopilotRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
) -> RecruiterCopilotResponse:
    result = await run_recruiter_copilot(
        db,
        user=user,
        question=body.question,
        job_id=body.job_id,
    )
    await log_action(
        db,
        user.id,
        "RECRUITER_COPILOT_ASK",
        "recruiter_copilot",
        body.job_id,
        details={
            "job_id": body.job_id,
            "data_scope": result.get("data_scope"),
            "question_length": len(body.question or ""),
        },
    )
    await db.commit()
    return RecruiterCopilotResponse(**result)
