from __future__ import annotations

import json
import os
import time
from typing import Any, Callable

import httpx

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


TERMINAL_TASK_STATUSES = {"completed", "failed", "canceled"}


class HireAIClientError(RuntimeError):
    """Raised when HIREAI cannot be reached or rejects a sidecar request."""


def _backend_url() -> str:
    return os.getenv("HIREAI_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")


def _timeout_seconds() -> float:
    raw = os.getenv("HIREAI_HTTP_TIMEOUT_SECONDS", "20")
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 20.0


def _token_for_scope(token_scope: str) -> str:
    if token_scope == "hr":
        token = os.getenv("HIREAI_ADMIN_AUTH_TOKEN") or os.getenv("HIREAI_A2A_SERVICE_TOKEN")
    else:
        token = os.getenv("HIREAI_A2A_SERVICE_TOKEN")
    if not token:
        if token_scope == "hr":
            raise HireAIClientError(
                "Missing HIREAI_ADMIN_AUTH_TOKEN or HIREAI_A2A_SERVICE_TOKEN for an HR-authenticated HIREAI request."
            )
        raise HireAIClientError("Missing HIREAI_A2A_SERVICE_TOKEN for A2A-authenticated HIREAI request.")
    return token.strip()


def _headers(token_scope: str) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-HIREAI-ADK-Sidecar": "hireai_screening_orchestrator",
    }
    if token_scope != "public":
        headers["Authorization"] = f"Bearer {_token_for_scope(token_scope)}"
    return headers


