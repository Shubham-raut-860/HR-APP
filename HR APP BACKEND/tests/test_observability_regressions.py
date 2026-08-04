"""Regression tests for optional observability adapters."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings, settings


def test_langfuse_disabled_by_default_in_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)
    cfg = Settings(_env_file=None)
    assert cfg.LANGFUSE_ENABLED is False


def test_langfuse_disabled_exports_noop_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LANGFUSE_ENABLED", False, raising=False)
    module = importlib.import_module("app.services.langfuse_service")
    module = importlib.reload(module)

    @module.observe(name="noop-test")
    async def _sample() -> str:
        return "ok"

    assert module.langfuse_context.get_current_trace_id() is None

    import asyncio

    assert asyncio.run(_sample()) == "ok"
