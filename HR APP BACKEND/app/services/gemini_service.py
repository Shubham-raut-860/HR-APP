"""
Azure OpenAI service — ALL AI calls go through here.

FIX LOG:
  BUG-B  _clamp() scale-rescale guard `0 < v <= 10 and v != int(v)` failed
         for LLM returning 10.0 (perfect score on 0-10 scale): `v != int(v)`
         evaluates False for 10.0, so 10.0 was treated as integer 10 not 100.
         Fix: guard changed to `0 < v <= 10` — any value in the 0-10 range
         (including whole numbers like 8, 9, 10) triggers the rescale.
         Exception: 0 and values > 10 are already on the 0-100 scale.

NEW FEATURES:
  - enhance_resume()          AI rewrites/improves a resume against a JD
  - build_resume_from_form()  Generates a structured resume from form data
  - generate_cover_letter()   Generates a personalised cover letter for a JD
  - analyze_career_path()     AI career gap & upskilling analysis
"""
from __future__ import annotations
from openai import AsyncAzureOpenAI

import asyncio
import functools
import json
import time
import logging
import threading

from app.config import settings
from app.services.token_monitor_service import get_token_monitor

logger = logging.getLogger(__name__)
_token_monitor = get_token_monitor()


class ModelOutputParseError(ValueError):
    """Raised when model output is malformed JSON in strict mode."""


# ─── MLflow Tracing wrapper for @observe ─────────────────────────────────────

def observe(*args, **kwargs):   # type: ignore[misc]
    """Decorator that delegates to mlflow.trace() for GenAI observability."""
    from app.services.mlflow_service import _mlflow_available

    def _noop_decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*a, **kw):
            return await fn(*a, **kw)
        return wrapper

    if not _mlflow_available:
        if args and callable(args[0]):
            return _noop_decorator(args[0])
        return _noop_decorator

    import mlflow
    name_arg = kwargs.pop('name', None)
    span_type = kwargs.pop('as_type', "UNKNOWN")

    def decorator(fn):
        trace_name = name_arg or fn.__name__
        return mlflow.trace(name=trace_name, span_type=span_type)(fn)

    if args and callable(args[0]):
        return decorator(args[0])
    return decorator


def _build_prompt(prompt_name: str, fallback_template: str, **kwargs) -> str:
    return fallback_template.format(**kwargs)


# ─── Plain OpenAI client ──────────────────────────────────────────────────────

# BUG-9 FIX: module-level logger.info fires before logging.basicConfig / any handler
# is attached (Python's lastResort only shows WARNING+). The info line was silently
# swallowed in production. Downgraded to debug — it's a startup trace, not a warning.
logger.debug("Plain openai client active - LLM calls traced via MLflow.")

_ENDPOINT = settings.AZURE_OPENAI_ENDPOINT.rstrip("/").removesuffix("/openai/v1")
_CHAT_DEPLOYMENT = settings.AZURE_CHAT_DEPLOYMENT
_EMBED_DEPLOYMENT = settings.AZURE_EMBEDDING_DEPLOYMENT

openai_client: AsyncAzureOpenAI | None = (
    AsyncAzureOpenAI(
        azure_endpoint=_ENDPOINT,
        api_key=settings.AZURE_OPENAI_API_KEY,
        api_version=settings.AZURE_OPENAI_API_VERSION,
    )
    if settings.AZURE_OPENAI_API_KEY else None
)

_AI_TRANSIENT_STATUS_CODES = {
    int(code.strip())
    for code in (settings.AI_TRANSIENT_STATUS_CODES or "").split(",")
    if code.strip().isdigit()
}
_AI_CIRCUIT_OPEN_UNTIL: float = 0.0
_AI_CONSECUTIVE_TRANSIENT_FAILURES: int = 0
_AI_CIRCUIT_LOCK = threading.Lock()
_DETERMINISTIC_SCORING_TASKS = {"score_resume", "evaluate_code"}
_MODEL_OUTPUT_PARSE_FAILURES = 0
_MISSING_DEPLOYMENTS: set[str] = set()
_MISSING_DEPLOYMENTS_LOCK = threading.Lock()
_PROBING_DEPLOYMENTS: set[str] = set()


def _increment_parse_failure_metric(task_name: str) -> None:
    global _MODEL_OUTPUT_PARSE_FAILURES
    _MODEL_OUTPUT_PARSE_FAILURES += 1
    logger.warning(
        "[Azure OpenAI] task=%s parse_failures_total=%d",
        task_name,
        _MODEL_OUTPUT_PARSE_FAILURES,
    )


def _parse_failure_fallback(task_name: str) -> dict[str, object] | None:
    if task_name != "score_resume":
        return None
    return {
        "skill_score": 0,
        "experience_score": 0,
        "project_score": 0,
        "matched_must_have": None,
        "missing_must_have": None,
        "matched_good_to_have": None,
        "missing_good_to_have": None,
        "reasoning": None,
        "domain_fit": None,
        "seniority_match": None,
        "red_flags": None,
        "standout_factors": None,
        "hire_recommendation": None,
        "confidence": None,
        "parse_failed": True,
    }


def _status_code_from_exception(exc: Exception) -> int | None:
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    resp = getattr(exc, "response", None)
    resp_code = getattr(resp, "status_code", None)
    if isinstance(resp_code, int):
        return resp_code
    body = str(exc).lower()
    for candidate in _AI_TRANSIENT_STATUS_CODES:
        if f"{candidate}" in body:
            return candidate
    return None


