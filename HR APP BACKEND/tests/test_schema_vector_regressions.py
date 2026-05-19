"""Regression tests for pgvector, candidate uniqueness, parse versioning, and startup drift checks."""

from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _run_python_snippet(code: str, *, env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )


def test_startup_raises_runtime_error_when_postgres_without_pgvector() -> None:
    code = """
import importlib.abc
import os
import sys

os.environ['DATABASE_URL'] = 'postgresql+asyncpg://demo:demo@127.0.0.1:5432/demo'
os.environ['HARNESS_MOUNT_ENABLED'] = 'false'
os.environ['ENABLE_METAFLOW'] = 'false'

for name in list(sys.modules):
    if name.startswith('app.') or name == 'app':
        sys.modules.pop(name, None)

class BlockPgvector(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('pgvector'):
            raise ImportError('blocked for test')
        return None

sys.meta_path.insert(0, BlockPgvector())

import app.models  # noqa: F401
"""
    proc = _run_python_snippet(code)
    output = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode != 0, output
    assert "pgvector is required for PostgreSQL databases" in output


def test_vector_column_dimension_tracks_settings() -> None:
    from app.config import settings
    from app.models import Candidate, JobDescription, StoredResume

    expected = int(settings.EMBEDDING_DIM)
    assert expected in (1536, 3072)

    for model in (Candidate, JobDescription, StoredResume):
        vector_type = model.__table__.c.embedding.type.dialect_impl(postgresql.dialect())
        assert getattr(vector_type, "dim", None) == expected


def test_application_unique_index_blocks_duplicate_non_null_pair() -> None:
    from app.database import Base
    from app.models import Candidate, JobDescription, User, UserRole

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user = User(
            email="dup@example.com",
            hashed_password="x",
            full_name="Duplicate User",
            role=UserRole.candidate,
        )
        job = JobDescription(title="Backend Engineer", role="Backend Engineer")
        session.add_all([user, job])
        session.commit()

        first = Candidate(user_id=user.id, job_id=job.id, email="first@example.com")
        second = Candidate(user_id=user.id, job_id=job.id, email="second@example.com")
        session.add(first)
        session.commit()

        session.add(second)
        with pytest.raises(IntegrityError):
            session.commit()


def test_application_null_bearing_rows_insert_when_nullable() -> None:
    from app.database import Base
    from app.models import Candidate, User, UserRole

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user = User(
            email="nullable@example.com",
            hashed_password="x",
            full_name="Nullable User",
            role=UserRole.candidate,
        )
        session.add(user)
        session.commit()

        row_a = Candidate(user_id=user.id, job_id=None, email="pool-a@example.com")
        row_b = Candidate(user_id=user.id, job_id=None, email="pool-b@example.com")
        session.add_all([row_a, row_b])
        session.commit()

        assert row_a.id is not None
        assert row_b.id is not None


def test_parse_version_set_to_parser_version_on_resume_cache_write() -> None:
    from app.constants.versions import PARSER_VERSION
    from app.database import Base
    from app.models import StoredResume, User, UserRole
    from app.routers.candidate_portal import _apply_stored_resume_parse_cache

    stored = StoredResume(
        user_id="u-1",
        label="Default",
        original_filename="resume.pdf",
        resume_path="/tmp/resume.pdf",
    )
    stored.parse_version = 0

    _apply_stored_resume_parse_cache(
        stored,
        {
            "normalized_skills": ["python"],
            "skills": ["Python"],
            "experience_years": 4.0,
        },
        [0.0] * 3,
        file_hash="abc123",
    )

    assert stored.parse_version == PARSER_VERSION

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(
            email="resume-owner@example.com",
            hashed_password="x",
            full_name="Resume Owner",
            role=UserRole.candidate,
        )
        session.add(user)
        session.flush()

        saved = StoredResume(
            user_id=user.id,
            label="Saved Resume",
            original_filename="saved.pdf",
            resume_path="/tmp/saved.pdf",
        )
        session.add(saved)
        session.commit()
        session.refresh(saved)
        assert saved.parse_version == PARSER_VERSION


def _import_main_for_startup_tests(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HARNESS_MOUNT_ENABLED", "false")
    monkeypatch.setenv("ENABLE_METAFLOW", "false")
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)

    config = importlib.import_module("app.config")
    monkeypatch.setattr(config.settings, "HARNESS_MOUNT_ENABLED", False, raising=False)
    monkeypatch.setattr(config.settings, "ENABLE_METAFLOW", False, raising=False)

    if "app.main" in sys.modules:
        del sys.modules["app.main"]
    return importlib.import_module("app.main")


def test_run_startup_database_health_checks_calls_schema_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_for_startup_tests(monkeypatch)
    database = importlib.import_module("app.database")

    drift_mock = AsyncMock(return_value=None)
    verify_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(database, "_check_schema_drift", drift_mock)
    monkeypatch.setattr(database, "verify_pgvector_registration", verify_mock)

    asyncio.run(main._run_startup_database_health_checks())
    assert drift_mock.await_count == 1


def test_lifespan_startup_invokes_database_health_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_for_startup_tests(monkeypatch)

    class _StartupStopped(RuntimeError):
        pass

    async def _stop_after_health_checks() -> None:
        raise _StartupStopped("stop after verifying startup hook execution")

    monkeypatch.setattr(main, "_run_startup_schema_guard", AsyncMock(return_value=None))
    monkeypatch.setattr(main, "_run_startup_database_health_checks", _stop_after_health_checks)

    async def _run_lifespan_once() -> None:
        async with main.lifespan(main.app):
            return None

    with pytest.raises(_StartupStopped):
        asyncio.run(_run_lifespan_once())


def test_sqlite_detection_handles_uppercase_scheme() -> None:
    from app.database import _is_sqlite_url

    assert _is_sqlite_url("SQLITE+aiosqlite:///./test.db") is True
    assert _is_sqlite_url("SQLite:///./test.db") is True
    assert _is_sqlite_url("postgresql+asyncpg://u:p@localhost/db") is False
