from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import threading
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.mlflow_service import (
    is_mlflow_tracing_available,
    mlflow_track_llm,
)
from app.services.multi_agent_runtime import (
    HRMultiAgentRuntimeError,
    hr_multi_agent_runtime,
)
from app.services.token_monitor_service import get_token_monitor

logger = logging.getLogger(__name__)

_HARNESS_REDIS_LOCK = threading.Lock()
_HARNESS_REDIS_UNAVAILABLE_UNTIL: float = 0.0
_HARNESS_REDIS_UNAVAILABLE_DETAIL: str = ""
_HARNESS_UNAVAILABLE_LOG_LOCK = threading.Lock()
_HARNESS_UNAVAILABLE_LOG_UNTIL: float = 0.0
_OBS_LOCK = threading.Lock()
_OBS_RECENT_FAILURES_MAX = 25
_SLOW_AGENT_CALL_MS = 4000.0
_OBS_STATE: dict[str, Any] = {
    "calls_total": 0,
    "calls_failed": 0,
    "source_counts": {},
    "status_counts": {},
    "agent_counts": {},
    "recent_failures": deque(maxlen=_OBS_RECENT_FAILURES_MAX),
}


def _obs_inc(container: dict[str, int], key: str) -> None:
    container[key] = int(container.get(key, 0)) + 1


def _record_observation(
    *,
    agent_type: str,
    source: str,
    status: str,
    latency_ms: float,
    error_detail: str | None,
    token_delta: dict[str, Any] | None,
) -> None:
    now = time.time()
    with _OBS_LOCK:
        _OBS_STATE["calls_total"] = int(_OBS_STATE.get("calls_total", 0)) + 1
        _obs_inc(_OBS_STATE["source_counts"], source)
        _obs_inc(_OBS_STATE["status_counts"], status)
        _obs_inc(_OBS_STATE["agent_counts"], agent_type)
        if status != "completed":
            _OBS_STATE["calls_failed"] = int(_OBS_STATE.get("calls_failed", 0)) + 1
            _OBS_STATE["recent_failures"].appendleft(
                {
                    "timestamp_epoch_s": round(now, 3),
                    "agent_type": agent_type,
                    "source": source,
                    "status": status,
                    "latency_ms": round(float(latency_ms), 2),
                    "error": str(error_detail or "")[:500],
                }
            )

    token_calls = int((token_delta or {}).get("calls", 0))
    total_tokens = int((token_delta or {}).get("total_tokens", 0))
    if status == "completed":
        log_msg = (
            "agent_orchestration_complete "
            "agent_type=%s source=%s latency_ms=%.2f token_calls=%s total_tokens=%s"
        )
        if source != "runtime" or float(latency_ms) >= _SLOW_AGENT_CALL_MS:
            logger.info(log_msg, agent_type, source, latency_ms, token_calls, total_tokens)
        else:
            logger.debug(log_msg, agent_type, source, latency_ms, token_calls, total_tokens)
        return

    logger.error(
        "agent_orchestration_failed "
        "agent_type=%s source=%s status=%s latency_ms=%.2f token_calls=%s total_tokens=%s error=%s",
        agent_type,
        source,
        status,
        latency_ms,
        token_calls,
        total_tokens,
        str(error_detail or ""),
    )


def get_runtime_observability_snapshot() -> dict[str, Any]:
    with _OBS_LOCK:
        calls_total = int(_OBS_STATE.get("calls_total", 0))
        calls_failed = int(_OBS_STATE.get("calls_failed", 0))
        source_counts = dict(_OBS_STATE.get("source_counts", {}))
        status_counts = dict(_OBS_STATE.get("status_counts", {}))
        agent_counts = dict(_OBS_STATE.get("agent_counts", {}))
        recent_failures = list(_OBS_STATE.get("recent_failures", []))

    return {
        "calls_total": calls_total,
        "calls_failed": calls_failed,
        "failure_rate_pct": round((calls_failed / calls_total) * 100.0, 2) if calls_total else 0.0,
        "source_counts": source_counts,
        "status_counts": status_counts,
        "agent_counts": agent_counts,
        "recent_failures": recent_failures,
    }


