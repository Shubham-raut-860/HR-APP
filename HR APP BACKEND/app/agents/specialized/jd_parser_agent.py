"""JDParserAgent — parses raw job description text into a structured JD dict."""
from __future__ import annotations
from typing import Any
import asyncio
from app.agents.base import BaseAgent
from app.config import settings
from app.services import gemini_service


def _fallback_parse_jd(jd_text: str) -> dict[str, Any]:
    lines = [ln.strip() for ln in (jd_text or "").splitlines() if ln.strip()]
    title = lines[0][:120] if lines else "Untitled Role"
    text_lower = jd_text.lower()
    must = []
    good = []
    for marker, bucket in (("must have", must), ("good to have", good)):
        idx = text_lower.find(marker)
        if idx >= 0:
            snippet = jd_text[idx: idx + 300]
            tail = snippet.split(":", 1)[-1]
            for tok in [t.strip(" .,\n\t-") for t in tail.replace("/", ",").split(",")]:
                if tok and len(tok) > 1:
                    bucket.append(tok)
    return {
        "title": title,
        "role": title,
        "description": jd_text[:4000],
        "must_have_skills": must[:25],
        "good_to_have_skills": good[:25],
        "experience_min": 0,
        "experience_max": 8,
        "location": "Remote",
    }


class JDParserAgent(BaseAgent):
    name = "jd_parser_agent"
    model_key = "jd_parser_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        # Accept extracted text from FileExtractionAgent (`text`) in addition to
        # explicit jd_text/job_description passed by callers.
        jd_text: str = state.get("jd_text") or state.get("job_description", "") or state.get("text", "")
        if not jd_text.strip():
            raise ValueError("JDParserAgent: 'jd_text' or 'job_description' is required in state")

        timeout_s = float(state.get("timeout_s", 45))
        ai_timeout_s = max(3.0, min(timeout_s, float(settings.AI_REQUEST_TIMEOUT_SECONDS)))
        model = self.resolve_model(state)
        if bool(settings.AI_FAIL_FAST_ON_UNAVAILABLE) and not gemini_service.is_realtime_ai_available():
            return {"parsed_job": _fallback_parse_jd(jd_text)}
        try:
            parsed_job = await asyncio.wait_for(
                gemini_service.parse_jd_from_document(jd_text, model=model),
                timeout=ai_timeout_s,
            )
        except Exception:
            parsed_job = _fallback_parse_jd(jd_text)
        return {"parsed_job": parsed_job}

    async def health(self) -> dict[str, Any]:
        ok = bool(gemini_service.openai_client)
        return {"agent": self.name, "status": "ok" if ok else "degraded"}
