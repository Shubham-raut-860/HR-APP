from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services import file_service
from app.services.token_monitor_service import get_token_monitor


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _score_status(avg_score: float, pass_rate: float) -> str:
    if avg_score >= 0.75 and pass_rate >= 0.80:
        return "good"
    if avg_score >= 0.55 and pass_rate >= 0.60:
        return "watch"
    return "needs_attention"


def _build_prompt_recommendation(avg_score: float, pass_rate: float) -> str:
    status = _score_status(avg_score, pass_rate)
    if status == "good":
        return "Prompt quality is stable. Continue periodic evals and regression checks."
    if status == "watch":
        return "Prompt quality is mixed. Run targeted evals on failed cases and tune prompts for weak operations."
    return "Prompt quality is below target. Prioritize prompt patching + operation-specific eval datasets."


async def _prompt_quality_section(db: AsyncSession, user_id: str) -> dict[str, Any]:
    rows = await db.execute(
        text(
            """
            SELECT
                operation,
                COUNT(*) AS total_evals,
                AVG(overall_score) AS avg_score,
                SUM(CASE WHEN passed THEN 1 ELSE 0 END) AS passed_count,
                MAX(evaluated_at) AS latest_eval
            FROM eval_results
            WHERE user_id = :uid
            GROUP BY operation
            ORDER BY operation
            """
        ),
        {"uid": user_id},
    )
    records = rows.mappings().all()
    by_operation: list[dict[str, Any]] = []
    total = 0
    weighted_sum = 0.0
    passed_total = 0
    latest_eval: datetime | None = None

    for rec in records:
        count = int(rec["total_evals"] or 0)
        avg = float(rec["avg_score"] or 0.0)
        passed = int(rec["passed_count"] or 0)
        pass_rate = (passed / count) if count else 0.0
        op_latest = rec["latest_eval"]
        if isinstance(op_latest, datetime):
            latest_eval = max(latest_eval, op_latest) if latest_eval else op_latest

        total += count
        weighted_sum += avg * count
        passed_total += passed

        by_operation.append(
            {
                "operation": str(rec["operation"]),
                "total_evals": count,
                "avg_score": round(avg, 4),
                "pass_rate": round(pass_rate, 4),
                "status": _score_status(avg, pass_rate),
            }
        )

    overall_avg = (weighted_sum / total) if total else 0.0
    overall_pass_rate = (passed_total / total) if total else 0.0
    return {
        "total_evals": total,
        "overall_avg_score": round(overall_avg, 4),
        "overall_pass_rate": round(overall_pass_rate, 4),
        "latest_eval_at": latest_eval.isoformat() if latest_eval else None,
        "status": _score_status(overall_avg, overall_pass_rate),
        "recommendation": _build_prompt_recommendation(overall_avg, overall_pass_rate),
        "by_operation": by_operation,
    }


def _model_fit_section(window_minutes: int) -> dict[str, Any]:
    monitor = get_token_monitor()
    summary = monitor.summary(window_minutes=window_minutes)
    models = monitor.model_efficiency(window_minutes=window_minutes)
    recommendations = monitor.recommendations(window_minutes=window_minutes, min_calls=5)

    model_notes: list[dict[str, Any]] = []
    for row in models:
        over_budget_rate = float(row.get("over_budget_rate_pct", 0.0) or 0.0)
        avg_latency = float(row.get("avg_latency_ms", 0.0) or 0.0)
        if over_budget_rate > 20.0 or avg_latency > 10000.0:
            status = "watch"
        else:
            status = "good"
        model_notes.append(
            {
                "model": row.get("model"),
                "status": status,
                "avg_latency_ms": row.get("avg_latency_ms"),
                "cost_per_1k_tokens_usd": row.get("cost_per_1k_tokens_usd"),
                "over_budget_rate_pct": row.get("over_budget_rate_pct"),
            }
        )

    return {
        "window_minutes": window_minutes,
        "token_summary": summary,
        "models": models,
        "recommendations": recommendations,
        "model_health_notes": model_notes,
        "configured_task_model_map": settings.agent_model_map,
    }