def _harness_redis_cooldown_remaining() -> float:
    with _HARNESS_REDIS_LOCK:
        remaining = _HARNESS_REDIS_UNAVAILABLE_UNTIL - time.monotonic()
    return remaining if remaining > 0 else 0.0


def _mark_harness_redis_unavailable(detail: str, cooldown_seconds: float = 30.0) -> None:
    global _HARNESS_REDIS_UNAVAILABLE_UNTIL, _HARNESS_REDIS_UNAVAILABLE_DETAIL
    with _HARNESS_REDIS_LOCK:
        _HARNESS_REDIS_UNAVAILABLE_UNTIL = time.monotonic() + max(5.0, cooldown_seconds)
        _HARNESS_REDIS_UNAVAILABLE_DETAIL = str(detail or "Redis unavailable")


def _clear_harness_redis_unavailable() -> None:
    global _HARNESS_REDIS_UNAVAILABLE_UNTIL, _HARNESS_REDIS_UNAVAILABLE_DETAIL
    with _HARNESS_REDIS_LOCK:
        _HARNESS_REDIS_UNAVAILABLE_UNTIL = 0.0
        _HARNESS_REDIS_UNAVAILABLE_DETAIL = ""


def _harness_redis_unavailable_detail() -> str:
    with _HARNESS_REDIS_LOCK:
        return _HARNESS_REDIS_UNAVAILABLE_DETAIL or "Redis unavailable"


def _should_log_harness_unavailable(now: float | None = None) -> bool:
    global _HARNESS_UNAVAILABLE_LOG_UNTIL
    now_ts = time.monotonic() if now is None else now
    with _HARNESS_UNAVAILABLE_LOG_LOCK:
        if now_ts >= _HARNESS_UNAVAILABLE_LOG_UNTIL:
            _HARNESS_UNAVAILABLE_LOG_UNTIL = now_ts + 10.0
            return True
    return False


class HarnessAgentError(Exception):
    def __init__(self, agent_type: str, status: str, detail: str):
        self.agent_type = agent_type
        self.status = status
        self.detail = detail
        super().__init__(f"[{agent_type}] {status}: {detail}")


@asynccontextmanager
async def _noop_trace():
    yield None


def _mlflow_trace_enabled() -> bool:
    if not settings.HARNESS_TRACE_RECORDER_ENABLED:
        return False
    if not bool((os.environ.get("MLFLOW_TRACKING_URI") or "").strip()):
        return False
    return is_mlflow_tracing_available()


def _safe_task_preview(task_data: dict[str, Any]) -> str:
    sanitized: dict[str, Any] = dict(task_data or {})
    sensitive_keys = {
        "file_bytes_b64",
        "content_b64",
        "raw_resume_text",
        "resume_text",
        "doc_text",
    }
    for key in sensitive_keys:
        value = sanitized.get(key)
        if isinstance(value, str) and value:
            sanitized[key] = f"<redacted:{len(value)} chars>"

    try:
        text = json.dumps(sanitized, ensure_ascii=False, default=str)
    except Exception:
        text = str(sanitized)
    if len(text) > 4000:
        return text[:4000] + "...<truncated>"
    return text


