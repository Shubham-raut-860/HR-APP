"""CodeEvaluationAgent — AI-evaluates a candidate's code submission against a problem statement."""
from __future__ import annotations
import asyncio
from typing import Any

from app.agents.base import BaseAgent
from app.services import gemini_service


class CodeEvaluationAgent(BaseAgent):
    name = "code_evaluation_agent"
    model_key = "code_evaluation_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        problem: str = state.get("problem_statement", "")
        code: str = state.get("user_code", "")
        language: str = state.get("language", "python")

        if not code.strip():
            raise ValueError("CodeEvaluationAgent: 'user_code' is required")
        if not problem.strip():
            raise ValueError("CodeEvaluationAgent: 'problem_statement' is required")

        # 60-second hard timeout — mirrors quiz.py behaviour
        model = self.resolve_model(state)
        result = await asyncio.wait_for(
            gemini_service.evaluate_code_submission(problem, code, language, model=model),
            timeout=60.0,
        )
        return {"code_eval_result": result}

    async def health(self) -> dict[str, Any]:
        ok = bool(gemini_service.openai_client)
        return {"agent": self.name, "status": "ok" if ok else "degraded"}
