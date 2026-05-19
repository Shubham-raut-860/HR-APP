"""
Quiz router – generate quiz from JD, send to candidates, handle attempts
"""
import html
import secrets
import asyncio
import logging
import string
from datetime import datetime, timezone, timedelta
import os
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request, Header, Query, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
# FIX Finding 21: Add rate limit to prevent code-eval abuse
from app.limiter import limiter
from sqlalchemy import select, func, update
from sqlalchemy.orm import selectinload
from typing import List, Optional, Any, Literal
import random
from importlib import import_module
from app.database import get_db, AsyncSessionLocal
from app.models import User, Quiz, Question, QuizAttempt, Candidate, JobDescription, QuizStatus, CandidateTag, NotificationType, UserRole
from app.services.notification_service import (
    push_notification,
    push_to_candidate_by_email,
    push_to_candidates_by_emails,
)
from app.schemas import (
    QuizGenerateRequest, QuizOut, QuizStartResponse, QuestionOut,
    QuestionWithAnswer, SubmitAnswersRequest, QuizResultOut, SendQuizLinkRequest,
    QuizAnswerItemOut, CandidateAnswerSheetOut, QuizMasterAnswerSheetOut
)
from app.services.auth_service import require_hr, require_candidate, log_action
from app.config import settings
from app.utils.quiz_validation import (
    QuestionValidationError,
    deduplicate_questions,
    difficulty_counts,
    rebalance_difficulty_distribution,
    validate_question,
)
from pydantic import BaseModel

router = APIRouter(prefix="/quiz", tags=["Quiz"])
logger = logging.getLogger(__name__)
class _LazyModule:
    def __init__(self, module_path: str):
        self._module_path = module_path
        self._module = None

    def _load(self):
        if self._module is None:
            self._module = import_module(self._module_path)
        return self._module

    def __getattr__(self, item):
        return getattr(self._load(), item)


gemini_service = _LazyModule("app.services.gemini_service")
scoring_service = _LazyModule("app.services.scoring_service")
file_service = _LazyModule("app.services.file_service")
harness_agent_client = _LazyModule("app.services.harness_agent_client")


def _is_harness_or_timeout_error(exc: Exception) -> bool:
    return isinstance(exc, asyncio.TimeoutError) or exc.__class__.__name__ == "HarnessAgentError"


_gemini = gemini_service
MAX_CODE_EVALS = 3
CODE_EVAL_GRACE_SECONDS = 60
_QUIZ_GENERATE_TIMEOUT_S = 12.0
_QUIZ_FALLBACK_TIMEOUT_S = 14.0
_QUIZ_PARSE_TIMEOUT_S = 20.0
_QUIZ_EMAIL_NOTIFY_TIMEOUT_S = 8.0
_QUIZ_CODE_EVAL_TIMEOUT_S = 25.0


class QuizMagicLinkContext(BaseModel):
    quiz_title: str
    job_title: Optional[str] = None
    has_existing_account: bool
    status: Literal["pending", "started", "completed"]


async def _run_quiz_generation_with_fallback(
    *,
    request: Request | None,
    jd_text: str,
    skills: list[str],
    easy: int,
    medium: int,
    hard: int,
) -> list[dict]:
    try:
        auth_header = request.headers.get("authorization") if request else None
        result = await asyncio.wait_for(
            harness_agent_client.run_agent(
                "quiz_generator",
                {
                    "jd_text": jd_text,
                    "skills": skills,
                    "easy": easy,
                    "medium": medium,
                    "hard": hard,
                },
                auth_header,
                timeout_s=_QUIZ_GENERATE_TIMEOUT_S,
            ),
            timeout=_QUIZ_GENERATE_TIMEOUT_S,
        )
        if isinstance(result, dict):
            questions = result.get("questions")
            if isinstance(questions, list):
                return questions
        return result if isinstance(result, list) else []
    except Exception as runtime_exc:
        if not _is_harness_or_timeout_error(runtime_exc):
            raise
        logger.warning(
            "Harness/runtime quiz_generator failed, using deterministic fallback questions: %s",
            runtime_exc,
        )
        return _fallback_quiz_questions(
            skills=skills,
            easy=easy,
            medium=medium,
            hard=hard,
        )


async def _run_quiz_document_parse_with_fallback(doc_text: str, request: Request | None = None) -> list[dict]:
    try:
        auth_header = request.headers.get("authorization") if request else None
        result = await asyncio.wait_for(
            harness_agent_client.run_agent(
                "quiz_parser",
                {"doc_text": doc_text},
                auth_header,
                timeout_s=_QUIZ_PARSE_TIMEOUT_S,
            ),
            timeout=_QUIZ_PARSE_TIMEOUT_S,
        )
        if isinstance(result, dict):
            questions = result.get("questions")
            if isinstance(questions, list):
                return questions
        return result if isinstance(result, list) else []
    except Exception as runtime_exc:
        if not _is_harness_or_timeout_error(runtime_exc):
            raise
        logger.warning("Harness fallback quiz_document_parse failed, using direct parser: %s", runtime_exc)
        return await asyncio.wait_for(
            gemini_service.parse_quiz_from_document(doc_text),
            timeout=_QUIZ_PARSE_TIMEOUT_S,
        )


async def _run_code_eval_with_fallback(
    *,
    request: Request | None,
    problem: str,
    code: str,
    language: str,
) -> dict:
    try:
        auth_header = request.headers.get("authorization") if request else None
        result = await asyncio.wait_for(
            harness_agent_client.run_agent(
                "code_evaluator",
                {
                    "problem_statement": problem,
                    "user_code": code,
                    "language": language,
                },
                auth_header,
                timeout_s=_QUIZ_CODE_EVAL_TIMEOUT_S,
            ),
            timeout=_QUIZ_CODE_EVAL_TIMEOUT_S,
        )
        if isinstance(result, dict) and isinstance(result.get("code_eval_result"), dict):
            return result["code_eval_result"]
        return result if isinstance(result, dict) else {}
    except Exception as runtime_exc:
        if not _is_harness_or_timeout_error(runtime_exc):
            raise
        logger.warning("Harness fallback code_evaluator failed, using direct evaluator: %s", runtime_exc)
        return await asyncio.wait_for(
            _gemini.evaluate_code_submission(problem, code, language),
            timeout=_QUIZ_CODE_EVAL_TIMEOUT_S,
        )


def _fallback_quiz_questions(
    skills: list[str],
    easy: int,
    medium: int,
    hard: int,
) -> list[dict]:
    """
    Deterministic fallback MCQ generator when AI question generation is unavailable.
    """
    pool = [s for s in skills if s] or [
        "Problem Solving",
        "APIs",
        "Databases",
        "Testing",
        "System Design",
    ]
    total = max(1, easy + medium + hard)
    difficulties = (["easy"] * easy) + (["medium"] * medium) + (["hard"] * hard)
    if len(difficulties) < total:
        difficulties.extend(["medium"] * (total - len(difficulties)))

    questions: list[dict] = []
    for idx in range(total):
        skill = pool[idx % len(pool)]
        difficulty = difficulties[idx]
        if difficulty == "easy":
            question_text = f"[Q{idx + 1}] Which statement best describes {skill} in software development?"
            correct_option = f"{skill} helps build reliable software outcomes"
            distractors = [
                f"{skill} is unrelated to development quality",
                f"{skill} is only useful for UI design",
                f"{skill} replaces code reviews entirely",
            ]
            weight = 1
        elif difficulty == "medium":
            question_text = f"[Q{idx + 1}] For {skill}, which approach is generally recommended in production systems?"
            correct_option = "Use repeatable, testable workflows with monitoring"
            distractors = [
                "Skip logging to improve speed in all cases",
                "Delay validation until after release",
                "Avoid versioning and change tracking",
            ]
            weight = 2
        else:
            question_text = f"[Q{idx + 1}] In advanced {skill} scenarios, what is the strongest engineering practice?"
            correct_option = "Design for failure handling, observability, and scalability"
            distractors = [
                "Rely only on manual testing in production",
                "Ship without rollback planning",
                "Disable alerts to reduce noise permanently",
            ]
            weight = 3

        options = [correct_option, *distractors]
        rng = random.Random(f"{skill}:{difficulty}:{idx}")
        rng.shuffle(options)
        correct = options.index(correct_option)

        questions.append({
            "question_text": question_text,
            "options": options,
            "correct_answer": correct,
            "difficulty": difficulty,
            "skill_tag": skill,
            "weight": weight,
        })

    return questions


