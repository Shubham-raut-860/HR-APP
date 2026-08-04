from __future__ import annotations

from typing import Any

from .tools.hireai_client import (
    get_a2a_audit,
    get_token_summary,
    list_a2a_artifacts,
    poll_a2a_task,
    run_resume_screening,
)


def build_resume_screening_graph_workflow() -> Any:
    """Build the ADK 2.x graph workflow when graph APIs are installed.

    The normal `root_agent` remains the compatible ADK agent. This builder lets
    the project opt into graph execution once the sidecar environment has ADK
    2.x installed and configured.
    """

    try:
        from google.adk import Event, Workflow
        from google.adk.workflow import JoinNode
    except ImportError as exc:  # pragma: no cover - depends on optional ADK install
        raise RuntimeError(
            "ADK graph workflow APIs are not available. Install an ADK 2.x package "
            "that exposes google.adk.Workflow, google.adk.Event, and google.adk.workflow.JoinNode."
        ) from exc

    def input_guard(node_input: dict[str, Any]) -> Any:
        resume_text = str((node_input or {}).get("resume_text") or "").strip()
        jd_text = str((node_input or {}).get("jd_text") or "").strip()
        if len(resume_text) < 20 or len(jd_text) < 20:
            return Event(route="INVALID_INPUT", output={"error": "resume_text and jd_text must both be at least 20 characters."})
        return Event(route="VALID_INPUT", output=node_input)

    def start_screening(node_input: dict[str, Any]) -> Any:
        result = run_resume_screening(
            resume_text=str(node_input.get("resume_text") or ""),
            jd_text=str(node_input.get("jd_text") or ""),
            label=str(node_input.get("label") or "ADK graph resume screening"),
            async_execution=True,
        )
        return Event(output=result)

    def poll_screening(node_input: dict[str, Any]) -> Any:
        data = (node_input or {}).get("data") if isinstance(node_input, dict) else None
        task_id = data.get("id") if isinstance(data, dict) else None
        if not task_id:
            return Event(output={"ok": False, "error": "No task id returned from run_resume_screening."})
        return Event(output=poll_a2a_task(str(task_id), timeout_seconds=90, interval_seconds=3))

    def fetch_artifacts(node_input: dict[str, Any]) -> Any:
        task = (node_input or {}).get("task") or {}
        task_id = task.get("id") if isinstance(task, dict) else None
        return Event(output=list_a2a_artifacts(str(task_id))) if task_id else Event(output={"ok": False, "error": "No task id for artifacts."})

    def fetch_audit(_: dict[str, Any]) -> Any:
        return Event(output=get_a2a_audit(limit=50))

    def fetch_tokens(_: dict[str, Any]) -> Any:
        return Event(output=get_token_summary(window_minutes=60))

    def invalid_input_summary(node_input: dict[str, Any]) -> Any:
        return Event(output={"ok": False, "summary": "Input validation failed.", "detail": node_input})

    def human_review_summary(node_input: dict[str, Any]) -> Any:
        return Event(
            output={
                "ok": True,
                "summary": "Graph workflow finished. Use HIREAI task/artifact output as decision support only.",
                "human_review_required": True,
                "inputs": node_input,
            }
        )

    join_results = JoinNode(name="join_screening_artifacts_audit_tokens")
    return Workflow(
        name="hireai_resume_screening_graph",
        edges=[
            ("START", input_guard),
            (
                input_guard,
                {
                    "VALID_INPUT": start_screening,
                    "INVALID_INPUT": invalid_input_summary,
                },
            ),
            (start_screening, poll_screening),
            (poll_screening, fetch_artifacts, join_results),
            (poll_screening, fetch_audit, join_results),
            (poll_screening, fetch_tokens, join_results),
            (join_results, human_review_summary),
        ],
    )
