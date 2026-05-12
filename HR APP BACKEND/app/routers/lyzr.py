"""
Lyzr router - server-side proxy for candidate ranking.

Keeps API keys on the backend and prevents browser-side secret exposure.
"""

from __future__ import annotations

import json
import time
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.config import settings
from app.models import User
from app.services.auth_service import require_hr


router = APIRouter(prefix="/ai/lyzr", tags=["AI"])


class LyzrCandidate(BaseModel):
    name: str
    skills: list[str]
    experience_years: float
    summary: str | None = None


class LyzrJD(BaseModel):
    title: str
    required_skills: list[str]
    experience_min: float
    experience_max: float
    description: str | None = None


class LyzrMatchRequest(BaseModel):
    jd: LyzrJD
    candidates: list[LyzrCandidate]


class LyzrMatchResult(BaseModel):
    rank: int
    candidate_name: str
    total_score: float
    category: Literal["Strong Fit", "Partial Fit", "Not a Fit"]
    verdict: Literal["First call", "Second round", "Third choice", "Reject"]
    biggest_gap: str
    differentiator: str
    one_line_reason: str


class LyzrAnalysisResult(BaseModel):
    jd_title: str
    results: list[LyzrMatchResult]
    recruiter_summary: str
    top_pick: str


class LyzrStatusOut(BaseModel):
    configured: bool
    missing_env_vars: list[str] = []
    detail: str


def _tokenize_skills(values: list[str]) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        for tok in value.lower().replace("/", " ").replace(",", " ").split():
            if tok:
                tokens.add(tok)
    return tokens


def _fallback_match(payload: LyzrMatchRequest) -> LyzrAnalysisResult:
    """
    Deterministic fallback when Lyzr is unavailable.
    Keeps the recruiter flow functional instead of failing with HTTP 503.
    """
    required = payload.jd.required_skills or []
    required_tokens = _tokenize_skills(required)
    exp_min = payload.jd.experience_min
    exp_max = payload.jd.experience_max
    rows: list[LyzrMatchResult] = []

    for candidate in payload.candidates:
        c_tokens = _tokenize_skills(candidate.skills or [])
        matched = sorted({skill for skill in required if _tokenize_skills([skill]) & c_tokens})
        missing = [skill for skill in required if skill not in matched]

        if required:
            skill_score = (len(matched) / len(required)) * 100.0
        elif required_tokens:
            skill_score = (len(c_tokens & required_tokens) / max(1, len(required_tokens))) * 100.0
        else:
            skill_score = 60.0

        exp = float(candidate.experience_years or 0.0)
        if exp_min <= exp <= exp_max:
            exp_score = 100.0
        elif exp < exp_min:
            exp_score = max(0.0, 100.0 - (exp_min - exp) * 30.0)
        else:
            exp_score = max(0.0, 100.0 - (exp - exp_max) * 20.0)

        total = round((0.72 * skill_score) + (0.28 * exp_score), 2)
        if total >= 75:
            category = "Strong Fit"
        elif total >= 50:
            category = "Partial Fit"
        else:
            category = "Not a Fit"

        gap = missing[0] if missing else "No critical skill gaps detected"
        differentiator = matched[0] if matched else "Relevant experience"
        rows.append(
            LyzrMatchResult(
                rank=0,
                candidate_name=candidate.name,
                total_score=total,
                category=category,
                verdict="Reject",
                biggest_gap=f"Missing: {gap}" if missing else gap,
                differentiator=f"Matched skill: {differentiator}" if matched else differentiator,
                one_line_reason=f"{len(matched)}/{max(1, len(required))} required skills matched, exp={exp}y",
            )
        )

    rows.sort(key=lambda r: r.total_score, reverse=True)
    for idx, row in enumerate(rows, start=1):
        row.rank = idx
        if idx == 1:
            row.verdict = "First call"
        elif idx <= 3:
            row.verdict = "Second round"
        elif idx <= 5:
            row.verdict = "Third choice"
        else:
            row.verdict = "Reject"

    top_pick = rows[0].candidate_name if rows else ""
    summary = (
        "Lyzr service is unavailable, so fallback ranking was used. "
        "Results are rule-based and should be reviewed manually."
    )
    return LyzrAnalysisResult(
        jd_title=payload.jd.title,
        results=rows,
        recruiter_summary=summary,
        top_pick=top_pick,
    )


