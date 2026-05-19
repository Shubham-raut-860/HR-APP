"""
Pydantic v2 schemas â€“ request bodies & response shapes

FIX LOG:
  SCHEMA-1  CandidatePortalOut.quiz_max_score was `float` (non-optional) but
            get_my_feedback() now correctly returns None when no quiz has been
            assigned. Changed to `Optional[float] = None` to match.

  SCHEMA-2  CandidateOut and CandidateListOut were missing `location: Optional[str]`
            even though the Candidate model has the column. HR could never see
            candidate location in any list/detail view.

  SCHEMA-3  PoolMatchOut was missing `location: Optional[str]` â€” pool match
            results showed no location for candidates in the pool.
"""
from __future__ import annotations
import re
from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator, computed_field
from app.models import UserRole, CandidateTag, QuizStatus, Difficulty
from app.constants.scoring import (
    candidate_tier_from_years,
    DEFAULT_SHORTLIST_THRESHOLD,
    JD_DEFAULT_PASS_THRESHOLD,
    MAX_QUIZ_QUESTIONS,
    SHORTLIST_WEIGHT_SUM_TOLERANCE_MAX,
    SHORTLIST_WEIGHT_SUM_TOLERANCE_MIN,
    STRONG_SHORTLIST_THRESHOLD,
)
from app.utils.password_policy import validate_password


# â”€â”€â”€ Shared helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


