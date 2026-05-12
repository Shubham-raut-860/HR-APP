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
from typing import Any

import httpx

from app.agents.base import BaseAgent
from app.config import settings


class RankingAgent(BaseAgent):
    name = "ranking_agent"

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
        """Sort candidates by their pre-computed resume_score descending."""
        ranked = sorted(candidates, key=lambda c: c.get("resume_score", 0), reverse=True)
        results = [
            {
                "rank": i + 1,
                "candidate_name": c.get("name", f"Candidate {i+1}"),
                "total_score": round(c.get("resume_score", 0), 1),
                "category": self._category(c.get("resume_score", 0)),
                "verdict": self._verdict(i),
                "biggest_gap": "",
                "differentiator": "",
                "one_line_reason": f"Rule-based score: {round(c.get('resume_score', 0), 1)}",
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
        prompt = self._build_lyzr_prompt(jd, candidates)
        session_id = settings.LYZR_SESSION_ID or f"{settings.LYZR_AGENT_ID}-{int(time.time() * 1000)}"
        body = {
            "user_id": settings.LYZR_USER_ID,
            "agent_id": settings.LYZR_AGENT_ID,
            "session_id": session_id,
            "message": prompt,
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            resp = await client.post(
                settings.LYZR_AGENT_URL,
                headers={"Content-Type": "application/json", "x-api-key": settings.LYZR_API_KEY},
                json=body,
            )
        resp.raise_for_status()
        data = resp.json()
        raw = (data.get("response") or data.get("message") or data.get("output") or "")
        raw = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(raw)
        parsed["source"] = "lyzr"
        return {"ranking_result": parsed}

    @staticmethod
    def _build_lyzr_prompt(jd: dict, candidates: list[dict]) -> str:
        cand_text = "\n\n".join(
            f"Candidate {i+1}: {c.get('name','?')}\n  Skills: {', '.join(c.get('skills', []))}\n  Experience: {c.get('experience_years', 0)} years\n  Summary: {c.get('summary', '')}"
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