def _detail_from_response(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text[:500] if text else response.reason_phrase
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message") or payload
        return json.dumps(detail, default=str)[:1000] if not isinstance(detail, str) else detail[:1000]
    return json.dumps(payload, default=str)[:1000]


def _request_json(
    method: str,
    path: str,
    *,
    token_scope: str = "a2a",
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | list[Any]:
    try:
        with httpx.Client(base_url=_backend_url(), timeout=_timeout_seconds()) as client:
            response = client.request(
                method,
                path,
                headers=_headers(token_scope),
                json=json_body,
                params=params,
            )
            response.raise_for_status()
            if not response.content:
                return {}
            try:
                return response.json()
            except ValueError:
                return {
                    "content": response.text,
                    "content_type": response.headers.get("content-type"),
                }
    except httpx.HTTPStatusError as exc:
        response = exc.response
        raise HireAIClientError(
            f"HIREAI returned HTTP {response.status_code} for {method} {path}: {_detail_from_response(response)}"
        ) from exc
    except httpx.RequestError as exc:
        raise HireAIClientError(f"Could not reach HIREAI at {_backend_url()}: {exc}") from exc


def _request_download(path: str, *, token_scope: str = "a2a") -> dict[str, Any]:
    try:
        with httpx.Client(base_url=_backend_url(), timeout=_timeout_seconds()) as client:
            response = client.get(path, headers=_headers(token_scope))
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            disposition = response.headers.get("content-disposition", "")
            if "application/json" in content_type:
                try:
                    data: Any = response.json()
                except ValueError:
                    data = response.text
            else:
                data = response.text
            return {
                "content_type": content_type,
                "content_disposition": disposition,
                "data": data,
            }
    except httpx.HTTPStatusError as exc:
        response = exc.response
        raise HireAIClientError(
            f"HIREAI returned HTTP {response.status_code} for GET {path}: {_detail_from_response(response)}"
        ) from exc
    except httpx.RequestError as exc:
        raise HireAIClientError(f"Could not reach HIREAI at {_backend_url()}: {exc}") from exc


def _tool_result(operation: str, call: Callable[[], Any]) -> dict[str, Any]:
    if os.getenv("ADK_INTEGRATION_ENABLED", "true").strip().lower() in {"0", "false", "no", "off"}:
        return {
            "ok": False,
            "operation": operation,
            "error": "ADK integration is disabled by ADK_INTEGRATION_ENABLED.",
        }
    try:
        return {"ok": True, "operation": operation, "data": call()}
    except HireAIClientError as exc:
        return {
            "ok": False,
            "operation": operation,
            "error": str(exc),
            "hint": "Check HIREAI_BACKEND_URL, bearer token configuration, and backend route permissions.",
        }


def run_resume_screening(
    resume_text: str,
    jd_text: str,
    label: str = "ADK resume screening evaluation",
    async_execution: bool = True,
) -> dict[str, Any]:
    """Start a HIREAI A2A resume-screening task for a resume and job description."""

    body = {
        "resume_text": resume_text,
        "jd_text": jd_text,
        "label": label,
        "execution_mode": "async" if async_execution else "sync",
    }
    return _tool_result(
        "run_resume_screening",
        lambda: _request_json(
            "POST",
            "/a2a/evaluations/resume-screening",
            token_scope="a2a",
            json_body=body,
        ),
    )


def get_platform_agent_card() -> dict[str, Any]:
    """Fetch the public HIREAI platform A2A agent card."""

    return _tool_result(
        "get_platform_agent_card",
        lambda: _request_json("GET", "/.well-known/agent-card.json", token_scope="public"),
    )


def list_a2a_agents(include_internal: bool = False) -> dict[str, Any]:
    """Discover HIREAI A2A agents visible to the configured A2A actor."""

    return _tool_result(
        "list_a2a_agents",
        lambda: _request_json(
            "GET",
            "/a2a/agents",
            token_scope="a2a",
            params={"include_internal": bool(include_internal)},
        ),
    )


def get_a2a_agent_card(agent_id: str = "resume_screening_orchestrator") -> dict[str, Any]:
    """Fetch one HIREAI A2A agent card before starting or explaining a task."""

    return _tool_result(
        "get_a2a_agent_card",
        lambda: _request_json("GET", f"/a2a/agents/{agent_id}/card", token_scope="a2a"),
    )


def get_a2a_task(task_id: str) -> dict[str, Any]:
    """Fetch the full HIREAI A2A task record for a task id."""

    return _tool_result(
        "get_a2a_task",
        lambda: _request_json("GET", f"/a2a/tasks/{task_id}", token_scope="a2a"),
    )


def get_a2a_task_status(task_id: str) -> dict[str, Any]:
    """Fetch only the HIREAI A2A task status for a task id."""

    return _tool_result(
        "get_a2a_task_status",
        lambda: _request_json("GET", f"/a2a/tasks/{task_id}/status", token_scope="a2a"),
    )


def poll_a2a_task(task_id: str, timeout_seconds: int = 60, interval_seconds: int = 2) -> dict[str, Any]:
    """Poll a HIREAI A2A task until it completes, fails, is canceled, or times out."""

    def _poll() -> dict[str, Any]:
        timeout = max(1, min(int(timeout_seconds), 300))
        interval = max(1, min(int(interval_seconds), 10))
        deadline = time.monotonic() + timeout
        last_status: dict[str, Any] | list[Any] | None = None
        while True:
            last_status = _request_json("GET", f"/a2a/tasks/{task_id}/status", token_scope="a2a")
            status_value = ""
            if isinstance(last_status, dict):
                status_value = str(last_status.get("status") or "").lower()
            if status_value in TERMINAL_TASK_STATUSES:
                task = _request_json("GET", f"/a2a/tasks/{task_id}", token_scope="a2a")
                return {
                    "terminal": True,
                    "status": status_value,
                    "status_response": last_status,
                    "task": task,
                }
            if time.monotonic() >= deadline:
                return {
                    "terminal": False,
                    "status": status_value or "unknown",
                    "status_response": last_status,
                    "timeout_seconds": timeout,
                }
            time.sleep(interval)

    return _tool_result("poll_a2a_task", _poll)


def list_a2a_artifacts(task_id: str) -> dict[str, Any]:
    """List downloadable artifacts produced by a HIREAI A2A task."""

    return _tool_result(
        "list_a2a_artifacts",
        lambda: _request_json("GET", f"/a2a/tasks/{task_id}/artifacts", token_scope="a2a"),
    )


def download_a2a_artifact(task_id: str, artifact_id: str) -> dict[str, Any]:
    """Download one HIREAI A2A artifact as JSON/text content."""

    return _tool_result(
        "download_a2a_artifact",
        lambda: _request_download(
            f"/a2a/tasks/{task_id}/artifacts/{artifact_id}/download",
            token_scope="a2a",
        ),
    )


def get_a2a_audit(limit: int = 50) -> dict[str, Any]:
    """Fetch recent HIREAI A2A audit events visible to the configured actor."""

    safe_limit = max(1, min(int(limit), 1000))
    return _tool_result(
        "get_a2a_audit",
        lambda: _request_json("GET", "/a2a/audit", token_scope="a2a", params={"limit": safe_limit}),
    )


def get_token_summary(window_minutes: int = 60) -> dict[str, Any]:
    """Fetch HIREAI token/cost summary when HR/admin auth is available."""

    safe_window = max(1, min(int(window_minutes), 1440))
    return _tool_result(
        "get_token_summary",
        lambda: _request_json(
            "GET",
            "/monitoring/tokens/summary",
            token_scope="hr",
            params={"window_minutes": safe_window},
        ),
    )


def run_eval_dataset(dataset_name: str = "golden_resume_screening") -> dict[str, Any]:
    """Report HIREAI eval capability for a named dataset.

    HIREAI currently exposes eval operation endpoints and metrics, but not a
    generic dataset runner over HTTP. This tool checks eval availability and
    returns a clear integration status instead of pretending a run occurred.
    """

    def _check() -> dict[str, Any]:
        metrics = _request_json("GET", "/evals/metrics", token_scope="hr")
        return {
            "dataset_name": dataset_name,
            "dataset_run_started": False,
            "reason": "HIREAI does not expose a generic /evals/datasets runner yet.",
            "available_metrics": metrics,
            "next_step": "Expose a backend dataset-run endpoint, then wire this tool to that route.",
        }

    return _tool_result("run_eval_dataset", _check)