async def _ocr_quality_section(db: AsyncSession, user_id: str, sample_limit: int = 200) -> dict[str, Any]:
    rows = await db.execute(
        text(
            """
            SELECT c.raw_resume_text
            FROM candidates c
            LEFT JOIN job_descriptions j ON c.job_id = j.id
            WHERE (
                (j.created_by = :uid)
                OR (c.job_id IS NULL AND c.user_id = :uid)
            )
            ORDER BY c.created_at DESC
            LIMIT :sample_limit
            """
        ),
        {"uid": user_id, "sample_limit": int(sample_limit)},
    )
    records = rows.fetchall()

    with_text = 0
    looks_valid = 0
    for (raw_text,) in records:
        if not raw_text:
            continue
        text_value = str(raw_text)
        if not text_value.strip():
            continue
        with_text += 1
        if file_service._text_looks_valid(text_value):
            looks_valid += 1

    quality_rate = (looks_valid / with_text) if with_text else 0.0
    if with_text == 0:
        status = "unknown"
        recommendation = "No parsed resumes yet. Upload sample resumes to benchmark OCR quality."
    elif quality_rate >= 0.90:
        status = "good"
        recommendation = "OCR/extraction quality looks healthy for recent resumes."
    elif quality_rate >= 0.75:
        status = "watch"
        recommendation = "Some resumes appear low-quality; monitor scanned PDFs and image uploads."
    else:
        status = "needs_attention"
        recommendation = "High OCR risk detected. Validate Tesseract setup and scanned-PDF preprocessing."

    return {
        "status": status,
        "recommendation": recommendation,
        "tesseract_available": bool(file_service._TESSERACT_AVAILABLE),
        "max_file_size_mb": int(settings.MAX_FILE_SIZE_MB),
        "ocr_pdf_text_threshold": int(file_service._PDF_TEXT_THRESHOLD),
        "ocr_max_pages": int(file_service._MAX_OCR_PAGES),
        "supported_extensions": sorted(file_service.ALL_ALLOWED_EXTENSIONS),
        "sampled_candidates": int(len(records)),
        "sampled_with_text": int(with_text),
        "valid_text_ratio": round(quality_rate, 4),
    }


def _harness_section() -> dict[str, Any]:
    backend_root = Path(__file__).resolve().parents[2]
    vendor_path = backend_root / "vendor" / "HarnessAgent-main"
    return {
        "vendor_present": vendor_path.exists(),
        "mount_enabled": bool(settings.HARNESS_MOUNT_ENABLED),
        "adapter_enabled": bool(settings.HARNESS_ADAPTER_ENABLED),
        "trace_recorder_enabled": bool(settings.HARNESS_TRACE_RECORDER_ENABLED),
        "bulk_use_harness_pipeline": bool(settings.BULK_USE_HARNESS_PIPELINE),
        "notes": [
            "Harness can evaluate prompt/model/runtime quality when mounted and routed through /harness/* endpoints.",
            "OCR quality is managed by HR app file_service OCR pipeline, not by Harness core.",
        ],
    }


async def build_ai_capability_report(
    *,
    db: AsyncSession,
    user_id: str,
    window_minutes: int,
) -> dict[str, Any]:
    prompt_quality = await _prompt_quality_section(db=db, user_id=user_id)
    model_fit = _model_fit_section(window_minutes=window_minutes)
    ocr_quality = await _ocr_quality_section(db=db, user_id=user_id)
    harness = _harness_section()

    return {
        "generated_at": _utc_now_iso(),
        "window_minutes": int(window_minutes),
        "prompt_quality": prompt_quality,
        "model_fit": model_fit,
        "ocr_quality": ocr_quality,
        "harness_runtime": harness,
    }

