from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
import asyncio

import pytest
from fastapi import HTTPException

from app.schemas.a2a import A2AAuditEvent, AgentMessage, AgentTask, ExecutionMetadata, TaskStatus, utcnow
from app.models import UserRole
from app.routers import a2a as a2a_router
from app.services import a2a_adapter
from app.services.adk_shadow_service import ADKShadowEvent, adk_shadow_recorder
from app.services.a2a_artifacts import build_result_artifact
from app.services.a2a_registry import (
    build_agent_card,
    get_agent_definition,
    list_agent_definitions,
)
from app.services.a2a_task_manager import A2ATaskManager, a2a_task_manager


def test_a2a_registry_exposes_only_low_risk_agents() -> None:
    exposed_ids = {definition.agent_id for definition in list_agent_definitions()}

    assert {
        "resume_parser_agent",
        "jd_parser_agent",
        "embedding_agent",
        "scoring_agent",
        "quiz_agent",
        "career_analyst_agent",
        "recruiter_assistant_agent",
    }.issubset(exposed_ids)
    assert "notification_agent" not in exposed_ids
    assert "ranking_agent" not in exposed_ids

    definition = get_agent_definition("scoring_agent")
    assert definition is not None
    card = build_agent_card(definition, "http://testserver")
    assert card.metadata["runtime"] == "hr_multi_agent_runtime"
    assert card.metadata["side_effects"] is False


def test_a2a_artifacts_redact_sensitive_fields_and_large_vectors() -> None:
    artifact = build_result_artifact(
        task_id="task-12345678",
        agent_id="resume_parser_agent",
        output={
            "parsed_resume": {
                "name": "Candidate",
                "email": "[email-redacted]",
                "phone": "+1-555-0100",
                "embedding": [0.1] * 128,
            }
        },
        output_keys=("parsed_resume",),
    )

    parsed_resume = artifact.data["parsed_resume"]  # type: ignore[index]
    assert parsed_resume["email"] == "[redacted]"
    assert parsed_resume["phone"] == "[redacted]"
    assert parsed_resume["embedding"]["dimensions"] == 128
    assert artifact.redacted is True


def test_a2a_task_manager_recovers_persisted_snapshot(tmp_path) -> None:
    snapshot_path = tmp_path / "a2a_tasks.json"
    manager = A2ATaskManager(persistence_enabled=True, persistence_path=snapshot_path)
    task = AgentTask(
        agent_id="jd_parser_agent",
        owner_id="owner-1",
        message=AgentMessage(content="Backend Engineer with Python"),
        execution=ExecutionMetadata(agent_id="jd_parser_agent"),
    )

    manager.create(task)
    artifact = build_result_artifact(
        task_id=task.id,
        agent_id=task.agent_id,
        output={"parsed_job": {"title": "Backend Engineer"}},
        output_keys=("parsed_job",),
    )
    manager.add_artifact(task.owner_id, artifact)
    manager.record_audit(
        A2AAuditEvent(
            actor_id="owner-1",
            actor_type="technical_admin",
            action="A2A_TASK_CREATE",
            resource="task",
            resource_id=task.id,
        )
    )

    restored = A2ATaskManager(persistence_enabled=True, persistence_path=snapshot_path)
    restored_task = restored.require_task(task.id, task.owner_id)
    restored_artifacts = restored.list_artifacts(task.id, task.owner_id)
    restored_audit = restored.recent_audit(limit=10)

    assert restored_task.id == task.id
    assert restored_task.artifact_ids == [artifact.id]
    assert restored_artifacts[0].data["parsed_job"]["title"] == "Backend Engineer"  # type: ignore[index]
    assert restored_audit[0].resource_id == task.id


def test_a2a_task_manager_does_not_recover_expired_snapshot_tasks(tmp_path) -> None:
    snapshot_path = tmp_path / "a2a_tasks.json"
    manager = A2ATaskManager(
        ttl_seconds=300,
        persistence_enabled=True,
        persistence_path=snapshot_path,
    )
    old_time = utcnow() - timedelta(seconds=600)
    task = AgentTask(
        agent_id="jd_parser_agent",
        owner_id="owner-1",
        message=AgentMessage(content="Old task"),
        execution=ExecutionMetadata(agent_id="jd_parser_agent"),
        created_at=old_time,
        updated_at=old_time,
    )

    manager.create(task)

    restored = A2ATaskManager(
        ttl_seconds=300,
        persistence_enabled=True,
        persistence_path=snapshot_path,
    )
    with pytest.raises(HTTPException) as exc_info:
        restored.require_task(task.id, task.owner_id)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_a2a_adapter_executes_through_multi_agent_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    async def _fake_run_agent(agent_id: str, state: dict):
        observed["agent_id"] = agent_id
        observed["state"] = state
        return {
            "parsed_job": {"title": "Backend Engineer", "must_have_skills": ["Python"]},
            "_agent_trace": [{"agent": agent_id, "elapsed_s": 0.01}],
        }

    monkeypatch.setattr(a2a_adapter.hr_multi_agent_runtime, "run_agent", _fake_run_agent)

    task = await a2a_adapter.execute_agent_message(
        agent_id="jd_parser_agent",
        message=AgentMessage(content="Backend Engineer with Python experience"),
        owner_id="test-owner",
        request=None,
    )

    assert observed["agent_id"] == "jd_parser_agent"
    assert observed["state"]["jd_text"] == "Backend Engineer with Python experience"  # type: ignore[index]
    assert task.status == TaskStatus.completed
    assert task.result is not None
    assert task.result.output["parsed_job"]["title"] == "Backend Engineer"  # type: ignore[index]
    assert len(a2a_task_manager.list_artifacts(task.id, "test-owner")) == 2


