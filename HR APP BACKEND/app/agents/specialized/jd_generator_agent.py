"""JDGeneratorAgent — generates a structured JD from role/params, with embedding-based cache."""
from __future__ import annotations
from typing import Any
import asyncio
from app.agents.base import BaseAgent
from app.config import settings
from app.services import gemini_service, cache_service


class JDGeneratorAgent(BaseAgent):
    name = "jd_generator_agent"
    model_key = "jd_generator_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        role: str = state.get("role", "")
        if not role.strip():
            raise ValueError("JDGeneratorAgent: 'role' is required in state")

        exp_min: int = int(state.get("experience_min") or 0)
        exp_max: int = int(state.get("experience_max") or 5)
        location: str = state.get("location") or "Remote"
        context: str = state.get("additional_context") or ""
        model = self.resolve_model(state)
        timeout_s = max(5.0, float(state.get("timeout_s", 25)))
        ai_timeout_s = max(3.0, min(timeout_s, float(settings.AI_REQUEST_TIMEOUT_SECONDS)))
        ai_available = gemini_service.is_realtime_ai_available()

        # Build cache key and check cache
        cache_query = f"Role: {role} Exp: {exp_min}-{exp_max} Loc: {location} Ctx: {context}"
        embedding: list[float] = []
        cache_lookup_timeout_s = min(2.5, max(0.8, ai_timeout_s * 0.15))
        if not bool(settings.AI_FAIL_FAST_ON_UNAVAILABLE) or ai_available:
            try:
                embedding = await asyncio.wait_for(
                    gemini_service.get_embedding(cache_query),
                    timeout=cache_lookup_timeout_s,
                )
            except Exception:
                embedding = []
        if embedding:
            cached = cache_service.get_cached_jd(embedding)
            if cached:
                return {"jd_data": cached, "cache_hit": True, "query_embedding": embedding}

        # Generate and cache
        if bool(settings.AI_FAIL_FAST_ON_UNAVAILABLE) and not ai_available:
            jd_data = {
                "title": role,
                "role": role,
                "description": (
                    f"{role} role based in {location}. "
                    f"Experience range: {exp_min}-{exp_max} years."
                ),
                "must_have_skills": [],
                "good_to_have_skills": [],
                "experience_min": exp_min,
                "experience_max": exp_max,
                "location": location,
            }
        else:
            jd_data = await asyncio.wait_for(
                gemini_service.generate_jd(
                    role=role, exp_min=exp_min, exp_max=exp_max,
                    location=location, context=context,
                    model=model,
                ),
                timeout=ai_timeout_s,
            )
        if embedding:
            cache_service.cache_jd(embedding, jd_data)
        return {"jd_data": jd_data, "cache_hit": False, "query_embedding": embedding}

    async def health(self) -> dict[str, Any]:
        ok = bool(gemini_service.openai_client)
        return {"agent": self.name, "status": "ok" if ok else "degraded"}
