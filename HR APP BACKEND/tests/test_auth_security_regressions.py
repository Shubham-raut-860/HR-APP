"""Security regression tests for auth hardening (BUG-17..26)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from jose import jwt
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings
from app.database import Base, get_db
from app.limiter import limiter
from app.models import UsedResetToken, User, UserRole
from app.routers import auth as auth_router
from app.services.auth_service import (
    DUMMY_PASSWORD_HASH,
    get_current_user,
    hash_password,
    issue_refresh_token,
    rotate_refresh_token,
)


def _make_session_factory(db_path: Path) -> tuple[object, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _init() -> None:
        import app.models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    return engine, session_local


def _build_auth_test_client(session_local: async_sessionmaker[AsyncSession]) -> TestClient:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(auth_router.router)

    async def _override_get_db():
        async with session_local() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def test_register_hr_role_blocked(tmp_path: Path) -> None:
    engine, session_local = _make_session_factory(tmp_path / "register_hr.sqlite")
    with _build_auth_test_client(session_local) as client:
        response = client.post(
            "/auth/register",
            json={
                "email": "[email-redacted]",
                "password": "Abcd1!ef",
                "full_name": "Escalation Attempt",
                "role": "hr",
            },
        )
        assert response.status_code == 422

    asyncio.run(engine.dispose())


def test_register_admin_role_blocked(tmp_path: Path) -> None:
    engine, session_local = _make_session_factory(tmp_path / "register_admin.sqlite")
    with _build_auth_test_client(session_local) as client:
        response = client.post(
            "/auth/register",
            json={
                "email": "[email-redacted]",
                "password": "Abcd1!ef",
                "full_name": "Escalation Attempt",
                "role": "admin",
            },
        )
        assert response.status_code == 422

    asyncio.run(engine.dispose())


def test_register_default_role_is_candidate(tmp_path: Path) -> None:
    engine, session_local = _make_session_factory(tmp_path / "register_candidate.sqlite")
    with _build_auth_test_client(session_local) as client:
        response = client.post(
            "/auth/register",
            json={
                "email": "[email-redacted]",
                "password": "Abcd1!ef",
                "full_name": "Candidate User",
            },
        )
        assert response.status_code == 201
        assert response.json()["role"] == "candidate"

    asyncio.run(engine.dispose())


def test_bcrypt_72_byte_guard() -> None:
    with pytest.raises(ValueError):
        hash_password("A" * 73)


def test_register_password_over_72_bytes_rejected(tmp_path: Path) -> None:
    engine, session_local = _make_session_factory(tmp_path / "register_password_len.sqlite")
    with _build_auth_test_client(session_local) as client:
        response = client.post(
            "/auth/register",
            json={
                "email": "[email-redacted]",
                "password": "A" * 73,
                "full_name": "Length Overflow",
            },
        )
        assert response.status_code == 422

    asyncio.run(engine.dispose())


def test_refresh_rotation_concurrent(tmp_path: Path) -> None:
    engine, session_local = _make_session_factory(tmp_path / "refresh_rotation.sqlite")

    async def _run() -> None:
        async with session_local() as session:
            user = User(
                email="[email-redacted]",
                hashed_password=hash_password("Abcd1!ef"),
                full_name="Refresh Rotator",
                role=UserRole.candidate,
            )
            session.add(user)
            await session.flush()
            raw_refresh = await issue_refresh_token(session, user.id)
            await session.commit()

        gate = asyncio.Event()

        async def _attempt_rotate() -> tuple[str, int | str]:
            await gate.wait()
            async with session_local() as s:
                try:
                    user_id, _new_refresh = await rotate_refresh_token(s, raw_refresh)
                    await s.commit()
                    return ("ok", user_id)
                except HTTPException as exc:
                    await s.rollback()
                    return ("err", exc.status_code)

        t1 = asyncio.create_task(_attempt_rotate())
        t2 = asyncio.create_task(_attempt_rotate())
        gate.set()
        results = await asyncio.gather(t1, t2)

        successes = [r for r in results if r[0] == "ok"]
        failures = [r for r in results if r[0] == "err"]
        assert len(successes) == 1
        assert len(failures) == 1
        assert failures[0][1] == 401

    asyncio.run(_run())
    asyncio.run(engine.dispose())


def test_get_current_user_missing_type(tmp_path: Path) -> None:
    engine, session_local = _make_session_factory(tmp_path / "missing_type.sqlite")

    async def _run() -> None:
        async with session_local() as session:
            user = User(
                email="[email-redacted]",
                hashed_password=hash_password("Abcd1!ef"),
                full_name="Type Missing",
                role=UserRole.candidate,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

            token = jwt.encode(
                {
                    "sub": user.id,
                    "jti": "missing-type-jti",
                    "iat": datetime.now(timezone.utc),
                },
                settings.SECRET_KEY,
                algorithm=settings.ALGORITHM,
            )
            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(credentials=creds, db=session)
            assert exc_info.value.status_code == 401

    asyncio.run(_run())
    asyncio.run(engine.dispose())


def test_get_current_user_missing_jti(tmp_path: Path) -> None:
    engine, session_local = _make_session_factory(tmp_path / "missing_jti.sqlite")

    async def _run() -> None:
        async with session_local() as session:
            user = User(
                email="[email-redacted]",
                hashed_password=hash_password("Abcd1!ef"),
                full_name="JTI Missing",
                role=UserRole.candidate,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

            token = jwt.encode(
                {
                    "sub": user.id,
                    "type": "access",
                    "iat": datetime.now(timezone.utc),
                },
                settings.SECRET_KEY,
                algorithm=settings.ALGORITHM,
            )
            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(credentials=creds, db=session)
            assert exc_info.value.status_code == 401

    asyncio.run(_run())
    asyncio.run(engine.dispose())


def test_reset_token_one_time_use(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", "S" * 64, raising=False)

    engine, session_local = _make_session_factory(tmp_path / "reset_replay.sqlite")

    async def _seed_user() -> User:
        async with session_local() as session:
            user = User(
                email="[email-redacted]",
                hashed_password=hash_password("OldPass1!"),
                full_name="Reset User",
                role=UserRole.candidate,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    user = asyncio.run(_seed_user())
    dynamic_secret = f"{settings.SECRET_KEY}{user.hashed_password}"
    token = jwt.encode(
        {
            "sub": user.email,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
            "type": "reset",
            "jti": "one-time-reset-jti",
        },
        dynamic_secret,
        algorithm=settings.ALGORITHM,
    )

    with _build_auth_test_client(session_local) as client:
        first = client.post(
            "/auth/reset-password",
            json={"token": token, "new_password": "NewPass1!"},
        )
        assert first.status_code == 200

        async def _count_used_tokens() -> int:
            async with session_local() as session:
                rows = (await session.execute(select(UsedResetToken))).scalars().all()
                return len(rows)

        assert asyncio.run(_count_used_tokens()) == 1

        second = client.post(
            "/auth/reset-password",
            json={"token": token, "new_password": "NewPass2!"},
        )
        assert second.status_code == 400
        assert second.json().get("detail") in {
            "Token already used",
            "Invalid or expired reset token",
        }

    asyncio.run(engine.dispose())


def test_reset_token_verify_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", "S" * 64, raising=False)
    engine, session_local = _make_session_factory(tmp_path / "reset_verify.sqlite")

    async def _seed_user() -> User:
        async with session_local() as session:
            user = User(
                email="[email-redacted]",
                hashed_password=hash_password("OldPass1!"),
                full_name="Verify User",
                role=UserRole.candidate,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    user = asyncio.run(_seed_user())
    token = jwt.encode(
        {
            "sub": user.email,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
            "type": "reset",
            "jti": "verify-reset-jti",
        },
        f"{settings.SECRET_KEY}{user.hashed_password}",
        algorithm=settings.ALGORITHM,
    )

    with _build_auth_test_client(session_local) as client:
        verify_first = client.post("/auth/reset-password/verify", json={"token": token})
        assert verify_first.status_code == 200
        assert verify_first.json()["valid"] is True

        reset_response = client.post(
            "/auth/reset-password",
            json={"token": token, "new_password": "NewPass1!"},
        )
        assert reset_response.status_code == 200

        verify_after_use = client.post("/auth/reset-password/verify", json={"token": token})
        assert verify_after_use.status_code == 400
        assert verify_after_use.json().get("detail") in {"Token already used", "Invalid or expired reset token"}

    asyncio.run(engine.dispose())


def test_me_rate_limit(tmp_path: Path) -> None:
    engine, session_local = _make_session_factory(tmp_path / "me_rate_limit.sqlite")

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(auth_router.router)

    async def _override_get_db():
        async with session_local() as session:
            yield session

    async def _override_current_user() -> User:
        return User(
            id="user-me",
            email="[email-redacted]",
            hashed_password="x",
            full_name="Me User",
            role=UserRole.candidate,
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[auth_router.get_current_user] = _override_current_user

    with TestClient(app) as client:
        statuses = [
            client.get("/auth/me", headers={"Authorization": "Bearer fake-token"}).status_code
            for _ in range(31)
        ]

    assert statuses[0] == 200
    assert statuses[30] == 429
    asyncio.run(engine.dispose())


def test_dummy_hash_rounds_match() -> None:
    rounds = int(DUMMY_PASSWORD_HASH.split("$")[2])
    assert rounds == settings.BCRYPT_ROUNDS