_EMAIL_LIKE_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_optional_email(value: Any) -> Optional[str]:
    """Best-effort outbound email normalizer for legacy dirty DB rows."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if not _EMAIL_LIKE_PATTERN.fullmatch(cleaned):
        return None
    return cleaned


def normalize_candidate_tag(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    lowered = value.strip().lower()
    mapping = {
        "strong": CandidateTag.strong,
        "medium": CandidateTag.medium,
        "reject": CandidateTag.reject,
    }
    return mapping.get(lowered, value)


# â”€â”€â”€ Shared â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class MessageResponse(BaseModel):
    message: str
    detail: Optional[str] = None


# â”€â”€â”€ Auth â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    full_name: str
    # Public self-registration supports candidate and recruiter (hr).
    # Admin provisioning still remains disallowed here.
    role: Literal["candidate", "hr"] = "candidate"

    # Canonical password policy shared with reset/change handlers via
    # app.utils.password_policy.validate_password().
    @field_validator("password")
    @classmethod
    def validate_password_field(cls, v: str) -> str:
        return validate_password(v)

    @field_validator("role")
    @classmethod
    def restrict_role(cls, v: str) -> str:
        if v not in {"candidate", "hr"}:
            raise ValueError("Role must be candidate or hr")
        return v


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    bio: Optional[str] = None
    preferences: Optional[Dict] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    user: UserOut


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# â”€â”€â”€ Job Description â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class JDCreate(BaseModel):
    # extra="ignore" â€” frontend sends extra fields like `company`, `company_bio`,
    # `company_blog` for display purposes. Silently drop them instead of 422.
    model_config = ConfigDict(extra="ignore")
    title: str
    role: str
    location: Optional[str] = None
    employment_type: Optional[str] = "Full-time"
    experience_min: int = 0
    experience_max: int = 10
    must_have_skills: List[str] = []
    good_to_have_skills: List[str] = []
    description: Optional[str] = None
    salary_range: Optional[str] = None
    education_requirement: Optional[str] = None
    file_hash: Optional[str] = None
    resume_weight: int = Field(default=50, ge=0, le=100)
    quiz_weight: int = Field(default=50, ge=0, le=100)
    pass_threshold: int = Field(default=JD_DEFAULT_PASS_THRESHOLD, ge=0, le=100)

    @field_validator("quiz_weight")
    @classmethod
    def weights_sum_100(cls, v, info):
        if "resume_weight" not in info.data:
            return v
        rw = info.data["resume_weight"]
        if rw + v != 100:
            raise ValueError("resume_weight + quiz_weight must equal 100")
        return v

    @field_validator("title", "role")
    @classmethod
    def validate_non_placeholder_text(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if len(cleaned) < 2:
            raise ValueError("Field is too short")
        if not any(ch.isalpha() for ch in cleaned):
            raise ValueError("Field must include alphabetic text")
        return cleaned

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("must_have_skills", "good_to_have_skills")
    @classmethod
    def normalize_skill_lists(cls, values: List[str]) -> List[str]:
        seen: set[str] = set()
        normalized: List[str] = []
        for raw in values or []:
            skill = (raw or "").strip()
            if not skill:
                continue
            key = skill.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(skill)
        return normalized

    @model_validator(mode="after")
    def validate_jd_quality(self):
        if self.experience_min > self.experience_max:
            raise ValueError("experience_min cannot be greater than experience_max")

        has_skills = bool(self.must_have_skills or self.good_to_have_skills)
        desc = (self.description or "").strip()
        has_meaningful_description = len(re.sub(r"[^a-zA-Z0-9]+", "", desc)) >= 20
        if not has_skills and not has_meaningful_description:
            raise ValueError(
                "Provide at least one must-have/good-to-have skill or a meaningful job description."
            )
        return self


class JDGenerateRequest(BaseModel):
    role: str
    experience_min: int = 0
    experience_max: int = 5
    location: Optional[str] = None
    additional_context: Optional[str] = None


class JDOut(BaseModel):
    id: str
    title: str
    role: str
    location: Optional[str]
    employment_type: Optional[str] = None
    experience_min: int
    experience_max: int
    must_have_skills: List[str]
    good_to_have_skills: List[str]
    description: Optional[str]
    salary_range: Optional[str] = None
    education_requirement: Optional[str] = None
    resume_weight: int
    quiz_weight: int
    pass_threshold: int
    is_active: bool
    created_at: datetime
    model_config = {"from_attributes": True}


# â”€â”€â”€ Resume / Candidate â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class EducationItem(BaseModel):
    degree: Optional[str] = None
    institute: Optional[str] = None
    year: Optional[str] = None
    gpa: Optional[str] = None


class ProjectItem(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    skills: List[str] = []


# â”€â”€â”€ Shared tier computation mixin â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class _CandidateTierMixin(BaseModel):
    """Shared model_validator for computing candidate_tier from score_breakdown
    or experience_years. Used by both CandidateOut and CandidateListOut."""
    candidate_tier: Optional[str] = None
    experience_years: float = 0.0

    @model_validator(mode="after")
    def _pull_candidate_tier(self) -> "_CandidateTierMixin":
        score_breakdown = getattr(self, "score_breakdown", None)
        if self.candidate_tier is None and isinstance(score_breakdown, dict):
            self.candidate_tier = score_breakdown.get("candidate_tier")
        if self.candidate_tier is None:
            self.candidate_tier = candidate_tier_from_years(self.experience_years or 0.0)
        return self


class CandidateOut(_CandidateTierMixin):
    id: str
    job_id: Optional[str]
    user_id: Optional[str] = None
    name: Optional[str]
    # Email is normalized on read; legacy rows may contain nullable values.
    email: Optional[str] = None
    phone: Optional[str]
    # SCHEMA-2 FIX: location was stored on the model but missing from this schema
    location: Optional[str] = None
    skills: List[str]
    normalized_skills: List[str]
    experience_years: float
    education: List[Dict]
    projects: List[Dict]
    work_experience: Optional[List[Dict]] = None
    skill_years: Optional[Dict] = None
    skill_match_pct: float
    experience_match_pct: float
    project_relevance_pct: float
    education_match_pct: float
    location_match_pct: Optional[float] = None
    candidate_tier: Optional[str] = None
    vector_similarity: float
    resume_score: float
    score_breakdown: Optional[Dict] = None
    career_breaks: Optional[List[Dict]] = None
    tag: Optional[CandidateTag]
    quiz_score: Optional[float]
    quiz_max: Optional[float] = None
    quiz_pct: Optional[float] = None
    final_score: Optional[float]
    rank: Optional[int]
    passed: Optional[bool]
    created_at: datetime
    model_config = {"from_attributes": True}

    @field_validator("tag", mode="before")
    @classmethod
    def normalize_tag_field(cls, value: Any) -> Any:
        return normalize_candidate_tag(value)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_field(cls, value: Any) -> Optional[str]:
        return normalize_optional_email(value)


class CandidateListOut(_CandidateTierMixin):
    """
    Lightweight list-view schema that omits heavy blob fields.
    `embedding` alone is ~6 KB per candidate; returning 500 rows with embeddings
    is ~3 MB of wasted payload. Use CandidateOut only for single-candidate detail.
    """
    id: str
    job_id: Optional[str]
    user_id: Optional[str] = None
    name: Optional[str]
    # Email is normalized on read; legacy rows may contain nullable values.
    email: Optional[str] = None
    phone: Optional[str]
    # SCHEMA-2 FIX: location was stored on the model but missing from this schema
    location: Optional[str] = None
    skills: List[str]
    normalized_skills: List[str]
    experience_years: float
    education: List[Dict]
    projects: List[Dict]
    skill_match_pct: float
    experience_match_pct: float
    project_relevance_pct: float
    education_match_pct: float
    location_match_pct: Optional[float] = None
    candidate_tier: Optional[str] = None
    vector_similarity: float
    resume_score: float
    score_breakdown: Optional[Dict] = None
    career_breaks: Optional[List[Dict]] = None
    tag: Optional[CandidateTag]
    quiz_score: Optional[float]
    quiz_max: Optional[float] = None
    quiz_pct: Optional[float] = None
    final_score: Optional[float]
    rank: Optional[int]
    passed: Optional[bool]
    created_at: datetime
    is_archived: bool = False
    model_config = {"from_attributes": True}

    @field_validator("tag", mode="before")
    @classmethod
    def normalize_tag_field(cls, value: Any) -> Any:
        return normalize_candidate_tag(value)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_field(cls, value: Any) -> Optional[str]:
        return normalize_optional_email(value)


class CandidatePipelineListOut(_CandidateTierMixin):
    """
    Lightweight pipeline list schema for GET /resumes/ used by recruiter list/kanban
    views. Excludes heavy JSON blobs (skills/education/projects/score_breakdown).
    """
    id: str
    job_id: Optional[str]
    user_id: Optional[str] = None
    name: Optional[str]
    email: Optional[str] = None
    phone: Optional[str]
    location: Optional[str] = None
    normalized_skills: List[str]
    experience_years: float
    skill_match_pct: float
    experience_match_pct: float
    candidate_tier: Optional[str] = None
    resume_score: float
    tag: Optional[CandidateTag]
    quiz_score: Optional[float]
    quiz_max: Optional[float] = None
    quiz_pct: Optional[float] = None
    final_score: Optional[float]
    rank: Optional[int]
    created_at: datetime
    is_archived: bool = False
    model_config = {"from_attributes": True}

    @field_validator("tag", mode="before")
    @classmethod
    def normalize_tag_field(cls, value: Any) -> Any:
        return normalize_candidate_tag(value)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_field(cls, value: Any) -> Optional[str]:
        return normalize_optional_email(value)


class PoolMatchOut(BaseModel):
    """A pool candidate with scores computed on-the-fly against a specific JD.
    Scores are NOT yet persisted â€” they are written to DB only on import."""
    id: str
    name: Optional[str]
    # Email is normalized on read; legacy rows may contain nullable values.
    email: Optional[str] = None
    phone: Optional[str] = None
    # SCHEMA-3 FIX: location was missing from pool match results
    location: Optional[str] = None
    skills: List[str]
    normalized_skills: List[str]
    experience_years: float
    computed_resume_score: float
    computed_skill_match_pct: float
    computed_experience_match_pct: float
    computed_tag: Optional[str]
    model_config = {"from_attributes": True}

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_field(cls, value: Any) -> Optional[str]:
        return normalize_optional_email(value)


class ShortlistConfig(BaseModel):
    """Custom shortlisting weights â€” forwarded to compute_resume_score()."""
    job_id: str
    strong_threshold: float = Field(default=STRONG_SHORTLIST_THRESHOLD, ge=0, le=100)
    medium_threshold: float = Field(default=DEFAULT_SHORTLIST_THRESHOLD, ge=0, le=100)
    skill_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    experience_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    project_weight: float = Field(default=0.20, ge=0.0, le=1.0)
    education_weight: float = Field(default=0.10, ge=0.0, le=1.0)
    location_weight: float = Field(default=0.10, ge=0.0, le=1.0)

    @field_validator("medium_threshold")
    @classmethod
    def check_thresholds(cls, v, info):
        strong = info.data.get("strong_threshold", STRONG_SHORTLIST_THRESHOLD)
        if v >= strong:
            raise ValueError("medium_threshold must be less than strong_threshold")
        return v

    @model_validator(mode="after")
    def normalize_weights(self) -> "ShortlistConfig":
        """Ensure scoring weights sum to 1.0.

        If the total is within 5% of 1.0 (0.95â€“1.05), weights are auto-
        normalized. Outside that range the input is rejected â€” the caller
        likely made a mistake (e.g. passed percentages instead of fractions).
        """
        weight_fields = [
            "skill_weight", "experience_weight", "project_weight",
            "education_weight", "location_weight",
        ]
        total = sum(getattr(self, f) for f in weight_fields)
        if total == 0:
            raise ValueError("At least one scoring weight must be > 0")
        if not (SHORTLIST_WEIGHT_SUM_TOLERANCE_MIN <= total <= SHORTLIST_WEIGHT_SUM_TOLERANCE_MAX):
            raise ValueError(
                f"Scoring weights must sum to ~1.0 (got {total:.4f}). "
                f"Adjust weights so they total 1.0, or stay within 5% tolerance."
            )
        if total != 1.0:
            # Auto-normalize small rounding differences
            for f in weight_fields:
                setattr(self, f, round(getattr(self, f) / total, 6))
        return self


# â”€â”€â”€ Candidate Portal (self-service) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class SkillFeedbackItem(BaseModel):
    """Per-skill gap feedback returned to a candidate."""
    skill: str
    required: bool                  # True = must-have, False = good-to-have
    candidate_has: bool             # Did AI find this skill in the resume?
    importance: str                 # "Critical" | "Important" | "Nice to have"
    suggestion: str                 # e.g. "Add a project using React to your resume"


class CandidatePortalOut(BaseModel):
    """What a logged-in candidate sees about their own application."""
    candidate_id: str
    job_id: str
    job_title: str
    job_role: str
    resume_score: float
    skill_match_pct: float
    experience_match_pct: float
    project_relevance_pct: float
    education_match_pct: float
    tag: Optional[str]
    quiz_score: Optional[float]
    # SCHEMA-1 FIX: was `float` (non-optional) â€” get_my_feedback() now correctly
    # returns None when no quiz has been assigned to the candidate yet.
    # Changing to Optional prevents a Pydantic ValidationError on None.
    quiz_max_score: Optional[float] = None
    final_score: Optional[float]
    passed: Optional[bool]
    rank: Optional[int]
    skill_feedback: List[SkillFeedbackItem]
    quiz_status: Optional[str]     # pending | in_progress | submitted | timed_out | None
    quiz_token: Optional[str]      # access token if quiz is pending/in_progress


class PublicJDOut(BaseModel):
    """Minimal JD info shown to candidates browsing jobs."""
    id: str
    title: str
    role: str
    location: Optional[str]
    employment_type: Optional[str]
    experience_min: int
    experience_max: int
    must_have_skills: List[str]
    good_to_have_skills: List[str]
    description: Optional[str]
    salary_range: Optional[str] = None
    created_at: datetime
    company: Optional[str] = None
    company_bio: Optional[str] = None
    company_blog: Optional[str] = None
    model_config = {"from_attributes": True}


# â”€â”€â”€ Quiz â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class QuizGenerateRequest(BaseModel):
    duration_minutes: Optional[int] = None
    job_id: str
    custom_title: Optional[str] = None


class QuestionOut(BaseModel):
    id: str
    question_text: str
    options: List[str]
    difficulty: Difficulty
    skill_tag: Optional[str]
    weight: int
    model_config = {"from_attributes": True}


class QuestionWithAnswer(QuestionOut):
    correct_answer: int


class QuizOut(BaseModel):
    id: str
    job_id: Optional[str]   # FK is nullable (SET NULL on job delete)
    title: str
    duration_minutes: int
    is_active: bool
    question_count: int
    created_at: datetime
    model_config = {"from_attributes": True}


class QuizStartResponse(BaseModel):
    attempt_id: str
    quiz_id: str
    duration_minutes: int
    # Include seconds already elapsed so the frontend can initialise the
    # countdown to the real remaining time on resume, not always reset to full.
    time_remaining_seconds: int
    started_at: datetime
    questions: List[QuestionOut]


class SubmitAnswersRequest(BaseModel):
    attempt_id: str
    answers: Dict[str, Any] = Field(..., max_length=MAX_QUIZ_QUESTIONS)
    tab_switches: int = Field(default=0, ge=0, le=10000)

    @field_validator("answers", mode="before")
    @classmethod
    def answers_not_empty(cls, v: Any) -> Dict[str, Any]:
        if not isinstance(v, dict):
            raise ValueError("answers must be an object mapping question IDs to answers")
        if not v:
            raise ValueError("At least one answer must be submitted")
        if len(v) > MAX_QUIZ_QUESTIONS:
            raise ValueError(
                f"answers cannot contain more than {MAX_QUIZ_QUESTIONS} items"
            )
        normalized: Dict[str, Any] = {}
        for key, value in v.items():
            if not isinstance(key, str):
                raise ValueError("All answer keys must be non-empty strings")
            key_clean = key.strip()
            if not key_clean:
                raise ValueError("All answer keys must be non-empty strings")
            if not isinstance(value, (str, int, list)):
                raise ValueError("Answer values must be str, int, or list")
            normalized[key_clean] = value
        return normalized

    @model_validator(mode="after")
    def validate_answers_payload(self) -> "SubmitAnswersRequest":
        if len(self.answers) > MAX_QUIZ_QUESTIONS:
            raise ValueError(
                f"answers cannot contain more than {MAX_QUIZ_QUESTIONS} items"
            )
        for key, value in self.answers.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("All answer keys must be non-empty strings")
            if not isinstance(value, (str, int, list)):
                raise ValueError("Answer values must be str, int, or list")
        return self


class QuizResultOut(BaseModel):
    attempt_id: str
    candidate_id: str
    status: QuizStatus
    raw_score: float
    max_score: float
    percentage: float
    skill_breakdown: Dict[str, Any]
    difficulty_breakdown: Dict[str, Any]
    passed: Optional[bool] = None


# â”€â”€â”€ Candidate Token (for quiz link) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class QuizAnswerItemOut(BaseModel):
    question_id: str
    question_type: str = "mcq"
    question_text: str
    skill_tag: Optional[str] = None
    difficulty: Optional[str] = None
    selected_answer: Optional[Any] = None
    selected_option_index: Optional[int] = None
    selected_option_text: Optional[str] = None
    correct_option_index: Optional[int] = None
    correct_option_text: Optional[str] = None
    is_correct: Optional[bool] = None
    score_awarded: Optional[float] = None
    max_score: Optional[float] = None


class CandidateAnswerSheetOut(BaseModel):
    attempt_id: str
    candidate_id: str
    candidate_name: Optional[str] = None
    candidate_email: Optional[str] = None
    status: QuizStatus
    raw_score: float
    max_score: float
    percentage: float
    passed: Optional[bool] = None
    submitted_at: Optional[datetime] = None
    answers: List[QuizAnswerItemOut]


class QuizMasterAnswerSheetOut(BaseModel):
    quiz_id: str
    quiz_title: str
    generated_at: datetime
    passed_only: bool = True
    total_candidates: int
    candidates: List[CandidateAnswerSheetOut]


class SendQuizLinkRequest(BaseModel):
    candidate_ids: List[str]
    quiz_id: str


# â”€â”€â”€ Analytics â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class AnalyticsSummary(BaseModel):
    total_applicants: int
    shortlisted_count: int
    shortlisted_pct: float
    strong_count: int
    medium_count: int
    reject_count: int
    quiz_taken_count: int
    ranked_count: int
    avg_resume_score: float
    avg_quiz_score: Optional[float]
    avg_quiz_pct: Optional[float] = None
    avg_final_score: Optional[float]
    pass_count: int
    fail_count: int


class SkillGapItem(BaseModel):
    skill: str
    required: bool
    candidate_match_pct: float
    gap_pct: float


class CandidateRankRow(BaseModel):
    rank: int
    candidate_id: str
    name: Optional[str]
    email: Optional[str]
    tag: Optional[str]
    resume_score: float
    quiz_score: Optional[float]
    quiz_max: Optional[float] = None
    quiz_pct: Optional[float] = None
    final_score: Optional[float]
    passed: Optional[bool]


# â”€â”€â”€ Audit â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class AuditLogOut(BaseModel):
    id: str
    user_id: Optional[str]
    action: str
    resource: str
    resource_id: Optional[str]
    details: Optional[Dict]
    ip_address: Optional[str]
    created_at: datetime
    model_config = {"from_attributes": True}


# â”€â”€â”€ Stored Resume Vault â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class StoredResumeOut(BaseModel):
    id: str
    label: str
    original_filename: str
    file_size_kb: int
    is_default: bool
    uploaded_at: datetime
    parsed_name: Optional[str] = None
    parsed_email: Optional[str] = None
    experience_years: Optional[float] = None
    normalized_skills: Optional[List[str]] = None
    summary: Optional[str] = None

    @computed_field
    @property
    def is_parsed(self) -> bool:
        return bool(self.normalized_skills)

    model_config = {"from_attributes": True}


class StoredResumeLabelUpdate(BaseModel):
    label: Optional[str] = None
    is_default: Optional[bool] = None


# â”€â”€â”€ User Update â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    bio: Optional[str] = None
    preferences: Optional[Dict] = None

    @field_validator("preferences")
    @classmethod
    def limit_preferences_size(cls, v: Optional[Dict]) -> Optional[Dict]:
        if v is not None:
            import json
            if len(json.dumps(v)) > 65536:
                raise ValueError("Preferences payload exceeds 64KB")
        return v


# â”€â”€â”€ Career Tools â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class ResumeEnhancementRequest(BaseModel):
    resume_text: str
    job_id: str


class BulletRewrite(BaseModel):
    original: str
    improved: str
    reasoning: str


class ResumeEnhancementResponse(BaseModel):
    suggestions: List[str]
    missing_keywords: List[str]
    bullet_rewrites: List[BulletRewrite]
    estimated_ats_score_increase: float


class ResumeBuilderRequest(BaseModel):
    target_role: str
    experience_summary: str
    skills_list: str
    education_summary: str


class ResumeBuilderResponse(BaseModel):
    professional_summary: str
    skills: List[str]
    experience_bullets: List[str]
    education: List[str]
    formatted_markdown: str


class CareerGapItem(BaseModel):
    identified_gap: str
    impact: str
    recommended_upskilling: str


class CareerAnalysisResponse(BaseModel):
    current_level: str
    trajectory_summary: str
    market_demand_alignment: str
    career_gaps: List[CareerGapItem]
    next_role_suggestions: List[str]


class CoverLetterRequest(BaseModel):
    resume_text: str
    job_id: str
    tone: str = "Professional"


class CoverLetterResponse(BaseModel):
    cover_letter_body: str
    subject_line: str

