"""
Regression tests for all confirmed bugs from qa_report.md and
qa_deepdive_new_findings.md.

Run with:  python -m pytest tests/test_qa_regression.py -v
"""
import html
import importlib
import pytest
import sys
import os
from datetime import datetime, timezone, timedelta
from app.constants.scoring import (
    DEFAULT_SHORTLIST_THRESHOLD,
    TIER_FRESHER_MAX_YEARS,
    TIER_MID_MAX_YEARS,
)

# Ensure the app module can be found when running via Pytest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# ──────────────────────── Helpers ────────────────────────────────────────────

def _scoring():
    """Lazily import scoring_service to avoid import-time side effects."""
    return importlib.import_module("app.services.scoring_service")


# ──────────────────────── DEEP-DIVE BUG 1: dotted degrees ────────────────────

class TestDegreeRank:
    """_degree_rank must handle dotted names like B.Tech, M.Sc, Ph.D."""

    def test_b_dot_tech_ranked_correctly(self):
        ss = _scoring()
        edu = [{"degree": "B.Tech in Computer Science"}]
        assert ss._degree_rank(edu) >= 3, "B.Tech should rank as bachelor (3)"

    def test_m_dot_sc_ranked_correctly(self):
        ss = _scoring()
        edu = [{"degree": "M.Sc in Physics"}]
        assert ss._degree_rank(edu) >= 4, "M.Sc should rank as master (4)"

    def test_ph_dot_d_ranked_correctly(self):
        ss = _scoring()
        edu = [{"degree": "Ph.D in Mathematics"}]
        assert ss._degree_rank(edu) >= 5, "Ph.D should rank as doctorate (5)"

    def test_plain_btech_still_works(self):
        ss = _scoring()
        edu = [{"degree": "BTech in CS"}]
        assert ss._degree_rank(edu) >= 3

    def test_empty_education(self):
        ss = _scoring()
        assert ss._degree_rank([]) == 0

    def test_no_degree_key(self):
        ss = _scoring()
        assert ss._degree_rank([{"major": "CS"}]) == 0


# ──────────────────────── DEEP-DIVE BUG 4: tier thresholds ───────────────────

class TestTierThresholds:
    """_CandidateTierMixin must use identical thresholds to detect_candidate_tier."""

    @pytest.mark.parametrize("years,expected", [
        (0.0, "fresher"),
        (0.5, "fresher"),
        (TIER_FRESHER_MAX_YEARS - 0.01, "fresher"),
        (TIER_FRESHER_MAX_YEARS, "mid"),
        (1.0, "mid"),
        (TIER_MID_MAX_YEARS - 0.01, "mid"),
        (TIER_MID_MAX_YEARS, "senior"),
        (5.0, "senior"),
        (10.0, "senior"),
    ])
    def test_detect_candidate_tier(self, years, expected):
        ss = _scoring()
        assert ss.detect_candidate_tier(years) == expected

    def test_schema_tier_matches_scoring(self):
        """Tier derived by schema fallback must match scoring_service."""
        from app.schemas import CandidateOut
        from app.services import scoring_service as ss

        for yrs in [
            0.0,
            0.5,
            TIER_FRESHER_MAX_YEARS - 0.01,
            TIER_FRESHER_MAX_YEARS,
            1.0,
            TIER_MID_MAX_YEARS - 0.01,
            TIER_MID_MAX_YEARS,
            5.0,
            10.0,
        ]:
            expected = ss.detect_candidate_tier(yrs)
            # Build minimal data to test the mixin with all required fields
            obj = CandidateOut.model_construct(
                id="test", job_id="job123", name="Test", email="[email-redacted]", phone="123",
                skills=[], normalized_skills=[], education=[], projects=[],
                skill_match_pct=0, experience_match_pct=0, project_relevance_pct=0,
                education_match_pct=0, vector_similarity=0, quiz_score=0,
                final_score=0, rank=0, passed=False, created_at=datetime.now(),
                experience_years=yrs, candidate_tier=None, score_breakdown=None,
                resume_score=0, tag="medium",
            )
            # Trigger the validator
            obj.__class__.model_validate(obj.model_dump())
            # The validator should set the same tier
            validated = CandidateOut.model_validate(obj.model_dump())
            assert validated.candidate_tier == expected, (
                f"Schema tier for {yrs} yrs = {validated.candidate_tier}, "
                f"expected {expected}"
            )


# ──────────────────── DEEP-DIVE BUG 10: experience_max default ───────────────

