from __future__ import annotations

import asyncio
from pathlib import Path
import sys

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agents.specialized.candidate_coach_agent import CandidateCoachAgent
from app.database import Base
from app.models import Candidate, CandidateTag, JobDescription, Quiz, QuizAttempt, QuizStatus, StoredResume, User, UserRole
from app.services.candidate_coach_service import build_candidate_coach_snapshot


def _make_session_factory(db_path: Path) -> tuple[object, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _init() -> None:
        import app.models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    return engine, session_local


def test_candidate_coach_snapshot_is_candidate_scoped(tmp_path) -> None:
    engine, session_local = _make_session_factory(tmp_path / "candidate_coach_scope.sqlite")

    async def _run() -> None:
        async with session_local() as session:
            recruiter = User(email="[email-redacted]", hashed_password="x", full_name="Recruiter", role=UserRole.hr)
            candidate_a = User(email="[email-redacted]", hashed_password="x", full_name="Candidate A", role=UserRole.candidate)
            candidate_b = User(email="[email-redacted]", hashed_password="x", full_name="Candidate B", role=UserRole.candidate)
            session.add_all([recruiter, candidate_a, candidate_b])
            await session.flush()

            job_a = JobDescription(
                title="Backend Engineer",
                role="Backend Engineer",
                description="Python APIs",
                created_by=recruiter.id,
                is_active=True,
            )
            job_b = JobDescription(
                title="Data Engineer",
                role="Data Engineer",
                description="Pipelines",
                created_by=recruiter.id,
                is_active=True,
            )
            session.add_all([job_a, job_b])
            await session.flush()

            owned_candidate = Candidate(
                job_id=job_a.id,
                user_id=candidate_a.id,
                name="Candidate A",
                email="[email-redacted]",
                phone="9999999999",
                raw_resume_text="private raw resume",
                resume_path="private/path.pdf",
                normalized_skills=["python", "fastapi"],
                tag=CandidateTag.strong,
                resume_score=88,
                final_score=91,
            )
            other_candidate = Candidate(
                job_id=job_b.id,
                user_id=candidate_b.id,
                name="Candidate B",
                email="[email-redacted]",
                phone="8888888888",
                raw_resume_text="other raw resume",
                resume_path="other/path.pdf",
                normalized_skills=["spark"],
                tag=CandidateTag.medium,
                resume_score=99,
                final_score=99,
            )
            session.add_all([owned_candidate, other_candidate])
            await session.flush()

            quiz = Quiz(job_id=job_a.id, title="Backend Quiz")
            session.add(quiz)
            await session.flush()
            session.add(
                QuizAttempt(
                    quiz_id=quiz.id,
                    candidate_id=owned_candidate.id,
                    token_hash="owned-token-hash",
                    status=QuizStatus.pending,
                )
            )
            session.add(
                StoredResume(
                    user_id=candidate_a.id,
                    label="Backend Resume",
                    original_filename="backend.pdf",
                    resume_path="vault/private.pdf",
                    normalized_skills=["python", "apis"],
                    summary="Backend API resume summary",
                    is_default=True,
                )
            )
            session.add(
                StoredResume(
                    user_id=candidate_b.id,
                    label="Other Resume",
                    original_filename="other.pdf",
                    resume_path="vault/other.pdf",
                    normalized_skills=["spark"],
                    summary="Other private resume",
                )
            )
            await session.commit()

        async with session_local() as session:
            snapshot = await build_candidate_coach_snapshot(session, user=candidate_a)

        assert snapshot["data_scope"] == "candidate_owned"
        assert snapshot["metrics"]["total_applications"] == 1
        assert snapshot["metrics"]["pending_assessments"] == 1
        assert snapshot["applications"][0]["job_title"] == "Backend Engineer"
        assert snapshot["resumes"][0]["label"] == "Backend Resume"
        snapshot_text = str(snapshot)
        assert "Candidate B" not in snapshot_text
        assert "Data Engineer" not in snapshot_text
        assert "[email-redacted]" not in snapshot_text
        assert "private raw resume" not in snapshot_text
        assert "owned-token-hash" not in snapshot_text
        assert "resume_path" not in snapshot_text

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(engine.dispose())


def test_candidate_coach_agent_returns_actionable_summary() -> None:
    async def _run() -> None:
        agent = CandidateCoachAgent()
        result = await agent(
            {
                "question": "What should I do next?",
                "snapshot": {
                    "data_scope": "candidate_owned",
                    "metrics": {
                        "total_applications": 1,
                        "active_applications": 1,
                        "pending_assessments": 1,
                        "completed_assessments": 0,
                        "vault_resumes": 1,
                    },
                    "applications": [
                        {
                            "candidate_id": "cand-1",
                            "job_title": "Backend Engineer",
                            "application_status": "active",
                            "quiz_status": "pending",
                            "final_score": 91,
                        }
                    ],
                    "resumes": [{"id": "resume-1", "label": "Backend Resume", "is_default": True}],
                    "risks": ["1 assessment(s) still need completion."],
                },
            }
        )

        payload = result["candidate_coach"]
        assert payload["data_scope"] == "candidate_owned"
        assert payload["recommendations"]
        assert "Backend Engineer" in payload["answer"]
        assert payload["applications"][0]["job_title"] == "Backend Engineer"

    asyncio.run(_run())
