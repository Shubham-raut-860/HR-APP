"""Regression tests for resume pipeline hardening (BUG-27..45)."""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.datastructures import Headers, UploadFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import Base
from app.models import BulkUploadJob, Candidate, JobDescription, User, UserRole
from app.routers import resumes
from app.services import encryption_service, file_service


def _make_session_factory(db_path: Path) -> tuple[object, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _init() -> None:
        import app.models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    return engine, session_local


def test_job_upload_hash_uses_decrypted_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_bytes = b"ciphertext-placeholder"
    normalized_bytes = b"%PDF-1.4 normalized"
    observed: dict[str, bytes] = {}

    async def _fake_extract(_filename: str, _raw: bytes) -> tuple[str, bytes]:
        return "parsed text", normalized_bytes

    def _fake_sha256(data: bytes) -> str:
        observed["sha_input"] = data
        return "h" * 64

    async def _fake_assert_job_owner(_job_id: str, _user, _db):
        return SimpleNamespace(
            id="job-1",
            title="Role",
            description="",
            must_have_skills=[],
            good_to_have_skills=[],
            experience_min=0,
            experience_max=10,
            location=None,
            education_requirement=None,
            resume_weight=50,
            quiz_weight=50,
            pass_threshold=60,
        )

    async def _fake_compute(filename, content, *_args, **_kwargs):
        observed["compute_content"] = content
        raise HTTPException(status_code=418, detail=f"stop:{filename}")

    class _Result:
        @staticmethod
        def scalar_one_or_none():
            return None

    class _FakeDB:
        async def execute(self, *_args, **_kwargs):
            return _Result()

    monkeypatch.setattr(file_service, "extract_text_normalised_from_bytes", _fake_extract)
    monkeypatch.setattr(resumes, "_sha256", _fake_sha256)
    monkeypatch.setattr(resumes, "_assert_job_owner", _fake_assert_job_owner)
    monkeypatch.setattr(resumes, "_compute_resume_data_from_bytes", _fake_compute)

    request = SimpleNamespace(headers={"authorization": "Bearer test", "content-length": str(len(raw_bytes))})
    response = Response()
    file = UploadFile(
        filename="resume.pdf",
        file=io.BytesIO(raw_bytes),
        headers=Headers({"content-length": str(len(raw_bytes))}),
    )
    user = SimpleNamespace(id="hr-1", email="hr@example.com", role=UserRole.hr)
    upload_impl = getattr(resumes.upload_resume, "__wrapped__", resumes.upload_resume)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            upload_impl(
                request=request,
                response=response,
                job_id="job-1",
                file=file,
                db=_FakeDB(),
                user=user,
            )
        )
    assert exc_info.value.status_code == 418
    assert observed["sha_input"] == normalized_bytes
    assert observed["compute_content"] == normalized_bytes


