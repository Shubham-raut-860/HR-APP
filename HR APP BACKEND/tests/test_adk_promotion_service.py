from __future__ import annotations

import asyncio
from pathlib import Path
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings
from app.services import adk_promotion_service
from app.services.adk_shadow_service import adk_shadow_recorder


def _enable_promotion(monkeypatch: pytest.MonkeyPatch, *, fallback: bool = True) -> None:
    monkeypatch.setattr(settings, "ADK_PROMOTION_ENABLED", True)
    monkeypatch.setattr(settings, "ADK_PROMOTION_WORKFLOW_ALLOWLIST", "quiz_generation")
    monkeypatch.setattr(settings, "ADK_PROMOTION_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(settings, "ADK_PROMOTION_FALLBACK_TO_LEGACY", fallback)
    monkeypatch.setattr(settings, "ADK_PROMOTION_MIN_QUIZ_QUALITY_SCORE", 70.0)


def _questions() -> list[dict]:
    return [
        {
            "question_text": "What does FastAPI primarily help teams build?",
            "options": ["APIs", "Images", "Spreadsheets", "Fonts"],
            "correct_answer": 0,
            "difficulty": "easy",
            "skill_tag": "FastAPI",
            "weight": 1,
        }
    ]


def test_adk_promotion_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ADK_PROMOTION_ENABLED", False)

    async def _unexpected(*args, **kwargs):
        raise AssertionError("promotion runtime should not be called when disabled")

    monkeypatch.setattr(adk_promotion_service.hr_multi_agent_runtime, "generate_quiz", _unexpected)

    async def _run() -> None:
        await adk_shadow_recorder.clear()
        result = await adk_promotion_service.try_promoted_quiz_generation(
            jd_text="Backend role",
            skills=["FastAPI"],
            easy=1,
            medium=0,
            hard=0,
        )
        events = await adk_shadow_recorder.recent()
        assert result is None
        assert events == []

    asyncio.run(_run())


def test_adk_promotion_returns_validated_quiz_output(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_promotion(monkeypatch)
    generated = _questions()

    async def _generate(**kwargs):
        return generated

    async def _validate(**kwargs):
        return {
            "passed": True,
            "quality_score": 92,
            "valid_question_count": 1,
            "issue_count": 0,
        }

    monkeypatch.setattr(adk_promotion_service.hr_multi_agent_runtime, "generate_quiz", _generate)
    monkeypatch.setattr(adk_promotion_service.hr_multi_agent_runtime, "validate_quiz", _validate)

    async def _run() -> None:
        await adk_shadow_recorder.clear()
        result = await adk_promotion_service.try_promoted_quiz_generation(
            jd_text="Backend role",
            skills=["FastAPI"],
            easy=1,
            medium=0,
            hard=0,
            actor_id="user-1",
            entity_id="job-1",
        )
        events = await adk_shadow_recorder.recent()
        assert result is not None
        assert result.output == generated
        assert events[0]["status"] == "completed"
        assert events[0]["execution_mode"] == "promoted"
        assert events[0]["metadata"]["quality_score"] == 92.0

    asyncio.run(_run())


def test_adk_promotion_quality_gate_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_promotion(monkeypatch, fallback=True)

    async def _generate(**kwargs):
        return _questions()

    async def _validate(**kwargs):
        return {
            "passed": False,
            "quality_score": 45,
            "valid_question_count": 1,
            "issue_count": 2,
        }

    monkeypatch.setattr(adk_promotion_service.hr_multi_agent_runtime, "generate_quiz", _generate)
    monkeypatch.setattr(adk_promotion_service.hr_multi_agent_runtime, "validate_quiz", _validate)

    async def _run() -> None:
        await adk_shadow_recorder.clear()
        result = await adk_promotion_service.try_promoted_quiz_generation(
            jd_text="Backend role",
            skills=["FastAPI"],
            easy=1,
            medium=0,
            hard=0,
        )
        events = await adk_shadow_recorder.recent()
        assert result is None
        assert events[0]["status"] == "fallback"
        assert "quality gate" in str(events[0]["error"])

    asyncio.run(_run())


def test_adk_promotion_strict_mode_raises_without_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_promotion(monkeypatch, fallback=False)

    async def _generate(**kwargs):
        raise RuntimeError("runtime unavailable")

    monkeypatch.setattr(adk_promotion_service.hr_multi_agent_runtime, "generate_quiz", _generate)

    async def _run() -> None:
        await adk_shadow_recorder.clear()
        with pytest.raises(RuntimeError, match="runtime unavailable"):
            await adk_promotion_service.try_promoted_quiz_generation(
                jd_text="Backend role",
                skills=["FastAPI"],
                easy=1,
                medium=0,
                hard=0,
            )
        events = await adk_shadow_recorder.recent()
        assert events[0]["status"] == "failed"
        assert events[0]["metadata"]["fallback_to_legacy"] is False

    asyncio.run(_run())
