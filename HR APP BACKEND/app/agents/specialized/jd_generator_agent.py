"""JDGeneratorAgent — generates a structured JD from role/params, with embedding-based cache."""
from __future__ import annotations
from typing import Any
from app.agents.base import BaseAgent
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

        # Build cache key and check cache
        cache_query = f"Role: {role} Exp: {exp_min}-{exp_max} Loc: {location} Ctx: {context}"
        embedding = await gemini_service.get_embedding(cache_query)
        cached = cache_service.get_cached_jd(embedding)
        if cached:
            return {"jd_data": cached, "cache_hit": True, "query_embedding": embedding}

        # Generate and cache
        jd_data = await gemini_service.generate_jd(
            role=role, exp_min=exp_min, exp_max=exp_max,
            location=location, context=context,
            model=model,
        )
        cache_service.cache_jd(embedding, jd_data)
        return {"jd_data": jd_data, "cache_hit": False, "query_embedding": embedding}

    async def health(self) -> dict[str, Any]:
        ok = bool(gemini_service.openai_client)
        return {"agent": self.name, "status": "ok" if ok else "degraded"}
