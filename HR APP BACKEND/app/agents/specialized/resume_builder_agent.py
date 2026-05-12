"""ResumeBuilderAgent - builds an ATS-optimized resume from structured form data."""
from __future__ import annotations

import asyncio
from typing import Any

from app.agents.base import BaseAgent
from app.services import gemini_service


class ResumeBuilderAgent(BaseAgent):
    name = "resume_builder_agent"
    model_key = "resume_builder_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        candidate_data: dict = state.get("candidate_data") or {}
        target_role: str = state.get("target_role") or ""

        if not candidate_data:
            raise ValueError("ResumeBuilderAgent: 'candidate_data' dict is required")

        timeout_s = float(state.get("timeout_s", 45))
        model = self.resolve_model(state)
        built = await asyncio.wait_for(
            gemini_service.build_resume_from_form(
                candidate_data=candidate_data,
                target_role=target_role or "General Software Engineering",
                model=model,
            ),
            timeout=max(5.0, timeout_s),
        )
        return {"built_resume": built, "target_role": target_role}

    async def health(self) -> dict[str, Any]:
        ok = bool(gemini_service.openai_client)
        return {"agent": self.name, "status": "ok" if ok else "degraded"}
