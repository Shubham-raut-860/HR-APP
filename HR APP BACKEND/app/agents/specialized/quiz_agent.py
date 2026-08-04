"""
QuizAgent — generates quiz questions from a JD and evaluates submitted answers.

Operations (set `state["operation"]`):
  - "generate" — generate MCQ questions for skills
  - "validate" — produce a deterministic quality report for generated questions
  - "evaluate" — score a completed quiz submission
  - "parse_document" — parse MCQ questions from an uploaded document
"""
from __future__ import annotations
from typing import Any
import asyncio
import logging

from app.agents.base import BaseAgent
from app.config import settings
from app.services import gemini_service, scoring_service
from app.utils.quiz_validation import (
    QuestionValidationError,
    deduplicate_questions,
    difficulty_counts,
    validate_question,
)

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


class QuizGenerationError(ValueError):
    """Raised when quiz generation cannot produce the required valid question count."""


class QuizAgent(BaseAgent):
    name = "quiz_agent"
    model_key = "quiz_agent_generate"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        operation = state.get("operation", "generate")

        if operation == "generate":
            return await self._generate(state)
        elif operation == "validate":
            return await self._validate(state)
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
        timeout_s = max(5.0, min(float(state.get("timeout_s", 45)), 120.0))
        ai_timeout_s = max(3.0, min(timeout_s, float(settings.AI_REQUEST_TIMEOUT_SECONDS)))
        model = self.resolve_model(state, key="quiz_agent_generate")
        if bool(settings.AI_FAIL_FAST_ON_UNAVAILABLE) and not gemini_service.is_realtime_ai_available():
            raw_questions = _fallback_quiz_questions(skills, easy, medium, hard)
        else:
            try:
                raw_questions = await asyncio.wait_for(
                    gemini_service.generate_quiz_questions(
                        jd_text=jd_text,
                        skills=skills,
                        easy=easy,
                    medium=medium,
                    hard=hard,
                    model=model,
                ),
                    timeout=ai_timeout_s,
                )
            except Exception as exc:
                logger.warning("QuizAgent generate fallback activated: %s", exc)
                raw_questions = _fallback_quiz_questions(skills, easy, medium, hard)

        validated: list[dict[str, Any]] = []
        for raw_question in raw_questions or []:
            try:
                validated.append(validate_question(raw_question))
            except (QuestionValidationError, ValueError, AssertionError) as validation_error:
                logger.warning("Dropping invalid generated question: %s | %r", validation_error, raw_question)

        validated, _ = deduplicate_questions(validated)
        required_count = max(1, easy + medium + hard)
        if len(validated) < required_count:
            raise QuizGenerationError(
                f"Only {len(validated)}/{required_count} valid questions generated"
            )
        return {"questions": validated[:required_count]}

    async def _validate(self, state: dict[str, Any]) -> dict[str, Any]:
        questions: list[dict[str, Any]] = state.get("questions") or []
        skills = [str(skill).strip().lower() for skill in (state.get("skills") or []) if str(skill).strip()]
        expected_easy = max(0, int(state.get("easy", 0) or 0))
        expected_medium = max(0, int(state.get("medium", 0) or 0))
        expected_hard = max(0, int(state.get("hard", 0) or 0))
        expected_total = expected_easy + expected_medium + expected_hard

        issues: list[str] = []
        validated: list[dict[str, Any]] = []
        for index, raw_question in enumerate(questions):
            try:
                validated.append(validate_question(raw_question))
            except QuestionValidationError as exc:
                issues.append(f"question_{index + 1}: {exc}")

        unique_questions, duplicate_count = deduplicate_questions(validated)
        if duplicate_count:
            issues.append(f"{duplicate_count} duplicate question(s)")

        counts = difficulty_counts(unique_questions)
        expected_counts = {"easy": expected_easy, "medium": expected_medium, "hard": expected_hard}
        for difficulty, expected_count in expected_counts.items():
            if expected_count and counts.get(difficulty, 0) != expected_count:
                issues.append(
                    f"{difficulty} count {counts.get(difficulty, 0)} does not match expected {expected_count}"
                )

        if expected_total and len(unique_questions) != expected_total:
            issues.append(f"question count {len(unique_questions)} does not match expected {expected_total}")

        tagged_skills = {
            str(question.get("skill_tag") or "").strip().lower()
            for question in unique_questions
            if str(question.get("skill_tag") or "").strip()
        }
        covered_skills = {skill for skill in skills if skill in tagged_skills}
        skill_coverage_pct = round((len(covered_skills) / len(skills)) * 100.0, 1) if skills else None
        if skills and skill_coverage_pct is not None and skill_coverage_pct < 50.0:
            issues.append(f"skill coverage is low at {skill_coverage_pct}%")

        score = 100
        score -= min(40, len(issues) * 10)
        if expected_total:
            valid_ratio = len(unique_questions) / expected_total
            score -= int(max(0.0, 1.0 - valid_ratio) * 40)
        if skill_coverage_pct is not None:
            score -= int(max(0.0, 80.0 - skill_coverage_pct) / 4)
        quality_score = max(0, min(100, score))

        return {
            "quiz_validation": {
                "passed": quality_score >= 70 and not any("question count" in issue for issue in issues),
                "quality_score": quality_score,
                "question_count": len(questions),
                "valid_question_count": len(unique_questions),
                "difficulty_counts": dict(counts),
                "expected_difficulty_counts": expected_counts,
                "skill_coverage_pct": skill_coverage_pct,
                "issue_count": len(issues),
                "issues": issues[:20],
            }
        }

    async def _evaluate(self, state: dict[str, Any]) -> dict[str, Any]:
        questions: list[dict] = state.get("questions") or []
        answers: dict[str, int] = state.get("answers") or {}
        if not questions:
            raise ValueError("QuizAgent[evaluate]: 'questions' is required")

        raw_score, skill_breakdown, difficulty_breakdown = scoring_service.compute_quiz_score(
            questions, answers
        )
        max_score = sum(
            max(1, int(q.get("weight", 1)))
            for q in questions
            if isinstance(q.get("weight", 1), (int, float, str))
            and str(q.get("weight", 1)).strip() != ""
        )
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
        if bool(settings.AI_FAIL_FAST_ON_UNAVAILABLE) and not gemini_service.is_realtime_ai_available():
            return {"questions": []}
        model = self.resolve_model(state, key="quiz_agent_parse_document")
        questions = await asyncio.wait_for(
            gemini_service.parse_quiz_from_document(doc_text, model=model),
            timeout=max(3.0, float(settings.AI_REQUEST_TIMEOUT_SECONDS)),
        )
        return {"questions": questions}

    async def health(self) -> dict[str, Any]:
        ok = bool(gemini_service.openai_client)
        return {"agent": self.name, "status": "ok" if ok else "degraded"}
