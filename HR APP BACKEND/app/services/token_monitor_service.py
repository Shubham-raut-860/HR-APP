"""
Token/cost monitoring for LLM calls.

Design goals:
- Zero external dependencies (works without Redis/Prometheus).
- In-memory rolling buffer with fast aggregation.
- Per-task token budgets + overrun detection.
- Cost estimation using model pricing table (USD / 1M tokens).
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import threading
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


MODEL_COSTS: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"input": 0.25, "output": 1.25},
    "claude-opus-4-7": {"input": 15.0, "output": 75.0},
    "gpt-4o": {"input": 2.50, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-5": {"input": 2.50, "output": 10.0},
    "gpt-5-mini": {"input": 0.40, "output": 1.60},
    "o3": {"input": 10.0, "output": 40.0},
    "o4-mini": {"input": 1.10, "output": 4.40},
    "local": {"input": 0.0, "output": 0.0},
}


def _model_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    costs = MODEL_COSTS.get(model)
    if costs is None:
        for key in MODEL_COSTS:
            if model.startswith(key):
                costs = MODEL_COSTS[key]
                break
    if costs is None:
        costs = {"input": 0.0, "output": 0.0}
    per_m = 1_000_000.0
    return (prompt_tokens * costs["input"] + completion_tokens * costs["output"]) / per_m


@dataclass
class TokenEvent:
    ts: str
    task_name: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    cost_usd: float
    budget_tokens: int
    over_budget: bool
    over_budget_by_pct: float
    cost_alert: bool


class TokenMonitor:
    def __init__(self) -> None:
        self._enabled = bool(settings.TOKEN_MONITOR_ENABLED)
        self._max_events = max(100, int(settings.TOKEN_MONITOR_MAX_EVENTS))
        self._default_budget = max(100, int(settings.TOKEN_MONITOR_DEFAULT_TOKEN_BUDGET))
        self._warn_multiplier = max(1.0, float(settings.TOKEN_MONITOR_WARN_MULTIPLIER))
        self._max_cost_per_call = max(0.0, float(settings.TOKEN_MONITOR_MAX_COST_USD_PER_CALL))
        self._events: deque[TokenEvent] = deque(maxlen=self._max_events)
        self._lock = threading.Lock()
        self._task_budgets = self._parse_task_budgets()

    def _parse_task_budgets(self) -> dict[str, int]:
        raw = settings.TOKEN_MONITOR_TASK_BUDGETS_JSON
        try:
            parsed = json.loads(raw) if raw else {}
            out: dict[str, int] = {}
            if isinstance(parsed, dict):
                for k, v in parsed.items():
                    try:
                        out[str(k)] = max(100, int(v))
                    except Exception:
                        continue
            return out
        except Exception:
            logger.warning("TOKEN_MONITOR_TASK_BUDGETS_JSON is invalid JSON; using defaults.")
            return {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _budget_for_task(self, task_name: str) -> int:
        return int(self._task_budgets.get(task_name, self._default_budget))

    def record(
        self,
        *,
        task_name: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
    ) -> TokenEvent | None:
        if not self._enabled:
            return None

        p = max(0, int(prompt_tokens))
        c = max(0, int(completion_tokens))
        t = max(0, p + c)
        budget = self._budget_for_task(task_name)
        threshold = int(budget * self._warn_multiplier)
        over_budget = t > threshold
        over_pct = ((t - budget) / budget * 100.0) if budget > 0 and t > budget else 0.0
        cost = _model_cost_usd(model, p, c)
        cost_alert = cost > self._max_cost_per_call if self._max_cost_per_call > 0 else False

        event = TokenEvent(
            ts=datetime.now(timezone.utc).isoformat(),
            task_name=task_name,
            model=model,
            prompt_tokens=p,
            completion_tokens=c,
            total_tokens=t,
            latency_ms=round(float(latency_ms), 2),
            cost_usd=round(cost, 6),
            budget_tokens=budget,
            over_budget=over_budget,
            over_budget_by_pct=round(over_pct, 2),
            cost_alert=cost_alert,
        )
        with self._lock:
            self._events.append(event)

        if over_budget or cost_alert:
            logger.warning(
                "[TokenMonitor] task=%s model=%s tokens=%d budget=%d over=%s cost=$%.6f cost_alert=%s",
                task_name, model, t, budget, over_budget, cost, cost_alert,
            )
        else:
            logger.debug(
                "[TokenMonitor] task=%s model=%s tokens=%d cost=$%.6f latency_ms=%.2f",
                task_name, model, t, cost, latency_ms,
            )
        return event

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        n = max(1, min(5000, int(limit)))
        with self._lock:
            items = list(self._events)[-n:]
        return [asdict(e) for e in reversed(items)]

    def checkpoint(self) -> int:
        """Return an opaque checkpoint (current event count) for delta queries."""
        with self._lock:
            return len(self._events)

    def delta_since(self, checkpoint: int) -> dict[str, Any]:
        """
        Return aggregate stats for events recorded after `checkpoint`.

        Note:
        - Buffer is bounded; if old events are evicted, this is best-effort.
        """
        with self._lock:
            events = list(self._events)
        cp = max(0, int(checkpoint))
        if cp >= len(events):
            return {
                "calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "over_budget_calls": 0,
                "cost_alert_calls": 0,
            }
        subset = events[cp:]
        calls = len(subset)
        prompt_tokens = sum(e.prompt_tokens for e in subset)
        completion_tokens = sum(e.completion_tokens for e in subset)
        total_tokens = sum(e.total_tokens for e in subset)
        total_cost = sum(e.cost_usd for e in subset)
        over_budget_calls = sum(1 for e in subset if e.over_budget)
        cost_alert_calls = sum(1 for e in subset if e.cost_alert)
        return {
            "calls": calls,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 6),
            "over_budget_calls": over_budget_calls,
            "cost_alert_calls": cost_alert_calls,
        }

    def summary(self, window_minutes: int = 60) -> dict[str, Any]:
        wm = max(1, min(24 * 60, int(window_minutes)))
        filtered = self._filtered_events(wm)

        total_calls = len(filtered)
        total_prompt = sum(e.prompt_tokens for e in filtered)
        total_completion = sum(e.completion_tokens for e in filtered)
        total_tokens = sum(e.total_tokens for e in filtered)
        total_cost = sum(e.cost_usd for e in filtered)
        total_latency = sum(e.latency_ms for e in filtered)
        over_budget_calls = sum(1 for e in filtered if e.over_budget)
        cost_alert_calls = sum(1 for e in filtered if e.cost_alert)

        by_task_calls = Counter(e.task_name for e in filtered)
        by_model_calls = Counter(e.model for e in filtered)
        by_task_tokens: Counter[str] = Counter()
        for e in filtered:
            by_task_tokens[e.task_name] += e.total_tokens

        return {
            "window_minutes": wm,
            "enabled": self._enabled,
            "calls": total_calls,
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 6),
            "avg_latency_ms": round((total_latency / total_calls), 2) if total_calls else 0.0,
            "over_budget_calls": over_budget_calls,
            "cost_alert_calls": cost_alert_calls,
            "top_tasks_by_calls": by_task_calls.most_common(10),
            "top_tasks_by_tokens": by_task_tokens.most_common(10),
            "top_models_by_calls": by_model_calls.most_common(10),
        }

    def _filtered_events(self, window_minutes: int) -> list[TokenEvent]:
        wm = max(1, min(24 * 60, int(window_minutes)))
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=wm)
        with self._lock:
            events = list(self._events)

        filtered: list[TokenEvent] = []
        for e in events:
            try:
                ts = datetime.fromisoformat(e.ts)
            except Exception:
                continue
            if ts >= cutoff:
                filtered.append(e)
        return filtered

    def hotspots(self, top_n: int = 10, window_minutes: int = 60) -> list[dict[str, Any]]:
        wm = max(1, min(24 * 60, int(window_minutes)))
        events = self._filtered_events(wm)
        grouped: dict[str, list[TokenEvent]] = {}
        for e in events:
            grouped.setdefault(e.task_name, []).append(e)

        rows = []
        for task, arr in grouped.items():
            calls = len(arr)
            tokens = sum(x.total_tokens for x in arr)
            cost = sum(x.cost_usd for x in arr)
            over = sum(1 for x in arr if x.over_budget)
            rows.append({
                "task_name": task,
                "calls": calls,
                "total_tokens": tokens,
                "avg_tokens_per_call": round(tokens / calls, 2) if calls else 0.0,
                "total_cost_usd": round(cost, 6),
                "over_budget_calls": over,
                "over_budget_rate_pct": round((over / calls * 100.0), 2) if calls else 0.0,
                "budget_tokens": self._budget_for_task(task),
            })

        rows.sort(key=lambda r: (r["over_budget_calls"], r["total_tokens"]), reverse=True)
        return rows[:max(1, min(100, int(top_n)))]

    def model_efficiency(self, window_minutes: int = 60) -> list[dict[str, Any]]:
        wm = max(1, min(24 * 60, int(window_minutes)))
        events = self._filtered_events(wm)
        grouped: dict[str, list[TokenEvent]] = {}
        for e in events:
            grouped.setdefault(e.model, []).append(e)

        rows: list[dict[str, Any]] = []
        for model, arr in grouped.items():
            calls = len(arr)
            prompt_tokens = sum(x.prompt_tokens for x in arr)
            completion_tokens = sum(x.completion_tokens for x in arr)
            total_tokens = sum(x.total_tokens for x in arr)
            total_cost = sum(x.cost_usd for x in arr)
            total_latency = sum(x.latency_ms for x in arr)
            over_budget_calls = sum(1 for x in arr if x.over_budget)
            cost_alert_calls = sum(1 for x in arr if x.cost_alert)
            cost_per_1k_tokens = (total_cost / total_tokens * 1000.0) if total_tokens > 0 else 0.0
            rows.append({
                "model": model,
                "calls": calls,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "avg_tokens_per_call": round(total_tokens / calls, 2) if calls else 0.0,
                "total_cost_usd": round(total_cost, 6),
                "avg_cost_per_call_usd": round(total_cost / calls, 6) if calls else 0.0,
                "cost_per_1k_tokens_usd": round(cost_per_1k_tokens, 6),
                "avg_latency_ms": round(total_latency / calls, 2) if calls else 0.0,
                "over_budget_calls": over_budget_calls,
                "over_budget_rate_pct": round((over_budget_calls / calls * 100.0), 2) if calls else 0.0,
                "cost_alert_calls": cost_alert_calls,
            })
        rows.sort(key=lambda r: (r["total_cost_usd"], r["total_tokens"]), reverse=True)
        return rows

    def recommendations(self, window_minutes: int = 60, min_calls: int = 8) -> dict[str, Any]:
        wm = max(1, min(24 * 60, int(window_minutes)))
        min_n = max(1, min(1000, int(min_calls)))
        events = self._filtered_events(wm)

        grouped: dict[str, dict[str, list[TokenEvent]]] = {}
        for e in events:
            task_models = grouped.setdefault(e.task_name, {})
            task_models.setdefault(e.model, []).append(e)

        opportunities: list[dict[str, Any]] = []
        for task, model_map in grouped.items():
            if len(model_map) < 2:
                continue

            stats_by_model: list[dict[str, Any]] = []
            for model, arr in model_map.items():
                calls = len(arr)
                total_tokens = sum(x.total_tokens for x in arr)
                total_cost = sum(x.cost_usd for x in arr)
                total_latency = sum(x.latency_ms for x in arr)
                avg_cost = (total_cost / calls) if calls else 0.0
                avg_tokens = (total_tokens / calls) if calls else 0.0
                avg_latency = (total_latency / calls) if calls else 0.0
                cost_per_1k = (total_cost / total_tokens * 1000.0) if total_tokens > 0 else 0.0
                stats_by_model.append({
                    "model": model,
                    "calls": calls,
                    "avg_cost_per_call_usd": avg_cost,
                    "avg_tokens_per_call": avg_tokens,
                    "avg_latency_ms": avg_latency,
                    "cost_per_1k_tokens_usd": cost_per_1k,
                })

            stable = [s for s in stats_by_model if s["calls"] >= min_n]
            if len(stable) < 2:
                continue

            baseline = max(stable, key=lambda s: s["calls"])
            cheapest = min(stable, key=lambda s: s["cost_per_1k_tokens_usd"])
            if cheapest["model"] == baseline["model"]:
                continue

            savings_per_call = baseline["avg_cost_per_call_usd"] - cheapest["avg_cost_per_call_usd"]
            if savings_per_call <= 0:
                continue

            token_ratio = (
                cheapest["avg_tokens_per_call"] / baseline["avg_tokens_per_call"]
                if baseline["avg_tokens_per_call"] > 0 else 1.0
            )
            latency_ratio = (
                cheapest["avg_latency_ms"] / baseline["avg_latency_ms"]
                if baseline["avg_latency_ms"] > 0 else 1.0
            )

            if stable and min(baseline["calls"], cheapest["calls"]) >= 30:
                confidence = "high"
            elif stable and min(baseline["calls"], cheapest["calls"]) >= 15:
                confidence = "medium"
            else:
                confidence = "low"

            opportunities.append({
                "task_name": task,
                "current_model": baseline["model"],
                "suggested_model": cheapest["model"],
                "estimated_savings_per_call_usd": round(savings_per_call, 6),
                "estimated_savings_pct": round(
                    (savings_per_call / baseline["avg_cost_per_call_usd"] * 100.0)
                    if baseline["avg_cost_per_call_usd"] > 0 else 0.0,
                    2,
                ),
                "token_ratio_vs_current": round(token_ratio, 3),
                "latency_ratio_vs_current": round(latency_ratio, 3),
                "current_calls": baseline["calls"],
                "suggested_calls": cheapest["calls"],
                "confidence": confidence,
                "note": (
                    "Recommendation is cost/latency-based. Validate output quality with A/B checks "
                    "before switching fully."
                ),
            })

        opportunities.sort(
            key=lambda o: (
                o["estimated_savings_per_call_usd"],
                o["estimated_savings_pct"],
            ),
            reverse=True,
        )

        return {
            "window_minutes": wm,
            "min_calls": min_n,
            "opportunities": opportunities[:25],
            "model_efficiency": self.model_efficiency(window_minutes=wm),
        }

    def budgets(self) -> dict[str, Any]:
        return {
            "default_token_budget": self._default_budget,
            "warn_multiplier": self._warn_multiplier,
            "max_cost_usd_per_call": self._max_cost_per_call,
            "task_budgets": dict(sorted(self._task_budgets.items())),
        }


_monitor_singleton: TokenMonitor | None = None


def get_token_monitor() -> TokenMonitor:
    global _monitor_singleton
    if _monitor_singleton is None:
        _monitor_singleton = TokenMonitor()
    return _monitor_singleton