def _build_magic_link(raw_token: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/take-quiz?token={raw_token}"


def _new_quiz_token_pair() -> tuple[str, str]:
    raw_token = secrets.token_urlsafe(32)
    return raw_token, QuizAttempt.hash_access_token(raw_token)


def _prepare_questions_for_persist(
    raw_questions: list[dict[str, Any]],
    *,
    expected_easy: int | None = None,
    expected_medium: int | None = None,
    expected_hard: int | None = None,
    fallback_skills: list[str] | None = None,
) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    for raw in raw_questions:
        validated.append(validate_question(raw))

    validated, dropped = deduplicate_questions(validated)
    if dropped:
        logger.warning("Dropped %s duplicate/invalid question(s) before quiz persistence", dropped)

    if (
        expected_easy is not None
        and expected_medium is not None
        and expected_hard is not None
    ):
        expected = {
            "easy": max(0, int(expected_easy)),
            "medium": max(0, int(expected_medium)),
            "hard": max(0, int(expected_hard)),
        }
        observed = difficulty_counts(validated)
        for diff_name, expected_count in expected.items():
            actual_count = observed.get(diff_name, 0)
            if actual_count != expected_count:
                logger.warning(
                    "Difficulty drift detected: expected %s=%s, got %s",
                    diff_name,
                    expected_count,
                    actual_count,
                )

        def _fallback_factory(missing_easy: int, missing_medium: int, missing_hard: int) -> list[dict[str, Any]]:
            return _fallback_quiz_questions(
                fallback_skills or [],
                missing_easy,
                missing_medium,
                missing_hard,
            )

        validated = rebalance_difficulty_distribution(
            validated,
            expected_easy=expected["easy"],
            expected_medium=expected["medium"],
            expected_hard=expected["hard"],
            fallback_factory=_fallback_factory,
        )

    return validated


def _resolve_quiz_token(token: Optional[str], x_quiz_token: Optional[str], *, missing_status: int = 400) -> str:
    if token and not x_quiz_token:
        logger.warning("Quiz token via query param is deprecated")
    resolved_token = (x_quiz_token or token or "").strip()
    if not resolved_token:
        raise HTTPException(status_code=missing_status, detail="Quiz token is required")
    return resolved_token


def _quiz_token_hash_candidates(token: str) -> list[str]:
    """
    Build hash candidates for quiz auth.

    Only raw tokens are accepted as credentials. Pre-hashed 64-char values are
    explicitly rejected to prevent token_hash replay attacks.
    """
    normalized = (token or "").strip()
    if len(normalized) == 64 and all(ch in string.hexdigits for ch in normalized):
        raise HTTPException(status_code=400, detail="Invalid token format")
    return [QuizAttempt.hash_access_token(normalized)]


async def _load_attempt_by_token(
    db: AsyncSession,
    token: str,
    *,
    with_lock: bool = False,
    include_candidate: bool = False,
    include_quiz: bool = False,
) -> QuizAttempt:
    token_hash = QuizAttempt.hash_access_token(token)
    query = select(QuizAttempt)
    opts = []
    if include_candidate:
        opts.append(selectinload(QuizAttempt.candidate))
    if include_quiz:
        opts.append(selectinload(QuizAttempt.quiz))
    if opts:
        query = query.options(*opts)
    query = query.where(QuizAttempt.token_hash == token_hash)
    if with_lock and not settings.DATABASE_URL.startswith("sqlite"):
        query = query.with_for_update()
    attempt = (await db.execute(query)).scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Invalid quiz token")
    return attempt


@router.get("/magic-link/context", response_model=QuizMagicLinkContext)
async def quiz_magic_link_context(
    token: Optional[str] = Query(default=None),
    x_quiz_token: Optional[str] = Header(default=None, alias="X-Quiz-Token"),
    db: AsyncSession = Depends(get_db),
):
    resolved_token = _resolve_quiz_token(token, x_quiz_token)
    attempt = await _load_attempt_by_token(
        db,
        resolved_token,
        with_lock=False,
        include_candidate=True,
        include_quiz=True,
    )
    candidate = attempt.candidate
    if not candidate:
        raise HTTPException(status_code=404, detail="Assessment candidate record not found")

    if attempt.token_expires_at:
        expires_utc = (
            attempt.token_expires_at
            if attempt.token_expires_at.tzinfo is not None
            else attempt.token_expires_at.replace(tzinfo=timezone.utc)
        )
        if datetime.now(timezone.utc) > expires_utc:
            raise HTTPException(status_code=410, detail="This quiz invitation has expired")

    has_account = False
    if candidate.email:
        existing_user = (await db.execute(
            select(User.id).where(func.lower(User.email) == candidate.email.lower())
        )).scalar_one_or_none()
        has_account = existing_user is not None

    job_title: Optional[str] = None
    if attempt.quiz and attempt.quiz.job_id:
        job_row = (await db.execute(
            select(JobDescription.title).where(JobDescription.id == attempt.quiz.job_id)
        )).scalar_one_or_none()
        if job_row:
            job_title = job_row

    status_map = {
        QuizStatus.pending: "pending",
        QuizStatus.in_progress: "started",
        QuizStatus.submitted: "completed",
        QuizStatus.timed_out: "completed",
    }
    status = status_map.get(attempt.status, "pending")

    return {
        "quiz_title": attempt.quiz.title if attempt.quiz else "Assessment",
        "job_title": job_title,
        "has_existing_account": has_account,
        "status": status,
    }


@router.post("/magic-link/claim")
async def claim_quiz_magic_link(
    token: Optional[str] = Query(default=None),
    x_quiz_token: Optional[str] = Header(default=None, alias="X-Quiz-Token"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    resolved_token = _resolve_quiz_token(token, x_quiz_token)
    attempt = await _load_attempt_by_token(
        db,
        resolved_token,
        with_lock=True,
        include_candidate=True,
        include_quiz=False,
    )
    if attempt.token_expires_at:
        expires_utc = (
            attempt.token_expires_at
            if attempt.token_expires_at.tzinfo is not None
            else attempt.token_expires_at.replace(tzinfo=timezone.utc)
        )
        if datetime.now(timezone.utc) > expires_utc:
            return JSONResponse(status_code=410, content={"detail": "Invitation has expired"})
    candidate = attempt.candidate
    if not candidate:
        raise HTTPException(status_code=404, detail="Assessment candidate record not found")
    # If this invite is already bound to the current candidate account,
    # treat claim as idempotent success even if resume-parsed email differs.
    if candidate.user_id == user.id:
        return {"message": "Assessment invite linked to your account"}
    if not candidate.email:
        raise HTTPException(status_code=409, detail="Assessment invite has no candidate email to verify")
    if candidate.email.lower() != user.email.lower():
        raise HTTPException(
            status_code=409,
            detail="This assessment invite is linked to a different email address.",
        )
    if candidate.user_id and candidate.user_id != user.id:
        raise HTTPException(
            status_code=409,
            detail="This assessment invite has already been claimed by another account.",
        )
    candidate.user_id = user.id
    await db.commit()
    return {"message": "Assessment invite linked to your account"}


# ─── Internal ownership helper ────────────────────────────────────────────────

async def _assert_quiz_owner(quiz_id: str, user: User, db: AsyncSession) -> Quiz:
    quiz = (await db.execute(select(Quiz).where(Quiz.id == quiz_id))).scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    if user.role not in (UserRole.admin, UserRole.hr):
        raise HTTPException(status_code=403, detail="HR or Admin access required")
    if user.role != UserRole.admin:
        if quiz.job_id is None:
            raise HTTPException(
                status_code=403, detail="Orphaned quizzes can only be accessed by an Admin")
        else:
            jd_check = (await db.execute(
                select(JobDescription).where(
                    JobDescription.id == quiz.job_id,
                    JobDescription.created_by == user.id,
                )
            )).scalar_one_or_none()
            if not jd_check:
                raise HTTPException(status_code=403, detail="You do not have access to this quiz")
    return quiz


@router.post("/generate", response_model=QuizOut, status_code=201)
async def generate_quiz(
    request: Request,
    body: QuizGenerateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    res = await db.execute(select(JobDescription).where(JobDescription.id == body.job_id))
    jd = res.scalar_one_or_none()
    if not jd:
        raise HTTPException(status_code=404, detail="JD not found")

    if user.role != UserRole.admin and jd.created_by != user.id:
        raise HTTPException(
            status_code=403, detail="You do not have permission to generate a quiz for this job")

    all_skills = (jd.must_have_skills or []) + (jd.good_to_have_skills or [])

    if settings.DATABASE_URL.startswith("sqlite"):
        # Local sqlite runtime is prone to long stalls when AI generation fails.
        # Keep quiz generation responsive by using deterministic questions.
        questions_data = _fallback_quiz_questions(
            all_skills,
            settings.QUIZ_EASY_COUNT,
            settings.QUIZ_MEDIUM_COUNT,
            settings.QUIZ_HARD_COUNT,
        )
    else:
        try:
            questions_data = await asyncio.wait_for(
                _run_quiz_generation_with_fallback(
                    request=request,
                    jd_text=jd.raw_text or jd.description or jd.title,
                    skills=all_skills,
                    easy=settings.QUIZ_EASY_COUNT,
                    medium=settings.QUIZ_MEDIUM_COUNT,
                    hard=settings.QUIZ_HARD_COUNT,
                ),
                timeout=_QUIZ_FALLBACK_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            logger.warning("Quiz generation timed out for job_id=%s; using deterministic fallback", jd.id)
            questions_data = []
        except Exception as gen_exc:
            logger.warning("Quiz generation degraded for job_id=%s: %s", jd.id, gen_exc)
            questions_data = []

    if not questions_data:
        questions_data = _fallback_quiz_questions(
            all_skills,
            settings.QUIZ_EASY_COUNT,
            settings.QUIZ_MEDIUM_COUNT,
            settings.QUIZ_HARD_COUNT,
        )
    try:
        questions_data = _prepare_questions_for_persist(
            questions_data,
            expected_easy=settings.QUIZ_EASY_COUNT,
            expected_medium=settings.QUIZ_MEDIUM_COUNT,
            expected_hard=settings.QUIZ_HARD_COUNT,
            fallback_skills=all_skills,
        )
    except QuestionValidationError as validation_error:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid generated quiz questions: {validation_error}",
        ) from validation_error

    quiz = Quiz(
        job_id=jd.id,
        title=body.custom_title or f"{jd.title} - Assessment",
        duration_minutes=body.duration_minutes or settings.QUIZ_DURATION_MINUTES,
    )
    db.add(quiz)
    await db.flush()

    for idx, qdata in enumerate(questions_data):
        q = Question(
            quiz_id=quiz.id,
            question_text=qdata["question_text"],
            options=qdata["options"],
            correct_answer=qdata["correct_answer"],
            difficulty=qdata["difficulty"],
            skill_tag=qdata.get("skill_tag"),
            weight=qdata.get("weight", 1),
            order=idx,
        )
        db.add(q)

    await db.flush()
    if settings.DATABASE_URL.startswith("sqlite"):
        q_count = len(questions_data)
        await log_action(
            db,
            user.id,
            "GENERATE_QUIZ",
            "quiz",
            quiz.id,
            details={"auto_distributed_to": 0, "distribution_skipped": "sqlite"},
        )
        await db.commit()
        await db.refresh(quiz)
        return QuizOut(
            id=quiz.id, job_id=quiz.job_id, title=quiz.title,
            duration_minutes=quiz.duration_minutes, is_active=quiz.is_active,
            question_count=q_count, created_at=quiz.created_at,
        )

    portal_cands_res = await db.execute(
        select(Candidate).where(
            Candidate.job_id == jd.id,
            Candidate.tag.in_([CandidateTag.strong, CandidateTag.medium]),
            Candidate.user_id.isnot(None),
        )
    )
    portal_cands = portal_cands_res.scalars().all()

    # BUG 8 FIX: check for existing quiz attempts to avoid duplicate emails
    if portal_cands:
        existing_attempt_res = await db.execute(
            select(QuizAttempt.candidate_id).where(
                QuizAttempt.quiz_id == quiz.id,
                QuizAttempt.candidate_id.in_([c.id for c in portal_cands]),
            )
        )
        already_assigned = set(existing_attempt_res.scalars().all())
    else:
        already_assigned = set()

    # Collect email tasks to send AFTER commit (BUG 3 FIX)
    email_tasks: list[tuple] = []
    for c in portal_cands:
        if c.id in already_assigned:
            continue  # BUG 8 FIX: skip - already has a token for this quiz
        token = secrets.token_urlsafe(32)
        db.add(QuizAttempt(
            quiz_id=quiz.id,
            candidate_id=c.id,
            token_hash=QuizAttempt.hash_access_token(token),
            token_expires_at=datetime.now(timezone.utc) + timedelta(days=7),  # BUG 7 FIX
        ))
        if c.email:
            # BUG 9 FIX: HTML-escape candidate name to prevent XSS in emails
            safe_name = html.escape(c.name or "Candidate")
            magic_link = f"{settings.FRONTEND_URL}/take-quiz?token={token}"
            email_tasks.append((c.email, safe_name, magic_link))

    await db.flush()
    await log_action(db, user.id, "GENERATE_QUIZ", "quiz", quiz.id,
                     details={"auto_distributed_to": len(portal_cands) - len(already_assigned)})

    q_count = len(questions_data)
    # BUG 3 FIX: commit FIRST - tokens now durable - then send emails
    await db.commit()
    await db.refresh(quiz)

    # Now send emails - tokens guaranteed to exist in DB
    from app.services.email_service import send_email

    # Keep gather limited to SMTP I/O. DB writes happen after gather to avoid
    # concurrent use of one AsyncSession across tasks.
    async def _send_email_safe(cand_email: str, subject: str, html_body: str) -> tuple[str, bool]:
        try:
            await asyncio.wait_for(
                asyncio.to_thread(send_email, cand_email, subject, html_body),
                timeout=_QUIZ_EMAIL_NOTIFY_TIMEOUT_S,
            )
            return cand_email, True
        except Exception as email_err:
            import logging as _log
            from app.services.email_service import _redact_email
            _log.getLogger(__name__).error(
                "Auto-distribute email failed for %s: %s", _redact_email(cand_email), email_err)
            return cand_email, False

    if email_tasks:
        send_payloads: list[tuple[str, str, str]] = []
        safe_quiz_title = html.escape(quiz.title or "Assessment", quote=True)
        for cand_email, safe_name, magic_link in email_tasks:
            subject = f"Action Required: Assessment Invitation for {quiz.title}"
            html_body = f"""
            <div style="font-family:sans-serif; max-width:600px; margin:auto; padding:20px; border:1px solid #ddd; border-radius:8px;">
                <h2 style="color:#2563eb;">Assessment Invitation</h2>
                <p>Hi <b>{safe_name}</b>,</p>
                <p>You have been shortlisted! We'd like to invite you to take a technical assessment for <b>{safe_quiz_title}</b>.</p>
                <p style="margin: 30px 0;">
                    <a href="{magic_link}" style="background-color:#2563eb; color:white; padding:12px 24px; text-decoration:none; border-radius:6px; font-weight:bold;">Start Assessment</a>
                </p>
                <p style="color:#666; font-size:12px;">If the button doesn't work, copy and paste this link:<br>{magic_link}</p>
            </div>
            """
            send_payloads.append((cand_email, subject, html_body))

        send_results = await asyncio.wait_for(
            asyncio.gather(*[
                _send_email_safe(cand_email, subject, html_body)
                for cand_email, subject, html_body in send_payloads
            ]),
            timeout=_QUIZ_EMAIL_NOTIFY_TIMEOUT_S,
        )
        successful_emails = [email for email, ok in send_results if ok]
        if successful_emails:
            try:
                await asyncio.wait_for(
                    push_to_candidates_by_emails(
                        db,
                        successful_emails,
                        title=f"Assessment Invitation: {quiz.title}",
                        message="You've been shortlisted! A technical assessment is waiting for you. Check your email for the secure link.",
                        ntype=NotificationType.quiz_link,
                        related_id=quiz.job_id,
                    ),
                    timeout=_QUIZ_EMAIL_NOTIFY_TIMEOUT_S,
                )
                await db.commit()
            except Exception as notify_err:
                logger.warning("Post-quiz notification fanout failed for quiz_id=%s: %s", quiz.id, notify_err)

    return QuizOut(
        id=quiz.id, job_id=quiz.job_id, title=quiz.title,
        duration_minutes=quiz.duration_minutes, is_active=quiz.is_active,
        question_count=q_count, created_at=quiz.created_at,
    )


@router.post("/from-file", response_model=QuizOut, status_code=201)
async def create_quiz_from_file(
    request: Request,
    job_id: str,
    duration_minutes: int = 30,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    allowed = set(settings.allowed_extensions_list) | {".txt"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Accepted: {', '.join(sorted(allowed))}.",
        )

    res = await db.execute(select(JobDescription).where(JobDescription.id == job_id))
    jd = res.scalar_one_or_none()
    if not jd:
        raise HTTPException(status_code=404, detail="Job not found")
    if user.role != UserRole.admin and jd.created_by != user.id:
        raise HTTPException(
            status_code=403, detail="You do not have permission to add a quiz to this job")

    content_bytes = await file.read()
    doc_text = await file_service.extract_text_from_bytes(file.filename or "quiz.pdf", content_bytes)
    if not doc_text.strip():
        raise HTTPException(
            status_code=422, detail="Could not extract any text from the uploaded file.")

    try:
        questions_data = await _run_quiz_document_parse_with_fallback(doc_text, request)
    except Exception as exc:
        logger.exception("AI parsing failed in create_quiz_from_file")
        raise HTTPException(status_code=500, detail="An internal error occurred.") from exc

    if not questions_data:
        raise HTTPException(status_code=422, detail="No MCQ questions found in the document.")
    try:
        questions_data = _prepare_questions_for_persist(questions_data)
    except QuestionValidationError as validation_error:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid parsed quiz questions: {validation_error}",
        ) from validation_error
    if not questions_data:
        raise HTTPException(status_code=422, detail="No valid MCQ questions found in the uploaded document.")

    fname = os.path.splitext(file.filename or "Quiz")[
        0].replace("_", " ").replace("-", " ").title()
    quiz = Quiz(
        job_id=jd.id,
        title=f"{fname} – {jd.title}",
        duration_minutes=duration_minutes,
    )
    db.add(quiz)
    await db.flush()

    for idx, qdata in enumerate(questions_data):
        db.add(Question(
            quiz_id=quiz.id,
            question_text=qdata["question_text"],
            options=qdata["options"],
            correct_answer=qdata["correct_answer"],
            difficulty=qdata.get("difficulty", "medium"),
            skill_tag=qdata.get("skill_tag"),
            weight=qdata.get("weight", 1),
            order=idx,
        ))

    await db.flush()
    await log_action(db, user.id, "CREATE_QUIZ_FROM_FILE", "quiz", quiz.id,
                     details={"filename": file.filename, "question_count": len(questions_data)})

    q_count = len(questions_data)
    await db.commit()
    # BUG-J FIX: refresh AFTER commit so the object reflects committed state
    await db.refresh(quiz)

    return QuizOut(
        id=quiz.id, job_id=quiz.job_id, title=quiz.title,
        duration_minutes=quiz.duration_minutes, is_active=quiz.is_active,
        question_count=q_count, created_at=quiz.created_at,
    )


@router.get("/", response_model=List[QuizOut])
async def list_quizzes(
    job_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    query = select(Quiz).where(Quiz.is_active == True)
    if job_id:
        query = query.where(Quiz.job_id == job_id)
    if user.role != UserRole.admin:
        owned_res = await db.execute(select(JobDescription.id).where(JobDescription.created_by == user.id))
        owned_job_ids = [r[0] for r in owned_res.all()]
        if not owned_job_ids:
            return []
        query = query.where(Quiz.job_id.in_(owned_job_ids))
    res = await db.execute(query.order_by(Quiz.created_at.desc()))
    quizzes = res.scalars().all()

    if not quizzes:
        return []

    quiz_ids = [qz.id for qz in quizzes]
    qcount_res = await db.execute(
        select(Question.quiz_id, func.count(Question.id))
        .where(Question.quiz_id.in_(quiz_ids))
        .group_by(Question.quiz_id)
    )
    counts = dict(qcount_res.all())

    return [
        QuizOut(
            id=qz.id, job_id=qz.job_id, title=qz.title,
            duration_minutes=qz.duration_minutes, is_active=qz.is_active,
            question_count=counts.get(qz.id, 0),
            created_at=qz.created_at,
        )
        for qz in quizzes
    ]


@router.get("/{quiz_id}/questions", response_model=List[QuestionWithAnswer])
async def get_questions_with_answers(
    quiz_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    await _assert_quiz_owner(quiz_id, user, db)
    res = await db.execute(
        select(Question).where(Question.quiz_id == quiz_id).order_by(Question.order)
    )
    return res.scalars().all()


async def _dispatch_quiz_links_background(
    links_to_send: list[dict],
    quiz_title: str,
    quiz_id: str,
) -> None:
    if not links_to_send:
        return

    from app.services.email_service import send_email, _redact_email

    async def _send_link_safe(link_info: dict) -> tuple[str, str, bool]:
        normalized_email = (link_info.get("email") or "").strip().lower()
        try:
            await asyncio.to_thread(
                send_email,
                link_info["email"],
                link_info["subject"],
                link_info["html_body"],
            )
            return str(link_info["candidate_id"]), normalized_email, True
        except Exception as email_err:
            logger.error(
                "Email send failed for %s: %s",
                _redact_email(link_info.get("email") or ""),
                email_err,
            )
            return str(link_info["candidate_id"]), normalized_email, False

    send_results = await asyncio.gather(*[_send_link_safe(info) for info in links_to_send])
    successful_candidate_ids = [cid for cid, _email, ok in send_results if ok]
    failed_candidate_ids = [cid for cid, _email, ok in send_results if not ok]
    successful_emails = [email for _cid, email, ok in send_results if ok and email]

    async with AsyncSessionLocal() as notif_db:
        try:
            if successful_emails:
                await push_to_candidates_by_emails(
                    notif_db,
                    successful_emails,
                    title=f"Assessment Invitation: {quiz_title}",
                    message="You have been invited to take a technical assessment. Check your email for the secure link.",
                    ntype=NotificationType.quiz_link,
                    related_id=quiz_id,
                )
            await notif_db.commit()
        except Exception as notif_exc:
            await notif_db.rollback()
            logger.warning(
                "Quiz link background notification write failed quiz_id=%s error=%s",
                quiz_id,
                notif_exc,
            )

    logger.info(
        "Quiz link background dispatch summary quiz_id=%s success=%d failed=%d",
        quiz_id,
        len(successful_candidate_ids),
        len(failed_candidate_ids),
    )


@router.post("/send-links")
async def send_quiz_links(
    body: SendQuizLinkRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    quiz = await _assert_quiz_owner(body.quiz_id, user, db)
    candidate_ids = list(dict.fromkeys(body.candidate_ids))
    if not candidate_ids:
        return {"message": "No candidate IDs provided", "links": []}

    cand_res = await db.execute(
        select(Candidate).where(
            Candidate.id.in_(candidate_ids),
            Candidate.job_id == quiz.job_id,
        )
    )
    existing_candidates = {str(c.id): c for c in cand_res.scalars().all()}
    invalid_ids = [cid for cid in candidate_ids if str(cid) not in existing_candidates]
    if invalid_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Candidates {invalid_ids} do not belong to job {quiz.job_id}",
        )

    existing_attempts_res = await db.execute(
        select(QuizAttempt).where(
            QuizAttempt.quiz_id == body.quiz_id,
            QuizAttempt.candidate_id.in_(candidate_ids),
        ).order_by(QuizAttempt.created_at.desc())
    )
    existing_attempt_rows = list(existing_attempts_res.scalars().all())
    existing_attempts: dict[str, list[QuizAttempt]] = {}
    for row in existing_attempt_rows:
        existing_attempts.setdefault(str(row.candidate_id), []).append(row)

    created = 0
    rotated = 0
    links: list[dict[str, Any]] = []
    skipped_links: list[dict[str, Any]] = []
    new_links: list[dict[str, Any]] = []

    for cid in candidate_ids:
        candidate = existing_candidates[str(cid)]
        cand_email = candidate.email or "unknown@email.com"
        cand_name = candidate.name or "Candidate"
        candidate_attempts = existing_attempts.get(str(cid), [])

        raw_token: str | None = None
        link_state = "created"

        if candidate_attempts:
            pending_attempt = next(
                (attempt for attempt in candidate_attempts if attempt.status == QuizStatus.pending),
                None,
            )
            if pending_attempt is None:
                latest = candidate_attempts[0]
                reason = f"attempt_status={latest.status.value}; cannot resend"
                skipped_links.append({"candidate_id": str(cid), "reason": reason})
                links.append(
                    {
                        "name": cand_name,
                        "email": cand_email,
                        "link": None,
                        "reason": reason,
                    }
                )
                continue

            raw_token, token_hash = _new_quiz_token_pair()
            pending_attempt.token_hash = token_hash
            pending_attempt.token_expires_at = datetime.now(timezone.utc) + timedelta(days=7)
            rotated += 1
            link_state = "rotated"
        else:
            raw_token, token_hash = _new_quiz_token_pair()
            new_attempt = QuizAttempt(
                quiz_id=quiz.id,
                candidate_id=cid,
                token_hash=token_hash,
                token_expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            )
            db.add(new_attempt)
            existing_attempts.setdefault(str(cid), []).append(new_attempt)
            created += 1

        magic_link = _build_magic_link(raw_token)
        safe_quiz_title = html.escape(quiz.title or "Assessment", quote=True)
        subject = f"Action Required: Assessment Invitation for {quiz.title}"
        html_body = f"""
        <div style="font-family:sans-serif; max-width:600px; margin:auto; padding:20px; border:1px solid #ddd; border-radius:8px;">
            <h2 style="color:#2563eb;">Assessment Invitation</h2>
            <p>Hi <b>{html.escape(cand_name)}</b>,</p>
            <p>Congratulations! Your resume stood out to our team. We would like to invite you to take a technical assessment for the <b>{safe_quiz_title}</b> position.</p>
            <p style="margin: 30px 0;">
                <a href="{magic_link}" style="background-color:#2563eb; color:white; padding:12px 24px; text-decoration:none; border-radius:6px; font-weight:bold;">Start Secure Assessment</a>
            </p>
            <p style="color:#666; font-size:12px;">If the button doesn't work, copy and paste this link into your browser:<br>{magic_link}</p>
        </div>
        """

        entry = {
            "candidate_id": str(cid),
            "name": cand_name,
            "email": cand_email,
            "link": magic_link,
            "subject": subject,
            "html_body": html_body,
        }
        links.append({"name": cand_name, "email": cand_email, "link": magic_link, "state": link_state})
        new_links.append(entry)

    if new_links:
        names_preview = ", ".join([link["name"] for link in new_links[:3]])
        if len(new_links) > 3:
            names_preview += f" +{len(new_links)-3} more"
        await push_notification(
            db, user.id,
            title=f"Quiz links sent: {quiz.title}",
            message=f"Sent to {len(new_links)} candidate(s): {names_preview}",
            ntype=NotificationType.quiz_link,
            related_id=quiz.id,
        )
    await log_action(
        db,
        user.id,
        "SEND_QUIZ_LINKS",
        "quiz",
        quiz.id,
        details={
            "candidate_count": len(new_links),
            "created_count": created,
            "rotated_count": rotated,
            "skipped_count": len(skipped_links),
        },
    )
    await db.flush()
    logger.info("quiz.generate question_rows_created quiz_id=%s", quiz.id)
    await db.commit()
    if new_links:
        background_tasks.add_task(
            _dispatch_quiz_links_background,
            new_links,
            quiz.title,
            quiz.id,
        )

    return {
        "message": f"Quiz links queued for dispatch to {len(new_links)} candidates",
        "links": links,
        "created_count": created,
        "rotated_count": rotated,
        "skipped": skipped_links,
    }


@router.post("/start", response_model=QuizStartResponse)
async def start_quiz(
    request: Request,
    token: Optional[str] = Query(default=None),
    x_quiz_token: Optional[str] = Header(default=None, alias="X-Quiz-Token"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    # Preferred transport is header (avoids token exposure in URL logs/history).
    # Keep query-param fallback for backward compatibility with existing links.
    resolved_token = _resolve_quiz_token(token, x_quiz_token)

    _use_row_lock = not settings.DATABASE_URL.startswith("sqlite")

    token_hashes = _quiz_token_hash_candidates(resolved_token)

    base_query = (
        select(QuizAttempt)
        .options(selectinload(QuizAttempt.quiz), selectinload(QuizAttempt.candidate))
        .where(QuizAttempt.token_hash.in_(token_hashes))
    )
    if _use_row_lock:
        base_query = base_query.with_for_update()

    res = await db.execute(base_query)
    attempt = res.scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Invalid quiz token")
    if not attempt.candidate or attempt.candidate.user_id != user.id:
        raise HTTPException(status_code=403, detail="This assessment link is not assigned to your account")
    client_ip = request.client.host if request.client else "unknown"
    logger.info("Quiz start attempt=%s client_ip=%s", attempt.id, client_ip)
    # BUG 7 FIX: check token expiry
    # FIX: SQLAlchemy on SQLite strips tzinfo from datetime columns, making
    # attempt.token_expires_at a naive datetime. Comparing it directly to
    # datetime.now(timezone.utc) (aware) raises:
    #   TypeError: can't compare offset-naive and offset-aware datetimes
    # Apply the same .replace(tzinfo=timezone.utc) fallback used in submit_quiz.
    if attempt.token_expires_at:
        expires_utc = (
            attempt.token_expires_at
            if attempt.token_expires_at.tzinfo is not None
            else attempt.token_expires_at.replace(tzinfo=timezone.utc)
        )
        if datetime.now(timezone.utc) > expires_utc:
            raise HTTPException(status_code=410, detail="This quiz invitation has expired")
    if attempt.status == QuizStatus.submitted:
        raise HTTPException(status_code=400, detail="Quiz already submitted")
    if attempt.status == QuizStatus.timed_out:
        raise HTTPException(status_code=400, detail="Quiz time expired")

    response_questions: list[dict[str, Any]] = []
    if attempt.status == QuizStatus.pending:
        attempt.status = QuizStatus.in_progress
        attempt.started_at = datetime.now(timezone.utc)
        qres = await db.execute(
            select(Question).where(Question.quiz_id == attempt.quiz_id)
        )
        questions = list(qres.scalars().all())
        random.shuffle(questions)
        attempt.question_order = [str(q.id) for q in questions]
        snapshot: list[dict[str, Any]] = []
        for question in questions:
            difficulty = question.difficulty.value if hasattr(question.difficulty, "value") else str(question.difficulty)
            entry = {
                "id": str(question.id),
                "text": question.question_text,
                "options": list(question.options or []),
                "correct_answer": int(question.correct_answer),
                "weight": int(question.weight or 1),
                "difficulty": difficulty,
                "skill_tag": question.skill_tag,
            }
            snapshot.append(entry)
            response_questions.append(
                {
                    "id": str(question.id),
                    "question_text": question.question_text,
                    "options": list(question.options or []),
                    "difficulty": difficulty,
                    "skill_tag": question.skill_tag,
                    "weight": int(question.weight or 1),
                }
            )
        attempt.question_snapshot = snapshot
    else:
        if isinstance(attempt.question_snapshot, list) and attempt.question_snapshot:
            for item in attempt.question_snapshot:
                if not isinstance(item, dict):
                    continue
                response_questions.append(
                    {
                        "id": str(item.get("id")),
                        "question_text": item.get("text") or "",
                        "options": list(item.get("options") or []),
                        "difficulty": item.get("difficulty") or "medium",
                        "skill_tag": item.get("skill_tag"),
                        "weight": int(item.get("weight") or 1),
                    }
                )
            if not attempt.question_order:
                attempt.question_order = [str(item.get("id")) for item in attempt.question_snapshot if isinstance(item, dict)]
        else:
            qres = await db.execute(
                select(Question).where(Question.quiz_id == attempt.quiz_id)
            )
            all_questions = {str(q.id): q for q in qres.scalars().all()}
            if attempt.question_order:
                ordered_questions = [all_questions[qid] for qid in attempt.question_order if qid in all_questions]
                dropped = len(attempt.question_order) - len(ordered_questions)
                if dropped > 0:
                    logger.warning(
                        "Quiz resume: %d question(s) dropped for attempt %s (quiz was edited mid-attempt)",
                        dropped,
                        attempt.id,
                    )
                for question in ordered_questions:
                    difficulty = question.difficulty.value if hasattr(question.difficulty, "value") else str(question.difficulty)
                    response_questions.append(
                        {
                            "id": str(question.id),
                            "question_text": question.question_text,
                            "options": list(question.options or []),
                            "difficulty": difficulty,
                            "skill_tag": question.skill_tag,
                            "weight": int(question.weight or 1),
                        }
                    )
            else:
                for question in all_questions.values():
                    difficulty = question.difficulty.value if hasattr(question.difficulty, "value") else str(question.difficulty)
                    response_questions.append(
                        {
                            "id": str(question.id),
                            "question_text": question.question_text,
                            "options": list(question.options or []),
                            "difficulty": difficulty,
                            "skill_tag": question.skill_tag,
                            "weight": int(question.weight or 1),
                        }
                    )

    await db.flush()
    await db.commit()

    total_seconds = attempt.quiz.duration_minutes * 60
    started_at_utc = (
        attempt.started_at
        if attempt.started_at.tzinfo is not None
        else attempt.started_at.replace(tzinfo=timezone.utc)
    )
    elapsed = int((datetime.now(timezone.utc) - started_at_utc).total_seconds())
    remaining = max(0, min(total_seconds, total_seconds - elapsed))

    return QuizStartResponse(
        attempt_id=attempt.id,
        quiz_id=attempt.quiz_id,
        duration_minutes=attempt.quiz.duration_minutes,
        time_remaining_seconds=remaining,
        started_at=attempt.started_at,
        questions=[
            QuestionOut(
                id=q["id"],
                question_text=q["question_text"],
                options=q["options"],
                difficulty=q["difficulty"],
                skill_tag=q.get("skill_tag"),
                weight=q["weight"],
            )
            for q in response_questions
        ],
    )


@router.post("/submit", response_model=QuizResultOut)
async def submit_quiz(
    body: SubmitAnswersRequest,
    request: Request,
    token: Optional[str] = Query(default=None),
    x_quiz_token: Optional[str] = Header(default=None, alias="X-Quiz-Token"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    resolved_token = _resolve_quiz_token(token, x_quiz_token, missing_status=401)
    token_hashes = _quiz_token_hash_candidates(resolved_token)

    # BUG 2 FIX: original fetch had no row lock. Two simultaneous submits
    # (mobile retry, double-tap) could both pass the finalization guard and
    # write two score rows + fire two email notifications. Mirror the
    # with_for_update() pattern already used in start_quiz.
    _use_row_lock = not settings.DATABASE_URL.startswith("sqlite")
    filters = [QuizAttempt.id == body.attempt_id]
    _base_query = (
        select(QuizAttempt)
        .options(selectinload(QuizAttempt.quiz), selectinload(QuizAttempt.candidate))
        .where(*filters)
    )
    if _use_row_lock:
        _base_query = _base_query.with_for_update()
    attempt = (await db.execute(_base_query)).scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    if attempt.token_hash not in token_hashes:
        raise HTTPException(status_code=403, detail="Invalid quiz token for this attempt")
    if not attempt.candidate or attempt.candidate.user_id != user.id:
        raise HTTPException(status_code=403, detail="This assessment link is not assigned to your account")
    if attempt.token_expires_at:
        expires_utc = (
            attempt.token_expires_at
            if attempt.token_expires_at.tzinfo is not None
            else attempt.token_expires_at.replace(tzinfo=timezone.utc)
        )
        if datetime.now(timezone.utc) > expires_utc:
            raise HTTPException(status_code=403, detail="Quiz invitation has expired")
    client_ip = request.client.host if request.client else "unknown"
    logger.info("Quiz submit attempt=%s client_ip=%s", attempt.id, client_ip)
    if attempt.status in (QuizStatus.submitted, QuizStatus.timed_out):
        raise HTTPException(status_code=400, detail="Quiz already finalized")

    if not attempt.started_at:
        raise HTTPException(status_code=400, detail="Quiz not started")

    started_utc = (
        attempt.started_at
        if attempt.started_at.tzinfo is not None
        else attempt.started_at.replace(tzinfo=timezone.utc)
    )
    elapsed = (
        datetime.now(timezone.utc) - started_utc
    ).total_seconds() / 60
    if elapsed > attempt.quiz.duration_minutes + 1:
        attempt.status = QuizStatus.timed_out
        attempt.submitted_at = datetime.now(timezone.utc)
        await db.commit()
        raise HTTPException(status_code=400, detail="Quiz time has expired")

    questions: list[dict[str, Any]] = []
    if isinstance(attempt.question_snapshot, list) and attempt.question_snapshot:
        for item in attempt.question_snapshot:
            if not isinstance(item, dict):
                continue
            questions.append(
                {
                    "id": str(item.get("id")) if item.get("id") is not None else None,
                    "correct_answer": item.get("correct_answer"),
                    "difficulty": item.get("difficulty"),
                    "skill_tag": item.get("skill_tag"),
                    "weight": item.get("weight"),
                    "options": item.get("options"),
                }
            )
    else:
        logger.warning("Scoring attempt %s without question snapshot (legacy fallback)", attempt.id)
        qres = await db.execute(select(Question).where(Question.quiz_id == attempt.quiz_id))
        db_questions = qres.scalars().all()
        questions = [
            {
                "id": str(q.id),
                "correct_answer": q.correct_answer,
                "difficulty": q.difficulty.value if hasattr(q.difficulty, "value") else str(q.difficulty),
                "skill_tag": q.skill_tag,
                "weight": q.weight,
                "options": q.options,
            }
            for q in db_questions
        ]

    def _resolved_weight(question: dict[str, Any]) -> int:
        raw_weight = question.get("weight")
        try:
            weight = int(raw_weight) if raw_weight is not None else None
        except (TypeError, ValueError):
            weight = None
        if not weight:
            diff_key = str(question.get("difficulty") or "medium").strip().lower()
            weight = scoring_service.WEIGHT_MAP.get(diff_key, 1)
        return max(1, int(weight))

    dynamic_max_score = sum(_resolved_weight(question) for question in questions)
    raw_score, skill_bd, diff_bd = scoring_service.compute_quiz_score(questions, body.answers)

    # FIX: preserve the Practical Coding entry written by /evaluate-code.
    # compute_quiz_score only knows about MCQ questions and returns a fresh
    # skill_bd dict — it has no knowledge of the coding challenge score.
    # Without this guard, submitting the quiz permanently wipes the coding
    # score and it is never reflected in raw_score or max_score.
    prior_breakdown = attempt.skill_breakdown or {}
    coding_entry = prior_breakdown.get("Practical Coding")
    if coding_entry:
        skill_bd["Practical Coding"] = coding_entry
        coding_pts = coding_entry.get("score", 0)
        coding_max = coding_entry.get("max", 10)
        raw_score = round(raw_score + coding_pts, 2)
        dynamic_max_score += coding_max

    attempt.answers = body.answers
    attempt.raw_score = raw_score
    attempt.max_score = dynamic_max_score
    attempt.skill_breakdown = skill_bd
    attempt.difficulty_breakdown = diff_bd
    # Server-side tab switch count is updated via a dedicated endpoint.
    attempt.tab_switches = int(attempt.tab_switches or 0)
    attempt.status = QuizStatus.submitted
    attempt.submitted_at = datetime.now(timezone.utc)

    candidate = attempt.candidate
    # FIX Finding 33: Store raw score instead of percentage to prevent data corruption.
    # The frontend and export reports expect the raw points scored to calculate their own formats.
    candidate.quiz_score = raw_score
    candidate.quiz_max = float(dynamic_max_score) if dynamic_max_score is not None else None
    candidate.quiz_pct = round((raw_score / dynamic_max_score) * 100, 1) if dynamic_max_score and dynamic_max_score > 0 else 0.0
    jd_res = await db.execute(
        select(JobDescription).where(JobDescription.id == candidate.job_id)
    )
    jd = jd_res.scalar_one_or_none()
    if jd:
        candidate.final_score = scoring_service.compute_final_score(
            candidate.resume_score, raw_score, dynamic_max_score, jd.resume_weight, jd.quiz_weight
        )
        candidate.passed = candidate.final_score >= jd.pass_threshold

    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.exception("Failed to save quiz result")
        raise HTTPException(status_code=500, detail="An internal error occurred.") from exc

    if jd:
        from app.routers.resumes import _recompute_job_rank_and_tags
        await _recompute_job_rank_and_tags(db, jd)
        await db.commit()


    try:
        if candidate.email:
            pct = round((raw_score / dynamic_max_score) * 100, 2) if dynamic_max_score else 0.0
            if candidate.passed is True:
                await push_to_candidate_by_email(
                    db, candidate.email,
                    title=f"Assessment submitted — result under review",
                    message=(
                        f"You scored {pct:.0f}% on '{attempt.quiz.title}'. "
                        f"Congratulations! Your score meets the minimum requirement. "
                        f"Your result has been recorded and the hiring team will review it shortly."
                    ),
                    ntype=NotificationType.quiz_result,
                    related_id=candidate.job_id,
                )
            elif candidate.passed is False:
                await push_to_candidate_by_email(
                    db, candidate.email,
                    title=f"Assessment submitted — result under review",
                    message=(
                        f"You scored {pct:.0f}% on '{attempt.quiz.title}'. "
                        f"Unfortunately, this does not meet our minimum threshold for this position. "
                        f"However, we will keep your profile on file for future opportunities."
                    ),
                    ntype=NotificationType.quiz_result,
                    related_id=candidate.job_id,
                )
            else:
                await push_to_candidate_by_email(
                    db, candidate.email,
                    title=f"Assessment submitted — result under review",
                    message=(
                        f"You scored {raw_score}/{dynamic_max_score} on '{attempt.quiz.title}'. "
                        f"Your result has been recorded and the hiring team will be in touch shortly."
                    ),
                    ntype=NotificationType.quiz_result,
                    related_id=candidate.job_id,
                )

        if jd and jd.created_by:
            await push_notification(
                db, jd.created_by,
                # FIX Finding 25: html.escape candidate name in notification to prevent XSS
                title=f"Quiz submitted: {html.escape(candidate.name or candidate.email or 'Candidate')}",
                message=f"Score: {raw_score}/{dynamic_max_score} ({round((raw_score/dynamic_max_score)*100) if dynamic_max_score else 0}%) — {'Passed ✅' if candidate.passed else 'Failed ❌' if candidate.passed is False else 'Pending'}",
                ntype=NotificationType.quiz_result,
                related_id=candidate.id,
            )

        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Non-fatal: quiz submission notifications failed for attempt %s", attempt.id)

    # FIX: return the actual computed passed value instead of hardcoded None.
    # candidate.passed was correctly computed above (when jd exists); returning
    # None here was hiding the result from the candidate immediately after submit.
    return QuizResultOut(
        attempt_id=attempt.id, candidate_id=attempt.candidate_id, status=attempt.status,
        raw_score=raw_score, max_score=dynamic_max_score,
        percentage=round((raw_score / dynamic_max_score) * 100, 2) if dynamic_max_score else 0.0,
        skill_breakdown=skill_bd, difficulty_breakdown=diff_bd,
        passed=candidate.passed,  # FIX: was hardcoded None
    )


@router.get("/{quiz_id}/results", response_model=List[QuizResultOut])
async def get_quiz_results(
    quiz_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    await _assert_quiz_owner(quiz_id, user, db)
    res = await db.execute(
        select(QuizAttempt)
        .options(selectinload(QuizAttempt.candidate))
        .where(QuizAttempt.quiz_id == quiz_id)
    )
    attempts = res.scalars().all()

    return [
        QuizResultOut(
            attempt_id=a.id, candidate_id=a.candidate_id, status=a.status,
            raw_score=a.raw_score or 0, max_score=a.max_score or 0,
            # FIX Finding 31: Guard against None raw_score / max_score to prevent TypeError
            percentage=round((a.raw_score / a.max_score) * 100, 2) if a.max_score and a.raw_score is not None else 0,
            skill_breakdown=a.skill_breakdown, difficulty_breakdown=a.difficulty_breakdown,
            passed=a.candidate.passed if a.candidate else None,
        )
        for a in attempts
    ]


@router.get("/{quiz_id}/answer-sheet", response_model=QuizMasterAnswerSheetOut)
async def get_quiz_master_answer_sheet(
    quiz_id: str,
    passed_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    quiz = await _assert_quiz_owner(quiz_id, user, db)

    qres = await db.execute(
        select(Question)
        .where(Question.quiz_id == quiz_id)
        .order_by(Question.order.asc(), Question.id.asc())
    )
    questions = qres.scalars().all()

    ares = await db.execute(
        select(QuizAttempt)
        .options(selectinload(QuizAttempt.candidate))
        .where(QuizAttempt.quiz_id == quiz_id)
        .order_by(QuizAttempt.created_at.desc())
    )
    attempts = ares.scalars().all()

    candidate_rows: List[CandidateAnswerSheetOut] = []
    for attempt in attempts:
        candidate = attempt.candidate
        if not candidate:
            continue
        if passed_only and candidate.passed is not True:
            continue

        answers_obj = attempt.answers if isinstance(attempt.answers, dict) else {}
        answer_items: List[QuizAnswerItemOut] = []

        if isinstance(attempt.question_snapshot, list) and attempt.question_snapshot:
            question_rows = [
                {
                    "id": str(item.get("id")),
                    "question_text": item.get("text") or "",
                    "options": list(item.get("options") or []),
                    "correct_answer": item.get("correct_answer"),
                    "difficulty": item.get("difficulty"),
                    "skill_tag": item.get("skill_tag"),
                    "weight": item.get("weight"),
                }
                for item in attempt.question_snapshot
                if isinstance(item, dict)
            ]
        else:
            question_rows = [
                {
                    "id": str(question.id),
                    "question_text": question.question_text,
                    "options": list(question.options or []),
                    "correct_answer": question.correct_answer,
                    "difficulty": question.difficulty.value if hasattr(question.difficulty, "value") else str(question.difficulty),
                    "skill_tag": question.skill_tag,
                    "weight": question.weight,
                }
                for question in questions
            ]

        for question in question_rows:
            options = question.get("options") or []
            answer_key = str(question.get("id"))
            selected_raw: Any = answers_obj.get(answer_key)

            selected_index: Optional[int] = None
            if isinstance(selected_raw, int):
                selected_index = selected_raw
            elif isinstance(selected_raw, str) and selected_raw.isdigit():
                selected_index = int(selected_raw)

            if selected_index is not None and (selected_index < 0 or selected_index >= len(options)):
                selected_index = None

            correct_answer = question.get("correct_answer")
            correct_index = correct_answer if isinstance(correct_answer, int) and 0 <= correct_answer < len(options) else None
            selected_text = options[selected_index] if selected_index is not None else None
            correct_text = options[correct_index] if correct_index is not None else None
            is_correct = (
                selected_index == correct_index
                if selected_index is not None and correct_index is not None
                else None
            )

            answer_items.append(
                QuizAnswerItemOut(
                    question_id=str(question.get("id")),
                    question_type="mcq",
                    question_text=question.get("question_text") or "",
                    skill_tag=question.get("skill_tag"),
                    difficulty=question.get("difficulty"),
                    selected_answer=selected_raw,
                    selected_option_index=selected_index,
                    selected_option_text=selected_text,
                    correct_option_index=correct_index,
                    correct_option_text=correct_text,
                    is_correct=is_correct,
                    score_awarded=float(question.get("weight") or 1) if is_correct is True else (0.0 if selected_index is not None else None),
                    max_score=float(question.get("weight") or 1),
                )
            )

        coding_payload = answers_obj.get("coding_challenge")
        if isinstance(coding_payload, dict):
            skill_breakdown = attempt.skill_breakdown if isinstance(attempt.skill_breakdown, dict) else {}
            coding_breakdown = (
                skill_breakdown.get("Practical Coding", {})
                if isinstance(skill_breakdown.get("Practical Coding", {}), dict)
                else {}
            )
            answer_items.append(
                QuizAnswerItemOut(
                    question_id="coding_challenge",
                    question_type="coding",
                    question_text="Practical Coding Challenge",
                    skill_tag="Practical Coding",
                    difficulty=None,
                    selected_answer=coding_payload,
                    selected_option_index=None,
                    selected_option_text=None,
                    correct_option_index=None,
                    correct_option_text=None,
                    is_correct=None,
                    score_awarded=float(coding_breakdown.get("score", coding_payload.get("score", 0)) or 0),
                    max_score=float(coding_breakdown.get("max", 10) or 10),
                )
            )

        percentage = (
            round((attempt.raw_score / attempt.max_score) * 100, 2)
            if attempt.max_score and attempt.raw_score is not None
            else 0.0
        )

        candidate_rows.append(
            CandidateAnswerSheetOut(
                attempt_id=attempt.id,
                candidate_id=attempt.candidate_id,
                candidate_name=candidate.name,
                candidate_email=candidate.email,
                status=attempt.status,
                raw_score=float(attempt.raw_score or 0.0),
                max_score=float(attempt.max_score or 0.0),
                percentage=percentage,
                passed=candidate.passed,
                submitted_at=attempt.submitted_at,
                answers=answer_items,
            )
        )

    return QuizMasterAnswerSheetOut(
        quiz_id=quiz.id,
        quiz_title=quiz.title,
        generated_at=datetime.now(timezone.utc),
        passed_only=passed_only,
        total_candidates=len(candidate_rows),
        candidates=candidate_rows,
    )


class CodeSubmitRequest(BaseModel):
    attempt_id: str
    problem: str
    code: str
    language: str


@router.post("/attempt/{attempt_id}/tab-switch")
@limiter.limit("120/minute")
async def record_tab_switch(
    request: Request,
    attempt_id: str,
    token: Optional[str] = Query(default=None),
    x_quiz_token: Optional[str] = Header(default=None, alias="X-Quiz-Token"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    resolved_token = _resolve_quiz_token(token, x_quiz_token, missing_status=401)
    token_hashes = _quiz_token_hash_candidates(resolved_token)
    _use_row_lock = not settings.DATABASE_URL.startswith("sqlite")

    attempt_query = (
        select(QuizAttempt)
        .options(selectinload(QuizAttempt.candidate))
        .where(QuizAttempt.id == attempt_id)
    )
    if _use_row_lock:
        attempt_query = attempt_query.with_for_update()
    attempt = (await db.execute(attempt_query)).scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    if attempt.token_hash not in token_hashes:
        raise HTTPException(status_code=403, detail="Invalid quiz token for this attempt")
    if not attempt.candidate or attempt.candidate.user_id != user.id:
        raise HTTPException(status_code=403, detail="This assessment link is not assigned to your account")
    if attempt.status != QuizStatus.in_progress:
        raise HTTPException(status_code=403, detail="Tab switch tracking requires an active quiz attempt")

    await db.execute(
        update(QuizAttempt)
        .where(QuizAttempt.id == attempt.id)
        .values(tab_switches=func.coalesce(QuizAttempt.tab_switches, 0) + 1)
    )
    await db.commit()
    tab_switch_count = (await db.execute(
        select(QuizAttempt.tab_switches).where(QuizAttempt.id == attempt.id)
    )).scalar_one()
    return {"attempt_id": attempt.id, "tab_switches": int(tab_switch_count or 0)}


@router.post("/evaluate-code")
@limiter.limit("10/minute")
async def evaluate_code_endpoint(
    request: Request,
    body: CodeSubmitRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_candidate),
):
    _use_row_lock = not settings.DATABASE_URL.startswith("sqlite")
    attempt_query = (
        select(QuizAttempt)
        .options(selectinload(QuizAttempt.candidate), selectinload(QuizAttempt.quiz))
        .where(QuizAttempt.id == body.attempt_id)
    )
    if _use_row_lock:
        attempt_query = attempt_query.with_for_update()

    attempt = (await db.execute(attempt_query)).scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    if not attempt.candidate or attempt.candidate.user_id != user.id:
        raise HTTPException(
            status_code=403, detail="You are not authorized to submit code for this attempt")
    if attempt.status != QuizStatus.in_progress:
        raise HTTPException(
            status_code=403, detail="Code evaluation requires an active quiz attempt")
    if not attempt.started_at:
        raise HTTPException(status_code=403, detail="Quiz not started")

    started_utc = (
        attempt.started_at
        if attempt.started_at.tzinfo is not None
        else attempt.started_at.replace(tzinfo=timezone.utc)
    )
    elapsed_seconds = (datetime.now(timezone.utc) - started_utc).total_seconds()
    duration_seconds = (attempt.quiz.duration_minutes if attempt.quiz else 0) * 60
    if elapsed_seconds > duration_seconds + CODE_EVAL_GRACE_SECONDS:
        raise HTTPException(
            status_code=403, detail="Quiz time window has expired")
    if int(attempt.code_eval_count or 0) >= MAX_CODE_EVALS:
        raise HTTPException(
            status_code=429,
            detail=f"Maximum code evaluations ({MAX_CODE_EVALS}) reached for this attempt",
        )

    # BUG-18 FIX: Enforce a time limit on code evaluation to prevent
    # infinite loops or excessively slow LLM responses from hanging the request.
    try:
        result = await _run_code_eval_with_fallback(
            request=request,
            problem=body.problem,
            code=body.code,
            language=body.language,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="Code evaluation timed out (60s limit)")

    current_answers = attempt.answers.copy() if attempt.answers else {}
    current_answers["coding_challenge"] = result
    attempt.answers = current_answers

    current_skills = attempt.skill_breakdown.copy() if attempt.skill_breakdown else {}
    coding_score = result.get("score", 0)
    current_skills["Practical Coding"] = {
        "score": coding_score,
        "max": 10,
        "pct": round(coding_score * 10, 2),
    }
    attempt.skill_breakdown = current_skills
    attempt.code_eval_count = int(attempt.code_eval_count or 0) + 1

    # BUG #7 FIX (HIGH): Wrap commit in try/except with rollback. Previously,
    # a commit failure silently lost the coding score while the client received
    # a success response — the candidate's "score saved" UI was a lie.
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.exception("Failed to save code evaluation result")
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred.",
        )
    return result
