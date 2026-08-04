"""ResumeParserAgent — uses Azure OpenAI to parse raw resume text into structured data."""
from __future__ import annotations
from typing import Any
import asyncio
from app.agents.base import BaseAgent
from app.config import settings
from app.services import gemini_service
from app.services import resume_fallback_parser


class ResumeParserAgent(BaseAgent):
    name = "resume_parser_agent"
    model_key = "resume_parser_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        text: str = state.get("text") or state.get("resume_text", "")
        if not text.strip():
            raise ValueError("ResumeParserAgent: 'text' (resume text) is required in state")

        timeout_s = float(state.get("timeout_s", 45))
        ai_timeout_s = max(3.0, min(timeout_s, float(settings.AI_REQUEST_TIMEOUT_SECONDS)))
        model = self.resolve_model(state)
        if bool(settings.AI_FAIL_FAST_ON_UNAVAILABLE) and not gemini_service.is_realtime_ai_available():
            parsed = resume_fallback_parser.coerce_parsed_resume(None, text=text)
            return {"parsed_resume": parsed}
        try:
            parsed = await asyncio.wait_for(
                gemini_service.parse_resume(text, model=model),
                timeout=ai_timeout_s,
            )
        except Exception:
            parsed = resume_fallback_parser.coerce_parsed_resume(None, text=text)
        else:
            parsed = resume_fallback_parser.coerce_parsed_resume(
                parsed if isinstance(parsed, dict) else None,
                text=text,
            )
        return {"parsed_resume": parsed}

    async def health(self) -> dict[str, Any]:
        ok = bool(gemini_service.openai_client)
        return {"agent": self.name, "status": "ok" if ok else "degraded",
                "note": "Azure OpenAI client not configured" if not ok else None}
