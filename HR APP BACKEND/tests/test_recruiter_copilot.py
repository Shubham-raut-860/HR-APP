from __future__ import annotations

import asyncio
from pathlib import Path
import sys

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agents.specialized.recruiter_assistant_agent import RecruiterAssistantAgent
from app.database import Base
from app.models import Candidate, CandidateTag, JobDescription, User, UserRole
from app.services.recruiter_copilot_service import build_recruiter_pipeline_snapshot


def _make_session_factory(db_path: Path) -> tuple[object, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _init() -> None:
        import app.models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    return engine, session_local


def test_recruiter_copilot_snapshot_is_recruiter_scoped(tmp_path) -> None:
    engine, session_local = _make_session_factory(tmp_path / "copilot_scope.sqlite")

    async def _run() -> None:
        async with session_local() as session:
            recruiter_a = User(email="[email-redacted]", hashed_password="x", full_name="Recruiter A", role=UserRole.hr)
            recruiter_b = User(email="[email-redacted]", hashed_password="x", full_name="Recruiter B", role=UserRole.hr)
            session.add_all([recruiter_a, recruiter_b])
            await session.flush()

            job_a = JobDescription(
                title="Backend Engineer",
                role="Backend Engineer",
                description="Python APIs",
                created_by=recruiter_a.id,
                is_active=True,
            )
            job_b = JobDescription(
                title="Frontend Engineer",
                role="Frontend Engineer",
                description="React UI",
                created_by=recruiter_b.id,
                is_active=True,
            )
            session.add_all([job_a, job_b])
            await session.flush()

            session.add_all(
                [
                    Candidate(
                        job_id=job_a.id,
                        user_id=recruiter_a.id,
                        name="Owned Candidate",
                        email="[email-redacted]",
                        tag=CandidateTag.strong,
                        resume_score=91,
                        final_score=91,
                    ),
                    Candidate(
                        job_id=job_b.id,
                        user_id=recruiter_b.id,
                        name="Other Candidate",
                        email="[email-redacted]",
                        tag=CandidateTag.strong,
                        resume_score=99,
                        final_score=99,
                    ),
                ]
            )
            await session.commit()

        async with session_local() as session:
            snapshot = await build_recruiter_pipeline_snapshot(session, user=recruiter_a)

        assert snapshot["metrics"]["total_jobs"] == 1
        assert snapshot["metrics"]["total_candidates"] == 1
        assert snapshot["jobs"][0]["title"] == "Backend Engineer"
        assert snapshot["top_candidates"][0]["name"] == "Owned Candidate"
        assert "email" not in snapshot["top_candidates"][0]
        assert "Other Candidate" not in str(snapshot)

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(engine.dispose())


def test_recruiter_assistant_agent_returns_actionable_summary() -> None:
    async def _run() -> None:
        agent = RecruiterAssistantAgent()
        result = await agent(
            {
                "question": "What should I do next?",
                "snapshot": {
                    "data_scope": "recruiter_owned",
                    "metrics": {
                        "total_jobs": 1,
                        "active_jobs": 1,
                        "total_candidates": 2,
                        "strong_candidates": 1,
                        "medium_candidates": 1,
                        "completed_assessments": 0,
                    },
                    "jobs": [
                        {
                            "id": "job-1",
                            "title": "Backend Engineer",
                            "candidate_count": 2,
                            "strong_candidates": 1,
                            "completed_assessments": 0,
                        }
                    ],
                    "top_candidates": [{"id": "cand-1", "name": "Candidate A", "final_score": 91}],
                    "risks": ["Backend Engineer has candidates but no assessment generated."],
                },
            }
        )

        payload = result["recruiter_copilot"]
        assert payload["data_scope"] == "recruiter_owned"
        assert payload["recommendations"]
        assert "Candidate A" in payload["answer"]
        assert payload["focus_jobs"][0]["title"] == "Backend Engineer"

    asyncio.run(_run())