def _is_transient_ai_error(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    if "timeout" in name or "connection" in name:
        return True
    status = _status_code_from_exception(exc)
    if status is not None:
        return status in _AI_TRANSIENT_STATUS_CODES
    text = str(exc).lower()
    transient_tokens = (
        "timed out",
        "timeout",
        "connection",
        "rate limit",
        "service unavailable",
        "server error",
        "temporarily unavailable",
    )
    return any(token in text for token in transient_tokens)


def _is_deployment_not_found_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return ("deploymentnotfound" in text) or ("api deployment for this resource does not exist" in text)


def _circuit_remaining_seconds() -> float:
    with _AI_CIRCUIT_LOCK:
        remaining = _AI_CIRCUIT_OPEN_UNTIL - time.monotonic()
    return remaining if remaining > 0 else 0.0


def _is_circuit_open() -> bool:
    return _circuit_remaining_seconds() > 0


def _mark_ai_success() -> None:
    global _AI_CONSECUTIVE_TRANSIENT_FAILURES, _AI_CIRCUIT_OPEN_UNTIL
    with _AI_CIRCUIT_LOCK:
        _AI_CONSECUTIVE_TRANSIENT_FAILURES = 0
        _AI_CIRCUIT_OPEN_UNTIL = 0.0


def _mark_ai_failure(exc: Exception) -> None:
    global _AI_CONSECUTIVE_TRANSIENT_FAILURES, _AI_CIRCUIT_OPEN_UNTIL
    if not _is_transient_ai_error(exc):
        return
    with _AI_CIRCUIT_LOCK:
        _AI_CONSECUTIVE_TRANSIENT_FAILURES += 1
        threshold = max(1, int(settings.AI_CIRCUIT_BREAKER_FAILURE_THRESHOLD))
        if _AI_CONSECUTIVE_TRANSIENT_FAILURES >= threshold:
            _AI_CIRCUIT_OPEN_UNTIL = time.monotonic() + max(1, int(settings.AI_CIRCUIT_BREAKER_SECONDS))
            logger.warning(
                "[Azure OpenAI] Circuit opened for %ss after %d transient failures",
                int(settings.AI_CIRCUIT_BREAKER_SECONDS),
                _AI_CONSECUTIVE_TRANSIENT_FAILURES,
            )


def is_realtime_ai_available() -> bool:
    if not openai_client:
        return False
    if not settings.AI_FAIL_FAST_ON_UNAVAILABLE:
        return True
    return not _is_circuit_open()


def ai_runtime_status() -> dict[str, object]:
    with _AI_CIRCUIT_LOCK:
        transient_failures = _AI_CONSECUTIVE_TRANSIENT_FAILURES
    return {
        "configured": bool(openai_client),
        "available": is_realtime_ai_available(),
        "circuit_open": _is_circuit_open(),
        "circuit_remaining_seconds": round(_circuit_remaining_seconds(), 2),
        "transient_failures": transient_failures,
    }


# ─── Core LLM helper ──────────────────────────────────────────────────────────

async def _generate_json(
    prompt: str,
    task_name: str = "azure_generation",
    max_tokens: int = 1200,
    model: str | None = None,
) -> dict | list:
    if not openai_client:
        raise ValueError("AZURE_OPENAI_API_KEY is not configured in .env")
    if settings.AI_FAIL_FAST_ON_UNAVAILABLE and _is_circuit_open():
        wait_s = round(_circuit_remaining_seconds(), 2)
        raise RuntimeError(f"AI service temporarily unavailable (circuit open for {wait_s}s)")

    max_retries = max(1, int(settings.AI_RETRY_MAX_ATTEMPTS))
    timeout_s = max(1.0, float(settings.AI_REQUEST_TIMEOUT_SECONDS))
    start = time.perf_counter()
    deployment = (model or settings.agent_model_map.get(task_name) or _CHAT_DEPLOYMENT).strip()
    requested_deployment = deployment
    chat_fallback_attempted = False
    owns_probe_slot = False

    if deployment != _CHAT_DEPLOYMENT:
        with _MISSING_DEPLOYMENTS_LOCK:
            if deployment in _MISSING_DEPLOYMENTS and _CHAT_DEPLOYMENT:
                logger.debug(
                    "[Azure OpenAI] task=%s deployment=%s previously marked missing; using chat deployment=%s",
                    task_name, deployment, _CHAT_DEPLOYMENT
                )
                deployment = _CHAT_DEPLOYMENT
                chat_fallback_attempted = True
            elif deployment in _PROBING_DEPLOYMENTS and _CHAT_DEPLOYMENT:
                # Avoid thundering herd during bulk uploads: while one request is
                # probing a deployment, concurrent requests immediately use chat.
                logger.debug(
                    "[Azure OpenAI] task=%s deployment=%s currently probing; using chat deployment=%s",
                    task_name, deployment, _CHAT_DEPLOYMENT
                )
                deployment = _CHAT_DEPLOYMENT
                chat_fallback_attempted = True
            else:
                _PROBING_DEPLOYMENTS.add(deployment)
                owns_probe_slot = True

    for attempt in range(max_retries):
        try:
            completion_kwargs: dict[str, object] = {}
            if task_name in _DETERMINISTIC_SCORING_TASKS:
                # Deterministic params required for scoring reproducibility.
                completion_kwargs = {"temperature": 0, "top_p": 1, "seed": 42}
            response = await asyncio.wait_for(
                openai_client.chat.completions.create(
                    model=deployment,
                    max_completion_tokens=max_tokens,
                    response_format={"type": "json_object"},
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a strict data extraction AI. Return ONLY valid raw JSON - no markdown fences, no explanation."
                        },
                        {"role": "user", "content": prompt},
                    ],
                    **completion_kwargs,
                ),
                timeout=timeout_s,
            )

            raw = response.choices[0].message.content.strip()

            if raw.startswith("```json"):
                raw = raw[7:]
            elif raw.startswith("```"):
                raw = raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

            parsed = _parse_json_response_strict(raw, task_name=task_name)

            _record_token_usage(
                task_name=task_name,
                model=deployment,
                response=response,
                start=start,
            )
            _mark_ai_success()
            if owns_probe_slot and requested_deployment != _CHAT_DEPLOYMENT:
                with _MISSING_DEPLOYMENTS_LOCK:
                    _PROBING_DEPLOYMENTS.discard(requested_deployment)
                    _MISSING_DEPLOYMENTS.discard(requested_deployment)
            logger.debug("[Azure OpenAI] task=%s latency=%.2fs",
                         task_name, time.perf_counter() - start)
            return parsed

        except ModelOutputParseError:
            _increment_parse_failure_metric(task_name)
            fallback = _parse_failure_fallback(task_name)
            if fallback is not None:
                return fallback
            raise
        except Exception as exc:
            if (
                not chat_fallback_attempted
                and deployment != _CHAT_DEPLOYMENT
                and _CHAT_DEPLOYMENT
                and _is_deployment_not_found_error(exc)
            ):
                with _MISSING_DEPLOYMENTS_LOCK:
                    first_time_missing = deployment not in _MISSING_DEPLOYMENTS
                    _MISSING_DEPLOYMENTS.add(deployment)
                    _PROBING_DEPLOYMENTS.discard(deployment)
                if first_time_missing:
                    logger.warning(
                        "[Azure OpenAI] task=%s deployment=%s not found. Falling back to chat deployment=%s",
                        task_name,
                        deployment,
                        _CHAT_DEPLOYMENT,
                    )
                else:
                    logger.debug(
                        "[Azure OpenAI] task=%s deployment=%s still missing. Falling back to chat deployment=%s",
                        task_name,
                        deployment,
                        _CHAT_DEPLOYMENT,
                    )
                deployment = _CHAT_DEPLOYMENT
                chat_fallback_attempted = True
                owns_probe_slot = False
                continue

            _mark_ai_failure(exc)
            if owns_probe_slot and requested_deployment != _CHAT_DEPLOYMENT:
                with _MISSING_DEPLOYMENTS_LOCK:
                    _PROBING_DEPLOYMENTS.discard(requested_deployment)
                owns_probe_slot = False
            can_retry = (
                attempt < max_retries - 1
                and _is_transient_ai_error(exc)
                and not _is_circuit_open()
            )
            if can_retry:
                wait_time = max(0.0, float(settings.AI_RETRY_BACKOFF_SECONDS)) * (2 ** attempt)
                logger.warning("[Azure OpenAI] task=%s attempt=%d failed: %s. Retrying in %.2fs...",
                               task_name, attempt + 1, exc, wait_time)
                await asyncio.sleep(wait_time)
            else:
                logger.error("[Azure OpenAI] task=%s error=%s", task_name, exc)
                raise