class TestExperienceMaxDefault:
    def test_default_is_10_not_99(self):
        from app.models import JobDescription
        col = JobDescription.__table__.columns["experience_max"]
        assert col.default.arg == 10, (
            f"experience_max default should be 10, got {col.default.arg}"
        )


# ──────────────────── DEEP-DIVE BUG 7: token_expires_at column ───────────────

class TestQuizTokenExpiry:
    def test_column_exists(self):
        from app.models import QuizAttempt
        assert hasattr(QuizAttempt, "token_expires_at"), (
            "QuizAttempt must have token_expires_at column"
        )

    def test_column_is_nullable(self):
        from app.models import QuizAttempt
        col = QuizAttempt.__table__.columns["token_expires_at"]
        assert col.nullable is True


# ──────────────────── DEEP-DIVE BUG 2: jd.py logger ─────────────────────────

class TestJDLogger:
    def test_logger_defined(self):
        mod = importlib.import_module("app.routers.jd")
        assert hasattr(mod, "logger"), "jd.py must define a module-level logger"


# ──────────────────── qa_report BUG 1: required→strict mapping ───────────────

class TestEducationRequiredMapping:
    def test_required_maps_to_strict_behavior(self):
        """When jd_education_requirement='required', freshers must get pure base
        score (strict mode), NOT a boosted score."""
        ss = _scoring()
        edu = [{"degree": "High School Diploma"}]
        base = ss._base_edu_score(edu)

        strict_score = ss.education_match_score(
            edu, experience_years=0.3,
            jd_education_requirement="required",
        )
        # strict mode for fresher returns base directly
        assert strict_score == base, (
            f"'required' should map to strict (score={base}), got {strict_score}"
        )

    def test_preferred_still_applied(self):
        ss = _scoring()
        edu = [{"degree": "High School Diploma"}]
        preferred_score = ss.education_match_score(
            edu, experience_years=0.3,
            jd_education_requirement="preferred",
        )
        base = ss._base_edu_score(edu)
        # preferred: max(base * 0.95, 40.0)
        expected = max(base * 0.95, 40.0)
        assert abs(preferred_score - expected) < 0.01


# ──────────── qa_report BUG 2: c/c# false positive prevention ────────────────

class TestSubstringExclusions:
    def test_c_does_not_match_csharp(self):
        ss = _scoring()
        score = ss.skill_match_score(
            candidate_skills=["c"],
            must_have=["c#"],
            good_to_have=[],
        )
        assert score < DEFAULT_SHORTLIST_THRESHOLD, f"'c' should NOT match 'c#', got score={score}"

    def test_csharp_does_not_match_c(self):
        ss = _scoring()
        score = ss.skill_match_score(
            candidate_skills=["c#"],
            must_have=["c"],
            good_to_have=[],
        )
        assert score < DEFAULT_SHORTLIST_THRESHOLD, f"'c#' should NOT match 'c', got score={score}"

    def test_c_does_not_match_cpp(self):
        ss = _scoring()
        score = ss.skill_match_score(
            candidate_skills=["c"],
            must_have=["c++"],
            good_to_have=[],
        )
        assert score < DEFAULT_SHORTLIST_THRESHOLD, f"'c' should NOT match 'c++', got score={score}"

    def test_sql_does_not_match_nosql(self):
        ss = _scoring()
        score = ss.skill_match_score(
            candidate_skills=["sql"],
            must_have=["nosql"],
            good_to_have=[],
        )
        assert score < DEFAULT_SHORTLIST_THRESHOLD, f"'sql' should NOT match 'nosql', got score={score}"

    def test_exact_c_match_works(self):
        ss = _scoring()
        score = ss.skill_match_score(
            candidate_skills=["c"],
            must_have=["c"],
            good_to_have=[],
        )
        assert score >= 80.0, f"'c' should match 'c' exactly, got score={score}"


# ──────────── qa_report ISSUE 5: quiz_pct capped at 100 ──────────────────────

