from __future__ import annotations

import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from google.adk.agents import Agent

from .model_config import get_adk_model_status, get_agent_model
from .tools.hireai_client import (
    download_a2a_artifact,
    get_a2a_audit,
    get_a2a_agent_card,
    get_a2a_task,
    get_a2a_task_status,
    get_platform_agent_card,
    get_token_summary,
    list_a2a_agents,
    list_a2a_artifacts,
    poll_a2a_task,
    run_eval_dataset,
    run_resume_screening,
)
from .workflow_specs import get_adk_workflow, list_adk_workflows


ADK_MODEL = get_agent_model()


root_agent = Agent(
    name="hireai_screening_orchestrator",
    model=ADK_MODEL,
    description=(
        "Technical-admin orchestration agent for HIREAI resume screening. "
        "It delegates scoring, artifact creation, and audit trails to the HIREAI backend."
    ),
    instruction="""
You are the HIREAI technical-admin resume screening orchestrator.

Core rules:
- Use HIREAI tools for every score, task, artifact, audit, and token/cost fact.
- Do not invent candidate facts, scores, trace ids, artifact ids, or audit events.
- Use A2A discovery tools when asked about available agents, agent cards, or backend capabilities.
- Prefer asynchronous A2A screening, then poll task status before summarizing.
- Retrieve artifacts after a task completes and cite artifact ids in the response.
- Use get_adk_model_status when asked which ADK model/profile is active.
- Use list_adk_workflows or get_adk_workflow when asked about multi-agent, multi-node, or graph workflow design.
- If the backend returns an error, explain the exact failed tool operation and stop.
- If token or eval endpoints are not authorized, say that the A2A run still worked but HR/admin auth is needed for that extra data.
- Always state that HIREAI screening is decision support and human review is required.

Expected output:
- Task id, task status, and agent id.
- Score or fit summary from HIREAI output only.
- Matched skills, missing skills, risks, and confidence if present in artifacts or task result.
- Artifact ids and audit summary when available.
- Token/cost summary when available.
- A clear human-review recommendation.
""",
    tools=[
        get_platform_agent_card,
        list_a2a_agents,
        get_a2a_agent_card,
        run_resume_screening,
        get_a2a_task,
        get_a2a_task_status,
        poll_a2a_task,
        list_a2a_artifacts,
        download_a2a_artifact,
        get_a2a_audit,
        get_token_summary,
        run_eval_dataset,
        get_adk_model_status,
        list_adk_workflows,
        get_adk_workflow,
    ],
)