def _log_agent_trace_artifacts(
    *,
    agent_type: str,
    source: str,
    status: str,
    latency_ms: float,
    task_data: dict[str, Any],
    token_delta: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    if not _mlflow_trace_enabled():
        return
    try:
        import mlflow

        mlflow.log_param("agent_type", agent_type)
        mlflow.log_param("orchestration_source", source)
        mlflow.log_param("status", status)
        mlflow.log_metric("latency_ms_total", round(latency_ms, 2))
        mlflow.log_metric("payload_size_chars", float(len(_safe_task_preview(task_data))))
        if token_delta:
            mlflow.log_metric("token_calls", float(token_delta.get("calls", 0)))
            mlflow.log_metric("prompt_tokens", float(token_delta.get("prompt_tokens", 0)))
            mlflow.log_metric("completion_tokens", float(token_delta.get("completion_tokens", 0)))
            mlflow.log_metric("total_tokens", float(token_delta.get("total_tokens", 0)))
            mlflow.log_metric("token_cost_usd", float(token_delta.get("total_cost_usd", 0.0)))
            mlflow.log_metric("token_over_budget_calls", float(token_delta.get("over_budget_calls", 0)))
            mlflow.log_metric("token_cost_alert_calls", float(token_delta.get("cost_alert_calls", 0)))
        if error:
            mlflow.log_text(str(error), "harness_agent_error.txt")
        mlflow.log_text(_safe_task_preview(task_data), "harness_agent_task_payload.json")
    except Exception as _tr_exc:
        # Non-fatal: tracing must never break agent execution.
        import logging as _tlog
        _tlog.getLogger(__name__).debug(
            "MLflow tracing skipped (non-fatal): %s", _tr_exc
        )


def _extract_bearer_token(auth_header: str | None) -> str | None:
    if not auth_header:
        return None
    raw = auth_header.strip()
    if not raw:
        return None
    if raw.lower().startswith("bearer "):
        token = raw[7:].strip()
        return token or None
    return None


def _resolve_tenant_id(auth_header: str | None) -> str:
    token = _extract_bearer_token(auth_header)
    if not token:
        # Dev-safe fallback for internal/background flows without explicit auth header.
        return "default"
    try:
        from app.services.auth_service import decode_token

        payload = decode_token(token)
    except Exception as exc:
        raise HarnessAgentError("auth", "auth_failed", str(exc)) from exc

    tenant_id = payload.get("tenant_id") or payload.get("sub")
    if not tenant_id:
        raise HarnessAgentError("auth", "auth_failed", "Token missing tenant identifier")
    return str(tenant_id)


def _extract_result_payload(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"result": result}
    nested = result.get("data")
    if isinstance(nested, dict):
        return nested
    return result


def _first_string(task_data: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = task_data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _decode_bytes(task_data: dict[str, Any]) -> bytes:
    raw = task_data.get("file_bytes_b64") or task_data.get("content_b64")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Missing file_bytes_b64/content_b64 payload")
    return base64.b64decode(raw)


async def _run_via_multi_agent_runtime(
    *,
    agent_type: str,
    task_data: dict[str, Any],
) -> dict[str, Any]:
    try:
        timeout_s = float(task_data.get("timeout_s") or 45.0)

        if agent_type == "resume_parser":
            text = _first_string(task_data, ("text", "resume_text", "doc_text"))
            if not text:
                raise ValueError("resume_parser requires text")
            updates = await hr_multi_agent_runtime.run_agent(
                "resume_parser_agent",
                {"text": text, "timeout_s": timeout_s},
            )
            parsed = updates.get("parsed_resume")
            if not isinstance(parsed, dict):
                raise ValueError("resume_parser_agent missing parsed_resume")
            return {"parsed_resume": parsed}

        if agent_type == "embedding":
            text = _first_string(task_data, ("text", "embed_text"))
            if not text:
                raise ValueError("embedding requires text")
            updates = await hr_multi_agent_runtime.run_agent(
                "embedding_agent",
                {"embed_text": text, "timeout_s": timeout_s},
            )
            embedding = updates.get("embedding")
            return {"embedding": embedding if isinstance(embedding, list) else []}

        if agent_type == "resume_scorer":
            parsed_resume = task_data.get("parsed_resume")
            if not isinstance(parsed_resume, dict) or not parsed_resume:
                raise ValueError("resume_scorer requires parsed_resume")
            return {
                "score_result": await hr_multi_agent_runtime.score_resume(
                    parsed_resume=parsed_resume,
                    job_title=str(task_data.get("job_title") or task_data.get("title") or task_data.get("role") or "Role"),
                    exp_min=int(task_data.get("exp_min") or task_data.get("experience_min") or 0),
                    exp_max=int(task_data.get("exp_max") or task_data.get("experience_max") or 5),
                    must_have=list(task_data.get("must_have") or task_data.get("must_have_skills") or []),
                    good_to_have=list(task_data.get("good_to_have") or task_data.get("good_to_have_skills") or []),
                    description=str(task_data.get("description") or ""),
                    jd_embedding=list(task_data.get("jd_embedding") or []),
                )
            }

        if agent_type == "jd_parser":
            text = _first_string(task_data, ("doc_text", "jd_text", "job_description"))
            if not text:
                raise ValueError("jd_parser requires doc_text/jd_text")
            updates = await hr_multi_agent_runtime.run_agent(
                "jd_parser_agent",
                {"jd_text": text, "timeout_s": timeout_s},
            )
            parsed_job = updates.get("parsed_job")
            if not isinstance(parsed_job, dict):
                raise ValueError("jd_parser_agent missing parsed_job")
            return {"parsed_job": parsed_job}

        if agent_type == "jd_generator":
            updates = await hr_multi_agent_runtime.run_agent(
                "jd_generator_agent",
                {
                    "role": str(task_data.get("role") or "Role"),
                    "experience_min": int(task_data.get("experience_min") or 0),
                    "experience_max": int(task_data.get("experience_max") or 5),
                    "location": str(task_data.get("location") or "Remote"),
                    "additional_context": str(task_data.get("additional_context") or task_data.get("context") or ""),
                    "timeout_s": timeout_s,
                },
            )
            jd_data = updates.get("jd_data")
            if not isinstance(jd_data, dict):
                raise ValueError("jd_generator_agent missing jd_data")
            return {"jd_data": jd_data}

        if agent_type == "quiz_generator":
            return {
                "questions": await hr_multi_agent_runtime.generate_quiz(
                    jd_text=str(task_data.get("jd_text") or ""),
                    skills=list(task_data.get("skills") or []),
                    easy=int(task_data.get("easy") or 8),
                    medium=int(task_data.get("medium") or 8),
                    hard=int(task_data.get("hard") or 4),
                    timeout_s=timeout_s,
                )
            }

        if agent_type == "quiz_parser":
            text = _first_string(task_data, ("doc_text", "quiz_text"))
            if not text:
                raise ValueError("quiz_parser requires doc_text")
            return {"questions": await hr_multi_agent_runtime.parse_quiz_document(text)}

        if agent_type == "code_evaluator":
            return {
                "code_eval_result": await hr_multi_agent_runtime.evaluate_code(
                    problem_statement=str(task_data.get("problem_statement") or task_data.get("problem") or ""),
                    user_code=str(task_data.get("user_code") or task_data.get("code") or ""),
                    language=str(task_data.get("language") or "python"),
                )
            }

        if agent_type == "resume_enhancer":
            return {
                "enhancement_result": await hr_multi_agent_runtime.enhance_resume(
                    resume_text=_first_string(task_data, ("resume_text", "text")),
                    job_title=str(task_data.get("job_title") or task_data.get("title") or task_data.get("role") or "Role"),
                    must_have=list(task_data.get("must_have") or task_data.get("must_have_skills") or []),
                    good_to_have=list(task_data.get("good_to_have") or task_data.get("good_to_have_skills") or []),
                    job_description=str(task_data.get("description") or ""),
                )
            }

        if agent_type == "resume_builder":
            return {
                "built_resume": await hr_multi_agent_runtime.build_resume(
                    candidate_data=task_data.get("candidate_data") or {},
                    target_role=str(task_data.get("target_role") or ""),
                )
            }

        if agent_type == "cover_letter":
            parsed_resume = task_data.get("parsed_resume") or {}
            return {
                "cover_letter": await hr_multi_agent_runtime.generate_cover_letter(
                    candidate_name=str(task_data.get("candidate_name") or parsed_resume.get("name") or "Candidate"),
                    exp_years=float(task_data.get("exp_years") or parsed_resume.get("experience_years") or 0.0),
                    skills=list(task_data.get("skills") or parsed_resume.get("skills") or []),
                    work_history=list(task_data.get("work_history") or parsed_resume.get("work_experience") or []),
                    education=list(task_data.get("education") or parsed_resume.get("education") or []),
                    company_name=str(task_data.get("company_name") or "the company"),
                    job_title=str(task_data.get("job_title") or task_data.get("title") or task_data.get("role") or "Role"),
                    must_have=list(task_data.get("must_have") or task_data.get("must_have_skills") or []),
                    job_description=str(task_data.get("description") or ""),
                )
            }

        if agent_type == "career_analyst":
            return {
                "career_analysis": await hr_multi_agent_runtime.analyze_career_path(
                    candidate_name=str(task_data.get("candidate_name") or "Candidate"),
                    experience_years=float(task_data.get("experience_years") or task_data.get("exp_years") or 0.0),
                    skills=list(task_data.get("skills") or []),
                    work_history=list(task_data.get("work_history") or []),
                    education=list(task_data.get("education") or []),
                    career_breaks=list(task_data.get("career_breaks") or []),
                    target_role=str(task_data.get("target_role") or "Software Engineer"),
                )
            }

        if agent_type == "hr_email_draft":
            return {
                "draft": await hr_multi_agent_runtime.draft_hr_email(
                    email_type=str(task_data.get("email_type") or "general"),
                    candidate_name=str(task_data.get("candidate_name") or "Candidate"),
                    job_title=str(task_data.get("job_title") or "Role"),
                    resume_score=float(task_data.get("resume_score") or 0.0),
                    quiz_score=float(task_data.get("quiz_score") or 0.0),
                )
            }

        if agent_type == "candidate_ranker":
            return {
                "ranking_result": await hr_multi_agent_runtime.rank_candidates(
                    jd=task_data.get("jd") or {},
                    candidates=task_data.get("candidates") or [],
                    use_lyzr=bool(task_data.get("use_lyzr", True)),
                )
            }

        if agent_type == "resume_pipeline":
            parsed_job = task_data.get("parsed_job")
            if not isinstance(parsed_job, dict):
                parsed_job = {}
            state = await hr_multi_agent_runtime.run_resume_pipeline(
                filename=str(task_data.get("filename") or "resume.pdf"),
                content=_decode_bytes(task_data),
                parsed_job=parsed_job,
                job_id=task_data.get("job_id"),
                candidate_email=task_data.get("candidate_email"),
                timeout_s=timeout_s,
            )
            return state if isinstance(state, dict) else {"result": state}
    except (HRMultiAgentRuntimeError, ValueError, TypeError) as exc:
        raise HarnessAgentError(agent_type, "runtime_error", str(exc)) from exc
    except Exception as exc:
        raise HarnessAgentError(agent_type, "runtime_error", str(exc)) from exc

    raise HarnessAgentError(agent_type, "unsupported", f"No runtime dispatch for agent_type={agent_type}")


async def _run_via_harness(
    *,
    agent_type: str,
    task_data: dict[str, Any],
    auth_header: str | None,
    timeout_s: float,
    poll_interval_s: float,
) -> dict[str, Any]:
    del poll_interval_s

    cooldown_left = _harness_redis_cooldown_remaining()
    if cooldown_left > 0:
        raise HarnessAgentError(
            agent_type,
            "harness_unavailable",
            f"{_harness_redis_unavailable_detail()} (retrying harness in ~{cooldown_left:.1f}s)",
        )

    try:
        import redis.asyncio as aioredis
        from harness.core.config import get_config
        from harness.orchestrator.runner import AgentRunner
        from harness.workers.agent_worker import build_agent_factory, register_agent

        from app.agents.harness_plugins import HR_AGENT_TYPES, _HR_AGENT_FACTORY

        if agent_type not in HR_AGENT_TYPES:
            raise HarnessAgentError(agent_type, "unsupported", f"Unsupported harness agent_type={agent_type}")

        # Ensure HR plugin agent types are present in the upstream Harness registry.
        for registered_type, agent_cls in _HR_AGENT_FACTORY.items():
            register_agent(registered_type, agent_cls)

        cfg = get_config()
        tenant_id = _resolve_tenant_id(auth_header)
        task_payload = json.dumps(task_data, ensure_ascii=False)
        redis_url = settings.REDIS_URL or cfg.redis_url or "redis://127.0.0.1:6379/0"
        redis_client = aioredis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
        )

        workspace_base = Path(__file__).resolve().parents[2] / "harness_workspaces"
        workspace_base.mkdir(parents=True, exist_ok=True)
        agent_factory = build_agent_factory(cfg)

        runner = AgentRunner(
            redis=redis_client,
            agent_factory=agent_factory,
            workspace_base=str(workspace_base),
        )
    except HarnessAgentError:
        raise
    except Exception as setup_exc:
        detail = f"harness setup unavailable: {setup_exc}"
        _mark_harness_redis_unavailable(detail)
        raise HarnessAgentError(agent_type, "harness_unavailable", detail) from setup_exc
    run_id: str | None = None
    try:
        try:
            await redis_client.ping()
            _clear_harness_redis_unavailable()
        except Exception as redis_exc:
            _mark_harness_redis_unavailable(str(redis_exc))
            raise HarnessAgentError(agent_type, "harness_error", str(redis_exc)) from redis_exc

        record = await runner.create_run(
            tenant_id=tenant_id,
            agent_type=agent_type,
            task=task_payload,
            metadata={
                "source": "hr_app",
                "inspect_mode": True,
            },
        )
        run_id = record.run_id
        finished = await asyncio.wait_for(
            runner.execute_run(run_id),
            timeout=max(5.0, timeout_s),
        )
        status = str(finished.status or "failed").lower()
        if status != "completed":
            result_obj = finished.result
            detail = ""
            if isinstance(result_obj, dict):
                detail = str(result_obj.get("error_message") or result_obj)
            if not detail:
                detail = f"run_id={run_id} status={status}"
            raise HarnessAgentError(agent_type, status, detail)
        return _extract_result_payload(finished.result)
    except asyncio.TimeoutError as exc:
        if run_id:
            try:
                await runner.cancel_run(run_id)
            except Exception:
                pass
        raise HarnessAgentError(
            agent_type,
            "timeout",
            f"Run {run_id} did not finish in {timeout_s:.1f}s",
        ) from exc
    except HarnessAgentError:
        raise
    except Exception as exc:
        detail = str(exc)
        lowered = detail.lower()
        if (
            "redis" in lowered
            or "127.0.0.1:6379" in lowered
            or "connection refused" in lowered
            or "error 22 connecting" in lowered
        ):
            _mark_harness_redis_unavailable(detail)
        raise HarnessAgentError(agent_type, "harness_error", str(exc)) from exc
    finally:
        await redis_client.aclose()


async def run_agent(
    agent_type: str,
    task_data: dict[str, Any],
    auth_header: str | None,
    *,
    timeout_s: float = 90.0,
    poll_interval_s: float = 0.4,
) -> dict[str, Any]:
    trace_cm = (
        mlflow_track_llm(
            task_name=f"harness.run_agent.{agent_type}",
            run_name=f"harness.agent.{agent_type}",
            tags={
                "component": "harness_agent_client",
                "agent_type": agent_type,
            },
        )
        if _mlflow_trace_enabled()
        else _noop_trace()
    )

    async with trace_cm:
        started = time.perf_counter()
        overall_timeout_s = max(5.0, float(timeout_s))
        deadline = started + overall_timeout_s
        token_monitor = get_token_monitor()
        token_checkpoint = token_monitor.checkpoint() if token_monitor.enabled else None
        source = "runtime"
        status = "completed"
        error_detail: str | None = None
        harness_error: HarnessAgentError | None = None

        def _remaining_s() -> float:
            return max(0.0, deadline - time.perf_counter())

        try:
            if (
                settings.HARNESS_EXECUTION_ENABLED
                and settings.HARNESS_ADAPTER_ENABLED
                and settings.HARNESS_MOUNT_ENABLED
            ):
                try:
                    harness_timeout_s = _remaining_s()
                    if harness_timeout_s <= 0:
                        raise HarnessAgentError(
                            agent_type,
                            "timeout",
                            f"Execution deadline exceeded before harness run ({overall_timeout_s:.1f}s budget)",
                        )
                    result = await _run_via_harness(
                        agent_type=agent_type,
                        task_data=task_data,
                        auth_header=auth_header,
                        timeout_s=harness_timeout_s,
                        poll_interval_s=poll_interval_s,
                    )
                    source = "harness"
                    return result
                except HarnessAgentError as exc:
                    harness_error = exc
                    if exc.status == "harness_unavailable":
                        if _should_log_harness_unavailable():
                            logger.warning(
                                "Harness temporarily unavailable for agent_type=%s; using in-process runtime fallback: %s",
                                agent_type,
                                exc,
                            )
                        else:
                            logger.debug(
                                "Harness temporarily unavailable for agent_type=%s; using in-process runtime fallback: %s",
                                agent_type,
                                exc,
                            )
                    else:
                        logger.warning(
                            "Harness run failed for agent_type=%s; falling back to in-process runtime: %s",
                            agent_type,
                            exc,
                        )
            elif not settings.HARNESS_EXECUTION_ENABLED:
                logger.debug(
                    "Harness execution disabled (HARNESS_EXECUTION_ENABLED=false). "
                    "Using in-process multi-agent runtime for agent_type=%s",
                    agent_type,
                )
            elif not settings.HARNESS_ADAPTER_ENABLED:
                logger.info(
                    "Harness adapter disabled (HARNESS_ADAPTER_ENABLED=false). "
                    "Using in-process multi-agent runtime for agent_type=%s",
                    agent_type,
                )

            runtime_timeout_s = _remaining_s()
            if runtime_timeout_s <= 0:
                raise HarnessAgentError(
                    agent_type,
                    "timeout",
                    f"Execution deadline exceeded before runtime fallback ({overall_timeout_s:.1f}s budget)",
                )

            runtime_task_data = dict(task_data or {})
            runtime_task_data["timeout_s"] = float(runtime_timeout_s)
            result = await _run_via_multi_agent_runtime(
                agent_type=agent_type,
                task_data=runtime_task_data,
            )
            source = "runtime_fallback" if harness_error is not None else "runtime"
            return result
        except HarnessAgentError as runtime_exc:
            status = "failed"
            if harness_error is not None:
                error_detail = (
                    f"harness={harness_error.detail}; runtime={runtime_exc.detail}"
                )
                raise HarnessAgentError(
                    agent_type,
                    "unavailable",
                    error_detail,
                ) from runtime_exc
            error_detail = runtime_exc.detail
            raise
        except Exception as exc:
            status = "failed"
            error_detail = str(exc)
            raise
        finally:
            token_delta = (
                token_monitor.delta_since(token_checkpoint)
                if token_checkpoint is not None
                else None
            )
            latency_ms = (time.perf_counter() - started) * 1000.0
            _log_agent_trace_artifacts(
                agent_type=agent_type,
                source=source,
                status=status,
                latency_ms=latency_ms,
                task_data=task_data,
                token_delta=token_delta,
                error=error_detail,
            )
            _record_observation(
                agent_type=agent_type,
                source=source,
                status=status,
                latency_ms=latency_ms,
                error_detail=error_detail,
                token_delta=token_delta,
            )


async def _execute_run_directly(*, run_id: str, agent_type: str) -> None:
    # Legacy no-op placeholder retained for backward compatibility with any
    # external imports; direct harness execution now happens inside _run_via_harness.
    del run_id, agent_type