def _record_token_usage(task_name: str, model: str, response: object, start: float) -> None:
    """
    Capture tokens/cost from Azure OpenAI responses and feed TokenMonitor.

    This is intentionally best-effort and never raises.
    """
    try:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", 0) or 0)
        if total_tokens and completion_tokens == 0 and total_tokens >= prompt_tokens:
            completion_tokens = total_tokens - prompt_tokens
        latency_ms = (time.perf_counter() - start) * 1000.0
        _token_monitor.record(
            task_name=task_name,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
        )
    except Exception as exc:
        logger.debug("Token monitor capture skipped for task=%s: %s", task_name, exc)


def _parse_json_response_strict(raw_output: str, *, task_name: str) -> dict | list:
    """Strict mode: no repair. Malformed = rejected."""
    try:
        return json.loads(raw_output, strict=False)
    except json.JSONDecodeError as exc:
        logger.warning(
            "[Azure OpenAI] task=%s malformed JSON rejected: %s raw_output=%r",
            task_name,
            exc,
            raw_output,
        )
        raise ModelOutputParseError(
            f"Malformed JSON output from LLM for task={task_name}"
        ) from exc


# ─── Embeddings ───────────────────────────────────────────────────────────────

@observe(as_type="generation")
async def get_embedding(text: str) -> list[float]:
    if not openai_client:
        return []
    if settings.AI_FAIL_FAST_ON_UNAVAILABLE and _is_circuit_open():
        return []
    with _MISSING_DEPLOYMENTS_LOCK:
        if _EMBED_DEPLOYMENT in _MISSING_DEPLOYMENTS:
            logger.warning(
                "[Azure OpenAI Embeddings] deployment=%s previously marked missing. Returning empty embedding.",
                _EMBED_DEPLOYMENT,
            )
            return []

    max_retries = max(1, int(settings.AI_RETRY_MAX_ATTEMPTS))
    timeout_s = max(1.0, float(settings.AI_REQUEST_TIMEOUT_SECONDS))
    for attempt in range(max_retries):
        try:
            start = time.perf_counter()
            response = await asyncio.wait_for(
                openai_client.embeddings.create(
                    input=text[:30_000],
                    model=_EMBED_DEPLOYMENT,
                ),
                timeout=timeout_s,
            )
            _record_token_usage(
                task_name="get_embedding",
                model=_EMBED_DEPLOYMENT,
                response=response,
                start=start,
            )
            _mark_ai_success()
            if not response.data:
                logger.warning("OpenAI returned an empty embedding array for text hash %s", hash(text))
                return []
            return response.data[0].embedding
        except Exception as exc:
            _mark_ai_failure(exc)
            can_retry = (
                attempt < max_retries - 1
                and _is_transient_ai_error(exc)
                and not _is_circuit_open()
            )
            if can_retry:
                wait_time = max(0.0, float(settings.AI_RETRY_BACKOFF_SECONDS)) * (2 ** attempt)
                logger.warning(
                    "[Azure OpenAI Embeddings] attempt=%d failed: %s. Retrying in %.2fs...",
                    attempt + 1,
                    exc,
                    wait_time,
                )
                await asyncio.sleep(wait_time)
            else:
                if _is_deployment_not_found_error(exc):
                    with _MISSING_DEPLOYMENTS_LOCK:
                        _MISSING_DEPLOYMENTS.add(_EMBED_DEPLOYMENT)
                    logger.warning(
                        "[Azure OpenAI Embeddings] deployment=%s not found. Future embedding calls will fast-return empty vectors.",
                        _EMBED_DEPLOYMENT,
                    )
                logger.warning("[Azure OpenAI Embeddings] failed: %s", exc)
                return []

