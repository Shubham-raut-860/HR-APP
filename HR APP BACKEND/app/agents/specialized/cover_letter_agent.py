"""CoverLetterAgent - generates a personalized cover letter for a candidate and JD."""
from __future__ import annotations

import asyncio
from typing import Any

from app.agents.base import BaseAgent
from app.services import gemini_service


class CoverLetterAgent(BaseAgent):
    name = "cover_letter_agent"
    model_key = "cover_letter_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        parsed_resume: dict = state.get("parsed_resume") or {}
        parsed_job: dict = state.get("parsed_job") or {}
        candidate_name: str = state.get("candidate_name") or parsed_resume.get("name") or "Candidate"
        company_name: str = state.get("company_name") or "the company"

        if not parsed_job:
            raise ValueError("CoverLetterAgent: 'parsed_job' is required")

        timeout_s = float(state.get("timeout_s", 45))
        model = self.resolve_model(state)
        cover_letter = await asyncio.wait_for(
            gemini_service.generate_cover_letter(
                candidate_name=candidate_name,
                exp_years=float(parsed_resume.get("experience_years") or 0.0),
                skills=parsed_resume.get("skills") or parsed_resume.get("normalized_skills") or [],
                work_history=parsed_resume.get("work_experience") or [],
                education=parsed_resume.get("education") or [],
                company_name=company_name,
                job_title=parsed_job.get("title") or parsed_job.get("role") or "Role",
                must_have=parsed_job.get("must_have_skills") or [],
                job_description=parsed_job.get("description") or "",
                model=model,
            ),
            timeout=max(5.0, timeout_s),
        )

        return {"cover_letter": cover_letter}

    async def health(self) -> dict[str, Any]:
        ok = bool(gemini_service.openai_client)
        return {"agent": self.name, "status": "ok" if ok else "degraded"}