@pytest.mark.asyncio
async def test_a2a_adapter_rejects_internal_agents() -> None:
    with pytest.raises(Exception):
        await a2a_adapter.execute_agent_message(
            agent_id="notification_agent",
            message=AgentMessage(content="Draft email"),
            owner_id="test-owner",
            request=None,
        )


@pytest.mark.asyncio
async def test_a2a_router_requires_dedicated_technical_admin() -> None:
    allowed = SimpleNamespace(role=UserRole.admin, email="[email-redacted]")
    denied = SimpleNamespace(role=UserRole.admin, email="[email-redacted]")

    assert await a2a_router.require_technical_admin(allowed) is allowed
    with pytest.raises(HTTPException) as exc_info:
        await a2a_router.require_technical_admin(denied)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_a2a_router_allows_configured_service_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(a2a_router.settings, "A2A_SERVICE_TOKENS", "svc-token")

    actor = await a2a_router.require_a2a_actor(
        credentials=SimpleNamespace(credentials="svc-token"),
        db=None,
    )

    assert actor.actor_type == "service_token"
    assert actor.owner_id.startswith("service:")


@pytest.mark.asyncio
async def test_a2a_router_exposes_adk_shadow_observability(monkeypatch: pytest.MonkeyPatch) -> None:
    await adk_shadow_recorder.clear()
    monkeypatch.setattr(a2a_router.settings, "ADK_SHADOW_MODE_ENABLED", True)
    monkeypatch.setattr(a2a_router.settings, "ADK_SHADOW_EXECUTION_MODE", "runtime_compare")
    await adk_shadow_recorder.add(
        ADKShadowEvent(
            workflow="quiz_generation",
            status="completed",
            started_at="2026-06-10T00:00:00+00:00",
            latency_ms=42.5,
            production_hash="prod",
            shadow_hash="shadow",
            match=False,
            execution_mode="runtime_compare",
            entity_id="quiz-1",
            metadata={"source": "test"},
        )
    )

    summary = await a2a_router.get_adk_shadow_summary(a2a_router.A2AActor(owner_id="owner", actor_type="technical_admin"))
    recent = await a2a_router.get_adk_shadow_recent(
        limit=10,
        _=a2a_router.A2AActor(owner_id="owner", actor_type="technical_admin"),
    )

    assert summary["enabled"] is True
    assert summary["execution_mode"] == "runtime_compare"
    assert summary["events"] == 1
    assert summary["completed"] == 1
    assert summary["compared"] == 1
    assert summary["match_rate_pct"] == 0.0
    assert recent["events"][0]["workflow"] == "quiz_generation"
    assert recent["events"][0]["metadata"] == {"source": "test"}
    await adk_shadow_recorder.clear()


@pytest.mark.asyncio
async def test_a2a_router_exposes_adk_promotion_status(monkeypatch: pytest.MonkeyPatch) -> None:
    await adk_shadow_recorder.clear()
    monkeypatch.setattr(a2a_router.settings, "ADK_PROMOTION_ENABLED", True)
    monkeypatch.setattr(a2a_router.settings, "ADK_PROMOTION_WORKFLOW_ALLOWLIST", "quiz_generation")
    monkeypatch.setattr(a2a_router.settings, "ADK_PROMOTION_FALLBACK_TO_LEGACY", True)
    monkeypatch.setattr(a2a_router.settings, "ADK_PROMOTION_TIMEOUT_SECONDS", 12.0)
    monkeypatch.setattr(a2a_router.settings, "ADK_PROMOTION_MIN_QUIZ_QUALITY_SCORE", 75.0)
    await adk_shadow_recorder.add(
        ADKShadowEvent(
            workflow="quiz_generation",
            status="completed",
            started_at="2026-06-10T00:00:00+00:00",
            latency_ms=40.0,
            execution_mode="promoted",
            entity_id="job-1",
            metadata={"quality_score": 88},
        )
    )
    await adk_shadow_recorder.add(
        ADKShadowEvent(
            workflow="quiz_generation",
            status="fallback",
            started_at="2026-06-10T00:01:00+00:00",
            latency_ms=50.0,
            execution_mode="promoted",
            entity_id="job-2",
            error="quality gate",
        )
    )

    status_payload = await a2a_router.get_adk_promotion_status(
        limit=10,
        _=a2a_router.A2AActor(owner_id="owner", actor_type="technical_admin"),
    )

    assert status_payload["enabled"] is True
    assert status_payload["allowlist"] == ["quiz_generation"]
    assert status_payload["effective_workflows"] == {"quiz_generation": True}
    assert status_payload["fallback_to_legacy"] is True
    assert status_payload["timeout_seconds"] == 12.0
    assert status_payload["min_quiz_quality_score"] == 75.0
    assert status_payload["recent_counts"]["completed"] == 1
    assert status_payload["recent_counts"]["fallback"] == 1
    assert len(status_payload["recent"]) == 2
    await adk_shadow_recorder.clear()


