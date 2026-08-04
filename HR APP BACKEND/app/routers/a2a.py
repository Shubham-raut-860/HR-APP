from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserRole
from app.schemas.a2a import (
    A2AAuditEvent,
    A2AAuditResponse,
    AgentArtifact,
    AgentCard,
    AgentDirectoryResponse,
    AgentMessage,
    AgentTask,
    CreateTaskRequest,
    EvaluationRunRequest,
    TaskExecutionMode,
    TaskStatusResponse,
)
from app.database import get_db
from app.services.a2a_adapter import (
    execute_agent_message,
    queue_agent_message,
    request_meta_from_request,
)
from app.services.a2a_registry import (
    build_agent_card,
    build_platform_agent_card,
    get_agent_definition,
    list_agent_definitions,
)
from app.services.a2a_task_manager import a2a_task_manager
from app.services.auth_service import get_current_user, log_action, require_hr
from app.services.adk_shadow_service import adk_shadow_recorder
from app.services.adk_promotion_service import promotion_enabled_for
from app.config import settings

router = APIRouter(tags=["A2A"])
_optional_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class A2AActor:
    owner_id: str
    actor_type: str
    user: User | None = None


def _configured_service_tokens() -> set[str]:
    return {
        token.strip()
        for token in (settings.A2A_SERVICE_TOKENS or "").split(",")
        if token.strip()
    }


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _owner_id(user: User) -> str:
    return str(user.id)


def _owner_id_from_token(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    return f"service:{digest}"


async def require_technical_admin(user: User = Depends(require_hr)) -> User:
    if not settings.TECHNICAL_ADMIN_LOGIN_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Technical admin console is disabled")
    configured_email = (settings.TECHNICAL_ADMIN_EMAIL or "").strip().lower()
    if user.role != UserRole.admin or user.email.lower() != configured_email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Technical admin access required")
    return user


async def require_a2a_actor(
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    db: AsyncSession = Depends(get_db),
) -> A2AActor:
    if credentials and credentials.credentials:
        token = credentials.credentials.strip()
        if token in _configured_service_tokens():
            return A2AActor(owner_id=_owner_id_from_token(token), actor_type="service_token")
        user = await get_current_user(credentials=credentials, db=db)
        await require_technical_admin(user)
        return A2AActor(owner_id=_owner_id(user), actor_type="technical_admin", user=user)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="A2A bearer token required",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _record_a2a_audit(
    *,
    actor: A2AActor,
    action: str,
    resource: str,
    resource_id: str | None = None,
    detail: dict[str, Any] | None = None,
    db: AsyncSession | None = None,
) -> None:
    a2a_task_manager.record_audit(
        A2AAuditEvent(
            actor_id=actor.owner_id,
            actor_type=actor.actor_type,  # type: ignore[arg-type]
            action=action,
            resource=resource,
            resource_id=resource_id,
            detail=detail or {},
        )
    )
    if db is not None and actor.user is not None:
        try:
            await log_action(
                db,
                actor.user.id,
                action,
                resource,
                resource_id[:36] if resource_id else None,
                details=detail or {},
            )
            await db.commit()
        except Exception:
            await db.rollback()


@router.get("/.well-known/agent-card.json", response_model=AgentCard)
async def well_known_agent_card(request: Request) -> AgentCard:
    return build_platform_agent_card(_base_url(request))


@router.get("/a2a/agents", response_model=AgentDirectoryResponse)
async def list_a2a_agents(
    request: Request,
    include_internal: bool = Query(default=False),
    actor: A2AActor = Depends(require_a2a_actor),
) -> AgentDirectoryResponse:
    can_view_internal = actor.actor_type == "technical_admin"
    definitions = list_agent_definitions(include_internal=include_internal and can_view_internal)
    cards = [build_agent_card(definition, _base_url(request)) for definition in definitions]
    internal_count = len([card for card in cards if card.visibility == "internal"])
    return AgentDirectoryResponse(agents=cards, internal_count=internal_count)


@router.get("/a2a/agents/{agent_id}", response_model=AgentCard)
async def get_a2a_agent(agent_id: str, request: Request, _: A2AActor = Depends(require_a2a_actor)) -> AgentCard:
    definition = get_agent_definition(agent_id)
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="A2A agent not found")
    return build_agent_card(definition, _base_url(request))


