from __future__ import annotations

import asyncio
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings
from app.agents.specialized.quiz_agent import QuizAgent
from app.services import adk_shadow_service


def _enable_shadow(monkeypatch, *, mode: str = "record_only") -> None:
    monkeypatch.setattr(settings, "ADK_SHADOW_MODE_ENABLED", True)
    monkeypatch.setattr(settings, "ADK_SHADOW_EXECUTION_MODE", mode)
    monkeypatch.setattr(settings, "ADK_SHADOW_WORKFLOW_ALLOWLIST", "jd_generation,quiz_generation,quiz_validation")
    monkeypatch.setattr(settings, "ADK_SHADOW_SAMPLE_RATE", 1.0)
    monkeypatch.setattr(settings, "ADK_SHADOW_TIMEOUT_SECONDS", 1.0)


def _valid_questions() -> list[dict]:
    return [
        {
            "question_text": "What does FastAPI primarily help Python teams build?",
            "options": ["Images", "APIs", "Spreadsheets", "Video codecs"],
            "correct_answer": 1,
            "difficulty": "easy",
            "skill_tag": "FastAPI",
            "weight": 1,
        },
        {
            "question_text": "Which React concept is used to manage component-local state?",
            "options": ["Migrations", "Hooks", "Indexes", "Queues"],
            "correct_answer": 1,
            "difficulty": "medium",
            "skill_tag": "React",
            "weight": 2,
        },
        {
            "question_text": "Which PostgreSQL feature helps enforce relational integrity?",
            "options": ["Foreign keys", "CSS rules", "JWT claims", "DOM events"],
            "correct_answer": 0,
            "difficulty": "hard",
            "skill_tag": "PostgreSQL",
            "weight": 3,
        },
    ]


def test_adk_shadow_schedule_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ADK_SHADOW_MODE_ENABLED", False)

    async def _run() -> None:
        await adk_shadow_service.adk_shadow_recorder.clear()
        scheduled = adk_shadow_service.schedule_adk_shadow_observation(
            workflow="jd_generation",
            inputs={"role": "Backend Engineer"},
            production_output={"title": "Backend Engineer"},
        )
        await asyncio.sleep(0)
        summary = await adk_shadow_service.adk_shadow_recorder.summary()
        assert scheduled is False
        assert summary["events"] == 0

    asyncio.run(_run())


def test_adk_shadow_record_only_observation(monkeypatch) -> None:
    _enable_shadow(monkeypatch, mode="record_only")

    async def _run() -> None:
        await adk_shadow_service.adk_shadow_recorder.clear()
        scheduled = adk_shadow_service.schedule_adk_shadow_observation(
            workflow="quiz_generation",
            inputs={"jd_text": "Backend role", "skills": ["Python"]},
            production_output=[{"question_text": "Q?", "options": ["A"], "correct_answer": 0}],
            actor_id="user-1",
            entity_id="job-1",
            metadata={"email": "[email-redacted]", "route": "/quiz/generate"},
        )
        await asyncio.sleep(0.05)
        events = await adk_shadow_service.adk_shadow_recorder.recent()
        assert scheduled is True
        assert len(events) == 1
        assert events[0]["status"] == "recorded"
        assert events[0]["execution_mode"] == "record_only"
        assert "email_sha256" in events[0]["metadata"]
        assert "[email-redacted]" not in str(events[0])

    asyncio.run(_run())


def test_adk_shadow_runtime_compare_records_match(monkeypatch) -> None:
    _enable_shadow(monkeypatch, mode="runtime_compare")
    output = {"title": "Backend Engineer"}

    async def _fake_runtime(workflow: str, inputs: dict) -> dict:
        assert workflow == "jd_generation"
        return output

    monkeypatch.setattr(adk_shadow_service, "_run_shadow_runtime", _fake_runtime)

    async def _run() -> None:
        await adk_shadow_service.adk_shadow_recorder.clear()
        event = await adk_shadow_service.run_adk_shadow_observation(
            workflow="jd_generation",
            inputs={"role": "Backend Engineer", "experience_min": 2, "experience_max": 5},
            production_output=output,
        )
        assert event.status == "completed"
        assert event.match is True
        assert event.shadow_hash == event.production_hash

    asyncio.run(_run())


def test_adk_shadow_runtime_failure_is_captured(monkeypatch) -> None:
    _enable_shadow(monkeypatch, mode="runtime_compare")

    async def _fake_runtime(workflow: str, inputs: dict) -> dict:
        raise RuntimeError("shadow backend unavailable")

    monkeypatch.setattr(adk_shadow_service, "_run_shadow_runtime", _fake_runtime)

    async def _run() -> None:
        await adk_shadow_service.adk_shadow_recorder.clear()
        event = await adk_shadow_service.run_adk_shadow_observation(
            workflow="jd_generation",
            inputs={"role": "Backend Engineer", "experience_min": 2, "experience_max": 5},
            production_output={"title": "Backend Engineer"},
        )
        assert event.status == "failed"
        assert "shadow backend unavailable" in str(event.error)
        summary = await adk_shadow_service.adk_shadow_recorder.summary()
        assert summary["failed"] == 1

    asyncio.run(_run())


def test_adk_shadow_quiz_validation_records_quality_metadata(monkeypatch) -> None:
    _enable_shadow(monkeypatch, mode="runtime_compare")

    async def _run() -> None:
        await adk_shadow_service.adk_shadow_recorder.clear()
        event = await adk_shadow_service.run_adk_shadow_observation(
            workflow="quiz_validation",
            inputs={
                "jd_text": "Build APIs with FastAPI, React, and PostgreSQL.",
                "skills": ["FastAPI", "React", "PostgreSQL"],
                "questions": _valid_questions(),
                "easy": 1,
                "medium": 1,
                "hard": 1,
            },
            production_output={"accepted_by_persistence_validation": True, "question_count": 3},
        )
        assert event.status == "completed"
        assert event.match is True
        assert event.metadata["validation_passed"] is True
        assert event.metadata["quality_score"] >= 70
        assert event.metadata["valid_question_count"] == 3
        assert event.metadata["issue_count"] == 0

    asyncio.run(_run())


def test_quiz_agent_validation_flags_low_quality_questions() -> None:
    async def _run() -> None:
        agent = QuizAgent()
        result = await agent(
            {
                "operation": "validate",
                "skills": ["FastAPI", "React"],
                "easy": 1,
                "medium": 1,
                "hard": 0,
                "questions": [
                    {
                        "question_text": "Duplicate question?",
                        "options": ["A", "B", "C", "D"],
                        "correct_answer": 1,
                        "difficulty": "easy",
                        "skill_tag": "FastAPI",
                        "weight": 1,
                    },
                    {
                        "question_text": "Duplicate question?",
                        "options": ["A", "B", "C", "D"],
                        "correct_answer": 1,
                        "difficulty": "easy",
                        "skill_tag": "FastAPI",
                        "weight": 1,
                    },
                ],
            }
        )
        report = result["quiz_validation"]
        assert report["passed"] is False
        assert report["issue_count"] >= 1
        assert report["quality_score"] < 100

    asyncio.run(_run())