# --- Resume Parsing -----------------------------------------------------------
RESUME_PARSE_PROMPT = """\
You are a precise resume parser. Extract structured data from the resume text below.

CRITICAL RULES:
- normalized_skills: lowercase canonical names only
- experience_years: TOTAL years of professional work experience as a float
- work_experience: extract EVERY job/role listed.
- career_breaks: identify gaps LARGER THAN 6 MONTHS.
- skill_years: flat dict mapping each normalized skill to TOTAL years used.
- projects: include BOTH standalone projects AND significant work experience entries.
- Return ONLY valid JSON — no markdown.

Resume:
{resume_text}

JSON schema:
{{
  "name": "string|null",
  "email": "string|null",
  "phone": "string|null",
  "location": "string|null",
  "skills": ["raw skill strings"],
  "normalized_skills": ["lowercase canonical names"],
  "experience_years": 0.0,
  "work_experience": [
    {{"company": "", "role": "", "start_date": "", "end_date": "", "duration_years": 0.0, "skills": []}}
  ],
  "career_breaks": [
    {{"start": "", "end": "", "duration_months": 0, "reason": null, "notes": null}}
  ],
  "skill_years": {{"csharp": 3.0}},
  "education": [{{"degree": "", "institute": "", "year": "", "gpa": null}}],
  "projects": [{{"title": "", "description": "", "skills": []}}],
  "summary": "2-3 sentence summary"
}}
"""


@observe()
async def parse_resume(resume_text: str, model: str | None = None) -> dict:
    prompt = RESUME_PARSE_PROMPT.format(resume_text=resume_text[:40_000])
    return await _generate_json(prompt, task_name="parse_resume", max_tokens=8000, model=model)


# ─── AI Resume Scoring ────────────────────────────────────────────────────────

SCORE_RESUME_PROMPT = """\
You are a senior technical recruiter with 15+ years of experience.
Your job is to accurately and fairly evaluate candidates against the Job Requirements.

SKILL MATCHING RULES — read carefully:
1. Match must-have skills that are EXPLICITLY stated OR where an obvious technical equivalent/synonym is present in the resume.
   Common accepted equivalences (not exhaustive):
   - ".NET Core" = ".NET 6" / ".NET 7" / ".NET 8" / "Dot Net Core" / "ASP.NET Core"
   - "C#" = "CSharp" / "c sharp"
   - "Authentication/Authorization" = "JWT" / "OAuth" / "Identity Framework" / "ASP.NET Identity"
   - "SQL Server" = "MSSQL" / "Microsoft SQL Server" / "T-SQL"
   - "Web API" = "ASP.NET Web API" / "REST API" / "RESTful API" / "Dot Net Core Web APIs"
   - "Git" = "GitHub" / "GitLab" / "Bitbucket" / "source control"
   - "Design Patterns" = "SOLID" / "Repository Pattern" / "CQRS" / "design patterns"
2. Do NOT infer skills that are not present even loosely.
3. Do NOT hallucinate domain experience unless explicitly written.
4. Good-to-Have items that are missing go in "missing_good_to_have" — NEVER in "missing_must_have".
5. Base scores on actual evidence from the profile below, not assumptions.

Job Requirements:
Title: {title}
Experience Required: {exp_min}–{exp_max} years
Must-Have Skills: {must_have}
Good-to-Have Skills: {good_to_have}
Job Description: {description}

Candidate Profile:
Name: {name}
Total Experience: {exp_years} years
Raw Skills from Resume: {raw_skills}
Normalized Skills: {normalized_skills}
Per-Skill Experience: {skill_years_readable}
Work History: {work_exp}
Projects: {projects}
Location: {location}

SCORING SCALE: skill_score, experience_score, and project_score must be INTEGERS between 0 and 100. Do NOT use a 0-10 scale or decimal fractions.

RETURN ONLY VALID JSON:
{{
  "skill_score": 0,
  "experience_score": 0,
  "project_score": 0,
  "matched_must_have": [],
  "missing_must_have": [],
  "matched_good_to_have": [],
  "missing_good_to_have": [],
  "reasoning": "3-4 sentences citing specific evidence from the profile",
  "domain_fit": "exact|adjacent|different",
  "seniority_match": "exact|underqualified|overqualified_minor|overqualified_major",
  "red_flags": [],
  "standout_factors": [],
  "hire_recommendation": "strong_hire|hire|maybe|no_hire|strong_no_hire",
  "confidence": "high|medium|low"
}}
"""


