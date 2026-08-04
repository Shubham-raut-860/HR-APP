"""Security and correctness regression tests for quiz subsystem (BUG-59..82)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import sys
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import Base, get_db
from app.limiter import limiter
from app.models import Candidate, Difficulty, JobDescription, Question, Quiz, QuizAttempt, QuizStatus, User, UserRole
from app.routers import candidate_portal, quiz as quiz_router
from app.services import scoring_service
from app.utils.quiz_validation import QuestionValidationError, deduplicate_questions, validate_question


def _make_session_factory(db_path: Path) -> tuple[object, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _init() -> None:
        import app.models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    return engine, session_local


def _build_quiz_client(
    session_local: async_sessionmaker[AsyncSession],
    *,
    current_user: SimpleNamespace,
) -> TestClient:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(quiz_router.router)

    async def _override_get_db():
        async with session_local() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def _override_candidate():
        return current_user

    async def _override_hr():
        return current_user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[quiz_router.require_candidate] = _override_candidate
    app.dependency_overrides[quiz_router.require_hr] = _override_hr
    return TestClient(app)


def _build_quiz_candidate_client(
    session_local: async_sessionmaker[AsyncSession],
    *,
    current_user: SimpleNamespace,
) -> TestClient:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(quiz_router.router)
    app.include_router(candidate_portal.router)

    async def _override_get_db():
        async with session_local() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def _override_candidate():
        return current_user

    async def _override_hr():
        return current_user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[quiz_router.require_candidate] = _override_candidate
    app.dependency_overrides[quiz_router.require_hr] = _override_hr
    app.dependency_overrides[candidate_portal.require_candidate] = _override_candidate
    app.dependency_overrides[candidate_portal.require_hr] = _override_hr
    return TestClient(app)


def _token_from_link(link: str) -> str:
    token = parse_qs(urlparse(link).query).get("token", [""])[0]
    return token


async def _seed_quiz_fixture(session_local: async_sessionmaker[AsyncSession]) -> dict[str, str]:
    async with session_local() as session:
        hr = User(
            email="[email-redacted]",
            hashed_password="hash",
            full_name="HR User",
            role=UserRole.hr,
        )
        candidate_user = User(
            email="[email-redacted]",
            hashed_password="hash",
            full_name="Candidate User",
            role=UserRole.candidate,
        )
        session.add_all([hr, candidate_user])
        await session.flush()

        job_a = JobDescription(
            title="Backend Engineer",
            role="Engineer",
            created_by=hr.id,
            description="Build APIs",
            must_have_skills=["Python"],
            good_to_have_skills=[],
        )
        job_b = JobDescription(
            title="Data Engineer",
            role="Engineer",
            created_by=hr.id,
            description="Build data systems",
            must_have_skills=["SQL"],
            good_to_have_skills=[],
        )
        session.add_all([job_a, job_b])
        await session.flush()

        candidate_a = Candidate(
            job_id=job_a.id,
            user_id=candidate_user.id,
            name="Candidate A",
            email="[email-redacted]",
            skills=[],
            normalized_skills=[],
        )
        candidate_b = Candidate(
            job_id=job_b.id,
            user_id=candidate_user.id,
            name="Candidate B",
            email="[email-redacted]",
            skills=[],
            normalized_skills=[],
        )
        session.add_all([candidate_a, candidate_b])
        await session.flush()

        quiz = Quiz(job_id=job_a.id, title="Python Assessment", duration_minutes=30, is_active=True)
        session.add(quiz)
        await session.flush()

        question = Question(
            quiz_id=quiz.id,
            question_text="What is Python?",
            options=["Language", "Database", "Protocol", "Compiler"],
            correct_answer=0,
            difficulty=Difficulty.easy,
            skill_tag="Python",
            weight=1,
            order=0,
        )
        session.add(question)
        await session.commit()

        return {
            "hr_id": hr.id,
            "hr_email": hr.email,
            "candidate_user_id": candidate_user.id,
            "candidate_user_email": candidate_user.email,
            "job_a_id": job_a.id,
            "job_b_id": job_b.id,
            "candidate_a_id": candidate_a.id,
            "candidate_b_id": candidate_b.id,
            "quiz_id": quiz.id,
            "question_id": question.id,
        }


async def _create_attempt(
    session_local: async_sessionmaker[AsyncSession],
    *,
    quiz_id: str,
    candidate_id: str,
    status: QuizStatus = QuizStatus.pending,
    started_at: datetime | None = None,
    token_expires_at: datetime | None = None,
    code_eval_count: int = 0,
) -> tuple[str, str]:
    raw_token = "tok_" + QuizAttempt.hash_access_token(f"{quiz_id}:{candidate_id}:{status.value}")[:24]
    token_hash = QuizAttempt.hash_access_token(raw_token)
    async with session_local() as session:
        attempt = QuizAttempt(
            quiz_id=quiz_id,
            candidate_id=candidate_id,
            token_hash=token_hash,
            status=status,
            started_at=started_at,
            token_expires_at=token_expires_at,
            code_eval_count=code_eval_count,
        )
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)
        return attempt.id, raw_token


def test_token_hash_not_in_email(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, session_local = _make_session_factory(tmp_path / "quiz_token_email.sqlite")
    seeded = asyncio.run(_seed_quiz_fixture(session_local))
    hr_user = SimpleNamespace(id=seeded["hr_id"], email=seeded["hr_email"], role=UserRole.hr)

    sent_payloads: list[tuple[str, str, str]] = []

    async def _noop_async(*_args, **_kwargs):
        return None

    def _fake_send_email(email: str, subject: str, html_body: str) -> None:
        sent_payloads.append((email, subject, html_body))

    monkeypatch.setattr("app.services.email_service.send_email", _fake_send_email)
    monkeypatch.setattr(quiz_router, "push_notification", _noop_async)
    monkeypatch.setattr(quiz_router, "push_to_candidate_by_email", _noop_async)

    with _build_quiz_client(session_local, current_user=hr_user) as client:
        response = client.post(
            "/quiz/send-links",
            json={"quiz_id": seeded["quiz_id"], "candidate_ids": [seeded["candidate_a_id"]]},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["created_count"] == 1
        link = payload["links"][0]["link"]
        raw_token = _token_from_link(link)
        assert raw_token
        assert len(raw_token) != 64

    async def _verify() -> None:
        async with session_local() as session:
            attempt = (await session.execute(
                select(QuizAttempt).where(
                    QuizAttempt.quiz_id == seeded["quiz_id"],
                    QuizAttempt.candidate_id == seeded["candidate_a_id"],
                )
            )).scalar_one()
            assert raw_token != attempt.token_hash
            assert QuizAttempt.hash_access_token(raw_token) == attempt.token_hash
            assert attempt.token_hash not in link

    asyncio.run(_verify())
    assert sent_payloads, "Expected at least one email dispatch"
    assert raw_token in sent_payloads[0][2]
    asyncio.run(engine.dispose())


def test_hashed_token_rejected_at_start(tmp_path: Path) -> None:
    engine, session_local = _make_session_factory(tmp_path / "quiz_hashed_start.sqlite")
    seeded = asyncio.run(_seed_quiz_fixture(session_local))
    attempt_id, raw_token = asyncio.run(
        _create_attempt(session_local, quiz_id=seeded["quiz_id"], candidate_id=seeded["candidate_a_id"])
    )
    assert attempt_id and raw_token

    candidate_user = SimpleNamespace(
        id=seeded["candidate_user_id"],
        email=seeded["candidate_user_email"],
        role=UserRole.candidate,
    )

    with _build_quiz_client(session_local, current_user=candidate_user) as client:
        response = client.post(
            "/quiz/start",
            headers={"X-Quiz-Token": QuizAttempt.hash_access_token(raw_token)},
        )
        assert response.status_code == 400
        assert "Invalid token format" in response.text

    asyncio.run(engine.dispose())


def test_submit_requires_token(tmp_path: Path) -> None:
    engine, session_local = _make_session_factory(tmp_path / "quiz_submit_requires_token.sqlite")
    seeded = asyncio.run(_seed_quiz_fixture(session_local))
    attempt_id, _raw_token = asyncio.run(
        _create_attempt(
            session_local,
            quiz_id=seeded["quiz_id"],
            candidate_id=seeded["candidate_a_id"],
            status=QuizStatus.in_progress,
            started_at=datetime.now(timezone.utc),
            token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
    )

    candidate_user = SimpleNamespace(
        id=seeded["candidate_user_id"],
        email=seeded["candidate_user_email"],
        role=UserRole.candidate,
    )

    with _build_quiz_client(session_local, current_user=candidate_user) as client:
        response = client.post(
            "/quiz/submit",
            json={"attempt_id": attempt_id, "answers": {seeded["question_id"]: 0}},
        )
        assert response.status_code == 401

    asyncio.run(engine.dispose())


def test_submit_expired_token(tmp_path: Path) -> None:
    engine, session_local = _make_session_factory(tmp_path / "quiz_submit_expired.sqlite")
    seeded = asyncio.run(_seed_quiz_fixture(session_local))
    attempt_id, raw_token = asyncio.run(
        _create_attempt(
            session_local,
            quiz_id=seeded["quiz_id"],
            candidate_id=seeded["candidate_a_id"],
            status=QuizStatus.in_progress,
            started_at=datetime.now(timezone.utc),
            token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
    )

    candidate_user = SimpleNamespace(
        id=seeded["candidate_user_id"],
        email=seeded["candidate_user_email"],
        role=UserRole.candidate,
    )

    with _build_quiz_client(session_local, current_user=candidate_user) as client:
        response = client.post(
            "/quiz/submit",
            json={"attempt_id": attempt_id, "answers": {seeded["question_id"]: 0}},
            headers={"X-Quiz-Token": raw_token},
        )
        assert response.status_code == 403
        assert "expired" in response.text.lower()

    asyncio.run(engine.dispose())


def test_cross_job_candidate_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, session_local = _make_session_factory(tmp_path / "quiz_cross_job.sqlite")
    seeded = asyncio.run(_seed_quiz_fixture(session_local))
    hr_user = SimpleNamespace(id=seeded["hr_id"], email=seeded["hr_email"], role=UserRole.hr)

    async def _noop_async(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.email_service.send_email", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(quiz_router, "push_notification", _noop_async)
    monkeypatch.setattr(quiz_router, "push_to_candidate_by_email", _noop_async)

    with _build_quiz_client(session_local, current_user=hr_user) as client:
        response = client.post(
            "/quiz/send-links",
            json={"quiz_id": seeded["quiz_id"], "candidate_ids": [seeded["candidate_b_id"]]},
        )
        assert response.status_code == 400
        assert "do not belong to job" in response.text

    asyncio.run(engine.dispose())


def test_magic_link_expired_returns_410(tmp_path: Path) -> None:
    engine, session_local = _make_session_factory(tmp_path / "quiz_magic_link_expired.sqlite")
    seeded = asyncio.run(_seed_quiz_fixture(session_local))
    _attempt_id, raw_token = asyncio.run(
        _create_attempt(
            session_local,
            quiz_id=seeded["quiz_id"],
            candidate_id=seeded["candidate_a_id"],
            status=QuizStatus.pending,
            token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
    )
    candidate_user = SimpleNamespace(
        id=seeded["candidate_user_id"],
        email=seeded["candidate_user_email"],
        role=UserRole.candidate,
    )

    with _build_quiz_client(session_local, current_user=candidate_user) as client:
        response = client.post("/quiz/magic-link/claim", headers={"X-Quiz-Token": raw_token})
        assert response.status_code == 410

    asyncio.run(engine.dispose())


def test_duplicate_candidate_ids_single_attempt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, session_local = _make_session_factory(tmp_path / "quiz_dedup_ids.sqlite")
    seeded = asyncio.run(_seed_quiz_fixture(session_local))
    hr_user = SimpleNamespace(id=seeded["hr_id"], email=seeded["hr_email"], role=UserRole.hr)

    async def _noop_async(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.email_service.send_email", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(quiz_router, "push_notification", _noop_async)
    monkeypatch.setattr(quiz_router, "push_to_candidate_by_email", _noop_async)

    with _build_quiz_client(session_local, current_user=hr_user) as client:
        response = client.post(
            "/quiz/send-links",
            json={
                "quiz_id": seeded["quiz_id"],
                "candidate_ids": [seeded["candidate_a_id"], seeded["candidate_a_id"]],
            },
        )
        assert response.status_code == 200
        assert response.json()["created_count"] == 1

    async def _verify() -> None:
        async with session_local() as session:
            count = len((await session.execute(
                select(QuizAttempt).where(
                    QuizAttempt.quiz_id == seeded["quiz_id"],
                    QuizAttempt.candidate_id == seeded["candidate_a_id"],
                )
            )).scalars().all())
            assert count == 1

    asyncio.run(_verify())
    asyncio.run(engine.dispose())


def test_tab_switch_server_increment(tmp_path: Path) -> None:
    engine, session_local = _make_session_factory(tmp_path / "quiz_tab_switch_increment.sqlite")
    seeded = asyncio.run(_seed_quiz_fixture(session_local))
    attempt_id, raw_token = asyncio.run(
        _create_attempt(
            session_local,
            quiz_id=seeded["quiz_id"],
            candidate_id=seeded["candidate_a_id"],
            status=QuizStatus.in_progress,
            started_at=datetime.now(timezone.utc),
            token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
    )
    candidate_user = SimpleNamespace(
        id=seeded["candidate_user_id"],
        email=seeded["candidate_user_email"],
        role=UserRole.candidate,
    )

    with _build_quiz_client(session_local, current_user=candidate_user) as client:
        first = client.post(f"/quiz/attempt/{attempt_id}/tab-switch", headers={"X-Quiz-Token": raw_token})
        second = client.post(f"/quiz/attempt/{attempt_id}/tab-switch", headers={"X-Quiz-Token": raw_token})
        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["tab_switches"] == 2

    asyncio.run(engine.dispose())


def test_token_rotation_sends_email(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, session_local = _make_session_factory(tmp_path / "quiz_rotation_email.sqlite")
    seeded = asyncio.run(_seed_quiz_fixture(session_local))
    hr_user = SimpleNamespace(id=seeded["hr_id"], email=seeded["hr_email"], role=UserRole.hr)

    attempt_id, old_raw_token = asyncio.run(
        _create_attempt(
            session_local,
            quiz_id=seeded["quiz_id"],
            candidate_id=seeded["candidate_a_id"],
            status=QuizStatus.pending,
            token_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
    )
    old_hash = QuizAttempt.hash_access_token(old_raw_token)

    sent_payloads: list[str] = []

    async def _noop_async(*_args, **_kwargs):
        return None

    def _fake_send_email(_email: str, _subject: str, html_body: str) -> None:
        sent_payloads.append(html_body)

    monkeypatch.setattr("app.services.email_service.send_email", _fake_send_email)
    monkeypatch.setattr(quiz_router, "push_notification", _noop_async)
    monkeypatch.setattr(quiz_router, "push_to_candidate_by_email", _noop_async)

    with _build_quiz_client(session_local, current_user=hr_user) as client:
        response = client.post(
            "/quiz/send-links",
            json={"quiz_id": seeded["quiz_id"], "candidate_ids": [seeded["candidate_a_id"]]},
        )
        assert response.status_code == 200
        assert response.json()["rotated_count"] == 1

    async def _verify() -> None:
        async with session_local() as session:
            attempt = (await session.execute(select(QuizAttempt).where(QuizAttempt.id == attempt_id))).scalar_one()
            assert attempt.token_hash != old_hash
            assert sent_payloads
            link_token = _token_from_link(response.json()["links"][0]["link"])
            assert QuizAttempt.hash_access_token(link_token) == attempt.token_hash

    asyncio.run(_verify())
    asyncio.run(engine.dispose())


def test_assessment_link_uses_configured_frontend_origin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, session_local = _make_session_factory(tmp_path / "quiz_frontend_origin.sqlite")
    seeded = asyncio.run(_seed_quiz_fixture(session_local))
    hr_user = SimpleNamespace(id=seeded["hr_id"], email=seeded["hr_email"], role=UserRole.hr)

    async def _noop_async(*_args, **_kwargs):
        return None

    monkeypatch.setattr(quiz_router.settings, "FRONTEND_URL", "http://127.0.0.1:3000")
    monkeypatch.setattr("app.services.email_service.send_email", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(quiz_router, "push_notification", _noop_async)
    monkeypatch.setattr(quiz_router, "push_to_candidate_by_email", _noop_async)

    with _build_quiz_client(session_local, current_user=hr_user) as client:
        response = client.post(
            "/quiz/send-links",
            json={"quiz_id": seeded["quiz_id"], "candidate_ids": [seeded["candidate_a_id"]]},
        )

    assert response.status_code == 200
    link = response.json()["links"][0]["link"]
    assert link.startswith("http://127.0.0.1:3000/take-quiz?token=")
    asyncio.run(engine.dispose())


def test_candidate_quiz_dashboard_does_not_rotate_existing_magic_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, session_local = _make_session_factory(tmp_path / "quiz_dashboard_no_rotate.sqlite")
    seeded = asyncio.run(_seed_quiz_fixture(session_local))
    candidate_user = SimpleNamespace(
        id=seeded["candidate_user_id"],
        email=seeded["candidate_user_email"],
        role=UserRole.candidate,
    )
    attempt_id, raw_token = asyncio.run(
        _create_attempt(
            session_local,
            quiz_id=seeded["quiz_id"],
            candidate_id=seeded["candidate_a_id"],
            status=QuizStatus.pending,
            token_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
    )
    original_hash = QuizAttempt.hash_access_token(raw_token)

    with _build_quiz_candidate_client(session_local, current_user=candidate_user) as client:
        before = client.get("/quiz/magic-link/context", headers={"X-Quiz-Token": raw_token})
        first_dashboard = client.get("/candidate/quiz")
        second_dashboard = client.get("/candidate/quiz")
        after = client.get("/quiz/magic-link/context", headers={"X-Quiz-Token": raw_token})

    assert before.status_code == 200
    assert first_dashboard.status_code == 200
    assert second_dashboard.status_code == 200
    assert after.status_code == 200
    payload = second_dashboard.json()
    assert payload["pending"] is True
    assert payload["attempts"][0]["token"] is None

    async def _verify_hash_stable() -> None:
        async with session_local() as session:
            attempt = (await session.execute(select(QuizAttempt).where(QuizAttempt.id == attempt_id))).scalar_one()
            assert attempt.token_hash == original_hash

    asyncio.run(_verify_hash_stable())
    asyncio.run(engine.dispose())


def test_send_links_resend_invalidates_old_token_and_returns_new_valid_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, session_local = _make_session_factory(tmp_path / "quiz_resend_invalidates_old.sqlite")
    seeded = asyncio.run(_seed_quiz_fixture(session_local))
    hr_user = SimpleNamespace(id=seeded["hr_id"], email=seeded["hr_email"], role=UserRole.hr)
    _, old_raw_token = asyncio.run(
        _create_attempt(
            session_local,
            quiz_id=seeded["quiz_id"],
            candidate_id=seeded["candidate_a_id"],
            status=QuizStatus.pending,
            token_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
    )

    async def _noop_async(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.email_service.send_email", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(quiz_router, "push_notification", _noop_async)
    monkeypatch.setattr(quiz_router, "push_to_candidate_by_email", _noop_async)

    with _build_quiz_client(session_local, current_user=hr_user) as client:
        response = client.post(
            "/quiz/send-links",
            json={"quiz_id": seeded["quiz_id"], "candidate_ids": [seeded["candidate_a_id"]]},
        )
        old_context = client.get("/quiz/magic-link/context", headers={"X-Quiz-Token": old_raw_token})
        new_token = _token_from_link(response.json()["links"][0]["link"])
        new_context = client.get("/quiz/magic-link/context", headers={"X-Quiz-Token": new_token})

    assert response.status_code == 200
    assert response.json()["rotated_count"] == 1
    assert new_token and new_token != old_raw_token
    assert old_context.status_code == 404
    assert new_context.status_code == 200
    asyncio.run(engine.dispose())


def test_no_rotation_on_submitted_attempt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, session_local = _make_session_factory(tmp_path / "quiz_no_rotate_submitted.sqlite")
    seeded = asyncio.run(_seed_quiz_fixture(session_local))
    hr_user = SimpleNamespace(id=seeded["hr_id"], email=seeded["hr_email"], role=UserRole.hr)

    attempt_id, raw_token = asyncio.run(
        _create_attempt(
            session_local,
            quiz_id=seeded["quiz_id"],
            candidate_id=seeded["candidate_a_id"],
            status=QuizStatus.submitted,
            started_at=datetime.now(timezone.utc) - timedelta(minutes=15),
            token_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
    )
    original_hash = QuizAttempt.hash_access_token(raw_token)
    sent_count = {"n": 0}

    async def _noop_async(*_args, **_kwargs):
        return None

    def _fake_send_email(*_args, **_kwargs) -> None:
        sent_count["n"] += 1

    monkeypatch.setattr("app.services.email_service.send_email", _fake_send_email)
    monkeypatch.setattr(quiz_router, "push_notification", _noop_async)
    monkeypatch.setattr(quiz_router, "push_to_candidate_by_email", _noop_async)

    with _build_quiz_client(session_local, current_user=hr_user) as client:
        response = client.post(
            "/quiz/send-links",
            json={"quiz_id": seeded["quiz_id"], "candidate_ids": [seeded["candidate_a_id"]]},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["rotated_count"] == 0
        assert payload["skipped"]
        assert "attempt_status=submitted" in payload["skipped"][0]["reason"]

    async def _verify() -> None:
        async with session_local() as session:
            attempt = (await session.execute(select(QuizAttempt).where(QuizAttempt.id == attempt_id))).scalar_one()
            assert attempt.token_hash == original_hash

    asyncio.run(_verify())
    assert sent_count["n"] == 0
    asyncio.run(engine.dispose())


def test_scoring_uses_snapshot_after_question_edit(tmp_path: Path) -> None:
    engine, session_local = _make_session_factory(tmp_path / "quiz_snapshot_score.sqlite")
    seeded = asyncio.run(_seed_quiz_fixture(session_local))

    attempt_id, raw_token = asyncio.run(
        _create_attempt(
            session_local,
            quiz_id=seeded["quiz_id"],
            candidate_id=seeded["candidate_a_id"],
            status=QuizStatus.pending,
            token_expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
        )
    )
    assert attempt_id and raw_token

    candidate_user = SimpleNamespace(
        id=seeded["candidate_user_id"],
        email=seeded["candidate_user_email"],
        role=UserRole.candidate,
    )

    with _build_quiz_client(session_local, current_user=candidate_user) as client:
        start_response = client.post("/quiz/start", headers={"X-Quiz-Token": raw_token})
        assert start_response.status_code == 200

    async def _mutate_question() -> None:
        async with session_local() as session:
            question = (await session.execute(
                select(Question).where(Question.id == seeded["question_id"])
            )).scalar_one()
            question.correct_answer = 1
            question.options = ["Wrong0", "NowCorrect1", "Other2", "Other3"]
            await session.commit()

    asyncio.run(_mutate_question())

    with _build_quiz_client(session_local, current_user=candidate_user) as client:
        submit_response = client.post(
            "/quiz/submit",
            json={"attempt_id": attempt_id, "answers": {seeded["question_id"]: 0}},
            headers={"X-Quiz-Token": raw_token},
        )
        assert submit_response.status_code == 200
        payload = submit_response.json()
        assert payload["raw_score"] == 1.0
        assert payload["max_score"] == 1.0

    asyncio.run(engine.dispose())


def test_evaluate_code_status_gate(tmp_path: Path) -> None:
    engine, session_local = _make_session_factory(tmp_path / "quiz_eval_status_gate.sqlite")
    seeded = asyncio.run(_seed_quiz_fixture(session_local))
    attempt_id, _raw_token = asyncio.run(
        _create_attempt(
            session_local,
            quiz_id=seeded["quiz_id"],
            candidate_id=seeded["candidate_a_id"],
            status=QuizStatus.pending,
            token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
    )
    candidate_user = SimpleNamespace(
        id=seeded["candidate_user_id"],
        email=seeded["candidate_user_email"],
        role=UserRole.candidate,
    )

    with _build_quiz_client(session_local, current_user=candidate_user) as client:
        response = client.post(
            "/quiz/evaluate-code",
            json={
                "attempt_id": attempt_id,
                "problem": "sum two numbers",
                "code": "print(1+1)",
                "language": "python",
            },
        )
        assert response.status_code == 403
        assert "active quiz attempt" in response.text.lower()

    asyncio.run(engine.dispose())


def test_evaluate_code_count_cap(tmp_path: Path) -> None:
    engine, session_local = _make_session_factory(tmp_path / "quiz_eval_count_cap.sqlite")
    seeded = asyncio.run(_seed_quiz_fixture(session_local))
    attempt_id, _raw_token = asyncio.run(
        _create_attempt(
            session_local,
            quiz_id=seeded["quiz_id"],
            candidate_id=seeded["candidate_a_id"],
            status=QuizStatus.in_progress,
            started_at=datetime.now(timezone.utc),
            token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            code_eval_count=3,
        )
    )
    candidate_user = SimpleNamespace(
        id=seeded["candidate_user_id"],
        email=seeded["candidate_user_email"],
        role=UserRole.candidate,
    )

    with _build_quiz_client(session_local, current_user=candidate_user) as client:
        response = client.post(
            "/quiz/evaluate-code",
            json={
                "attempt_id": attempt_id,
                "problem": "sum two numbers",
                "code": "print(1+1)",
                "language": "python",
            },
        )
        assert response.status_code == 429
        assert "maximum code evaluations" in response.text.lower()

    asyncio.run(engine.dispose())


def test_question_validation_bad_options() -> None:
    with pytest.raises(QuestionValidationError, match="Expected 4 options"):
        validate_question(
            {
                "question_text": "Bad options",
                "options": ["A", "B", "C"],
                "correct_answer": 0,
                "difficulty": "easy",
                "weight": 1,
            }
        )


def test_question_validation_correct_index_oob() -> None:
    with pytest.raises(QuestionValidationError, match="out of range"):
        validate_question(
            {
                "question_text": "Bad index",
                "options": ["A", "B", "C", "D"],
                "correct_answer": 4,
                "difficulty": "medium",
                "weight": 1,
            }
        )


def test_question_dedup() -> None:
    unique, dropped = deduplicate_questions(
        [
            {
                "question_text": "What is Python?",
                "options": ["A", "B", "C", "D"],
                "correct_answer": 0,
                "difficulty": "easy",
                "weight": 1,
            },
            {
                "question_text": "  what   is   python? ",
                "options": ["A", "B", "C", "D"],
                "correct_answer": 0,
                "difficulty": "easy",
                "weight": 1,
            },
        ]
    )
    assert len(unique) == 1
    assert dropped == 1


def test_quiz_score_zero_weight_fallback() -> None:
    score, _, _ = scoring_service.compute_quiz_score(
        [
            {
                "id": "q1",
                "difficulty": "hard",
                "weight": 0,
                "correct_answer": 1,
                "skill_tag": "python",
            }
        ],
        {"q1": 1},
    )
    assert score == 3.0


def test_quiz_score_negative_weight_floor() -> None:
    score, _, _ = scoring_service.compute_quiz_score(
        [
            {
                "id": "q1",
                "difficulty": "easy",
                "weight": -5,
                "correct_answer": 2,
                "skill_tag": "python",
            }
        ],
        {"q1": 2},
    )
    assert score == 1.0
