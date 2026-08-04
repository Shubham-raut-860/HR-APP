"""
SQLAlchemy ORM models for HR Platform

CHANGES:
  - Added `file_hash` column to Candidate (VARCHAR 64, nullable, indexed).
    This stores the SHA-256 hex digest of the raw uploaded file bytes and
    is used by the bulk upload endpoints for fast duplicate detection.
    Run add_file_hash_migration.py once to add this column to existing DBs.

  - Added `is_archived` column to Candidate (Boolean, default False).
    When HR clicks "Clear Displayed" on the Candidates pipeline view,
    candidates are archived (is_archived=True) rather than permanently deleted.
    Archived candidates are hidden from the pipeline view but remain visible
    in the All Data master archive modal.
    Run add_is_archived_migration.py once to add this column to existing DBs.
"""
import uuid
import hashlib
import logging as _log
from datetime import datetime, timezone
from typing import Optional
import sqlalchemy as sa
from sqlalchemy import (
    String, Text, Integer, Float, Boolean, DateTime,
    ForeignKey, JSON, Enum as SAEnum, Index, CheckConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.ext.mutable import MutableList, MutableDict
from app.config import settings
from app.constants.versions import PARSER_VERSION
from app.database import Base
import enum


def _is_postgres_url(database_url: str) -> bool:
    url = (database_url or "").strip().lower()
    return url.startswith("postgresql") or url.startswith("postgres://")


try:
    from pgvector.sqlalchemy import Vector
except Exception:  # pragma: no cover - optional dependency in local sqlite dev
    Vector = None

_pgvector_available = Vector is not None
if not _pgvector_available:
    _db_url = ""
    try:
        from app.config import settings as _s
        _db_url = str(_s.DATABASE_URL or "")
    except Exception:
        pass
    if _is_postgres_url(_db_url) or "postgresql" in _db_url.lower() or "postgres" in _db_url.lower():
        raise RuntimeError(
            "pgvector Python package is required for PostgreSQL deployments. "
            "Run: pip install pgvector"
        )
    _log.getLogger(__name__).warning(
        "pgvector not available; embedding columns will use JSON (SQLite/dev mode only)."
    )


def gen_uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


EMBEDDING_DIM = settings.EMBEDDING_DIM
if Vector is not None:
    EMBEDDING_SA_TYPE = JSON().with_variant(Vector(EMBEDDING_DIM), "postgresql")
else:
    EMBEDDING_SA_TYPE = JSON()

# ─── Enums ────────────────────────────────────────────────────────────────────


class UserRole(str, enum.Enum):
    hr = "hr"
    admin = "admin"
    candidate = "candidate"


class CandidateTag(str, enum.Enum):
    """Candidate classification tags assigned by the scoring engine.

    Canonical values are Title Case for API/frontend compatibility.
    Member names remain lowercase for ergonomic server-side references.
    """
    strong = "Strong"
    medium = "Medium"
    reject = "Reject"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            normalized = value.strip().lower()
            mapping = {
                "strong": cls.strong,
                "medium": cls.medium,
                "reject": cls.reject,
            }
            return mapping.get(normalized)
        return None


class QuizStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    submitted = "submitted"
    timed_out = "timed_out"


class Difficulty(str, enum.Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


class NotificationType(str, enum.Enum):
    job_posted = "job_posted"
    email_sent = "email_sent"
    quiz_link = "quiz_link"
    shortlisted = "shortlisted"
    tag_updated = "tag_updated"
    quiz_result = "quiz_result"
    system = "system"

# ─── User ─────────────────────────────────────────────────────────────────────


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), default=UserRole.candidate)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Preferences are validated in UserUpdate (schemas.py) with a 64KB size limit
    # to prevent storage abuse via PUT /auth/me with multi-megabyte payloads.
    preferences: Mapped[Optional[dict]] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    # Invalidate all access tokens issued before this timestamp.
    token_revoked_before: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="user")
    candidate_profiles: Mapped[list["Candidate"]] = relationship(back_populates="user")
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="user", cascade="all, delete-orphan")
    stored_resumes: Mapped[list["StoredResume"]] = relationship(back_populates="user")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    revoked_tokens: Mapped[list["RevokedToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    used_reset_tokens: Mapped[list["UsedResetToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    bulk_upload_jobs: Mapped[list["BulkUploadJob"]] = relationship(
        back_populates="creator", cascade="all, delete-orphan"
    )

# ─── Notification ─────────────────────────────────────────────────────────────


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey(
        "users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[NotificationType] = mapped_column(
        SAEnum(NotificationType), default=NotificationType.system)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    is_dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    related_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    user: Mapped["User"] = relationship(back_populates="notifications")

# ─── Job Description ──────────────────────────────────────────────────────────


class JobDescription(Base):
    __tablename__ = "job_descriptions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(255))
    experience_min: Mapped[int] = mapped_column(Integer, default=0)
    experience_max: Mapped[int] = mapped_column(Integer, default=10)
    must_have_skills: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    good_to_have_skills: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    employment_type: Mapped[Optional[str]] = mapped_column(String(50), default="Full-time")
    description: Mapped[Optional[str]] = mapped_column(Text)
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    embedding: Mapped[Optional[list]] = mapped_column(EMBEDDING_SA_TYPE, nullable=True)
    resume_weight: Mapped[int] = mapped_column(Integer, default=50)
    quiz_weight: Mapped[int] = mapped_column(Integer, default=50)
    pass_threshold: Mapped[int] = mapped_column(Integer, default=60)
    # FIX [C1]: salary_range was sent by frontend but silently discarded — no column existed.
    salary_range: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # ISSUE 7 FIX: education_requirement extracted by LLM during JD parsing.
    # Values: "required" | "preferred" | "none" (null = not yet extracted / legacy row).
    # Stored here so education_match_score can skip its regex detection entirely.
    # Run add_education_requirement_migration.py to add this column to existing DBs.
    education_requirement: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # SHA-256 of uploaded source document — used to skip re-parsing identical files
    file_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    candidates: Mapped[list["Candidate"]] = relationship(back_populates="job")
    quizzes: Mapped[list["Quiz"]] = relationship(back_populates="job")

# ─── Candidate / Resume ───────────────────────────────────────────────────────


class Candidate(Base):
    __tablename__ = "candidates"
    # FIX Finding 14: Prevent duplicate email+job_id combinations at DB level.
    #
    # CHANGED: The old UniqueConstraint("email", "job_id") treated NULL job_id
    # as distinct per SQL spec, so pool candidates (job_id=NULL) could have
    # duplicate emails on PostgreSQL but NOT on SQLite — inconsistent behavior.
    #
    # New approach: a partial unique index that only enforces uniqueness when
    # job_id IS NOT NULL.  Pool-candidate (job_id=NULL) dedup is handled in
    # application logic (see resumes.py upload_resume and candidate_portal.py).
    #
    # MIGRATION REQUIRED:
    #   DROP INDEX IF EXISTS uq_candidate_email_job;  -- or the constraint
    #   CREATE UNIQUE INDEX ix_candidate_email_job
    #       ON candidates (email, job_id) WHERE job_id IS NOT NULL;
    __table_args__ = (
        # Candidate self-apply uniqueness should apply only when both identifiers
        # are present; pool and recruiter-managed rows intentionally keep one side null.
        Index(
            "uq_application_user_job",
            "user_id",
            "job_id",
            unique=True,
            postgresql_where=sa.text("user_id IS NOT NULL AND job_id IS NOT NULL"),
            sqlite_where=sa.text("user_id IS NOT NULL AND job_id IS NOT NULL"),
        ),
        Index(
            "ix_candidate_email_job",
            "email",
            "job_id",
            unique=True,
            postgresql_where=sa.text("job_id IS NOT NULL"),
            sqlite_where=sa.text("job_id IS NOT NULL"),
        ),
        Index(
            "uq_pool_candidate_email_user",
            sa.text("lower(email)"),
            "user_id",
            unique=True,
            postgresql_where=sa.text("job_id IS NULL AND email IS NOT NULL AND user_id IS NOT NULL"),
            sqlite_where=sa.text("job_id IS NULL AND email IS NOT NULL AND user_id IS NOT NULL"),
        ),
        # Prevent fully orphaned rows that bypass both ownership dimensions.
        CheckConstraint(
            "job_id IS NOT NULL OR user_id IS NOT NULL",
            name="ck_candidates_job_or_user_present",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    # PERF 8 FIX: added index=True — nearly every query filters by job_id (list
    # candidates, shortlisting, ranking, analytics, skill-gap, archive, restore).
    # Without an index every request causes a full table scan on large tables.
    # Run add_job_id_index_migration.py to create the index on existing DBs.
    job_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("job_descriptions.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey(
        "users.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    email: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    # BUG 2 FIX: location column was missing — parsed location was computed and
    # used for the initial score but never persisted. Pool re-scoring and import
    # always fell back to location_match_pct=50.0 (neutral) because
    # getattr(c, "location", None) returned None for every candidate.
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    skills: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    normalized_skills: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    experience_years: Mapped[float] = mapped_column(Float, default=0.0)
    education: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    projects: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    work_experience: Mapped[Optional[list]] = mapped_column(
        MutableList.as_mutable(JSON), nullable=True)
    skill_years: Mapped[Optional[dict]] = mapped_column(
        MutableDict.as_mutable(JSON), nullable=True)
    raw_resume_text: Mapped[Optional[str]] = mapped_column(Text)
    resume_path: Mapped[Optional[str]] = mapped_column(String(512))

    # SHA-256 content hash for duplicate detection.
    file_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    # ARCHIVE FLAG — set to True when HR removes a candidate from the pipeline
    # via "Clear Displayed". The record is retained in the All Data master archive.
    # Hard-delete from AllDataModal sets this and then permanently removes the row.
    # Migration: add_is_archived_migration.py
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # PostgreSQL uses pgvector vector(settings.EMBEDDING_DIM); non-PostgreSQL uses JSON
    # fallback to keep local sqlite/dev and tests operational.
    embedding: Mapped[Optional[list]] = mapped_column(EMBEDDING_SA_TYPE, nullable=True)
    skill_match_pct: Mapped[float] = mapped_column(Float, default=0.0)
    experience_match_pct: Mapped[float] = mapped_column(Float, default=0.0)
    project_relevance_pct: Mapped[float] = mapped_column(Float, default=0.0)
    education_match_pct: Mapped[float] = mapped_column(Float, default=0.0)
    vector_similarity: Mapped[float] = mapped_column(Float, default=0.0)
    resume_score: Mapped[float] = mapped_column(Float, default=0.0)

    # ── AI Scoring fields (added in scoring v2) ───────────────────────────────
    # location_match_pct: score (0–100) for how well the candidate's location
    # matches the job location. Stored separately so it can be shown in the UI.
    location_match_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # score_breakdown: JSON blob with AI scoring metadata — matched/missing
    # skills, reasoning text, whether AI scoring was used vs rule-based fallback.
    # Schema: {ai_score_used, matched_must_have, missing_must_have,
    #           matched_good_to_have, reasoning}
    # Migration: add_scoring_v2_migration.py
    score_breakdown: Mapped[Optional[dict]] = mapped_column(
        MutableDict.as_mutable(JSON), nullable=True
    )

    # career_breaks: JSON list of gaps detected between jobs, plus candidate-supplied
    # context (reason, notes). Each item: {start, end, duration_months, reason, notes}.
    # Populated during resume parsing; candidate can enrich via the apply portal.
    # Migration: add_career_breaks_migration.py
    career_breaks: Mapped[Optional[list]] = mapped_column(
        MutableList.as_mutable(JSON), nullable=True
    )
    tag: Mapped[Optional[CandidateTag]] = mapped_column(SAEnum(CandidateTag))
    quiz_score: Mapped[Optional[float]] = mapped_column(Float)
    quiz_max: Mapped[Optional[float]] = mapped_column(Float)
    quiz_pct: Mapped[Optional[float]] = mapped_column(Float)
    final_score: Mapped[Optional[float]] = mapped_column(Float)
    rank: Mapped[Optional[int]] = mapped_column(Integer)
    passed: Mapped[Optional[bool]] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    job: Mapped["JobDescription"] = relationship(back_populates="candidates")
    user: Mapped[Optional["User"]] = relationship(back_populates="candidate_profiles")
    quiz_attempts: Mapped[list["QuizAttempt"]] = relationship(back_populates="candidate")

# ─── Quiz ─────────────────────────────────────────────────────────────────────


class Quiz(Base):
    __tablename__ = "quizzes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    job_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey(
        "job_descriptions.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    job: Mapped["JobDescription"] = relationship(back_populates="quizzes")
    questions: Mapped[list["Question"]] = relationship(
        back_populates="quiz", cascade="all, delete-orphan")
    attempts: Mapped[list["QuizAttempt"]] = relationship(back_populates="quiz")


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    # BUG-P FIX: added index — every quiz start/submit fetches questions by quiz_id
    quiz_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("quizzes.id"), nullable=False, index=True)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list] = mapped_column(MutableList.as_mutable(JSON))
    correct_answer: Mapped[int] = mapped_column(Integer)
    difficulty: Mapped[Difficulty] = mapped_column(SAEnum(Difficulty))
    skill_tag: Mapped[Optional[str]] = mapped_column(String(100))
    weight: Mapped[int] = mapped_column(Integer, default=1)
    order: Mapped[int] = mapped_column(Integer, default=0)

    quiz: Mapped["Quiz"] = relationship(back_populates="questions")


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    quiz_id: Mapped[str] = mapped_column(String(36), ForeignKey("quizzes.id"), nullable=False, index=True)
    # BUG-O FIX: added index — quiz submission loads attempt with candidate join
    candidate_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("candidates.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[QuizStatus] = mapped_column(SAEnum(QuizStatus), default=QuizStatus.pending)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # DATA RETENTION: quiz answers are stored in plaintext JSON for auditing and
    # score verification. They are not classified as sensitive PII under most
    # regimes, but may be subject to retention policies in regulated industries.
    # If a data-retention schedule applies, implement a purge job that clears
    # this field N days after quiz submission while preserving aggregate scores.
    answers: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    raw_score: Mapped[float] = mapped_column(Float, default=0.0)
    max_score: Mapped[float] = mapped_column(Float, default=0.0)
    skill_breakdown: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    difficulty_breakdown: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    tab_switches: Mapped[int] = mapped_column(Integer, default=0)
    question_order: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    question_snapshot: Mapped[Optional[list]] = mapped_column(
        MutableList.as_mutable(JSON), nullable=True
    )
    code_eval_count: Mapped[int] = mapped_column(Integer, default=0)
    # BUG 7 FIX: quiz access tokens now expire after a configurable period
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    quiz: Mapped["Quiz"] = relationship(back_populates="attempts")
    candidate: Mapped["Candidate"] = relationship(back_populates="quiz_attempts")

    @staticmethod
    def hash_access_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    # Backward-compatible write-only alias for older call-sites that still pass
    # access_token=... when constructing QuizAttempt. Raw tokens are never stored,
    # so reading access_token from a DB-loaded row intentionally returns None.
    @property
    def access_token(self) -> Optional[str]:
        raw = getattr(self, "_raw_access_token", None)
        if raw is not None:
            return raw
        return None

    @access_token.setter
    def access_token(self, raw_token: str) -> None:
        self._raw_access_token = raw_token
        self.token_hash = self.hash_access_token(raw_token)


class StoredResume(Base):
    """Resume vault — candidates store multiple resumes and pick one per application.

    Parsed data (skills, embedding, work_experience, etc.) is cached in the DB
    on first upload so subsequent fit-score requests never re-call the AI API.
    """
    __tablename__ = "stored_resumes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey(
        "users.id", ondelete="CASCADE"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    resume_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    file_size_kb: Mapped[int] = mapped_column(Integer, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # ── Parsed / cached fields (populated on upload, reused on every fit-score) ──
    # Storing these avoids re-calling Azure OpenAI parse+embed on every preview.
    parsed_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    parsed_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    parsed_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    parsed_location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    skills: Mapped[Optional[list]] = mapped_column(MutableList.as_mutable(JSON), nullable=True)
    normalized_skills: Mapped[Optional[list]] = mapped_column(
        MutableList.as_mutable(JSON), nullable=True)
    experience_years: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    education: Mapped[Optional[list]] = mapped_column(MutableList.as_mutable(JSON), nullable=True)
    projects: Mapped[Optional[list]] = mapped_column(MutableList.as_mutable(JSON), nullable=True)
    work_experience: Mapped[Optional[list]] = mapped_column(
        MutableList.as_mutable(JSON), nullable=True)
    skill_years: Mapped[Optional[dict]] = mapped_column(
        MutableDict.as_mutable(JSON), nullable=True)
    career_breaks: Mapped[Optional[list]] = mapped_column(
        MutableList.as_mutable(JSON), nullable=True)
    embedding: Mapped[Optional[list]] = mapped_column(EMBEDDING_SA_TYPE, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parse_version: Mapped[int] = mapped_column(Integer, default=PARSER_VERSION)

    user: Mapped["User"] = relationship(back_populates="stored_resumes")


class BulkUploadJob(Base):
    __tablename__ = "bulk_upload_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="queued")
    created_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("job_descriptions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_committed_batch: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_summary: Mapped[Optional[dict]] = mapped_column(MutableDict.as_mutable(JSON), nullable=True)
    details: Mapped[Optional[dict]] = mapped_column(MutableDict.as_mutable(JSON), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, index=True
    )

    creator: Mapped[Optional["User"]] = relationship(back_populates="bulk_upload_jobs")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(100))
    resource: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[Optional[str]] = mapped_column(String(36))
    details: Mapped[Optional[dict]] = mapped_column(MutableDict.as_mutable(JSON))
    ip_address: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True)

    user: Mapped[Optional["User"]] = relationship(back_populates="audit_logs")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    replaced_by_token_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)

    user: Mapped[Optional["User"]] = relationship(back_populates="revoked_tokens")


class UsedResetToken(Base):
    __tablename__ = "used_reset_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    user: Mapped["User"] = relationship(back_populates="used_reset_tokens")
