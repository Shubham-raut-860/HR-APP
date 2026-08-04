"""Typed state contracts used by the LangGraph workflows and HarnessAgent."""

from __future__ import annotations

from typing import Any, Optional, TypedDict


class ResumeScreeningState(TypedDict, total=False):
    filename: str
    content: bytes
    text: str
    job: Any
    cached_candidate: Any
    user_email: Optional[str]
    parsed: dict[str, Any]
    resume_data: dict[str, Any]
    error: str


class JDGenerationState(TypedDict, total=False):
    role: str
    experience_min: int
    experience_max: int
    location: Optional[str]
    additional_context: Optional[str]
    cache_query: str
    query_embedding: list[float]
    jd_data: dict[str, Any]
    cache_hit: bool
    error: str


class QuizGenerationState(TypedDict, total=False):
    jd_text: str
    skills: list[str]
    easy: int
    medium: int
    hard: int
    questions: list[dict[str, Any]]
    error: str


class CandidateToolsState(TypedDict, total=False):
    operation: str
    resume_text: str
    job: Any
    current_score: float
    missing_skills: list[str]
    candidate_data: dict[str, Any]
    target_role: str
    result: dict[str, Any]
    error: str


class ResumeAgentState(TypedDict, total=False):
    file_bytes: bytes
    resume_text: str
    job_description: str
    score_result: dict[str, Any]
    filename: str
    parsed_resume: dict[str, Any]
    parsed_job: dict[str, Any]


# ── New: unified harness state used by HarnessAgent pipelines ─────────────────

class HarnessState(TypedDict, total=False):
    # Routing / tracing
    trace_id: str
    task: str
    pipeline: str
    _agent_trace: list[dict[str, Any]]

    # File / document
    filename: str
    content: bytes
    file_bytes: bytes
    text: str
    doc_text: str

    # Resume data
    parsed_resume: dict[str, Any]
    embedding: list[float]
    embed_text: str
    resume_text: str
    built_resume: dict[str, Any]
    enhancement_result: dict[str, Any]
    current_skill_match_pct: float
    missing_must_have: list[str]

    # JD data
    jd_text: str
    job_description: str
    parsed_job: dict[str, Any]
    jd_data: dict[str, Any]
    jd_embedding: list[float]
    query_embedding: list[float]
    cache_hit: bool
    role: str
    experience_min: int
    experience_max: int
    location: Optional[str]
    additional_context: Optional[str]

    # Scoring
    score_result: dict[str, Any]
    skip_ai_scoring: bool
    job_id: str
    db: Any  # AsyncSession — passed through but not serialised

    # Deduplication
    is_duplicate: bool
    duplicate_reason: Optional[str]
    file_hash: Optional[str]
    existing_candidate_id: Optional[str]
    candidate_email: Optional[str]

    # Quiz
    operation: str
    questions: list[dict[str, Any]]
    answers: dict[str, int]
    quiz_raw_score: float
    quiz_max_score: float
    quiz_pct: float
    quiz_skill_breakdown: dict[str, Any]
    quiz_difficulty_breakdown: dict[str, Any]
    easy: int
    medium: int
    hard: int

    # Code evaluation
    problem_statement: str
    user_code: str
    language: str
    code_eval_result: dict[str, Any]

    # Ranking
    candidates: list[dict[str, Any]]
    jd: dict[str, Any]
    use_lyzr: bool
    ranking_result: dict[str, Any]

    # Career tools
    candidate_name: str
    company_name: str
    target_role: str
    candidate_data: dict[str, Any]
    cover_letter: dict[str, Any]

    # Notifications
    user_id: str
    email: str
    to_email: str
    title: str
    message: str
    ntype: str
    related_id: Optional[str]
    notification_sent: bool
    count: int
    email_sent: bool
    email_body: str
    subject: str
    email_type: str
    job_title: str
    resume_score: float
    quiz_score: float
    error: str
