from __future__ import annotations

import logging
import time
import asyncio
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, Request, status

from app.config import settings
from app.schemas.a2a import (
    AgentMessage,
    AgentTask,
    ExecutionMetadata,
    TaskResult,
    TaskStatus,
    TraceMetadata,
    utcnow,
)
from app.services.a2a_artifacts import (
    build_error_artifact,
    build_result_artifact,
    build_trace_artifact,
)
from app.services.a2a_registry import get_agent_definition
from app.services.a2a_task_manager import a2a_task_manager
from app.services.multi_agent_runtime import HRMultiAgentRuntimeError, hr_multi_agent_runtime
from app.services.token_monitor_service import get_token_monitor

logger = logging.getLogger(__name__)


class A2AAdapterError(ValueError):
    pass


def _string_or_empty(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _first_text(message: AgentMessage, *context_keys: str) -> str:
    for key in context_keys:
        value = message.context.get(key)
        text = _string_or_empty(value)
        if text:
            return text
    return _string_or_empty(message.content)


def _require_dict(context: dict[str, Any], key: str) -> dict[str, Any]:
    value = context.get(key)
    if not isinstance(value, dict) or not value:
        raise A2AAdapterError(f"context.{key} is required and must be a non-empty object")
    return value


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _base_state(
    *,
    message: AgentMessage,
    task: AgentTask,
    request: Request | None = None,
    request_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = request_meta or {}
    request_id = meta.get("request_id") or (getattr(getattr(request, "state", None), "request_id", None) if request else None)
    run_id = meta.get("run_id") or (getattr(getattr(request, "state", None), "run_id", None) if request else None)
    return {
        "trace_id": task.trace.trace_id,
        "a2a_task_id": task.id,
        "a2a": True,
        "request_id": request_id,
        "run_id": run_id,
        "timeout_s": message.context.get("timeout_s", settings.AGENT_MAX_TIMEOUT_SECONDS),
        "model_override": message.context.get("model_override"),
        "model_overrides": message.context.get("model_overrides"),
    }


def build_runtime_state(
    agent_id: str,
    message: AgentMessage,
    task: AgentTask,
    request: Request | None = None,
    request_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = _base_state(message=message, task=task, request=request, request_meta=request_meta)
    context = message.context

    if agent_id == "resume_parser_agent":
        text = _first_text(message, "resume_text", "text")
        if not text:
            raise A2AAdapterError("Resume parser requires message content, context.text, or context.resume_text")
        return {**state, "text": text}

    if agent_id == "jd_parser_agent":
        jd_text = _first_text(message, "jd_text", "job_description", "doc_text", "text")
        if not jd_text:
            raise A2AAdapterError("JD parser requires message content, context.jd_text, or context.job_description")
        return {**state, "jd_text": jd_text, "doc_text": jd_text}

    if agent_id == "embedding_agent":
        embed_text = _first_text(message, "embed_text", "text", "jd_text", "resume_text")
        if not embed_text:
            raise A2AAdapterError("Embedding agent requires message content, context.text, or context.embed_text")
        return {**state, "embed_text": embed_text}

    if agent_id == "scoring_agent":
        return {
            **state,
            "parsed_resume": _require_dict(context, "parsed_resume"),
            "parsed_job": _require_dict(context, "parsed_job"),
        }

    if agent_id == "quiz_agent":
        operation = _string_or_empty(context.get("operation") or "generate")
        if operation not in {"generate", "parse_document"}:
            raise A2AAdapterError("context.operation must be either 'generate' or 'parse_document'")
        if operation == "parse_document":
            doc_text = _first_text(message, "doc_text", "text")
            if not doc_text:
                raise A2AAdapterError("Quiz document parsing requires content or context.doc_text")
            return {**state, "operation": operation, "doc_text": doc_text}
        jd_text = _first_text(message, "jd_text", "job_description", "text")
        if not jd_text:
            raise A2AAdapterError("Quiz generation requires content or context.jd_text")
        return {
            **state,
            "operation": "generate",
            "jd_text": jd_text,
            "skills": _normalize_string_list(context.get("skills")),
            "easy": int(context.get("easy", settings.QUIZ_EASY_COUNT)),
            "medium": int(context.get("medium", settings.QUIZ_MEDIUM_COUNT)),
            "hard": int(context.get("hard", settings.QUIZ_HARD_COUNT)),
        }

    if agent_id == "career_analyst_agent":
        parsed_resume = context.get("parsed_resume") if isinstance(context.get("parsed_resume"), dict) else {}
        candidate_name = _string_or_empty(context.get("candidate_name") or parsed_resume.get("name") or "Candidate")
        return {
            **state,
            "candidate_name": candidate_name,
            "experience_years": float(context.get("experience_years") or parsed_resume.get("experience_years") or 0),
            "skills": context.get("skills") or parsed_resume.get("skills") or parsed_resume.get("normalized_skills") or [],
            "work_history": context.get("work_history") or parsed_resume.get("work_experience") or [],
            "education": context.get("education") or parsed_resume.get("education") or [],
            "career_breaks": context.get("career_breaks") or [],
            "target_role": _string_or_empty(context.get("target_role") or context.get("job_title") or message.content or "Target role"),
        }

    if agent_id == "recruiter_assistant_agent":
        snapshot = context.get("snapshot")
        if not isinstance(snapshot, dict) or not snapshot:
            raise A2AAdapterError("Recruiter assistant requires context.snapshot")
        return {
            **state,
            "snapshot": snapshot,
            "question": _string_or_empty(context.get("question") or message.content),
        }

    raise A2AAdapterError(f"Agent '{agent_id}' is not exposed through A2A")


def _resolve_model_used(agent_id: str, state: dict[str, Any]) -> str | None:
    override = state.get("model_override")
    if isinstance(override, str) and override.strip():
        return override.strip()
    overrides = state.get("model_overrides")
    if isinstance(overrides, dict):
        model = overrides.get(agent_id)
        if isinstance(model, str) and model.strip():
            return model.strip()
    return settings.agent_model_map.get(agent_id) or settings.AZURE_CHAT_DEPLOYMENT


def _task_summary(agent_id: str, output: dict[str, Any], output_keys: tuple[str, ...]) -> str:
    present = [key for key in output_keys if key in output]
    if present:
        return f"{agent_id} completed with {', '.join(present)}"
    return f"{agent_id} completed"


def request_meta_from_request(request: Request | None) -> dict[str, Any]:
    if request is None:
        return {}
    return {
        "request_id": getattr(getattr(request, "state", None), "request_id", None),
        "run_id": getattr(getattr(request, "state", None), "run_id", None),
    }


def create_agent_task(
    *,
    agent_id: str,
    message: AgentMessage,
    owner_id: str,
    request_meta: dict[str, Any] | None = None,
) -> AgentTask:
    definition = get_agent_definition(agent_id)
    if definition is None or not definition.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="A2A agent is not exposed")

    meta = request_meta or {}
    trace_id = message.trace_id or str(uuid4())
    now = utcnow()
    task = AgentTask(
        agent_id=agent_id,
        owner_id=owner_id,
        status=TaskStatus.queued,
        message=message,
        trace=TraceMetadata(
            trace_id=trace_id,
            request_id=meta.get("request_id"),
            run_id=meta.get("run_id"),
            correlation_id=message.metadata.get("correlation_id") if isinstance(message.metadata, dict) else None,
        ),
        execution=ExecutionMetadata(agent_id=agent_id, started_at=now),
    )
    return a2a_task_manager.create(task)


async def _run_resume_screening_workflow(
    *,
    task: AgentTask,
    request_meta: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    message = task.message
    context = message.context
    resume_text = _first_text(message, "resume_text")
    jd_text = _first_text(message, "jd_text", "job_description")
    if not resume_text or not jd_text:
        raise A2AAdapterError("Resume screening workflow requires context.resume_text and context.jd_text")

    base_state = _base_state(message=message, task=task, request_meta=request_meta)
    resume_task = hr_multi_agent_runtime.run_agent(
        "resume_parser_agent",
        {**base_state, "text": resume_text},
    )
    jd_task = hr_multi_agent_runtime.run_agent(
        "jd_parser_agent",
        {**base_state, "jd_text": jd_text, "doc_text": jd_text},
    )
    resume_updates, jd_updates = await asyncio.gather(resume_task, jd_task)
    parsed_resume = resume_updates.get("parsed_resume")
    parsed_job = jd_updates.get("parsed_job")
    if not isinstance(parsed_resume, dict):
        raise HRMultiAgentRuntimeError("resume_parser_agent", "missing parsed_resume")
    if not isinstance(parsed_job, dict):
        raise HRMultiAgentRuntimeError("jd_parser_agent", "missing parsed_job")

    resume_embed_task = hr_multi_agent_runtime.run_agent(
        "embedding_agent",
        {**base_state, "embed_text": resume_text},
    )
    jd_embed_task = hr_multi_agent_runtime.run_agent(
        "embedding_agent",
        {**base_state, "embed_text": jd_text},
    )
    resume_embed_updates, jd_embed_updates = await asyncio.gather(resume_embed_task, jd_embed_task)

    score_updates = await hr_multi_agent_runtime.run_agent(
        "scoring_agent",
        {
            **base_state,
            "parsed_resume": parsed_resume,
            "parsed_job": {
                **parsed_job,
                "embedding": jd_embed_updates.get("embedding") or [],
            },
        },
    )
    score_result = score_updates.get("score_result")
    if not isinstance(score_result, dict):
        raise HRMultiAgentRuntimeError("scoring_agent", "missing score_result")

    trace: list[dict[str, Any]] = []
    for updates in (resume_updates, jd_updates, resume_embed_updates, jd_embed_updates, score_updates):
        if isinstance(updates.get("_agent_trace"), list):
            trace.extend(updates["_agent_trace"])

    output = {
        "parsed_resume": parsed_resume,
        "parsed_job": parsed_job,
        "resume_embedding": resume_embed_updates.get("embedding") or [],
        "jd_embedding": jd_embed_updates.get("embedding") or [],
        "score_result": score_result,
        "_agent_trace": trace,
    }
    state = {**base_state, "workflow": "resume_screening"}
    return output, trace, state


async def execute_existing_task(
    task: AgentTask,
    *,
    request_meta: dict[str, Any] | None = None,
    raise_http: bool = True,
) -> AgentTask:
    agent_id = task.agent_id
    definition = get_agent_definition(agent_id)
    if definition is None or not definition.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="A2A agent is not exposed")

    try:
        task.status = TaskStatus.running
        task.updated_at = utcnow()
        a2a_task_manager.update(task)

        token_monitor = get_token_monitor()
        token_checkpoint = token_monitor.checkpoint() if token_monitor.enabled else None
        started = time.perf_counter()
        if agent_id == "resume_screening_orchestrator":
            output, agent_trace, state = await _run_resume_screening_workflow(
                task=task,
                request_meta=request_meta,
            )
        else:
            state = build_runtime_state(agent_id, task.message, task, request_meta=request_meta)
            output = await hr_multi_agent_runtime.run_agent(agent_id, state)
            agent_trace = output.get("_agent_trace") if isinstance(output.get("_agent_trace"), list) else []
        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        token_delta = (
            token_monitor.delta_since(token_checkpoint)
            if token_checkpoint is not None
            else {}
        )

        task.trace.agent_trace = agent_trace
        task.execution.completed_at = utcnow()
        task.execution.latency_ms = latency_ms
        task.execution.model_used = _resolve_model_used(agent_id, state)
        task.execution.token_usage = token_delta if token_delta else (
            output.get("token_usage") if isinstance(output.get("token_usage"), dict) else {}
        )
        task.execution.status_code = "ok"

        result_artifact = build_result_artifact(
            task_id=task.id,
            agent_id=agent_id,
            output=output,
            output_keys=definition.output_keys,
        )
        a2a_task_manager.add_artifact(task.owner_id, result_artifact)

        if agent_trace:
            trace_artifact = build_trace_artifact(task_id=task.id, agent_id=agent_id, trace=agent_trace)
            a2a_task_manager.add_artifact(task.owner_id, trace_artifact)

        task.status = TaskStatus.completed
        task.result = TaskResult(
            summary=_task_summary(agent_id, output, definition.output_keys),
            output={
                key: output.get(key)
                for key in definition.output_keys
                if key in output
            },
            artifact_ids=list(task.artifact_ids),
        )
        task.updated_at = utcnow()
        return a2a_task_manager.update(task)
    except A2AAdapterError as exc:
        artifact = build_error_artifact(task_id=task.id, agent_id=agent_id, error=str(exc))
        a2a_task_manager.add_artifact(task.owner_id, artifact)
        task.execution.completed_at = utcnow()
        task.execution.status_code = "validation_error"
        task.updated_at = utcnow()
        a2a_task_manager.mark_failed(task, str(exc))
        logger.info("A2A validation failed agent=%s task=%s error=%s", agent_id, task.id, exc)
        if raise_http:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        return task
    except HRMultiAgentRuntimeError as exc:
        artifact = build_error_artifact(task_id=task.id, agent_id=agent_id, error=str(exc))
        a2a_task_manager.add_artifact(task.owner_id, artifact)
        task.execution.completed_at = utcnow()
        task.execution.status_code = "runtime_error"
        task.updated_at = utcnow()
        a2a_task_manager.mark_failed(task, str(exc))
        logger.warning("A2A runtime failed agent=%s task=%s error=%s", agent_id, task.id, exc)
        if raise_http:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="A2A agent execution failed") from exc
        return task
    except Exception as exc:
        artifact = build_error_artifact(task_id=task.id, agent_id=agent_id, error=type(exc).__name__)
        a2a_task_manager.add_artifact(task.owner_id, artifact)
        task.execution.completed_at = utcnow()
        task.execution.status_code = "unexpected_error"
        task.updated_at = utcnow()
        a2a_task_manager.mark_failed(task, "Unexpected A2A execution failure")
        logger.exception("A2A unexpected failure agent=%s task=%s", agent_id, task.id)
        if raise_http:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="A2A execution failed") from exc
        return task


def queue_agent_message(
    *,
    agent_id: str,
    message: AgentMessage,
    owner_id: str,
    request_meta: dict[str, Any] | None = None,
) -> AgentTask:
    task = create_agent_task(
        agent_id=agent_id,
        message=message,
        owner_id=owner_id,
        request_meta=request_meta,
    )
    asyncio.create_task(execute_existing_task(task, request_meta=request_meta, raise_http=False))
    return task


async def execute_agent_message(
    *,
    agent_id: str,
    message: AgentMessage,
    owner_id: str,
    request: Request | None = None,
) -> AgentTask:
    request_meta = request_meta_from_request(request)
    task = create_agent_task(
        agent_id=agent_id,
        message=message,
        owner_id=owner_id,
        request_meta=request_meta,
    )
    return await execute_existing_task(task, request_meta=request_meta, raise_http=True)
