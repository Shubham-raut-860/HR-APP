from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx
from app.config import settings

logger = logging.getLogger(__name__)


class HarnessAgentError(Exception):
    def __init__(self, agent_type: str, status: str, detail: str):
        self.agent_type = agent_type
        self.status = status
        self.detail = detail
        super().__init__(f"[{agent_type}] {status}: {detail}")


def _harness_base_url() -> str:
    port = int(getattr(settings, "APP_PORT", 8000) or 8000)
    return f"http://127.0.0.1:{port}/harness"


def _headers(auth_header: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if auth_header:
        headers["Authorization"] = auth_header
    return headers


def _ensure_harness_vendor_path() -> None:
    project_root = Path(__file__).resolve().parents[2]
    harness_src = project_root / "vendor" / "HarnessAgent-main" / "src"
    src_str = str(harness_src)
    if harness_src.exists() and src_str not in os.sys.path:
        os.sys.path.insert(0, src_str)


def _get_mounted_harness_redis() -> Any | None:
    main_mod = os.sys.modules.get("app.main")
    harness_app = getattr(main_mod, "_HARNESS_SUBAPP", None) if main_mod else None
    if harness_app is None:
        return None
    return getattr(getattr(harness_app, "state", None), "redis", None)


async def run_agent(
    agent_type: str,
    task_data: dict[str, Any],
    auth_header: str | None,
    *,
    timeout_s: float = 90.0,
    poll_interval_s: float = 0.4,
) -> dict[str, Any]:
    if not settings.HARNESS_ADAPTER_ENABLED:
        raise HarnessAgentError(agent_type, "disabled", "HARNESS_ADAPTER_ENABLED=False")

    base_url = _harness_base_url()
    payload = {
        "agent_type": agent_type,
        "task": json.dumps(task_data or {}, ensure_ascii=False),
        "metadata": {},
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        create_resp = await client.post(
            f"{base_url}/runs",
            json=payload,
            headers=_headers(auth_header),
        )

    if create_resp.status_code not in (200, 201):
        raise HarnessAgentError(
            agent_type,
            "create_failed",
            (create_resp.text or "")[:500],
        )

    try:
        run_record = create_resp.json()
    except Exception as exc:
        raise HarnessAgentError(agent_type, "create_parse_failed", str(exc)) from exc

    run_id = str((run_record or {}).get("run_id") or "").strip()
    if not run_id:
        raise HarnessAgentError(agent_type, "create_missing_run_id", str(run_record))

    # Bypass RQ queue stalls for custom agent_type queues.
    asyncio.create_task(_execute_run_directly(run_id, agent_type))

    deadline = time.monotonic() + max(5.0, timeout_s)
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        while time.monotonic() < deadline:
            await asyncio.sleep(max(0.2, poll_interval_s))
            poll_resp = await client.get(
                f"{base_url}/runs/{run_id}",
                headers=_headers(auth_header),
            )
            if poll_resp.status_code != 200:
                continue
            try:
                poll_data = poll_resp.json()
            except Exception:
                continue

            status = str((poll_data or {}).get("status") or "pending").lower()
            if status == "completed":
                result = (poll_data or {}).get("result") or {}
                if isinstance(result, dict):
                    output_data = result.get("output_data")
                    if isinstance(output_data, dict):
                        return output_data
                    return result
                return {}
            if status in {"failed", "cancelled", "budget_exceeded"}:
                result = (poll_data or {}).get("result") or {}
                detail = (
                    result.get("error_message")
                    if isinstance(result, dict)
                    else str(result)
                )
                raise HarnessAgentError(agent_type, status, str(detail or "unknown"))

    raise HarnessAgentError(agent_type, "timeout", f"Run {run_id} did not complete in {timeout_s}s")


async def _execute_run_directly(run_id: str, agent_type: str) -> None:
    _ensure_harness_vendor_path()
    import redis.asyncio as aioredis
    from harness.orchestrator.runner import AgentRunner

    from app.agents.harness_plugins import build_hr_agent
    redis_client: Any | None = None
    should_close = False
    try:
        redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
        )
        await redis_client.ping()
        should_close = True
    except Exception:
        redis_client = _get_mounted_harness_redis()
        if redis_client is None:
            logger.error(
                "Direct harness execute_run aborted run_id=%s agent_type=%s: no Redis backend available",
                run_id,
                agent_type,
            )
            return

    workspace_base = (
        os.getenv("WORKSPACE_BASE_PATH")
        or str((Path(__file__).resolve().parents[2] / "harness_workspaces").resolve())
    )
    try:
        runner = AgentRunner(
            redis=redis_client,
            agent_factory=build_hr_agent,
            workspace_base=workspace_base,
        )
        await runner.execute_run(run_id)
    except Exception as exc:
        logger.error(
            "Direct harness execute_run failed run_id=%s agent_type=%s error=%s",
            run_id,
            agent_type,
            exc,
        )
    finally:
        if should_close and redis_client is not None:
            await redis_client.aclose()