class TestQuizPctCap:
    def test_overflow_score_capped(self):
        ss = _scoring()
        # quiz_score=150, max=100 → quiz_pct was 150, now capped at 100
        result = ss.compute_final_score(
            resume_score=80.0,
            quiz_score=150.0,
            quiz_max_score=100.0,
            resume_weight=50,
            quiz_weight=50,
        )
        # Expected: (80*0.5) + (100*0.5) = 40 + 50 = 90.0
        assert result <= 90.0, f"Final score should be ≤90 with capped quiz, got {result}"

    def test_normal_score_unaffected(self):
        ss = _scoring()
        result = ss.compute_final_score(
            resume_score=80.0,
            quiz_score=70.0,
            quiz_max_score=100.0,
            resume_weight=50,
            quiz_weight=50,
        )
        # Expected: (80*0.5) + (70*0.5) = 40 + 35 = 75.0
        assert abs(result - 75.0) < 0.01


# ──────────── DEEP-DIVE BUG 9: XSS prevention ────────────────────────────────

class TestXSSPrevention:
    def test_html_escape_works_on_malicious_name(self):
        """Verify html.escape strips dangerous tags."""
        malicious = '<script>alert("xss")</script>'
        safe = html.escape(malicious)
        assert "<script>" not in safe
        assert "&lt;script&gt;" in safe

    def test_quiz_py_imports_html(self):
        """quiz.py must import html module for XSS protection."""
        import ast
        with open("app/routers/quiz.py", "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        imports = [
            node.names[0].name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
        ]
        assert "html" in imports, "quiz.py must import html module"

    def test_resumes_py_imports_html(self):
        """resumes.py must import html module for XSS protection."""
        import ast
        with open("app/routers/resumes.py", "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        imports = [
            node.names[0].name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
        ]
        assert "html" in imports, "resumes.py must import html module"


# ──────────── DEEP-DIVE BUG 11: import_from_pool uses asyncio.gather ─────────

class TestImportFromPoolConcurrency:
    def test_asyncio_gather_used(self):
        """import_from_pool must use asyncio.gather, not sequential loop."""
        with open("app/routers/resumes.py", "r", encoding="utf-8") as f:
            content = f.read()
        # Find the import_from_pool function and verify asyncio.gather
        func_start = content.find("async def import_from_pool")
        assert func_start > 0, "import_from_pool function must exist"
        # Look for asyncio.gather in the function body
        assert "asyncio.gather" in content[func_start:], (
            "import_from_pool must use asyncio.gather for concurrent AI scoring"
        )


# ──────────── DEEP-DIVE BUG 6: bulk_delete physical file deletion ────────────

class TestBulkDeleteFileCleanup:
    def test_unlink_in_bulk_delete(self):
        """bulk_delete_candidates must delete physical resume files."""
        with open("app/routers/resumes.py", "r", encoding="utf-8") as f:
            content = f.read()
        func_start = content.find("async def bulk_delete_candidates")
        assert func_start > 0
        assert "os.unlink" in content[func_start:], (
            "bulk_delete_candidates must call os.unlink to remove resume files"
        )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ DEEP-DIVE BUG 16: pool visibility ownership in list endpoint â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class TestPoolVisibilityOwnership:
    def test_non_admin_cannot_retrieve_other_recruiter_pool_candidates(self, tmp_path):
        import asyncio
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

        from app.database import Base
        from app.models import Candidate, User, UserRole
        from app.routers.resumes import get_all_data

        async def _run() -> None:
            db_file = tmp_path / "pool_visibility.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", future=True)
            SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            try:
                async with SessionLocal() as db:
                    owner = User(
                        email="[email-redacted]",
                        hashed_password="x",
                        full_name="Owner HR",
                        role=UserRole.hr,
                    )
                    other = User(
                        email="[email-redacted]",
                        hashed_password="x",
                        full_name="Other HR",
                        role=UserRole.hr,
                    )
                    db.add_all([owner, other])
                    await db.flush()

                    owner_pool = Candidate(
                        job_id=None,
                        user_id=owner.id,
                        name="Owner Pool Candidate",
                        email="[email-redacted]",
                    )
                    other_pool = Candidate(
                        job_id=None,
                        user_id=other.id,
                        name="Other Pool Candidate",
                        email="[email-redacted]",
                    )
                    db.add_all([owner_pool, other_pool])
                    await db.commit()

                    owner_id = owner.id
                    owner_pool_id = owner_pool.id
                    other_pool_id = other_pool.id

                async with SessionLocal() as db:
                    owner_user = await db.get(User, owner_id)
                    rows = await get_all_data(search=None, skip=0, limit=500, db=db, user=owner_user)
                    visible_ids = {row.id for row in rows}

                    assert owner_pool_id in visible_ids
                    assert other_pool_id not in visible_ids
            finally:
                await engine.dispose()

        asyncio.run(_run())