@observe()
async def score_resume_against_jd(
    parsed_resume: dict, job_title: str, exp_min: int, exp_max: int,
    must_have: list[str], good_to_have: list[str], description: str = "",
    model: str | None = None,
) -> dict:
    work_exp_summary = [{
        "role": w.get("role", ""), "company": w.get("company", ""),
        "duration_years": w.get("duration_years", 0), "skills": (w.get("skills") or [])[:15]
    } for w in (parsed_resume.get("work_experience") or [])[:20]]

    project_summary = [{
        "title": p.get("title", ""), "skills": (p.get("skills") or [])[:12],
        "description": (p.get("description") or "")[:300]
    } for p in (parsed_resume.get("projects") or [])[:20]]

    skill_years_dict = parsed_resume.get("skill_years") or {}
    skill_years_readable = ", ".join(
        f"{k}: {round(v, 1)}yr" for k, v in list(skill_years_dict.items())[:20]
    ) or "Not specified"

    raw_skills = ", ".join((parsed_resume.get("skills") or [])[:40])
    normalized_skills = ", ".join((parsed_resume.get("normalized_skills") or [])[:40])

    prompt = _build_prompt("score_resume", SCORE_RESUME_PROMPT,
                           title=job_title, exp_min=exp_min, exp_max=exp_max,
                           must_have=", ".join(must_have) if must_have else "None",
                           good_to_have=", ".join(good_to_have) if good_to_have else "None",
                           description=(description or "")[:1500],
                           name=parsed_resume.get("name") or "Unknown",
                           exp_years=parsed_resume.get("experience_years") or 0,
                           raw_skills=raw_skills or "Not specified",
                           normalized_skills=normalized_skills or "Not specified",
                           skill_years_readable=skill_years_readable,
                           work_exp=json.dumps(work_exp_summary),
                           projects=json.dumps(project_summary),
                           location=parsed_resume.get("location") or "Not specified",
                           )

    result = await _generate_json(prompt, task_name="score_resume", max_tokens=1500, model=model)
    if isinstance(result, dict) and result.get("parse_failed"):
        return result

    def _clamp(val, default: int = 50) -> int:
        """
        Normalise an LLM score to the 0-100 integer range.

        The prompt instructs the model to return integers on the 0-100 scale.
        In practice it occasionally returns the 0-10 scale instead.

        Rescale rule (exclusive lower bound avoids the ambiguous edge case
        where the LLM returns 1 meaning "1 out of 100" not "1 out of 10"):
          • 1 < v ≤ 10  → v × 10  (unambiguous 0-10 scale)
          • v == 0 or v == 1 → kept as-is (0 or 1 out of 100 are valid)
          • v > 10  → kept as-is (already on 0-100 scale)

        The previous version also rescaled 0 < v ≤ 1, which turned a
        legitimate score of 1 (1% match) into 100 (perfect match).
        """
        try:
            v = float(val)
            # Only rescale values that are unambiguously on the 0-10 scale
            if 1 < v <= 10:
                v = v * 10
            return max(0, min(100, int(round(v))))
        except (TypeError, ValueError):
            logger.warning("Score clamping failed for value %r, using default %s", val, default)
            return default

    return {
        "skill_score":          _clamp(result.get("skill_score"), 50),
        "experience_score":     _clamp(result.get("experience_score"), 50),
        "project_score":        _clamp(result.get("project_score"), 50),
        "matched_must_have":    result.get("matched_must_have") or [],
        "missing_must_have":    result.get("missing_must_have") or [],
        "matched_good_to_have": result.get("matched_good_to_have") or [],
        "missing_good_to_have":  result.get("missing_good_to_have") or [],
        "reasoning":            result.get("reasoning") or "",
        "domain_fit":           result.get("domain_fit") or "exact",
        "seniority_match":      result.get("seniority_match") or "exact",
        "red_flags":            result.get("red_flags") or [],
        "standout_factors":     result.get("standout_factors") or [],
        "hire_recommendation":  result.get("hire_recommendation") or "maybe",
        "confidence":           result.get("confidence") or "medium",
        "parse_failed":         bool(result.get("parse_failed", False)),
    }


# ─── JD Parsing ───────────────────────────────────────────────────────────────

JD_PARSE_PROMPT = """\
You are a precise job description parser. Extract structured data from the JD text below.

CRITICAL RULES:
- experience_min / experience_max: extract the NUMERIC year range (e.g. "3-5 years" → min=3, max=5).
  If only a minimum is stated ("at least 4 years") set max = min + 3.
- education_requirement: "required" | "preferred" | "none"
- must_have_skills: technologies/skills that are mandatory
- good_to_have_skills: technologies/skills listed as preferred/nice-to-have
- Return ONLY valid JSON — no markdown fences.

JD Text:
{doc_text}

JSON schema:
{{
  "title": "string",
  "role": "string",
  "description": "string",
  "must_have_skills": [],
  "good_to_have_skills": [],
  "experience_min": 0,
  "experience_max": 5,
  "location": "string",
  "employment_type": "string",
  "education_requirement": "none"
}}
"""


@observe()
async def parse_jd_from_document(doc_text: str, model: str | None = None) -> dict:
    prompt = JD_PARSE_PROMPT.format(doc_text=doc_text[:30_000])
    return await _generate_json(prompt, task_name="parse_jd_from_document", max_tokens=1500, model=model)


# ─── JD Generation ────────────────────────────────────────────────────────────