@router.get("/a2a/agents/{agent_id}/card", response_model=AgentCard)
async def get_a2a_agent_card(agent_id: str, request: Request, actor: A2AActor = Depends(require_a2a_actor)) -> AgentCard:
    return await get_a2a_agent(agent_id, request, actor)


@router.post("/a2a/agents/{agent_id}/message", response_model=AgentTask)
async def send_a2a_agent_message(
    agent_id: str,
    message: AgentMessage,
    request: Request,
    async_execution: bool = Query(default=False),
    actor: A2AActor = Depends(require_a2a_actor),
    db: AsyncSession = Depends(get_db),
) -> AgentTask:
    if async_execution:
        task = queue_agent_message(
            agent_id=agent_id,
            message=message,
            owner_id=actor.owner_id,
            request_meta=request_meta_from_request(request),
        )
    else:
        task = await execute_agent_message(
            agent_id=agent_id,
            message=message,
            owner_id=actor.owner_id,
            request=request,
        )
    await _record_a2a_audit(
        actor=actor,
        action="A2A_MESSAGE",
        resource="a2a_task",
        resource_id=task.id,
        detail={"agent_id": agent_id, "async_execution": async_execution},
        db=db,
    )
    return task


@router.post("/a2a/tasks", response_model=AgentTask)
async def create_a2a_task(
    body: CreateTaskRequest,
    request: Request,
    actor: A2AActor = Depends(require_a2a_actor),
    db: AsyncSession = Depends(get_db),
) -> AgentTask:
    if body.execution_mode == TaskExecutionMode.async_:
        task = queue_agent_message(
            agent_id=body.agent_id,
            message=body.message,
            owner_id=actor.owner_id,
            request_meta=request_meta_from_request(request),
        )
    else:
        task = await execute_agent_message(
            agent_id=body.agent_id,
            message=body.message,
            owner_id=actor.owner_id,
            request=request,
        )
    await _record_a2a_audit(
        actor=actor,
        action="A2A_TASK_CREATE",
        resource="a2a_task",
        resource_id=task.id,
        detail={"agent_id": body.agent_id, "execution_mode": body.execution_mode.value},
        db=db,
    )
    return task


@router.get("/a2a/tasks/{task_id}", response_model=AgentTask)
async def get_a2a_task(task_id: str, actor: A2AActor = Depends(require_a2a_actor)) -> AgentTask:
    return a2a_task_manager.require_task(task_id, actor.owner_id)


@router.get("/a2a/tasks/{task_id}/artifacts", response_model=list[AgentArtifact])
async def get_a2a_task_artifacts(task_id: str, actor: A2AActor = Depends(require_a2a_actor)) -> list[AgentArtifact]:
    return a2a_task_manager.list_artifacts(task_id, actor.owner_id)


@router.get("/a2a/tasks/{task_id}/artifacts/{artifact_id}/download")
async def download_a2a_artifact(
    task_id: str,
    artifact_id: str,
    actor: A2AActor = Depends(require_a2a_actor),
    db: AsyncSession = Depends(get_db),
) -> Response:
    artifact = a2a_task_manager.require_artifact(task_id, artifact_id, actor.owner_id)
    if isinstance(artifact.data, str):
        body = artifact.data
        media_type = artifact.mime_type or "text/plain"
        extension = "txt" if artifact.artifact_type in {"text", "error"} else "json"
    else:
        body = json.dumps(artifact.data, indent=2, default=str)
        media_type = "application/json"
        extension = "json"
    safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in artifact.name)
    await _record_a2a_audit(
        actor=actor,
        action="A2A_ARTIFACT_DOWNLOAD",
        resource="a2a_artifact",
        resource_id=artifact.id,
        detail={"task_id": task_id, "artifact_name": artifact.name},
        db=db,
    )
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.{extension}"'},
    )


