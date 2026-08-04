from __future__ import annotations

import pytest

from hireai_screening_agent.tools import hireai_client
from hireai_screening_agent.model_config import get_adk_model_status, get_model_profile
from hireai_screening_agent.workflow_specs import (
    RESUME_SCREENING_GRAPH,
    get_adk_workflow,
    validate_workflow_spec,
)


def test_run_resume_screening_uses_existing_a2a_evaluation_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_request_json(method: str, path: str, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured.update(kwargs)
        return {"id": "task-123", "status": "queued"}

    monkeypatch.setattr(hireai_client, "_request_json", fake_request_json)

    result = hireai_client.run_resume_screening(
        resume_text="Resume text long enough for backend validation.",
        jd_text="Job description text long enough for backend validation.",
        label="ADK smoke",
        async_execution=True,
    )

    assert result["ok"] is True
    assert captured["method"] == "POST"
    assert captured["path"] == "/a2a/evaluations/resume-screening"
    assert captured["token_scope"] == "a2a"
    assert captured["json_body"] == {
        "resume_text": "Resume text long enough for backend validation.",
        "jd_text": "Job description text long enough for backend validation.",
        "label": "ADK smoke",
        "execution_mode": "async",
    }


def test_get_token_summary_uses_hr_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_request_json(method: str, path: str, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured.update(kwargs)
        return {"total_tokens": 10}

    monkeypatch.setattr(hireai_client, "_request_json", fake_request_json)

    result = hireai_client.get_token_summary(window_minutes=120)

    assert result["ok"] is True
    assert captured["path"] == "/monitoring/tokens/summary"
    assert captured["token_scope"] == "hr"
    assert captured["params"] == {"window_minutes": 120}


def test_get_platform_agent_card_uses_public_well_known_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_request_json(method: str, path: str, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured.update(kwargs)
        return {"name": "HIREAI"}

    monkeypatch.setattr(hireai_client, "_request_json", fake_request_json)

    result = hireai_client.get_platform_agent_card()

    assert result["ok"] is True
    assert captured["method"] == "GET"
    assert captured["path"] == "/.well-known/agent-card.json"
    assert captured["token_scope"] == "public"


def test_list_a2a_agents_uses_directory_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_request_json(method: str, path: str, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured.update(kwargs)
        return {"agents": []}

    monkeypatch.setattr(hireai_client, "_request_json", fake_request_json)

    result = hireai_client.list_a2a_agents(include_internal=True)

    assert result["ok"] is True
    assert captured["method"] == "GET"
    assert captured["path"] == "/a2a/agents"
    assert captured["token_scope"] == "a2a"
    assert captured["params"] == {"include_internal": True}


def test_get_a2a_agent_card_uses_card_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_request_json(method: str, path: str, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured.update(kwargs)
        return {"id": "resume_screening_orchestrator"}

    monkeypatch.setattr(hireai_client, "_request_json", fake_request_json)

    result = hireai_client.get_a2a_agent_card()

    assert result["ok"] is True
    assert captured["method"] == "GET"
    assert captured["path"] == "/a2a/agents/resume_screening_orchestrator/card"
    assert captured["token_scope"] == "a2a"


def test_public_headers_do_not_require_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HIREAI_A2A_SERVICE_TOKEN", raising=False)

    headers = hireai_client._headers("public")

    assert "Authorization" not in headers
    assert headers["X-HIREAI-ADK-Sidecar"] == "hireai_screening_orchestrator"


def test_tool_result_converts_client_errors_to_agent_safe_payload() -> None:
    def failing_call():
        raise hireai_client.HireAIClientError("backend unavailable")

    result = hireai_client._tool_result("sample_operation", failing_call)

    assert result["ok"] is False
    assert result["operation"] == "sample_operation"
    assert "backend unavailable" in result["error"]


def test_a2a_headers_require_service_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HIREAI_A2A_SERVICE_TOKEN", raising=False)

    with pytest.raises(hireai_client.HireAIClientError):
        hireai_client._headers("a2a")


def test_default_model_profile_uses_requested_gemini_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADK_MODEL", raising=False)
    monkeypatch.delenv("ADK_MODEL_PROFILE", raising=False)

    profile = get_model_profile()

    assert profile.id == "screening_fast"
    assert profile.model == "gemini-2.0-flash"


def test_model_status_does_not_expose_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "secret-key-value")

    status = get_adk_model_status()

    assert status["ok"] is True
    assert status["auth"]["google_api_key_configured"] is True
    assert "secret-key-value" not in str(status)


def test_resume_screening_graph_spec_is_valid_and_multi_node() -> None:
    errors = validate_workflow_spec(RESUME_SCREENING_GRAPH)

    assert errors == []
    assert len(RESUME_SCREENING_GRAPH.nodes) >= 5
    assert any(edge.source == "task_poll" and edge.target == "artifact_fetch" for edge in RESUME_SCREENING_GRAPH.edges)
    assert any(edge.source == "task_poll" and edge.target == "audit_fetch" for edge in RESUME_SCREENING_GRAPH.edges)
    assert any(edge.source == "task_poll" and edge.target == "token_fetch" for edge in RESUME_SCREENING_GRAPH.edges)


def test_get_adk_workflow_returns_full_graph_spec() -> None:
    result = get_adk_workflow("resume_screening_graph")

    assert result["ok"] is True
    assert result["workflow"]["id"] == "resume_screening_graph"
    assert result["workflow"]["validation_errors"] == []
