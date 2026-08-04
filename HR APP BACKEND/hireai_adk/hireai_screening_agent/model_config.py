from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any


DEFAULT_MODEL_PROFILE = "screening_fast"
DEFAULT_ORCHESTRATION_MODEL = "gemini-2.0-flash"


@dataclass(frozen=True)
class ModelProfile:
    id: str
    model: str
    purpose: str
    latency: str
    cost: str
    risk_note: str


MODEL_PROFILES: dict[str, ModelProfile] = {
    "screening_fast": ModelProfile(
        id="screening_fast",
        model=DEFAULT_ORCHESTRATION_MODEL,
        purpose="Default HIREAI ADK orchestration model for A2A resume screening.",
        latency="low",
        cost="balanced",
        risk_note="Best default for admin orchestration because scoring still happens inside HIREAI.",
    ),
    "screening_deep_review": ModelProfile(
        id="screening_deep_review",
        model=os.getenv("ADK_DEEP_REVIEW_MODEL", DEFAULT_ORCHESTRATION_MODEL),
        purpose="Deeper explanation and audit summarization model. Keep HIREAI backend as scoring source of truth.",
        latency="medium",
        cost="higher",
        risk_note="Use for summaries and review narratives, not as an independent scorer.",
    ),
    "workflow_router": ModelProfile(
        id="workflow_router",
        model=os.getenv("ADK_ROUTER_MODEL", DEFAULT_ORCHESTRATION_MODEL),
        purpose="Routing model for choosing graph branches when deterministic routing is not enough.",
        latency="low",
        cost="balanced",
        risk_note="Prefer deterministic graph routes for production-critical HR decisions.",
    ),
}


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def get_model_profile(profile_id: str | None = None) -> ModelProfile:
    selected_id = _clean(profile_id) or _clean(os.getenv("ADK_MODEL_PROFILE")) or DEFAULT_MODEL_PROFILE
    profile = MODEL_PROFILES.get(selected_id, MODEL_PROFILES[DEFAULT_MODEL_PROFILE])
    explicit_model = _clean(os.getenv("ADK_MODEL"))
    if explicit_model:
        return ModelProfile(
            id=profile.id,
            model=explicit_model,
            purpose=profile.purpose,
            latency=profile.latency,
            cost=profile.cost,
            risk_note=f"{profile.risk_note} ADK_MODEL override is active.",
        )
    return profile


def get_agent_model() -> str:
    return get_model_profile().model


def get_adk_model_status() -> dict[str, Any]:
    """Return non-secret ADK model configuration for technical-admin inspection."""

    selected = get_model_profile()
    return {
        "ok": True,
        "selected_profile": asdict(selected),
        "available_profiles": [asdict(profile) for profile in MODEL_PROFILES.values()],
        "auth": {
            "google_api_key_configured": bool(_clean(os.getenv("GOOGLE_API_KEY"))),
            "vertex_project_configured": bool(_clean(os.getenv("GOOGLE_CLOUD_PROJECT"))),
            "vertex_location": _clean(os.getenv("GOOGLE_CLOUD_LOCATION")),
        },
        "guardrails": [
            "HIREAI backend remains the source of truth for resume parsing and scoring.",
            "ADK agents may orchestrate, summarize, route, and retrieve artifacts.",
            "Human review is required before hiring decisions.",
        ],
    }