@pytest.mark.asyncio
async def test_a2a_async_queue_completes_task(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_run_agent(agent_id: str, state: dict):
        await asyncio.sleep(0.01)
        return {
            "parsed_job": {"title": "Backend Engineer"},
            "_agent_trace": [{"agent": agent_id, "elapsed_s": 0.01}],
        }

    monkeypatch.setattr(a2a_adapter.hr_multi_agent_runtime, "run_agent", _fake_run_agent)

    task = a2a_adapter.queue_agent_message(
        agent_id="jd_parser_agent",
        message=AgentMessage(content="Backend Engineer with Python experience"),
        owner_id="async-owner",
    )
    assert task.status == TaskStatus.queued

    for _ in range(20):
        current = a2a_task_manager.require_task(task.id, "async-owner")
        if current.status == TaskStatus.completed:
            break
        await asyncio.sleep(0.02)

    current = a2a_task_manager.require_task(task.id, "async-owner")
    assert current.status == TaskStatus.completed
    assert current.result is not None
    assert current.result.output["parsed_job"]["title"] == "Backend Engineer"  # type: ignore[index]


@pytest.mark.asyncio
async def test_a2a_resume_screening_orchestrator_runs_multiple_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def _fake_run_agent(agent_id: str, state: dict):
        calls.append(agent_id)
        if agent_id == "resume_parser_agent":
            return {"parsed_resume": {"name": "Candidate", "normalized_skills": ["Python"]}, "_agent_trace": [{"agent": agent_id}]}
        if agent_id == "jd_parser_agent":
            return {"parsed_job": {"title": "Engineer", "must_have_skills": ["Python"]}, "_agent_trace": [{"agent": agent_id}]}
        if agent_id == "embedding_agent":
            return {"embedding": [0.1, 0.2], "_agent_trace": [{"agent": agent_id}]}
        if agent_id == "scoring_agent":
            return {"score_result": {"resume_score": 91}, "_agent_trace": [{"agent": agent_id}]}
        raise AssertionError(agent_id)

    monkeypatch.setattr(a2a_adapter.hr_multi_agent_runtime, "run_agent", _fake_run_agent)

    task = await a2a_adapter.execute_agent_message(
        agent_id="resume_screening_orchestrator",
        message=AgentMessage(
            content="screen",
            context={
                "resume_text": "Candidate has Python and API experience.",
                "jd_text": "Engineer with Python experience required.",
            },
        ),
        owner_id="workflow-owner",
    )

    assert task.status == TaskStatus.completed
    assert calls.count("embedding_agent") == 2
    assert "scoring_agent" in calls
    assert task.result is not None
    assert task.result.output["score_result"]["resume_score"] == 91  # type: ignore[index]


@pytest.mark.asyncio
async def test_a2a_recruiter_assistant_accepts_sanitized_snapshot() -> None:
    task = await a2a_adapter.execute_agent_message(
        agent_id="recruiter_assistant_agent",
        message=AgentMessage(
            content="What should I do next?",
            context={
                "snapshot": {
                    "data_scope": "recruiter_owned",
                    "metrics": {
                        "total_jobs": 1,
                        "active_jobs": 1,
                        "total_candidates": 1,
                        "strong_candidates": 1,
                        "completed_assessments": 0,
                    },
                    "jobs": [{"id": "job-1", "title": "Backend Engineer", "candidate_count": 1}],
                    "top_candidates": [{"id": "candidate-1", "name": "Candidate", "final_score": 90}],
                    "risks": [],
                }
            },
        ),
        owner_id="workflow-owner",
    )

    assert task.status == TaskStatus.completed
    assert task.result is not None
    assert task.result.output["recruiter_copilot"]["data_scope"] == "recruiter_owned"  # type: ignore[index]
