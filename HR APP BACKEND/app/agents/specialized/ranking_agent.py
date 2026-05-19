"""
RankingAgent — ranks a list of candidates against a JD using Lyzr AI (or rule-based fallback).

State inputs:
  - `candidates`: list of dicts with keys: name, skills, experience_years, summary
  - `jd`: dict with keys: title, required_skills, experience_min, experience_max, description
  - `use_lyzr`: bool (default True) — set False to use rule-based score sorting only

State outputs:
  - `ranking_result`: full Lyzr analysis or sorted list with scores
"""
from __future__ import annotations
import json
import time
import logging
import threading
from typing import Any

import httpx

from app.agents.base import BaseAgent
from app.config import settings

logger = logging.getLogger(__name__)

_LYZR_UNAVAILABLE_LOCK = threading.Lock()
_LYZR_UNAVAILABLE_UNTIL: float = 0.0
_LYZR_UNAVAILABLE_DETAIL: str = ""


def _lyzr_cooldown_remaining() -> float:
    with _LYZR_UNAVAILABLE_LOCK:
        remaining = _LYZR_UNAVAILABLE_UNTIL - time.monotonic()
    return remaining if remaining > 0 else 0.0


def _mark_lyzr_unavailable(detail: str, cooldown_seconds: float = 45.0) -> None:
    global _LYZR_UNAVAILABLE_UNTIL, _LYZR_UNAVAILABLE_DETAIL
    with _LYZR_UNAVAILABLE_LOCK:
        _LYZR_UNAVAILABLE_UNTIL = time.monotonic() + max(10.0, cooldown_seconds)
        _LYZR_UNAVAILABLE_DETAIL = str(detail or "Lyzr unavailable")


def _clear_lyzr_unavailable() -> None:
    global _LYZR_UNAVAILABLE_UNTIL, _LYZR_UNAVAILABLE_DETAIL
    with _LYZR_UNAVAILABLE_LOCK:
        _LYZR_UNAVAILABLE_UNTIL = 0.0
        _LYZR_UNAVAILABLE_DETAIL = ""


def _lyzr_unavailable_detail() -> str:
    with _LYZR_UNAVAILABLE_LOCK:
        return _LYZR_UNAVAILABLE_DETAIL or "Lyzr unavailable"


