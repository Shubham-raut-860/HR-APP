from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.ai_capability_report_service import build_ai_capability_report
from app.services.token_monitor_service import get_token_monitor


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_harness_vendor_path() -> None:
    project_root = Path(__file__).resolve().parents[2]
    harness_src = project_root / "vendor" / "HarnessAgent-main" / "src"
    src_str = str(harness_src)
    if harness_src.exists() and src_str not in sys.path:
        sys.path.insert(0, src_str)


def _empty_harness_snapshot(reason: str) -> dict[str, Any]:
    return {
        "status": reason,
        "redis_reachable": False,
        "run_count": 0,
        "recent_runs": [],
        "trace_summaries": [],
        "metrics": {
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "inflight": 0,
            "success_rate": 0.0,
            "avg_elapsed_seconds": 0.0,
            "avg_steps": 0.0,
            "avg_tokens": 0.0,
            "avg_cost_usd": 0.0,
        },
    }


def _run_metrics(recent_runs: list[dict[str, Any]]) -> dict[str, Any]:
    if not recent_runs:
        return {
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "inflight": 0,
            "success_rate": 0.0,
            "avg_elapsed_seconds": 0.0,
            "avg_steps": 0.0,
            "avg_tokens": 0.0,
            "avg_cost_usd": 0.0,
        }

    completed_rows = [r for r in recent_runs if r["status"] == "completed"]
    failed_rows = [r for r in recent_runs if r["status"] == "failed"]
    cancelled_rows = [r for r in recent_runs if r["status"] == "cancelled"]
    inflight_rows = [
        r for r in recent_runs if r["status"] in {"pending", "running"}
    ]
    term_rows = completed_rows + failed_rows + cancelled_rows
    success_rate = (
        len(completed_rows) / len(term_rows) if term_rows else 0.0
    )

    avg = lambda arr, key: (sum(float(x.get(key) or 0.0) for x in arr) / len(arr)) if arr else 0.0

    return {
        "completed": len(completed_rows),
        "failed": len(failed_rows),
        "cancelled": len(cancelled_rows),
        "inflight": len(inflight_rows),
        "success_rate": round(success_rate, 4),
        "avg_elapsed_seconds": round(avg(completed_rows, "elapsed_seconds"), 4),
        "avg_steps": round(avg(completed_rows, "steps"), 2),
        "avg_tokens": round(avg(completed_rows, "tokens"), 2),
        "avg_cost_usd": round(avg(completed_rows, "cost_usd"), 6),
    }


async def _harness_snapshot(
    *,
    user_id: str,
    run_limit: int,
    trace_limit: int,
) -> dict[str, Any]:
    if not settings.HARNESS_MOUNT_ENABLED:
        return _empty_harness_snapshot("disabled")

    _ensure_harness_vendor_path()

    try:
        import redis.asyncio as aioredis
        from harness.orchestrator.runner import AgentRunner
        from harness.observability.trace_recorder import TraceRecorder
    except Exception as exc:
        snap = _empty_harness_snapshot("unavailable")
        snap["detail"] = str(exc)
        return snap

    redis_url = (settings.REDIS_URL or "redis://127.0.0.1:6379/0").strip()
    redis_client = aioredis.from_url(
        redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=4,
    )
    recorder = None
    try:
        await redis_client.ping()
        runner = AgentRunner(
            redis=redis_client,
            agent_factory=lambda _agent_type: None,
            workspace_base=str((Path(__file__).resolve().parents[2] / "harness_workspaces").resolve()),
        )
        records = await runner.list_runs(
            tenant_id=str(user_id),
            limit=max(1, int(run_limit)),
            offset=0,
        )
        recent_runs: list[dict[str, Any]] = []
        trace_summaries: list[dict[str, Any]] = []

        for rec in records:
            result = rec.result if isinstance(rec.result, dict) else {}
            recent_runs.append(
                {
                    "run_id": rec.run_id,
                    "agent_type": rec.agent_type,
                    "status": rec.status,
                    "created_at": rec.created_at.isoformat() if rec.created_at else None,
                    "started_at": rec.started_at.isoformat() if rec.started_at else None,
                    "completed_at": rec.completed_at.isoformat() if rec.completed_at else None,
                    "success": bool(result.get("success", rec.status == "completed")),
                    "steps": int(result.get("steps") or 0),
                    "tokens": int(result.get("tokens") or 0),
                    "cost_usd": float(result.get("cost_usd") or 0.0),
                    "elapsed_seconds": float(result.get("elapsed_seconds") or 0.0),
                    "failure_class": result.get("failure_class"),
                    "error_message": result.get("error_message"),
                }
            )

        if recent_runs:
            recorder = TraceRecorder.create(redis_url=redis_url)
            trace_candidates = [
                r for r in recent_runs if r["status"] in {"completed", "failed", "cancelled"}
            ][: max(1, int(trace_limit))]
            for run_row in trace_candidates:
                try:
                    trace = await recorder.get_trace(run_row["run_id"])
                except Exception:
                    trace = None
                if not trace:
                    continue
                trace_summaries.append(
                    {
                        "run_id": run_row["run_id"],
                        "status": trace.status.value if hasattr(trace.status, "value") else str(trace.status),
                        "span_count": int(trace.span_count),
                        "duration_ms": float(trace.duration_ms or 0.0),
                        "total_input_tokens": int(trace.total_input_tokens),
                        "total_output_tokens": int(trace.total_output_tokens),
                        "total_cost_usd": float(trace.total_cost_usd),
                    }
                )

        return {
            "status": "ok",
            "redis_reachable": True,
            "run_count": len(recent_runs),
            "recent_runs": recent_runs,
            "trace_summaries": trace_summaries,
            "metrics": _run_metrics(recent_runs),
        }
    except Exception as exc:
        snap = _empty_harness_snapshot("error")
        snap["detail"] = str(exc)
        return snap
    finally:
        try:
            if recorder is not None and hasattr(recorder, "aclose"):
                await recorder.aclose()
        except Exception:
            pass
        await redis_client.aclose()


