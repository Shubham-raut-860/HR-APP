"""ResumeEnhancerAgent - AI rewrites resume content to improve ATS match for a specific JD."""
from __future__ import annotations

import asyncio
from typing import Any

from app.agents.base import BaseAgent
from app.services import gemini_service, scoring_service


class ResumeEnhancerAgent(BaseAgent):
    name = "resume_enhancer_agent"
    model_key = "resume_enhancer_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        resume_text: str = state.get("resume_text") or state.get("text", "")
        parsed_job: dict = state.get("parsed_job") or {}
        parsed_resume: dict = state.get("parsed_resume") or {}

        if not resume_text.strip():
            raise ValueError("ResumeEnhancerAgent: 'resume_text' is required")
        if not parsed_job:
            raise ValueError("ResumeEnhancerAgent: 'parsed_job' is required")

        must_have: list[str] = parsed_job.get("must_have_skills") or []
        good_to_have: list[str] = parsed_job.get("good_to_have_skills") or []
        job_title: str = parsed_job.get("title") or parsed_job.get("role") or "Role"
        job_description: str = parsed_job.get("description") or ""

        normalized_skills = parsed_resume.get("normalized_skills") or []
        current_score = scoring_service.skill_match_score(normalized_skills, must_have, good_to_have)
        missing_skills = [
            s for s in must_have
            if not scoring_service.semantic_skill_match(s, normalized_skills)
        ]

        timeout_s = float(state.get("timeout_s", 45))
        model = self.resolve_model(state)
        enhancement = await asyncio.wait_for(
            gemini_service.enhance_resume(
                resume_text=resume_text,
                job_title=job_title,
                must_have=must_have,
                good_to_have=good_to_have,
                job_description=job_description,
                current_score=current_score,
                missing_skills=missing_skills,
                model=model,
            ),
            timeout=max(5.0, timeout_s),
        )

        return {
            "enhancement_result": enhancement,
            "current_skill_match_pct": round(current_score, 1),
            "missing_must_have": missing_skills,
        }

    async def health(self) -> dict[str, Any]:
        ok = bool(gemini_service.openai_client)
        return {"agent": self.name, "status": "ok" if ok else "degraded"}