@router.get("/a2a/tasks/{task_id}/status", response_model=TaskStatusResponse)
async def get_a2a_task_status(task_id: str, actor: A2AActor = Depends(require_a2a_actor)) -> TaskStatusResponse:
    task = a2a_task_manager.require_task(task_id, actor.owner_id)
    return TaskStatusResponse(
        task_id=task.id,
        agent_id=task.agent_id,
        status=task.status,
        error=task.error,
        updated_at=task.updated_at,
    )


@router.post("/a2a/evaluations/resume-screening", response_model=AgentTask)
async def run_resume_screening_evaluation(
    body: EvaluationRunRequest,
    request: Request,
    actor: A2AActor = Depends(require_a2a_actor),
    db: AsyncSession = Depends(get_db),
) -> AgentTask:
    message = AgentMessage(
        role="user",
        content=body.label,
        context={
            "resume_text": body.resume_text,
            "jd_text": body.jd_text,
            "evaluation": True,
            "label": body.label,
        },
        metadata={"source": "a2a_evaluation_runner"},
    )
    if body.execution_mode == TaskExecutionMode.async_:
        task = queue_agent_message(
            agent_id="resume_screening_orchestrator",
            message=message,
            owner_id=actor.owner_id,
            request_meta=request_meta_from_request(request),
        )
    else:
        task = await execute_agent_message(
            agent_id="resume_screening_orchestrator",
            message=message,
            owner_id=actor.owner_id,
            request=request,
        )
    await _record_a2a_audit(
        actor=actor,
        action="A2A_EVALUATION_RUN",
        resource="a2a_task",
        resource_id=task.id,
        detail={"workflow": "resume_screening", "execution_mode": body.execution_mode.value},
        db=db,
    )
    return task


@router.get("/a2a/audit", response_model=A2AAuditResponse)
async def get_a2a_audit(
    limit: int = Query(default=100, ge=1, le=1000),
    _: A2AActor = Depends(require_a2a_actor),
) -> A2AAuditResponse:
    return A2AAuditResponse(events=a2a_task_manager.recent_audit(limit=limit))


@router.get("/a2a/adk-shadow/summary")
async def get_adk_shadow_summary(_: A2AActor = Depends(require_a2a_actor)) -> dict[str, Any]:
    return await adk_shadow_recorder.summary()


@router.get("/a2a/adk-shadow/recent")
async def get_adk_shadow_recent(
    limit: int = Query(default=50, ge=1, le=500),
    _: A2AActor = Depends(require_a2a_actor),
) -> dict[str, list[dict[str, Any]]]:
    return {"events": await adk_shadow_recorder.recent(limit=limit)}


@router.get("/a2a/adk-promotion/status")
async def get_adk_promotion_status(
    limit: int = Query(default=25, ge=1, le=100),
    _: A2AActor = Depends(require_a2a_actor),
) -> dict[str, Any]:
    allowlist = [
        item.strip()
        for item in str(getattr(settings, "ADK_PROMOTION_WORKFLOW_ALLOWLIST", "") or "").split(",")
        if item.strip()
    ]
    recent = await adk_shadow_recorder.recent(limit=500)
    promoted_events = [
        event
        for event in recent
        if event.get("execution_mode") == "promoted"
    ][:limit]
    fallback_count = sum(1 for event in promoted_events if event.get("status") == "fallback")
    failed_count = sum(1 for event in promoted_events if event.get("status") == "failed")
    completed_count = sum(1 for event in promoted_events if event.get("status") == "completed")
    return {
        "enabled": bool(getattr(settings, "ADK_PROMOTION_ENABLED", False)),
        "allowlist": allowlist,
        "effective_workflows": {
            workflow: promotion_enabled_for(workflow)
            for workflow in allowlist
        },
        "timeout_seconds": float(getattr(settings, "ADK_PROMOTION_TIMEOUT_SECONDS", 15.0)),
        "fallback_to_legacy": bool(getattr(settings, "ADK_PROMOTION_FALLBACK_TO_LEGACY", True)),
        "min_quiz_quality_score": float(getattr(settings, "ADK_PROMOTION_MIN_QUIZ_QUALITY_SCORE", 70.0)),
        "recent": promoted_events,
        "recent_counts": {
            "completed": completed_count,
            "fallback": fallback_count,
            "failed": failed_count,
        },
    }