@observe()
async def generate_jd(
    role: str,
    exp_min: int,
    exp_max: int,
    location: str = "Remote",
    context: str = "",
    model: str | None = None,
) -> dict:
    fallback = (
        "Write a JSON Job Description for Role: {role}, Exp: {exp_min}-{exp_max}, Loc: {location}. "
        "Context: {context}. "
        "Include title, role, description, must_have_skills, good_to_have_skills, "
        "experience_min (int), experience_max (int), location (string), "
        "employment_type (string), and education_requirement (string, one of: "
        "'required', 'preferred', 'none'). "
        "Use 'required' when a degree is mandatory, 'preferred' when nice-to-have, "
        "'none' when not mentioned. "
        "Return ONLY valid JSON — no markdown fences."
    )
    prompt = _build_prompt("generate_jd", fallback, role=role, exp_min=exp_min,
                           exp_max=exp_max, location=location, context=context)
    return await _generate_json(prompt, task_name="generate_jd", max_tokens=1500, model=model)


# ─── Quiz Generation ──────────────────────────────────────────────────────────

@observe()
async def generate_quiz_questions(
    jd_text: str,
    skills: list[str],
    easy: int = 8,
    medium: int = 8,
    hard: int = 4,
    model: str | None = None,
) -> list[dict]:
    fallback_prompt = (
        "Generate exactly {easy} easy, {medium} medium, and {hard} hard MCQ questions "
        "for these skills: {skills}. "
        "Return a JSON array. Each object must have: question_text (string), "
        "options (array of 4 strings), correct_answer (0-based index integer), "
        "difficulty ('easy'|'medium'|'hard'), skill_tag (string)."
    )
    prompt = _build_prompt(
        "generate_quiz", fallback_prompt,
        easy=easy, medium=medium, hard=hard,
        total=easy + medium + hard,
        skills=", ".join(skills) if isinstance(skills, list) else skills,
    )
    questions = await _generate_json(prompt, task_name="generate_quiz", max_tokens=2500, model=model)
    if isinstance(questions, dict):
        questions = next(iter(questions.values()), [])
    for q in questions:
        q["weight"] = {"easy": 1, "medium": 2, "hard": 3}.get(q.get("difficulty"), 1)
    return questions


@observe()
async def parse_quiz_from_document(doc_text: str, model: str | None = None) -> list[dict]:
    prompt = (
        "Parse this MCQ document into a JSON array. "
        "Each object MUST have exactly these fields:\n"
        "  - question_text: string (the question)\n"
        "  - options: array of 4 strings (the answer choices)\n"
        "  - correct_answer: integer (0-based index of the correct option)\n"
        "  - difficulty: string, one of 'easy', 'medium', 'hard'\n"
        "  - skill_tag: string (the skill/topic being tested)\n"
        "Return ONLY a valid JSON array — no markdown fences.\n\n"
        f"Document:\n{doc_text[:8000]}"
    )
    questions = await _generate_json(prompt, task_name="parse_quiz", max_tokens=3000, model=model)
    if isinstance(questions, dict):
        questions = next(iter(questions.values()), [])
    for q in questions:
        q["weight"] = {"easy": 1, "medium": 2, "hard": 3}.get(q.get("difficulty"), 1)
    return questions


# ─── Skill Normalisation ──────────────────────────────────────────────────────

@observe()
async def normalize_skills(skills: list[str], model: str | None = None) -> list[str]:
    result = await _generate_json(
        f"Normalize to lowercase canonical: {skills}. Return JSON object with a single array.",
        task_name="normalize_skills", max_tokens=400, model=model
    )
    if isinstance(result, dict):
        return next(iter(result.values()), [])
    return result


# ─── HR Email Drafting ────────────────────────────────────────────────────────

@observe()
async def generate_hr_email(
    email_type: str,
    candidate_name: str,
    job_title: str,
    resume_score: float,
    quiz_score: float,
    model: str | None = None,
) -> dict:
    prompt = (
        f"Draft a {email_type} email for {candidate_name} applying to {job_title}.\n"
        f"Resume Score: {resume_score}, Quiz Score: {quiz_score}\n\n"
        "Return ONLY a valid JSON object with exactly these fields:\n"
        "  - subject: string (the email subject line)\n"
        "  - body: string (the plain text email body)\n"
        "Do NOT include markdown fences, greetings outside the JSON, or any other fields."
    )
    return await _generate_json(prompt, task_name="generate_hr_email", max_tokens=800, model=model)


# ─── Code Evaluation ──────────────────────────────────────────────────────────

@observe()
async def evaluate_code_submission(
    problem_statement: str,
    user_code: str,
    language: str,
    model: str | None = None,
) -> dict:
    prompt = (
        f"Evaluate this {language} code submission against the problem statement.\n\n"
        f"Problem: {problem_statement}\n\n"
        f"Code ({language}):\n{user_code}\n\n"
        "Return ONLY a valid JSON object with exactly these fields:\n"
        "  - passed: boolean (true if the code correctly solves the problem)\n"
        "  - score: integer (0 to 10 rating of code quality/correctness)\n"
        "  - simulated_output: string (what the code would output, or an error trace)\n"
        "  - feedback: string (constructive feedback for the candidate)\n"
        "Do NOT include markdown fences or any other fields."
    )
    return await _generate_json(prompt, task_name="evaluate_code", max_tokens=600, model=model)


# ─── Resume Enhancement (NEW) ─────────────────────────────────────────────────

