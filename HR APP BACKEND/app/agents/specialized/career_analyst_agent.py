"""CareerAnalystAgent - generates career-path analysis for candidate planning."""
from __future__ import annotations

import asyncio
from typing import Any

from app.agents.base import BaseAgent
from app.services import gemini_service


class CareerAnalystAgent(BaseAgent):
    name = "career_analyst_agent"
    model_key = "career_analyst_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        candidate_name = state.get("candidate_name") or "Candidate"
        target_role = state.get("target_role") or "Software Engineer"
        timeout_s = float(state.get("timeout_s", 45))
        model = self.resolve_model(state)

        result = await asyncio.wait_for(
            gemini_service.analyze_career_path(
                candidate_name=candidate_name,
                exp_years=float(state.get("experience_years") or state.get("exp_years") or 0.0),
                skills=state.get("skills") or [],
                work_history=state.get("work_history") or [],
                education=state.get("education") or [],
                career_breaks=state.get("career_breaks") or [],
                target_role=target_role,
                model=model,
            ),
            timeout=max(5.0, timeout_s),
        )
        return {"career_analysis": result}

    async def health(self) -> dict[str, Any]:
        ok = bool(gemini_service.openai_client)
        return {"agent": self.name, "status": "ok" if ok else "degraded"}

