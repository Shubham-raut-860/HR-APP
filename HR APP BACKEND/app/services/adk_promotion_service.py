from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import time
from typing import Any

from app.config import settings
from app.services.adk_shadow_service import ADKShadowEvent, adk_shadow_recorder
from app.services.multi_agent_runtime import hr_multi_agent_runtime

logger = logging.getLogger(__name__)


@dataclass
class ADKPromotionResult:
    workflow: str
    output: Any
    validation: dict[str, Any] | None = None


def _promotion_allowlist() -> set[str]:
    raw = str(getattr(settings, "ADK_PROMOTION_WORKFLOW_ALLOWLIST", "") or "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def promotion_enabled_for(workflow: str) -> bool:
    if not bool(getattr(settings, "ADK_PROMOTION_ENABLED", False)):
        return False
    allowlist = _promotion_allowlist()
    return bool(allowlist) and workflow in allowlist


async def _record_promotion_event(
    *,
    workflow: str,
    status: str,
    started: float,
    actor_id: str | None = None,
    entity_id: str | None = None,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    await adk_shadow_recorder.add(
        ADKShadowEvent(
            workflow=workflow,
            status=status,
            started_at=datetime.now(timezone.utc).isoformat(),
            latency_ms=round((time.perf_counter() - started) * 1000.0, 2),
            execution_mode="promoted",
            actor_id=actor_id,
            entity_id=entity_id,
            error=(error or "")[:500] or None,
            metadata=metadata or {},
        )
    )


async def try_promoted_quiz_generation(
    *,
    jd_text: str,
    skills: list[str],
    easy: int,
    medium: int,
    hard: int,
    actor_id: str | None = None,
    entity_id: str | None = None,
) -> ADKPromotionResult | None:
    workflow = "quiz_generation"
    if not promotion_enabled_for(workflow):
        return None

    started = time.perf_counter()
    timeout_s = max(1.0, float(getattr(settings, "ADK_PROMOTION_TIMEOUT_SECONDS", 15.0)))
    fallback_to_legacy = bool(getattr(settings, "ADK_PROMOTION_FALLBACK_TO_LEGACY", True))
    min_quality = float(getattr(settings, "ADK_PROMOTION_MIN_QUIZ_QUALITY_SCORE", 70.0))
    failure_recorded = False

    try:
        questions = await asyncio.wait_for(
            hr_multi_agent_runtime.generate_quiz(
                jd_text=jd_text,
                skills=list(skills or []),
                easy=int(easy),
                medium=int(medium),
                hard=int(hard),
                timeout_s=timeout_s,
            ),
            timeout=timeout_s,
        )
        validation = await asyncio.wait_for(
            hr_multi_agent_runtime.validate_quiz(
                questions=list(questions or []),
                jd_text=jd_text,
                skills=list(skills or []),
                easy=int(easy),
                medium=int(medium),
                hard=int(hard),
                timeout_s=min(timeout_s, 10.0),
            ),
            timeout=timeout_s,
        )
        quality_score = float(validation.get("quality_score") or 0.0)
        passed = bool(validation.get("passed")) and quality_score >= min_quality
        metadata = {
            "promotion_enabled": True,
            "validation_passed": bool(validation.get("passed")),
            "quality_score": quality_score,
            "valid_question_count": validation.get("valid_question_count"),
            "issue_count": validation.get("issue_count"),
            "fallback_to_legacy": fallback_to_legacy,
        }
        if not passed:
            failure_recorded = True
            await _record_promotion_event(
                workflow=workflow,
                status="fallback" if fallback_to_legacy else "failed",
                started=started,
                actor_id=actor_id,
                entity_id=entity_id,
                error="promoted quiz validation did not pass quality gate",
                metadata=metadata,
            )
            if fallback_to_legacy:
                return None
            raise RuntimeError("Promoted quiz validation did not pass quality gate")

        await _record_promotion_event(
            workflow=workflow,
            status="completed",
            started=started,
            actor_id=actor_id,
            entity_id=entity_id,
            metadata=metadata,
        )
        return ADKPromotionResult(workflow=workflow, output=questions, validation=validation)
    except Exception as exc:
        logger.warning("ADK promoted workflow failed workflow=%s entity_id=%s error=%s", workflow, entity_id, exc)
        if not failure_recorded:
            await _record_promotion_event(
                workflow=workflow,
                status="fallback" if fallback_to_legacy else "failed",
                started=started,
                actor_id=actor_id,
                entity_id=entity_id,
                error=str(exc),
                metadata={"promotion_enabled": True, "fallback_to_legacy": fallback_to_legacy},
            )
        if fallback_to_legacy:
            return None
        raise
