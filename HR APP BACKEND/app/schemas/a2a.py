from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class A2ABaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    canceled = "canceled"


class TaskExecutionMode(str, Enum):
    sync = "sync"
    async_ = "async"


class Capability(A2ABaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=2, max_length=500)
    input_modes: list[str] = Field(default_factory=lambda: ["text", "json"], max_length=10)
    output_modes: list[str] = Field(default_factory=lambda: ["json"], max_length=10)
    streaming: bool = False
    side_effects: bool = False


class Skill(A2ABaseModel):
    id: str = Field(min_length=2, max_length=80, pattern=r"^[a-zA-Z0-9_.:-]+$")
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=2, max_length=800)
    tags: list[str] = Field(default_factory=list, max_length=20)
    examples: list[str] = Field(default_factory=list, max_length=10)


class AgentCard(A2ABaseModel):
    id: str = Field(min_length=2, max_length=80, pattern=r"^[a-zA-Z0-9_.:-]+$")
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=2, max_length=1200)
    protocol_version: str = "a2a-0.1"
    version: str = "1.0.0"
    url: str = Field(min_length=1, max_length=500)
    provider: str = "HIREAI"
    visibility: Literal["public", "hr", "internal"] = "hr"
    enabled: bool = True
    capabilities: list[Capability] = Field(default_factory=list, max_length=20)
    skills: list[Skill] = Field(default_factory=list, max_length=20)
    default_input_modes: list[str] = Field(default_factory=lambda: ["text", "json"])
    default_output_modes: list[str] = Field(default_factory=lambda: ["json"])
    auth_schemes: list[str] = Field(default_factory=lambda: ["bearer"])
    metadata: dict[str, Any] = Field(default_factory=dict)


class TraceMetadata(A2ABaseModel):
    trace_id: str = Field(default_factory=lambda: str(uuid4()), min_length=8, max_length=128)
    request_id: str | None = Field(default=None, max_length=128)
    run_id: str | None = Field(default=None, max_length=128)
    correlation_id: str | None = Field(default=None, max_length=128)
    agent_trace: list[dict[str, Any]] = Field(default_factory=list)


class ExecutionMetadata(A2ABaseModel):
    agent_id: str = Field(min_length=2, max_length=80)
    runtime: Literal["hr_multi_agent_runtime"] = "hr_multi_agent_runtime"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    model_used: str | None = Field(default=None, max_length=160)
    token_usage: dict[str, Any] = Field(default_factory=dict)
    status_code: str | None = Field(default=None, max_length=80)


class AgentMessage(A2ABaseModel):
    role: Literal["user", "agent", "system"] = "user"
    content: str = Field(default="", max_length=20000)
    context: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    task_id: str | None = Field(default=None, max_length=80)
    trace_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def content_or_context_required(self) -> "AgentMessage":
        if not (self.content or "").strip() and not self.context:
            raise ValueError("Either content or context is required")
        return self


class AgentArtifact(A2ABaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str = Field(min_length=8, max_length=80)
    name: str = Field(min_length=2, max_length=120)
    artifact_type: Literal["json", "text", "trace", "error"] = "json"
    mime_type: str = Field(default="application/json", max_length=120)
    data: dict[str, Any] | list[Any] | str
    redacted: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskResult(A2ABaseModel):
    summary: str = Field(default="", max_length=2000)
    output: dict[str, Any] = Field(default_factory=dict)
    artifact_ids: list[str] = Field(default_factory=list)


class AgentTask(A2ABaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_id: str = Field(min_length=2, max_length=80)
    status: TaskStatus = TaskStatus.queued
    owner_id: str = Field(min_length=1, max_length=120)
    message: AgentMessage
    result: TaskResult | None = None
    error: str | None = Field(default=None, max_length=2000)
    trace: TraceMetadata = Field(default_factory=TraceMetadata)
    execution: ExecutionMetadata
    artifact_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class CreateTaskRequest(A2ABaseModel):
    agent_id: str = Field(min_length=2, max_length=80)
    message: AgentMessage
    execution_mode: TaskExecutionMode = TaskExecutionMode.async_


class EvaluationRunRequest(A2ABaseModel):
    resume_text: str = Field(min_length=20, max_length=30000)
    jd_text: str = Field(min_length=20, max_length=30000)
    label: str = Field(default="Resume screening evaluation", max_length=120)
    execution_mode: TaskExecutionMode = TaskExecutionMode.async_


class TaskStatusResponse(A2ABaseModel):
    task_id: str
    agent_id: str
    status: TaskStatus
    error: str | None = None
    updated_at: datetime


class AgentDirectoryResponse(A2ABaseModel):
    agents: list[AgentCard]
    internal_count: int = 0


class A2AAuditEvent(A2ABaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    actor_id: str = Field(min_length=1, max_length=160)
    actor_type: Literal["technical_admin", "service_token"]
    action: str = Field(min_length=2, max_length=120)
    resource: str = Field(min_length=2, max_length=120)
    resource_id: str | None = Field(default=None, max_length=120)
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class A2AAuditResponse(A2ABaseModel):
    events: list[A2AAuditEvent]