class RankingAgent(BaseAgent):
    name = "ranking_agent"

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _ranking_score(self, candidate: dict[str, Any]) -> float:
        final_score = candidate.get("final_score")
        if final_score is not None:
            return self._to_float(final_score, 0.0)
        return self._to_float(candidate.get("resume_score"), 0.0)

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        candidates: list[dict] = state.get("candidates") or []
        jd: dict = state.get("jd") or {}
        use_lyzr: bool = state.get("use_lyzr", True)

        if not candidates:
            raise ValueError("RankingAgent: 'candidates' list is required")
        if not jd:
            raise ValueError("RankingAgent: 'jd' dict is required")

        # If Lyzr not configured or not requested, use rule-based sort
        lyzr_ready = all([settings.LYZR_AGENT_URL, settings.LYZR_API_KEY,
                          settings.LYZR_AGENT_ID, settings.LYZR_USER_ID])

        if not use_lyzr or not lyzr_ready:
            return self._rule_based_rank(candidates, jd)

        return await self._lyzr_rank(candidates, jd)

    def _rule_based_rank(self, candidates: list[dict], jd: dict) -> dict[str, Any]:
        """Sort candidates by final_score (when present), else resume_score."""
        ranked = sorted(candidates, key=self._ranking_score, reverse=True)
        results = [
            {
                "rank": i + 1,
                "candidate_name": c.get("name", f"Candidate {i+1}"),
                "total_score": round(self._ranking_score(c), 1),
                "category": self._category(self._ranking_score(c)),
                "verdict": self._verdict(i),
                "biggest_gap": "",
                "differentiator": "",
                "one_line_reason": f"Rule-based score: {round(self._ranking_score(c), 1)}",
            }
            for i, c in enumerate(ranked)
        ]
        return {
            "ranking_result": {
                "jd_title": jd.get("title", ""),
                "results": results,
                "recruiter_summary": f"Ranked {len(results)} candidates by resume score.",
                "top_pick": results[0]["candidate_name"] if results else "",
                "source": "rule_based",
            }
        }

    async def _lyzr_rank(self, candidates: list[dict], jd: dict) -> dict[str, Any]:
        cooldown_left = _lyzr_cooldown_remaining()
        if cooldown_left > 0:
            logger.warning(
                "Lyzr ranking temporarily skipped for %.1fs due to recent outage: %s",
                cooldown_left,
                _lyzr_unavailable_detail(),
            )
            fallback = self._rule_based_rank(candidates, jd)
            if isinstance(fallback.get("ranking_result"), dict):
                fallback["ranking_result"]["source"] = "rule_based_lyzr_cooldown"
                fallback["ranking_result"]["lyzr_unavailable"] = _lyzr_unavailable_detail()
            return fallback

        prompt = self._build_lyzr_prompt(jd, candidates)
        session_id = settings.LYZR_SESSION_ID or f"{settings.LYZR_AGENT_ID}-{int(time.time() * 1000)}"
        body = {
            "user_id": settings.LYZR_USER_ID,
            "agent_id": settings.LYZR_AGENT_ID,
            "session_id": session_id,
            "message": prompt,
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=8.0)) as client:
                resp = await client.post(
                    settings.LYZR_AGENT_URL,
                    headers={"Content-Type": "application/json", "x-api-key": settings.LYZR_API_KEY},
                    json=body,
                )
            resp.raise_for_status()
            data = resp.json()
            _clear_lyzr_unavailable()
        except Exception as exc:
            _mark_lyzr_unavailable(str(exc))
            logger.warning("Lyzr ranking request failed, falling back to rule-based ranking: %s", exc)
            fallback = self._rule_based_rank(candidates, jd)
            if isinstance(fallback.get("ranking_result"), dict):
                fallback["ranking_result"]["source"] = "rule_based_lyzr_request_fallback"
                fallback["ranking_result"]["lyzr_error"] = str(exc)
            return fallback
        raw = (data.get("response") or data.get("message") or data.get("output") or "")
        raw = raw.replace("```json", "").replace("```", "").strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("Lyzr ranking returned malformed JSON, falling back to rule-based ranking: %s", exc)
            fallback = self._rule_based_rank(candidates, jd)
            if isinstance(fallback.get("ranking_result"), dict):
                fallback["ranking_result"]["source"] = "rule_based_lyzr_json_fallback"
                fallback["ranking_result"]["lyzr_parse_error"] = str(exc)
            return fallback
        if not isinstance(parsed, dict):
            logger.warning(
                "Lyzr ranking returned unexpected JSON shape (%s), falling back to rule-based ranking",
                type(parsed).__name__,
            )
            fallback = self._rule_based_rank(candidates, jd)
            if isinstance(fallback.get("ranking_result"), dict):
                fallback["ranking_result"]["source"] = "rule_based_lyzr_shape_fallback"
                fallback["ranking_result"]["lyzr_shape"] = type(parsed).__name__
            return fallback
        parsed["source"] = "lyzr"
        return {"ranking_result": parsed}

    @staticmethod
    def _build_lyzr_prompt(jd: dict, candidates: list[dict]) -> str:
        def _skills_to_text(skills_raw: Any) -> str:
            if isinstance(skills_raw, str):
                skills_list = [skills_raw] if skills_raw.strip() else []
            elif isinstance(skills_raw, list):
                skills_list = [str(s).strip() for s in skills_raw if str(s).strip()]
            else:
                skills_list = []
            return ", ".join(skills_list)

        cand_text = "\n\n".join(
            (
                f"Candidate {i+1}: {c.get('name','?')}\n"
                f"  Skills: {_skills_to_text(c.get('skills', []))}\n"
                f"  Experience: {c.get('experience_years', 0)} years\n"
                f"  Summary: {c.get('summary', '')}"
            )
            for i, c in enumerate(candidates)
        )
        return (
            f"JD Title: {jd.get('title')}\nRequired Skills: {', '.join(jd.get('required_skills', []))}\n"
            f"Experience: {jd.get('experience_min', 0)}-{jd.get('experience_max', 5)} years\n\n"
            f"Candidates:\n{cand_text}\n\n"
            f"Force-rank all {len(candidates)} candidates. Return JSON with fields: jd_title, results[], recruiter_summary, top_pick.\n"
            "Each result: rank, candidate_name, total_score(0-100), category(Strong Fit/Partial Fit/Not a Fit), "
            "verdict(First call/Second round/Third choice/Reject), biggest_gap, differentiator, one_line_reason."
        )

    @staticmethod
    def _category(score: float) -> str:
        if score >= 75: return "Strong Fit"
        if score >= 55: return "Partial Fit"
        return "Not a Fit"

    @staticmethod
    def _verdict(rank: int) -> str:
        return ["First call", "Second round", "Third choice"][min(rank, 2)] if rank < 3 else "Reject"

    async def health(self) -> dict[str, Any]:
        lyzr_ok = all([settings.LYZR_AGENT_URL, settings.LYZR_API_KEY])
        return {
            "agent": self.name,
            "status": "ok",
            "lyzr_configured": lyzr_ok,
            "fallback": "rule_based sort available if Lyzr is unavailable",
        }
