"""
QuizAgent — generates quiz questions from a JD and evaluates submitted answers.

Operations (set `state["operation"]`):
  - "generate" — generate MCQ questions for skills
  - "evaluate" — score a completed quiz submission
  - "parse_document" — parse MCQ questions from an uploaded document
"""
from __future__ import annotations
from typing import Any
import asyncio
import logging

from app.agents.base import BaseAgent
from app.services import gemini_service, scoring_service

logger = logging.getLogger(__name__)


def _fallback_quiz_questions(skills: list[str], easy: int, medium: int, hard: int) -> list[dict[str, Any]]:
    """Deterministic fallback to avoid quiz-generation hard failures/timeouts."""
    total = max(1, int(easy) + int(medium) + int(hard))
    pool = [s.strip() for s in (skills or []) if isinstance(s, str) and s.strip()] or ["general software engineering"]
    diff_seq = (["easy"] * max(0, int(easy))) + (["medium"] * max(0, int(medium))) + (["hard"] * max(0, int(hard)))
    if not diff_seq:
        diff_seq = ["easy"] * total

    rows: list[dict[str, Any]] = []
    for i in range(total):
        skill = pool[i % len(pool)]
        difficulty = diff_seq[i] if i < len(diff_seq) else "medium"
        rows.append(
            {
                "question_text": f"What best describes your practical understanding of {skill}?",
                "options": [
                    f"No working experience with {skill}",
                    f"Used {skill} in one small project",
                    f"Applied {skill} across multiple production tasks",
                    f"Led architecture decisions and mentoring around {skill}",
                ],
                "correct_answer": 2,
                "difficulty": difficulty,
                "skill_tag": skill,
                "weight": 1 if difficulty == "easy" else 2 if difficulty == "medium" else 3,
            }
        )
    return rows


class QuizAgent(BaseAgent):
    name = "quiz_agent"
    model_key = "quiz_agent_generate"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        operation = state.get("operation", "generate")

        if operation == "generate":
            return await self._generate(state)
        elif operation == "evaluate":
            return await self._evaluate(state)
        elif operation == "parse_document":
            return await self._parse_document(state)
        else:
            raise ValueError(f"QuizAgent: unknown operation '{operation}'")

    async def _generate(self, state: dict[str, Any]) -> dict[str, Any]:
        jd_text: str = state.get("jd_text") or state.get("job_description", "")
        skills: list[str] = state.get("skills") or []
        easy = int(state.get("easy", 8))
        medium = int(state.get("medium", 8))
        hard = int(state.get("hard", 4))
        timeout_s = float(state.get("timeout_s", 45))
        model = self.resolve_model(state, key="quiz_agent_generate")
        try:
            questions = await asyncio.wait_for(
                gemini_service.generate_quiz_questions(
                    jd_text=jd_text,
                    skills=skills,
                    easy=easy,
                    medium=medium,
                    hard=hard,
                    model=model,
                ),
                timeout=max(5.0, timeout_s),
            )
            if not questions:
                questions = _fallback_quiz_questions(skills, easy, medium, hard)
        except Exception as exc:
            logger.warning("QuizAgent generate fallback activated: %s", exc)
            questions = _fallback_quiz_questions(skills, easy, medium, hard)
        return {"questions": questions}

    async def _evaluate(self, state: dict[str, Any]) -> dict[str, Any]:
        questions: list[dict] = state.get("questions") or []
        answers: dict[str, int] = state.get("answers") or {}
        if not questions:
            raise ValueError("QuizAgent[evaluate]: 'questions' is required")

        raw_score, skill_breakdown, difficulty_breakdown = scoring_service.compute_quiz_score(
            questions, answers
        )
        max_score = sum(q.get("weight", 1) for q in questions)
        pct = round((raw_score / max_score * 100) if max_score else 0.0, 1)

        return {
            "quiz_raw_score": raw_score,
            "quiz_max_score": max_score,
            "quiz_pct": pct,
            "quiz_skill_breakdown": skill_breakdown,
            "quiz_difficulty_breakdown": difficulty_breakdown,
        }

    async def _parse_document(self, state: dict[str, Any]) -> dict[str, Any]:
        doc_text: str = state.get("doc_text", "")
        if not doc_text.strip():
            raise ValueError("QuizAgent[parse_document]: 'doc_text' is required")
        model = self.resolve_model(state, key="quiz_agent_parse_document")
        questions = await gemini_service.parse_quiz_from_document(doc_text, model=model)
        return {"questions": questions}

    async def health(self) -> dict[str, Any]:
        ok = bool(gemini_service.openai_client)
        return {"agent": self.name, "status": "ok" if ok else "degraded"}
