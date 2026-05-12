"""
HarnessAgent — master orchestrator for all 14 HIRE AI specialized agents.

Responsibilities:
  1. Maintains a singleton registry of all agent instances
  2. Routes `task` names to the correct agent or pipeline by name
  3. Executes single-agent calls and multi-agent pipelines with parallel fan-out
  4. Wraps every agent call with retry + exponential backoff
  5. Builds a `_agent_trace` audit list in the state for every run
  6. Provides health aggregation across all registered agents

Runtime note (MED-2 FIX):
  The /harness/* API routes use HarnessAgent's own async step-runner (run_pipeline /
  run_parallel / run_agent).  The LangGraph compiled graphs in graphs.py are separate
  objects — they are not executed by this harness.  Both execution paths coexist:
    - graphs.py  → used directly where LangGraph state-machine semantics are needed
    - harness.py → used by /harness/* REST endpoints for dynamic task routing
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from app.agents.base import AgentError, BaseAgent
from app.agents.specialized import (
    FileExtractionAgent,
    ResumeParserAgent,
    JDParserAgent,
    JDGeneratorAgent,
    EmbeddingAgent,
    ScoringAgent,
    DeduplicationAgent,
    QuizAgent,
    CodeEvaluationAgent,
    RankingAgent,
    ResumeEnhancerAgent,
    ResumeBuilderAgent,
    CoverLetterAgent,
    NotificationAgent,
)

logger = logging.getLogger(__name__)

# ─── Retry configuration ──────────────────────────────────────────────────────
_MAX_RETRIES = 2
_RETRY_BASE_DELAY = 1.0  # seconds; doubles each attempt


class HarnessAgent:
    """
    Singleton orchestrator.  Use `HarnessAgent.instance()` to get the shared instance.

    Calling convention (single agent):
        result_state = await harness.run_agent("scoring_agent", state)

    Calling convention (named pipeline):
        result_state = await harness.run_pipeline("resume_screening", state)

    Calling convention (parallel fan-out):
        result_state = await harness.run_parallel(["resume_parser_agent", "embedding_agent"], state)
    """

    _instance: "HarnessAgent | None" = None

    def __init__(self):
        # Instantiate all agents once — they are stateless and safe to reuse
        self._agents: dict[str, BaseAgent] = {
            a.name: a for a in [
                FileExtractionAgent(),
                ResumeParserAgent(),
                JDParserAgent(),
                JDGeneratorAgent(),
                EmbeddingAgent(),
                ScoringAgent(),
                DeduplicationAgent(),
                QuizAgent(),
                CodeEvaluationAgent(),
                RankingAgent(),
                ResumeEnhancerAgent(),
                ResumeBuilderAgent(),
                CoverLetterAgent(),
                NotificationAgent(),
            ]
        }

        # Named pipelines — ordered list of agent names (or lists for parallel steps)
        self._pipelines: dict[str, list] = {
            # HR: Full resume screening pipeline
            "resume_screening": [
                "file_extraction_agent",            # extract text
                ["resume_parser_agent", "embedding_agent"],  # parallel: parse + embed
                "deduplication_agent",              # check for duplicates
                "scoring_agent",                    # score against JD
            ],
            # HR: JD generation with cache
            "jd_generation": [
                "jd_generator_agent",               # generate JD (includes embed + cache)
            ],
            # HR: JD parsing from uploaded document
            "jd_parsing": [
                "file_extraction_agent",
                "jd_parser_agent",
                "embedding_agent",
            ],
            # HR: Quiz generation for a JD
            "quiz_generation": [
                "quiz_agent",                       # operation=generate
            ],
            # Candidate: AI resume tools (enhance / build / cover letter)
            "candidate_tools": [
                # Routed dynamically by operation in harness
            ],
            # HR: Candidate ranking pipeline
            "ranking": [
                "ranking_agent",
            ],
            # HR: Notify candidates after quiz
            "notify_candidate": [
                "notification_agent",
            ],
            # Candidate: Full career tools pipeline
            "career_tools": [
                ["resume_enhancer_agent", "cover_letter_agent"],  # parallel
            ],
        }

    @classmethod
    def instance(cls) -> "HarnessAgent":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def agent_names(self) -> list[str]:
        return sorted(self._agents.keys())

    def get_agent(self, name: str) -> BaseAgent:
        if name not in self._agents:
            raise KeyError(f"HarnessAgent: unknown agent '{name}'. Available: {self.agent_names}")
        return self._agents[name]

    async def run_agent(self, agent_name: str, state: dict[str, Any]) -> dict[str, Any]:
        """Run a single named agent with retry logic."""
        state = self._ensure_trace_id(state)
        agent = self.get_agent(agent_name)
        return await self._run_with_retry(agent, state)

    async def run_parallel(self, agent_names: list[str], state: dict[str, Any]) -> dict[str, Any]:
        """
        Run multiple agents concurrently.  Results are merged into state.
        If any agent fails and is non-retryable, that error is logged but
        other agents' results are still applied (partial success).
        """
        state = self._ensure_trace_id(state)
        agents = [self.get_agent(n) for n in agent_names]
        # Give each parallel branch its own shallow state snapshot so in-place
        # writes inside one agent cannot bleed into sibling branches.
        tasks = [self._run_with_retry(a, dict(state)) for a in agents]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        merged: dict[str, Any] = {}
        for name, result in zip(agent_names, results):
            if isinstance(result, Exception):
                logger.error("HarnessAgent: parallel agent '%s' failed: %s", name, result)
                merged[f"_error_{name}"] = str(result)
            else:
                # Merge audit traces
                # Collect only new traces emitted by parallel branches.
                # The caller (run_pipeline) merges branch traces into the running
                # state; seeding with state trace here causes duplication.
                existing_trace = merged.get("_agent_trace", [])
                incoming_trace = result.pop("_agent_trace", [])
                merged.update(result)
                merged["_agent_trace"] = existing_trace + incoming_trace

        return merged

    async def run_pipeline(self, pipeline_name: str, state: dict[str, Any]) -> dict[str, Any]:
        """
        Execute a named pipeline: a sequence of agent names (or lists for parallel steps).
        State is threaded through each step, accumulating updates.
        """
        steps = self._pipelines.get(pipeline_name)
        if steps is None:
            raise KeyError(f"HarnessAgent: unknown pipeline '{pipeline_name}'. "
                           f"Available: {sorted(self._pipelines.keys())}")
        if len(steps) == 0:
            raise KeyError(
                f"HarnessAgent: pipeline '{pipeline_name}' has no executable steps configured."
            )

        state = self._ensure_trace_id(state)
        logger.info("HarnessAgent: starting pipeline '%s' trace_id=%s",
                    pipeline_name, state["trace_id"])

        for step in steps:
            if isinstance(step, list):
                # Parallel fan-out
                updates = await self.run_parallel(step, state)
            else:
                # Sequential single agent
                updates = await self.run_agent(step, state)
            # Merge updates into running state
            trace = state.get("_agent_trace", []) + updates.pop("_agent_trace", [])
            state = {**state, **updates, "_agent_trace": trace}

        logger.info("HarnessAgent: pipeline '%s' complete — %d agents fired",
                    pipeline_name, len(state.get("_agent_trace", [])))
        return state

    async def run(self, task: str, state: dict[str, Any]) -> dict[str, Any]:
        """
        Universal entry point.  Resolves `task` as either:
          - A pipeline name  → run_pipeline(task, state)
          - An agent name    → run_agent(task, state)
        """
        if task in self._pipelines:
            return await self.run_pipeline(task, state)
        if task in self._agents:
            return await self.run_agent(task, state)
        raise KeyError(
            f"HarnessAgent: '{task}' is neither a pipeline nor an agent. "
            f"Pipelines: {sorted(self._pipelines.keys())}  "
            f"Agents: {self.agent_names}"
        )

    async def health_all(self) -> dict[str, Any]:
        """Run all per-agent health probes concurrently and return a summary."""
        tasks = {name: agent.health() for name, agent in self._agents.items()}
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        report: dict[str, Any] = {}
        any_degraded = False
        for name, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                report[name] = {"status": "error", "detail": str(result)}
                any_degraded = True
            else:
                report[name] = result
                if result.get("status") != "ok":
                    any_degraded = True
        return {
            "harness_status": "degraded" if any_degraded else "ok",
            "agent_count": len(self._agents),
            "pipeline_count": len(self._pipelines),
            "agents": report,
            "pipelines": sorted(self._pipelines.keys()),
        }

    # ── Internals ──────────────────────────────────────────────────────────────

    @staticmethod
    def _ensure_trace_id(state: dict[str, Any]) -> dict[str, Any]:
        if "trace_id" not in state or not state["trace_id"]:
            state = {**state, "trace_id": state.get("session_id") or str(uuid.uuid4())}
        if "_agent_trace" not in state:
            state = {**state, "_agent_trace": []}
        return state

    async def _run_with_retry(self, agent: BaseAgent, state: dict[str, Any]) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                return await agent(state)
            except AgentError as exc:
                last_exc = exc
                if not exc.retryable or attempt == _MAX_RETRIES:
                    raise
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "HarnessAgent: agent '%s' attempt %d/%d failed, retrying in %.1fs: %s",
                    agent.name, attempt + 1, _MAX_RETRIES + 1, delay, exc,
                )
                await asyncio.sleep(delay)
        raise last_exc  # type: ignore[misc]
