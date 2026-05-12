"""
Base agent abstraction for HIRE AI multi-agent system.

Every specialized agent inherits from BaseAgent, which provides:
  - A standard `run(state) -> state` contract
  - A per-agent `health()` liveness probe
  - Standardised error wrapping so the HarnessAgent can catch and classify failures
  - Structured logging with agent name and trace_id propagation
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

S = TypeVar("S", bound=dict)


class AgentError(Exception):
    """Raised when an agent fails and the harness should attempt retry/fallback."""

    def __init__(self, agent_name: str, message: str, retryable: bool = True):
        super().__init__(message)
        self.agent_name = agent_name
        self.retryable = retryable


class BaseAgent(ABC):
    """
    Abstract base class for all HIRE AI agents.

    Subclasses must implement:
      - `name` class attribute (unique agent identifier)
      - `run(state)` — core logic; returns a dict to merge into the shared state
    """

    name: str = "base_agent"
    model_key: str | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    @abstractmethod
    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute the agent's core logic and return state updates."""
        ...

    async def health(self) -> dict[str, Any]:
        """
        Liveness probe.  Override in agents that depend on external services.
        Default: always healthy (logic is pure in-process).
        """
        return {"agent": self.name, "status": "ok"}

    def resolve_model(
        self,
        state: dict[str, Any],
        *,
        key: str | None = None,
        fallback: str | None = None,
    ) -> str:
        """
        Resolve deployment/model with deterministic precedence:
          1) state["model_override"] (single override)
          2) state["model_overrides"][key-or-agent] (per-agent override map)
          3) settings.agent_model_map[key-or-agent]
          4) explicit fallback argument
          5) settings.AZURE_CHAT_DEPLOYMENT
        """
        direct_override = state.get("model_override")
        if isinstance(direct_override, str) and direct_override.strip():
            return direct_override.strip()

        lookup_keys: list[str] = []
        if key:
            lookup_keys.append(key)
        if self.model_key:
            lookup_keys.append(self.model_key)
        lookup_keys.append(self.name)

        keyed_overrides = state.get("model_overrides")
        if isinstance(keyed_overrides, dict):
            for lookup_key in lookup_keys:
                override = keyed_overrides.get(lookup_key)
                if isinstance(override, str) and override.strip():
                    return override.strip()

        from app.config import settings

        for lookup_key in lookup_keys:
            mapped = settings.agent_model_map.get(lookup_key)
            if mapped:
                return mapped

        if fallback:
            return fallback
        return settings.AZURE_CHAT_DEPLOYMENT

    # ── Harness-called wrapper ────────────────────────────────────────────────

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        Called by the HarnessAgent.  Wraps `run()` with:
          - Timing
          - Structured logging (agent name + optional trace_id)
          - Exception → AgentError conversion
        """
        trace_id = state.get("trace_id", "")
        start = time.perf_counter()
        log_ctx = {"agent": self.name, "trace_id": trace_id}

        logger.debug("→ %s starting", self.name, extra=log_ctx)
        try:
            updates = await self.run(state)
            elapsed = time.perf_counter() - start
            logger.info(
                "✓ %s completed in %.2fs", self.name, elapsed, extra=log_ctx
            )
            # Include only THIS step's trace entry.
            # The harness owns cross-step aggregation; including prior state here
            # causes duplicate/exponential trace growth in multi-step pipelines.
            updates["_agent_trace"] = [
                {"agent": self.name, "elapsed_s": round(elapsed, 3)}
            ]
            return updates
        except AgentError:
            raise
        except Exception as exc:
            elapsed = time.perf_counter() - start
            logger.error(
                "✗ %s failed after %.2fs: %s",
                self.name, elapsed, exc, extra=log_ctx, exc_info=True
            )
            raise AgentError(
                agent_name=self.name,
                message=str(exc),
                retryable=self._is_retryable(exc),
            ) from exc

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        """Transient network/timeout errors are retryable; value errors are not."""
        non_retryable = (ValueError, TypeError, KeyError, AttributeError)
        transient = (TimeoutError, ConnectionError, OSError)
        if isinstance(exc, non_retryable):
            return False
        if isinstance(exc, transient):
            return True
        try:
            import httpx
            if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
                return True
        except Exception:
            pass
        return True  # default: assume retryable for unknown exceptions