RESUME_ENHANCE_PROMPT = """\
You are an expert resume coach and ATS optimization specialist with 15+ years of experience
helping candidates land interviews at top companies.

Your task: Rewrite and improve the candidate's resume content to better match the target job,
maximize ATS keyword matching, and make each bullet point stronger and more impactful.

Target Job:
Title: {job_title}
Must-Have Skills: {must_have}
Good-to-Have Skills: {good_to_have}
Job Description: {job_description}

Current Resume Content:
{resume_text}

Current Skill Match Score: {current_score}%
Missing Must-Have Skills: {missing_skills}

RULES:
1. NEVER fabricate experience, skills, or achievements the candidate doesn't have.
2. Rewrite existing bullets to be stronger using ACTION VERB + METRIC + IMPACT format.
3. Naturally weave in JD keywords where the candidate genuinely has that experience.
4. For missing must-have skills, suggest concrete ways to gain them (courses, projects).
5. ATS keywords should appear in context, not just listed.
6. Keep all dates, companies, and roles exactly as they are.

Return ONLY valid JSON:
{{
  "enhanced_summary": "2-3 powerful sentences that open with the candidate's strongest value proposition for THIS specific role",
  "enhanced_skills_section": ["skill1", "skill2"],
  "enhanced_work_experience": [
    {{
      "company": "same as original",
      "role": "same as original",
      "start_date": "same",
      "end_date": "same",
      "enhanced_bullets": [
        "Strong action-verb led bullet with metric and impact",
        "Another rewritten bullet"
      ]
    }}
  ],
  "keyword_additions": ["keywords naturally added to match JD"],
  "missing_skill_suggestions": [
    {{
      "skill": "skill name",
      "suggestion": "Specific actionable step: e.g. 'Complete Microsoft AZ-900 Azure Fundamentals (free, 8 hours) and add a small demo project'",
      "priority": "critical|high|medium"
    }}
  ],
  "ats_improvements": ["specific ATS formatting tips for this resume"],
  "estimated_score_after": 0,
  "improvement_summary": "2-3 sentences summarising what was changed and why"
}}
"""


@observe()
async def enhance_resume(
    resume_text: str,
    job_title: str,
    must_have: list[str],
    good_to_have: list[str],
    job_description: str,
    current_score: float,
    missing_skills: list[str],
    model: str | None = None,
) -> dict:
    """
    AI-powered resume enhancement tailored to a specific JD.
    Returns enhanced content sections and actionable improvement suggestions.
    """
    prompt = RESUME_ENHANCE_PROMPT.format(
        job_title=job_title,
        must_have=", ".join(must_have) if must_have else "None specified",
        good_to_have=", ".join(good_to_have) if good_to_have else "None specified",
        job_description=(job_description or "")[:1200],
        resume_text=resume_text[:8000],
        current_score=round(current_score, 1),
        missing_skills=", ".join(missing_skills) if missing_skills else "None",
    )
    return await _generate_json(prompt, task_name="enhance_resume", max_tokens=3000, model=model)


# ─── Resume Builder (NEW) ─────────────────────────────────────────────────────

RESUME_BUILD_PROMPT = """\
You are a professional resume writer. Create a complete, ATS-optimized resume from the
structured data below. The resume should be compelling, honest, and tailored to the
candidate's target role.

Candidate Information:
{candidate_data}

Target Role (optional): {target_role}

RULES:
1. Every bullet point must start with a strong action verb.
2. Quantify achievements wherever the data allows (even estimates like "team of X", "X% improvement").
3. Summary should be 2-3 sentences that immediately communicate value.
4. Skills should be grouped logically (e.g. Languages, Frameworks, Databases, Tools).
5. If target_role is provided, emphasize relevant experience.
6. Keep it truthful — only use information provided.

Return ONLY valid JSON:
{{
  "contact": {{
    "name": "",
    "email": "",
    "phone": "",
    "location": "",
    "linkedin": "",
    "github": ""
  }},
  "summary": "2-3 sentence professional summary",
  "skills": {{
    "languages": [],
    "frameworks": [],
    "databases": [],
    "tools": [],
    "cloud": [],
    "other": []
  }},
  "work_experience": [
    {{
      "company": "",
      "role": "",
      "start_date": "",
      "end_date": "",
      "location": "",
      "bullets": [
        "Action verb + what you did + measurable impact"
      ]
    }}
  ],
  "education": [
    {{
      "degree": "",
      "institution": "",
      "year": "",
      "gpa": null,
      "highlights": []
    }}
  ],
  "projects": [
    {{
      "title": "",
      "description": "2-3 sentences on what it does and your role",
      "technologies": [],
      "link": ""
    }}
  ],
  "certifications": [],
  "ats_keywords": ["top 15 ATS keywords for target role"]
}}
"""


@observe()
async def build_resume_from_form(
    candidate_data: dict,
    target_role: str = "",
    model: str | None = None,
) -> dict:
    """
    Generate a complete structured resume from form data.
    Returns a fully formatted resume object ready for frontend rendering/PDF export.
    """
    prompt = RESUME_BUILD_PROMPT.format(
        candidate_data=json.dumps(candidate_data, indent=2)[:6000],
        target_role=target_role or "General Software Engineering",
    )
    return await _generate_json(prompt, task_name="build_resume", max_tokens=3500, model=model)


# ─── Cover Letter Generator (NEW) ────────────────────────────────────────────

