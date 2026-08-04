from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class WorkflowNode:
    id: str
    kind: str
    owner: str
    purpose: str
    tool: str | None = None


@dataclass(frozen=True)
class WorkflowEdge:
    source: str
    target: str
    route: str = "default"


@dataclass(frozen=True)
class WorkflowSpec:
    id: str
    name: str
    purpose: str
    nodes: tuple[WorkflowNode, ...]
    edges: tuple[WorkflowEdge, ...]
    notes: tuple[str, ...] = ()


RESUME_SCREENING_GRAPH = WorkflowSpec(
    id="resume_screening_graph",
    name="Resume Screening A2A Graph",
    purpose=(
        "Multi-node workflow that validates inputs, starts HIREAI A2A resume screening, "
        "polls the async task, fans out to artifacts/audit/token checks, then prepares a human-review summary."
    ),
    nodes=(
        WorkflowNode(
            id="input_guard",
            kind="function_node",
            owner="adk_sidecar",
            purpose="Validate that resume_text and jd_text are present before a backend task is started.",
        ),
        WorkflowNode(
            id="a2a_screening_task",
            kind="tool_node",
            owner="hireai_backend",
            purpose="Create the async HIREAI resume_screening_orchestrator task.",
            tool="run_resume_screening",
        ),
        WorkflowNode(
            id="task_poll",
            kind="tool_node",
            owner="hireai_backend",
            purpose="Poll the A2A task until it reaches a terminal status or times out.",
            tool="poll_a2a_task",
        ),
        WorkflowNode(
            id="artifact_fetch",
            kind="tool_node",
            owner="hireai_backend",
            purpose="Fetch task artifacts and expose artifact ids for download.",
            tool="list_a2a_artifacts",
        ),
        WorkflowNode(
            id="audit_fetch",
            kind="tool_node",
            owner="hireai_backend",
            purpose="Fetch recent A2A audit events for technical traceability.",
            tool="get_a2a_audit",
        ),
        WorkflowNode(
            id="token_fetch",
            kind="tool_node",
            owner="hireai_backend",
            purpose="Fetch token/cost summary when HR/admin auth is configured.",
            tool="get_token_summary",
        ),
        WorkflowNode(
            id="human_review_summary",
            kind="agent_node",
            owner="adk_sidecar",
            purpose="Summarize only backend-returned facts and explicitly require human review.",
        ),
    ),
    edges=(
        WorkflowEdge("START", "input_guard"),
        WorkflowEdge("input_guard", "a2a_screening_task"),
        WorkflowEdge("a2a_screening_task", "task_poll"),
        WorkflowEdge("task_poll", "artifact_fetch", route="completed_or_failed"),
        WorkflowEdge("task_poll", "audit_fetch", route="completed_or_failed"),
        WorkflowEdge("task_poll", "token_fetch", route="completed_or_failed"),
        WorkflowEdge("artifact_fetch", "human_review_summary"),
        WorkflowEdge("audit_fetch", "human_review_summary"),
        WorkflowEdge("token_fetch", "human_review_summary"),
    ),
    notes=(
        "The graph intentionally keeps scoring inside the HIREAI backend.",
        "artifact_fetch, audit_fetch, and token_fetch are fan-out nodes after task polling.",
        "token_fetch is best-effort because token monitor endpoints require HR/admin auth.",
    ),
)


WORKFLOW_SPECS: dict[str, WorkflowSpec] = {
    RESUME_SCREENING_GRAPH.id: RESUME_SCREENING_GRAPH,
}


def validate_workflow_spec(spec: WorkflowSpec) -> list[str]:
    errors: list[str] = []
    node_ids = {node.id for node in spec.nodes}
    if not spec.nodes:
        errors.append("workflow must define at least one node")
    if not spec.edges:
        errors.append("workflow must define at least one edge")
    for edge in spec.edges:
        if edge.source != "START" and edge.source not in node_ids:
            errors.append(f"edge source {edge.source!r} is not START or a known node")
        if edge.target not in node_ids:
            errors.append(f"edge target {edge.target!r} is not a known node")
    return errors


def list_adk_workflows() -> dict[str, Any]:
    """Return graph workflow specs available in the ADK sidecar."""

    return {
        "ok": True,
        "workflows": [
            {
                "id": spec.id,
                "name": spec.name,
                "purpose": spec.purpose,
                "node_count": len(spec.nodes),
                "edge_count": len(spec.edges),
                "validation_errors": validate_workflow_spec(spec),
            }
            for spec in WORKFLOW_SPECS.values()
        ],
    }


def get_adk_workflow(workflow_id: str = "resume_screening_graph") -> dict[str, Any]:
    """Return a full graph workflow specification for ADK/admin inspection."""

    spec = WORKFLOW_SPECS.get(workflow_id)
    if spec is None:
        return {
            "ok": False,
            "error": f"Unknown workflow_id: {workflow_id}",
            "available_workflow_ids": sorted(WORKFLOW_SPECS),
        }
    return {
        "ok": True,
        "workflow": {
            **asdict(spec),
            "validation_errors": validate_workflow_spec(spec),
        },
    }
