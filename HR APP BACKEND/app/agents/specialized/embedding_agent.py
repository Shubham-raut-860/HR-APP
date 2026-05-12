"""EmbeddingAgent — converts text to a float vector via Azure OpenAI embeddings."""
from __future__ import annotations
from typing import Any
import asyncio
from app.agents.base import BaseAgent
from app.services import gemini_service


class EmbeddingAgent(BaseAgent):
    name = "embedding_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        # Prefers 'embed_text'; falls back to 'text' (resume text) with a 6000-char cap
        text: str = state.get("embed_text") or (state.get("text") or "")[:6000]
        if not text.strip():
            return {"embedding": []}  # non-fatal — downstream agents guard for empty embeddings

        timeout_s = float(state.get("timeout_s", 25))
        try:
            embedding = await asyncio.wait_for(
                gemini_service.get_embedding(text),
                timeout=max(5.0, timeout_s),
            )
        except Exception:
            embedding = []
        return {"embedding": embedding}

    async def health(self) -> dict[str, Any]:
        ok = bool(gemini_service.openai_client)
        return {"agent": self.name, "status": "ok" if ok else "degraded"}