def _readiness_report(
    *,
    capability: dict[str, Any],
    harness: dict[str, Any],
) -> dict[str, Any]:
    checks = {
        "harness_mount_enabled": bool(settings.HARNESS_MOUNT_ENABLED),
        "harness_execution_enabled": bool(settings.HARNESS_EXECUTION_ENABLED),
        "harness_trace_enabled": bool(settings.HARNESS_TRACE_RECORDER_ENABLED),
        "harness_redis_reachable": bool(harness.get("redis_reachable")),
        "mlflow_uri_configured": bool((os.environ.get("MLFLOW_TRACKING_URI") or settings.MLFLOW_TRACKING_URI or "").strip()),
        "evals_enabled": bool(settings.EVALS_ENABLED),
        "token_monitor_enabled": bool(settings.TOKEN_MONITOR_ENABLED),
    }

    pass_count = sum(1 for ok in checks.values() if ok)
    infra_score = round((pass_count / len(checks)) * 100.0, 2)
    harness_metrics = harness.get("metrics", {}) if isinstance(harness, dict) else {}
    success_rate = float(harness_metrics.get("success_rate") or 0.0)
    prompt_status = (
        capability.get("prompt_quality", {}).get("status")
        if isinstance(capability, dict)
        else "unknown"
    )

    if infra_score >= 85 and success_rate >= 0.75 and prompt_status in {"good", "watch"}:
        verdict = "production_ready"
    elif infra_score >= 65:
        verdict = "watch"
    else:
        verdict = "not_ready"

    notes: list[str] = []
    if not checks["harness_redis_reachable"]:
        notes.append("Harness Redis backend is unavailable; run orchestration and traces are degraded.")
    if not checks["harness_trace_enabled"]:
        notes.append("Harness trace recorder is disabled; behavior visibility is limited.")
    if not checks["harness_execution_enabled"]:
        notes.append("Harness is running in inspector-only mode; core task execution uses native multi-agent runtime.")
    if prompt_status == "needs_attention":
        notes.append("Prompt quality metrics are below target; tune prompts and re-run eval suites.")
    if success_rate < 0.5 and harness.get("run_count", 0) > 0:
        notes.append("Recent harness run success rate is low; investigate failed runs and traces.")
    if not notes:
        notes.append("Core inspector signals look healthy; continue periodic regression and load checks.")

    return {
        "verdict": verdict,
        "infrastructure_score": infra_score,
        "checks": checks,
        "notes": notes,
    }


async def build_hr_inspector_overview(
    *,
    db: AsyncSession,
    user_id: str,
    window_minutes: int = 1440,
    run_limit: int = 20,
    trace_limit: int = 8,
) -> dict[str, Any]:
    capability = await build_ai_capability_report(
        db=db,
        user_id=str(user_id),
        window_minutes=int(window_minutes),
    )
    harness = await _harness_snapshot(
        user_id=str(user_id),
        run_limit=max(1, min(100, int(run_limit))),
        trace_limit=max(1, min(25, int(trace_limit))),
    )
    monitor = get_token_monitor()
    token_summary = monitor.summary(window_minutes=int(window_minutes))
    token_recommendations = monitor.recommendations(
        window_minutes=int(window_minutes),
        min_calls=5,
    )
    readiness = _readiness_report(capability=capability, harness=harness)

    return {
        "generated_at": _utc_now_iso(),
        "window_minutes": int(window_minutes),
        "readiness": readiness,
        "harness": harness,
        "model_fit": capability.get("model_fit"),
        "prompt_quality": capability.get("prompt_quality"),
        "ocr_quality": capability.get("ocr_quality"),
        "token_monitor": {
            "summary": token_summary,
            "recommendations": token_recommendations,
        },
    }
