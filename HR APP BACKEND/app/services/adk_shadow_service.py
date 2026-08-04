from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
import random
import time
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ADKShadowEvent:
    workflow: str
    status: str
    started_at: str
    latency_ms: float = 0.0
    production_hash: str | None = None
    shadow_hash: str | None = None
    match: bool | None = None
    execution_mode: str = "record_only"
    entity_id: str | None = None
    actor_id: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ADKShadowRecorder:
    def __init__(self) -> None:
        max_events = max(10, int(getattr(settings, "ADK_SHADOW_MAX_EVENTS", 500)))
        self._events: deque[ADKShadowEvent] = deque(maxlen=max_events)
        self._lock = asyncio.Lock()

    async def add(self, event: ADKShadowEvent) -> None:
        async with self._lock:
            self._events.appendleft(event)

    async def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        async with self._lock:
            return [asdict(event) for event in list(self._events)[:safe_limit]]

    async def summary(self) -> dict[str, Any]:
        async with self._lock:
            events = list(self._events)
        total = len(events)
        completed = sum(1 for event in events if event.status == "completed")
        failed = sum(1 for event in events if event.status == "failed")
        matched = sum(1 for event in events if event.match is True)
        compared = sum(1 for event in events if event.match is not None)
        return {
            "enabled": bool(getattr(settings, "ADK_SHADOW_MODE_ENABLED", False)),
            "execution_mode": getattr(settings, "ADK_SHADOW_EXECUTION_MODE", "record_only"),
            "events": total,
            "completed": completed,
            "failed": failed,
            "compared": compared,
            "matched": matched,
            "match_rate_pct": round((matched / compared) * 100.0, 2) if compared else None,
        }

    async def clear(self) -> None:
        async with self._lock:
            self._events.clear()


adk_shadow_recorder = ADKShadowRecorder()


def _workflow_allowlist() -> set[str]:
    raw = str(getattr(settings, "ADK_SHADOW_WORKFLOW_ALLOWLIST", "") or "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def _enabled_for(workflow: str) -> bool:
    if not bool(getattr(settings, "ADK_SHADOW_MODE_ENABLED", False)):
        return False
    allowlist = _workflow_allowlist()
    if allowlist and workflow not in allowlist:
        return False
    sample_rate = max(0.0, min(1.0, float(getattr(settings, "ADK_SHADOW_SAMPLE_RATE", 1.0))))
    return random.random() <= sample_rate


def _canonical_hash(payload: Any) -> str:
    try:
        encoded = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    except Exception:
        encoded = str(payload)
    return hashlib.sha256(encoded.encode("utf-8", errors="replace")).hexdigest()


def _safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        if key.lower() in {"email", "token", "password", "secret", "resume_text", "jd_text"}:
            safe[f"{key}_sha256"] = _canonical_hash(value)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            text = str(value) if isinstance(value, str) else value
            safe[key] = text[:300] if isinstance(text, str) else text
        else:
            safe[key] = _canonical_hash(value)
    return safe


def _truncate_text(text: Any) -> str:
    limit = max(1000, int(getattr(settings, "ADK_SHADOW_MAX_PAYLOAD_CHARS", 20000)))
    return str(text or "")[:limit]


async def _run_shadow_runtime(workflow: str, inputs: dict[str, Any]) -> Any:
    from app.services.multi_agent_runtime import hr_multi_agent_runtime

    if workflow == "jd_generation":
        return await hr_multi_agent_runtime.generate_jd(
            role=str(inputs.get("role") or ""),
            experience_min=int(inputs.get("experience_min") or 0),
            experience_max=int(inputs.get("experience_max") or 0),
            location=str(inputs.get("location") or "Remote"),
            additional_context=str(inputs.get("additional_context") or ""),
        )
    if workflow == "quiz_generation":
        return await hr_multi_agent_runtime.generate_quiz(
            jd_text=_truncate_text(inputs.get("jd_text")),
            skills=list(inputs.get("skills") or []),
            easy=int(inputs.get("easy") or 0),
            medium=int(inputs.get("medium") or 0),
            hard=int(inputs.get("hard") or 0),
            timeout_s=float(getattr(settings, "ADK_SHADOW_TIMEOUT_SECONDS", 20.0)),
        )
    if workflow == "quiz_validation":
        return await hr_multi_agent_runtime.validate_quiz(
            questions=list(inputs.get("questions") or []),
            jd_text=_truncate_text(inputs.get("jd_text")),
            skills=list(inputs.get("skills") or []),
            easy=int(inputs.get("easy") or 0),
            medium=int(inputs.get("medium") or 0),
            hard=int(inputs.get("hard") or 0),
            timeout_s=float(getattr(settings, "ADK_SHADOW_TIMEOUT_SECONDS", 20.0)),
        )
    raise ValueError(f"Unsupported ADK shadow workflow: {workflow}")


async def run_adk_shadow_observation(
    *,
    workflow: str,
    inputs: dict[str, Any],
    production_output: Any,
    actor_id: str | None = None,
    entity_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ADKShadowEvent:
    started = time.perf_counter()
    mode = str(getattr(settings, "ADK_SHADOW_EXECUTION_MODE", "record_only") or "record_only").strip()
    event = ADKShadowEvent(
        workflow=workflow,
        status="recorded",
        started_at=datetime.now(timezone.utc).isoformat(),
        production_hash=_canonical_hash(production_output),
        execution_mode=mode,
        actor_id=actor_id,
        entity_id=entity_id,
        metadata=_safe_metadata(metadata),
    )
    try:
        if mode == "runtime_compare":
            shadow_output = await asyncio.wait_for(
                _run_shadow_runtime(workflow, inputs),
                timeout=max(1.0, float(getattr(settings, "ADK_SHADOW_TIMEOUT_SECONDS", 20.0))),
            )
            event.shadow_hash = _canonical_hash(shadow_output)
            if workflow == "quiz_validation" and isinstance(shadow_output, dict):
                event.match = bool(shadow_output.get("passed"))
                event.metadata.update(
                    _safe_metadata(
                        {
                            "validation_passed": bool(shadow_output.get("passed")),
                            "quality_score": shadow_output.get("quality_score"),
                            "valid_question_count": shadow_output.get("valid_question_count"),
                            "issue_count": shadow_output.get("issue_count"),
                            "skill_coverage_pct": shadow_output.get("skill_coverage_pct"),
                        }
                    )
                )
            else:
                event.match = event.shadow_hash == event.production_hash
            event.status = "completed"
        else:
            event.status = "recorded"
    except Exception as exc:
        event.status = "failed"
        event.error = str(exc)[:500]
        logger.warning("ADK shadow workflow failed workflow=%s entity_id=%s error=%s", workflow, entity_id, exc)
    finally:
        event.latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        await adk_shadow_recorder.add(event)
    return event


def schedule_adk_shadow_observation(
    *,
    workflow: str,
    inputs: dict[str, Any],
    production_output: Any,
    actor_id: str | None = None,
    entity_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    if not _enabled_for(workflow):
        return False
    try:
        asyncio.get_running_loop().create_task(
            run_adk_shadow_observation(
                workflow=workflow,
                inputs=inputs,
                production_output=production_output,
                actor_id=actor_id,
                entity_id=entity_id,
                metadata=metadata,
            )
        )
        return True
    except RuntimeError:
        logger.debug("ADK shadow scheduling skipped; no running event loop")
        return False
