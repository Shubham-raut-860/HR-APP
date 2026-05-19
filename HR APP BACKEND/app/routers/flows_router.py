"""
[EXPERIMENTAL] Flows router - Metaflow batch scoring dispatch.

This router is only registered when ENABLE_METAFLOW=True in .env.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.config import settings
from app.models import User
from app.services.auth_service import require_hr

logger = logging.getLogger(__name__)


def _metaflow_enabled_guard() -> None:
    if not settings.ENABLE_METAFLOW:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Metaflow integration is disabled.",
        )
    if str(getattr(settings, "APP_ENV", "")).lower() == "production":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Metaflow integration is disabled in production.",
        )


router = APIRouter(
    prefix="/admin/flows",
    tags=["Flows [EXPERIMENTAL]"],
    dependencies=[Depends(_metaflow_enabled_guard)],
)

_FLOWS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "flows")
_BATCH_SCORE_SCRIPT = os.path.abspath(os.path.join(_FLOWS_DIR, "batch_scoring_flow.py"))
_FLOW_LOGS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "logs", "flows"))
_FLOW_STATUS: dict[str, dict] = {}
_flow_background_tasks: set[asyncio.Task] = set()
_FLOW_DISPATCH_SEMAPHORE = asyncio.Semaphore(1)
_FLOW_QUEUE_MAX_SIZE = settings.FLOW_QUEUE_MAX_SIZE
_FLOW_QUEUE: asyncio.Queue[dict] = asyncio.Queue(maxsize=_FLOW_QUEUE_MAX_SIZE)
_FLOW_WORKER_TASK: asyncio.Task | None = None
_FLOW_WORKER_LOCK = asyncio.Lock()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _run_batch_score_subprocess(run_id: str, cmd: list[str], cwd: str, user_email: str) -> None:
    async with _FLOW_DISPATCH_SEMAPHORE:
        proc: asyncio.subprocess.Process | None = None
        log_path = os.path.join(_FLOW_LOGS_DIR, f"{run_id.replace('/', '_')}.log")
        Path(_FLOW_LOGS_DIR).mkdir(parents=True, exist_ok=True)
        try:
            _FLOW_STATUS[run_id] = {
                **_FLOW_STATUS.get(run_id, {}),
                "status": "running",
                "started_at": _utc_now_iso(),
                "log_path": log_path,
            }
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            _FLOW_STATUS[run_id]["pid"] = proc.pid
            stdout_bytes, stderr_bytes = await proc.communicate()
            stdout_text = (stdout_bytes or b"").decode("utf-8", errors="replace")
            stderr_text = (stderr_bytes or b"").decode("utf-8", errors="replace")
            combined_log = (
                f"[run_id] {run_id}\n"
                f"[requested_by] {user_email}\n"
                f"[started_at] {_FLOW_STATUS[run_id].get('started_at')}\n"
                f"[command] {' '.join(cmd)}\n\n"
                f"=== STDOUT ===\n{stdout_text}\n\n"
                f"=== STDERR ===\n{stderr_text}\n"
            )
            Path(log_path).write_text(combined_log, encoding="utf-8")
            stderr_tail = "\n".join((stderr_text or "").splitlines()[-200:])
            rc = proc.returncode if proc.returncode is not None else 1
            _FLOW_STATUS[run_id] = {
                **_FLOW_STATUS.get(run_id, {}),
                "status": "completed" if rc == 0 else "failed",
                "return_code": rc,
                "stderr_tail": stderr_tail,
                "finished_at": _utc_now_iso(),
            }
            logger.info(
                "BatchScoringFlow finished run_id=%s rc=%s pid=%s user=%s",
                run_id, rc, proc.pid, user_email
            )
        except asyncio.CancelledError:
            if proc and proc.returncode is None:
                proc.terminate()
                await proc.wait()
            _FLOW_STATUS[run_id] = {
                **_FLOW_STATUS.get(run_id, {}),
                "status": "cancelled",
                "finished_at": _utc_now_iso(),
            }
            raise
        except Exception as exc:
            logger.exception("BatchScoringFlow execution failed for run_id=%s", run_id)
            _FLOW_STATUS[run_id] = {
                **_FLOW_STATUS.get(run_id, {}),
                "status": "failed",
                "error": str(exc),
                "finished_at": _utc_now_iso(),
            }


async def _flow_worker_loop() -> None:
    while True:
        job = await _FLOW_QUEUE.get()
        run_id = job["run_id"]
        try:
            await _run_batch_score_subprocess(
                run_id=run_id,
                cmd=job["cmd"],
                cwd=job["cwd"],
                user_email=job["user_email"],
            )
        except Exception:
            logger.exception("Flow worker failed for run_id=%s", run_id)
        finally:
            _FLOW_QUEUE.task_done()


async def _ensure_flow_worker() -> None:
    global _FLOW_WORKER_TASK
    async with _FLOW_WORKER_LOCK:
        if _FLOW_WORKER_TASK and not _FLOW_WORKER_TASK.done():
            return
        _FLOW_WORKER_TASK = asyncio.create_task(_flow_worker_loop())
        _flow_background_tasks.add(_FLOW_WORKER_TASK)
        _FLOW_WORKER_TASK.add_done_callback(lambda t: _flow_background_tasks.discard(t))


class BatchScoreRequest(BaseModel):
    job_id: str = Field(..., description="UUID of the JobDescription to score candidates for")
    limit: int = Field(default=20, ge=0, le=500, description="Max candidates to score (0 = no limit)")
    use_llm: bool = Field(default=False, description="Enable AI-boosted scoring (costs Azure credits)")
    strong_threshold: float = Field(default=75.0, ge=0, le=100)
    medium_threshold: float = Field(default=55.0, ge=0, le=100)


class BatchScoreResponse(BaseModel):
    run_id: str
    status: str
    message: str
    pid: Optional[int] = None


@router.post(
    "/batch-score",
    response_model=BatchScoreResponse,
    summary="[EXPERIMENTAL] Dispatch a Metaflow batch candidate re-scoring run",
    description=(
        "Queues a BatchScoringFlow subprocess for the given job_id and returns "
        "immediately. Results are written back to the database asynchronously. "
        "Only available when ENABLE_METAFLOW=True in .env."
    ),
)
async def dispatch_batch_score(
    body: BatchScoreRequest,
    user: User = Depends(require_hr),
) -> BatchScoreResponse:
    if not os.path.isfile(_BATCH_SCORE_SCRIPT):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"BatchScoringFlow script not found at {_BATCH_SCORE_SCRIPT}. "
                "Ensure flows/batch_scoring_flow.py exists in the Backend directory."
            ),
        )

    cmd = [
        sys.executable,
        _BATCH_SCORE_SCRIPT,
        "run",
        "--job_id", body.job_id,
        "--limit", str(body.limit),
        "--use_llm", str(body.use_llm).lower(),
        "--strong_threshold", str(body.strong_threshold),
        "--medium_threshold", str(body.medium_threshold),
    ]

    run_id = f"BatchScoringFlow/job_{body.job_id[:8]}/{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    _FLOW_STATUS[run_id] = {
        "run_id": run_id,
        "job_id": body.job_id,
        "use_llm": body.use_llm,
        "limit": body.limit,
        "status": "queued",
        "queued_at": _utc_now_iso(),
        "queue_depth": _FLOW_QUEUE.qsize(),
        "requested_by": user.email,
    }
    backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    await _ensure_flow_worker()
    if _FLOW_QUEUE.full():
        _FLOW_STATUS[run_id] = {
            **_FLOW_STATUS.get(run_id, {}),
            "status": "rejected",
            "error": "Flow queue is full",
            "finished_at": _utc_now_iso(),
        }
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Flow queue is full. Try again shortly.",
        )
    await _FLOW_QUEUE.put({
        "run_id": run_id,
        "cmd": cmd,
        "cwd": backend_root,
        "user_email": user.email,
    })

    logger.info(
        "Queued BatchScoringFlow | job_id=%s limit=%d use_llm=%s run_id=%s user=%s",
        body.job_id, body.limit, body.use_llm, run_id, user.email,
    )

    return BatchScoreResponse(
        run_id=run_id,
        status="dispatched",
        message=(
            "BatchScoringFlow queued and supervised by API worker. "
            f"Scores will be written to DB for up to {body.limit or 'all'} candidates."
        ),
        pid=None,
    )


@router.get("/batch-score/{run_id}", summary="[EXPERIMENTAL] Get batch-score run status")
async def get_batch_score_status(
    run_id: str,
    user: User = Depends(require_hr),
) -> dict:
    status_row = _FLOW_STATUS.get(run_id)
    if not status_row:
        raise HTTPException(status_code=404, detail="Run not found")
    return status_row