def _build_prompt(jd: LyzrJD, candidates: list[LyzrCandidate]) -> str:
    jd_text = (
        f"JD Title: {jd.title}\n"
        f"Required Skills: {', '.join(jd.required_skills)}\n"
        f"Experience Required: {jd.experience_min}-{jd.experience_max} years\n"
        f"{f'Description: {jd.description}' if jd.description else ''}"
    ).strip()

    candidate_text = "\n\n".join(
        (
            f"Candidate {i + 1}: {candidate.name}\n"
            f"  Skills: {', '.join(candidate.skills) if candidate.skills else 'Not specified'}\n"
            f"  Experience: {candidate.experience_years} years\n"
            f"  {f'AI Summary: {candidate.summary}' if candidate.summary else ''}"
        ).strip()
        for i, candidate in enumerate(candidates)
    )

    return (
        f"Here is the Job Description and {len(candidates)} candidates to evaluate.\n\n"
        f"JD:\n{jd_text}\n\n"
        f"Candidates:\n{candidate_text}\n\n"
        f"Force-rank all {len(candidates)} candidates from 1 (best) to {len(candidates)} (worst) for this specific JD.\n\n"
        "For each candidate return a JSON array with these exact fields:\n"
        "- rank (number)\n"
        "- candidate_name (string)\n"
        "- total_score (0-100)\n"
        '- category: exactly one of "Strong Fit" / "Partial Fit" / "Not a Fit"\n'
        '- verdict: exactly one of "First call" / "Second round" / "Third choice" / "Reject"\n'
        "- biggest_gap (string - one specific gap vs this JD)\n"
        "- differentiator (string - one thing they have others do not)\n"
        "- one_line_reason (string)\n\n"
        'Only top 3 candidates should get "First call". Be specific and ruthless in differentiating.\n\n'
        'After the array, add a "recruiter_summary" string (2 sentences max) and "top_pick" string (just the name).\n\n'
        "Respond ONLY with valid JSON in this exact shape:\n"
        "{\n"
        f'  "jd_title": "{jd.title}",\n'
        '  "results": [...],\n'
        '  "recruiter_summary": "...",\n'
        '  "top_pick": "..."\n'
        "}"
    ).strip()


def _clean_json_text(raw: str) -> str:
    return (
        raw.replace("```json", "", 1)
        .replace("```", "", 1)
        .rstrip("`")
        .strip()
    )


@router.get("/status", response_model=LyzrStatusOut)
async def lyzr_status(user: User = Depends(require_hr)) -> LyzrStatusOut:
    del user  # access guard only
    required = {
        "LYZR_AGENT_URL": settings.LYZR_AGENT_URL,
        "LYZR_API_KEY": settings.LYZR_API_KEY,
        "LYZR_AGENT_ID": settings.LYZR_AGENT_ID,
        "LYZR_USER_ID": settings.LYZR_USER_ID,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        return LyzrStatusOut(
            configured=False,
            missing_env_vars=missing,
            detail="Lyzr service is not configured on the backend.",
        )
    return LyzrStatusOut(
        configured=True,
        detail="Lyzr service is configured.",
    )


@router.post("/match", response_model=LyzrAnalysisResult)
async def run_lyzr_match(
    payload: LyzrMatchRequest,
    user: User = Depends(require_hr),
) -> LyzrAnalysisResult:
    del user  # access guard only

    required = {
        "LYZR_AGENT_URL": settings.LYZR_AGENT_URL,
        "LYZR_API_KEY": settings.LYZR_API_KEY,
        "LYZR_AGENT_ID": settings.LYZR_AGENT_ID,
        "LYZR_USER_ID": settings.LYZR_USER_ID,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        return _fallback_match(payload)

    prompt = _build_prompt(payload.jd, payload.candidates)
    session_id = settings.LYZR_SESSION_ID or f"{settings.LYZR_AGENT_ID}-{int(time.time() * 1000)}"

    request_body = {
        "user_id": settings.LYZR_USER_ID,
        "agent_id": settings.LYZR_AGENT_ID,
        "session_id": session_id,
        "message": prompt,
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            response = await client.post(
                settings.LYZR_AGENT_URL,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": settings.LYZR_API_KEY,
                },
                json=request_body,
            )
    except httpx.HTTPError:
        return _fallback_match(payload)

    if response.status_code >= 400:
        return _fallback_match(payload)

    try:
        data = response.json()
    except ValueError:
        return _fallback_match(payload)

    raw = (
        data.get("response")
        or data.get("message")
        or data.get("output")
        or (((data.get("choices") or [{}])[0].get("message") or {}).get("content"))
        or ""
    )
    if not isinstance(raw, str) or not raw.strip():
        return _fallback_match(payload)

    try:
        parsed = json.loads(_clean_json_text(raw))
    except json.JSONDecodeError:
        return _fallback_match(payload)

    try:
        result = LyzrAnalysisResult.model_validate(parsed)
    except Exception:
        return _fallback_match(payload)

    result.results.sort(key=lambda item: item.rank)
    if not result.jd_title:
        result.jd_title = payload.jd.title
    if not result.top_pick and result.results:
        result.top_pick = result.results[0].candidate_name

    return result