COVER_LETTER_PROMPT = """\
You are an expert career coach. Write a compelling, personalised cover letter for
the candidate applying to the specified role.

Candidate Profile:
Name: {name}
Total Experience: {exp_years} years
Key Skills: {skills}
Work History Summary: {work_history}
Education: {education}

Target Job:
Company: {company}
Role: {job_title}
Key Requirements: {must_have}
Job Description: {job_description}

RULES:
1. Open with a hook that immediately connects the candidate's strongest experience to the role.
2. Cite 2-3 specific achievements from their work history as evidence.
3. Show genuine interest in THIS company/role — reference something specific from the JD.
4. Keep it to 3-4 paragraphs, under 350 words.
5. Professional but not stiff — conversational enough to feel human.
6. End with a clear call to action.

Return ONLY valid JSON:
{{
  "subject_line": "Application for [Role] — [Name]",
  "body": "Full cover letter text with \\n\\n between paragraphs",
  "word_count": 0,
  "key_selling_points": ["3-4 bullet points of the strongest points made"]
}}
"""


@observe()
async def generate_cover_letter(
    candidate_name: str,
    exp_years: float,
    skills: list[str],
    work_history: list[dict],
    education: list[dict],
    company_name: str,
    job_title: str,
    must_have: list[str],
    job_description: str,
    model: str | None = None,
) -> dict:
    """Generate a personalised cover letter for a specific job application."""
    work_summary = [
        f"{w.get('role', '')} at {w.get('company', '')} ({w.get('duration_years', 0):.1f}yr)"
        for w in (work_history or [])[:5]
    ]
    edu_summary = [
        f"{e.get('degree', '')} from {e.get('institute', '')}"
        for e in (education or [])[:2]
    ]

    prompt = COVER_LETTER_PROMPT.format(
        name=candidate_name or "Candidate",
        exp_years=round(exp_years, 1),
        skills=", ".join((skills or [])[:20]),
        work_history="; ".join(work_summary) or "Not specified",
        education="; ".join(edu_summary) or "Not specified",
        company=company_name or "the company",
        job_title=job_title,
        must_have=", ".join(must_have[:15]) if must_have else "Not specified",
        job_description=(job_description or "")[:800],
    )
    return await _generate_json(prompt, task_name="generate_cover_letter", max_tokens=1200, model=model)


# ─── Career Path Analysis (NEW) ──────────────────────────────────────────────

CAREER_ANALYSIS_PROMPT = """\
You are a senior career strategist and tech industry expert. Analyze this candidate's
career trajectory and provide actionable, honest guidance.

Candidate Profile:
Name: {name}
Total Experience: {exp_years} years
Current Skills: {skills}
Work History: {work_history}
Education: {education}
Career Breaks: {career_breaks}
Target Role (if any): {target_role}

ANALYSIS TASKS:
1. Career trajectory: Is the candidate progressing logically? Any concerning patterns?
2. Skill gaps: What skills should they learn NEXT given their background and market demand?
3. Market positioning: How do they compare to typical candidates for their experience level?
4. Upskilling roadmap: Prioritized, actionable 6-month learning plan.
5. Career break guidance: If applicable, how to address gaps positively.

Return ONLY valid JSON:
{{
  "career_stage": "early|growth|senior|lead|transition",
  "trajectory_assessment": "2-3 sentences on career progression pattern",
  "strengths": ["top 3-4 genuine career strengths"],
  "skill_gaps": [
    {{
      "skill": "skill name",
      "why_important": "1 sentence on market relevance",
      "how_to_learn": "specific resource (e.g. 'AWS Certified Developer course on A Cloud Guru — 40hr')",
      "time_to_competency": "e.g. 4-6 weeks",
      "priority": "high|medium|low"
    }}
  ],
  "market_positioning": "2-3 sentences on how competitive they are for their target role",
  "six_month_roadmap": [
    {{
      "month_range": "Month 1-2",
      "focus": "What to focus on",
      "actions": ["specific action 1", "specific action 2"],
      "milestone": "What they'll have achieved"
    }}
  ],
  "career_break_advice": "Advice on addressing gaps (null if no breaks)",
  "next_role_suggestions": ["2-3 specific role titles that match their trajectory"],
  "salary_range_estimate": "Based on skills and experience, approximate market range"
}}
"""


@observe()
async def analyze_career_path(
    candidate_name: str,
    exp_years: float,
    skills: list[str],
    work_history: list[dict],
    education: list[dict],
    career_breaks: list[dict],
    target_role: str = "",
    model: str | None = None,
) -> dict:
    """
    AI-powered career trajectory analysis with upskilling roadmap.
    Returns strengths, gaps, and a concrete 6-month improvement plan.
    """
    work_summary = [{
        "role": w.get("role", ""),
        "company": w.get("company", ""),
        "duration_years": w.get("duration_years", 0),
        "skills": (w.get("skills") or [])[:8],
    } for w in (work_history or [])[:10]]

    edu_summary = [{
        "degree": e.get("degree", ""),
        "institute": e.get("institute", ""),
        "year": e.get("year", ""),
    } for e in (education or [])[:3]]

    breaks_summary = [{
        "duration_months": b.get("duration_months", 0),
        "reason": b.get("reason", "Not specified"),
    } for b in (career_breaks or [])[:5]]

    prompt = CAREER_ANALYSIS_PROMPT.format(
        name=candidate_name or "Candidate",
        exp_years=round(exp_years, 1),
        skills=", ".join((skills or [])[:30]),
        work_history=json.dumps(work_summary),
        education=json.dumps(edu_summary),
        career_breaks=json.dumps(breaks_summary) if breaks_summary else "None",
        target_role=target_role or "Not specified",
    )
    return await _generate_json(prompt, task_name="analyze_career_path", max_tokens=2500, model=model)




