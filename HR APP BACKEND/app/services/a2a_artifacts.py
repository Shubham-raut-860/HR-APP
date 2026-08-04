from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.schemas.a2a import AgentArtifact


_SENSITIVE_KEY_TOKENS = {
    "email",
    "phone",
    "mobile",
    "address",
    "token",
    "password",
    "secret",
    "authorization",
    "ssn",
    "aadhaar",
    "pan",
}


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in _SENSITIVE_KEY_TOKENS)


def _redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): ("[redacted]" if _is_sensitive_key(str(key)) else _redact_value(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        if len(value) > 64 and all(isinstance(item, (int, float)) for item in value[:64]):
            return {
                "kind": "numeric_vector",
                "dimensions": len(value),
                "preview": value[:8],
                "truncated": True,
            }
        return [_redact_value(item) for item in value[:250]]
    if isinstance(value, str) and len(value) > 12000:
        return value[:12000] + "...[truncated]"
    return value


def build_result_artifact(
    *,
    task_id: str,
    agent_id: str,
    output: dict[str, Any],
    output_keys: tuple[str, ...],
) -> AgentArtifact:
    selected = {
        key: output.get(key)
        for key in output_keys
        if key in output
    }
    if not selected:
        selected = {
            key: value
            for key, value in output.items()
            if not key.startswith("_") and key not in {"db", "content", "file_bytes", "file_bytes_b64"}
        }
    redacted = _redact_value(selected)
    return AgentArtifact(
        task_id=task_id,
        name=f"{agent_id}.result",
        artifact_type="json",
        data=redacted,
        redacted=redacted != selected,
        metadata={"agent_id": agent_id, "output_keys": list(output_keys)},
    )


def build_trace_artifact(*, task_id: str, agent_id: str, trace: list[dict[str, Any]]) -> AgentArtifact:
    return AgentArtifact(
        task_id=task_id,
        name=f"{agent_id}.trace",
        artifact_type="trace",
        data=_redact_value(trace),
        redacted=True,
        metadata={"agent_id": agent_id},
    )


def build_error_artifact(*, task_id: str, agent_id: str, error: str) -> AgentArtifact:
    return AgentArtifact(
        task_id=task_id,
        name=f"{agent_id}.error",
        artifact_type="error",
        mime_type="text/plain",
        data=error[:2000],
        redacted=False,
        metadata={"agent_id": agent_id},
    )