def test_pool_upload_ghost_candidate_prevented(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _raise_save(*_args, **_kwargs):
        raise RuntimeError("disk unavailable")

    monkeypatch.setattr(file_service, "save_file", _raise_save)

    with pytest.raises(RuntimeError, match="could not be saved"):
        asyncio.run(
            resumes._compute_pool_resume_data_from_bytes(
                filename="pool.pdf",
                content=b"%PDF-1.4 pool",
                text="Candidate Resume Text",
                user_email="hr@example.com",
                auth_header="Bearer test",
                pre_parsed_data={"name": "Pool Candidate", "email": "pool@example.com"},
            )
        )


def test_bulk_detects_hrappa2_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(encryption_service, "try_decrypt_file", lambda _content: b"%PDF-decrypted")
    encrypted = b"HRAPPA2\x00" + (b"x" * 128)
    out = resumes._maybe_decrypt_bulk_upload_content("resume.pdf", ".pdf", encrypted)
    assert out == b"%PDF-decrypted"


def test_pool_dedup_user_scoped(tmp_path: Path) -> None:
    engine, session_local = _make_session_factory(tmp_path / "pool_scope.sqlite")

    async def _run() -> None:
        async with session_local() as session:
            user_a = User(
                id="user-a",
                email="a@example.com",
                hashed_password="hash",
                full_name="User A",
                role=UserRole.hr,
            )
            user_b = User(
                id="user-b",
                email="b@example.com",
                hashed_password="hash",
                full_name="User B",
                role=UserRole.hr,
            )
            session.add_all([user_a, user_b])
            await session.flush()

            session.add(
                Candidate(
                    user_id="user-a",
                    job_id=None,
                    email="shared@example.com",
                    file_hash="abc123",
                    name="Shared Candidate",
                    skills=[],
                    normalized_skills=[],
                    education=[],
                    projects=[],
                )
            )
            await session.commit()

            hashes_a = await resumes._existing_hashes(session, ["abc123"], owner_user_id="user-a")
            hashes_b = await resumes._existing_hashes(session, ["abc123"], owner_user_id="user-b")
            emails_a = await resumes._existing_pool_emails(
                session, ["shared@example.com"], owner_user_id="user-a"
            )
            emails_b = await resumes._existing_pool_emails(
                session, ["shared@example.com"], owner_user_id="user-b"
            )

            assert "abc123" in hashes_a
            assert hashes_b == set()
            assert "shared@example.com" in emails_a
            assert emails_b == set()

    asyncio.run(_run())
    asyncio.run(engine.dispose())


def test_download_legacy_plaintext() -> None:
    plain_pdf = b"%PDF-1.4 legacy plaintext"
    assert encryption_service.decrypt_file(plain_pdf) == plain_pdf

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_fp:
        temp_fp.write(plain_pdf)
        temp_path = temp_fp.name
    try:
        assert encryption_service.decrypt_file_from_path(temp_path) == plain_pdf
    finally:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass


def test_magic_byte_validation() -> None:
    with pytest.raises(HTTPException) as exc_info:
        file_service.validate_file_magic(b"%PDF-1.4", ".docx")
    assert exc_info.value.status_code == 422


def test_bulk_per_row_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, session_local = _make_session_factory(tmp_path / "bulk_isolation.sqlite")

    async def _run() -> None:
        async with session_local() as session:
            user = User(
                id="hr-user",
                email="hr@example.com",
                hashed_password="hash",
                full_name="HR User",
                role=UserRole.hr,
            )
            job = JobDescription(
                id="job-1",
                title="Engineer",
                role="Engineer",
                created_by=user.id,
                must_have_skills=[],
                good_to_have_skills=[],
            )
            session.add_all([user, job])
            await session.commit()

            async def _fake_assert_job_owner(_job_id: str, _user, _db):
                return job

            async def _fake_extract(fname: str, _content: bytes) -> str:
                return f"text-for-{fname}"

            async def _fake_parse(text: str, auth_header: str | None = None) -> dict:
                if "one.pdf" in text:
                    return {"name": "One", "email": "one@example.com"}
                return {"name": "Two", "email": "two@example.com"}

            async def _fake_compute(fname: str, content: bytes, _text: str, _job, **_kwargs) -> dict:
                return {
                    "id": "dup-id",
                    "job_id": "job-1",
                    "file_hash": hashlib.sha256(content).hexdigest(),
                    "name": fname,
                    "email": f"{fname}@example.com",
                    "phone": None,
                    "location": None,
                    "skills": [],
                    "normalized_skills": [],
                    "experience_years": 1.0,
                    "education": [],
                    "projects": [],
                    "work_experience": [],
                    "career_breaks": [],
                    "skill_years": {},
                    "raw_resume_text": "encrypted",
                    "resume_path": "/tmp/fake.pdf",
                    "embedding": [],
                    "skill_match_pct": 0.0,
                    "experience_match_pct": 0.0,
                    "project_relevance_pct": 0.0,
                    "education_match_pct": 0.0,
                    "location_match_pct": 0.0,
                    "vector_similarity": 0.0,
                    "resume_score": 0.0,
                    "final_score": 0.0,
                    "score_breakdown": {},
                    "tag": None,
                }

            async def _noop(*_args, **_kwargs):
                return None

            monkeypatch.setattr(resumes, "_assert_job_owner", _fake_assert_job_owner)
            monkeypatch.setattr(file_service, "extract_text_from_bytes", _fake_extract)
            monkeypatch.setattr(resumes, "_run_resume_parser_with_fallback", _fake_parse)
            monkeypatch.setattr(resumes, "_compute_resume_data_from_bytes", _fake_compute)
            monkeypatch.setattr(resumes, "_recompute_job_rank_and_tags", _noop)
            monkeypatch.setattr(resumes, "log_action", _noop)

            files = [
                UploadFile(filename="one.pdf", file=io.BytesIO(b"%PDF-one")),
                UploadFile(filename="two.pdf", file=io.BytesIO(b"%PDF-two")),
            ]
            request = SimpleNamespace(headers={"authorization": "Bearer test"})
            response = Response()
            upload_bulk_impl = getattr(resumes.upload_bulk_resumes, "__wrapped__", resumes.upload_bulk_resumes)
            result = await upload_bulk_impl(
                request=request,
                response=response,
                job_id="job-1",
                files=files,
                file_ids=["id-1", "id-2"],
                progress_run_id=None,
                db=session,
                user=user,
            )

            assert result["success_count"] == 1
            assert result["failed_count"] >= 1
            total_rows = (await session.execute(select(Candidate))).scalars().all()
            assert len(total_rows) == 1

    asyncio.run(_run())
    asyncio.run(engine.dispose())


def test_bulk_state_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, session_local = _make_session_factory(tmp_path / "bulk_recovery.sqlite")

    async def _run() -> None:
        async with session_local() as session:
            user = User(
                id="owner-1",
                email="owner@example.com",
                hashed_password="hash",
                full_name="Owner",
                role=UserRole.hr,
            )
            session.add(user)
            await session.flush()

            temp_path = tmp_path / "orphan.tmp"
            temp_path.write_bytes(b"temp")

            session.add(
                BulkUploadJob(
                    id="run-1",
                    status="running",
                    created_by=user.id,
                    total=2,
                    processed=1,
                    failed=0,
                    last_committed_batch=1,
                    error_summary=None,
                    details={
                        "id": "run-1",
                        "status": "running",
                        "owner_user_id": user.id,
                        "progress": {"processed": 1, "total": 2, "failed_count": 0},
                        "temp_paths": [str(temp_path)],
                    },
                    created_at=datetime.now(timezone.utc) - timedelta(minutes=30),
                    updated_at=datetime.now(timezone.utc) - timedelta(minutes=30),
                )
            )
            await session.commit()

        monkeypatch.setattr(resumes, "AsyncSessionLocal", session_local)
        recovered = await resumes.recover_stale_bulk_upload_jobs(grace_minutes=1)
        assert recovered == 1

        async with session_local() as verify_session:
            row = await verify_session.get(BulkUploadJob, "run-1")
            assert row is not None
            assert row.status == "failed"
            assert (row.error_summary or {}).get("error") == "recovered_from_restart"
        assert not temp_path.exists()

    asyncio.run(_run())
    asyncio.run(engine.dispose())
