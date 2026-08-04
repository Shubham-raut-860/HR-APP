"""
flows/_async_bridge.py — Sync wrapper for async coroutines
===========================================================

Metaflow steps run as normal synchronous Python subprocesses. The Jobora
scoring pipeline (gemini_service, file_service, etc.) is built on asyncio.

`run_async()` bridges the gap: it spins up a *fresh* event loop per call,
runs the coroutine to completion, and tears it down cleanly. This avoids
"Event loop is closed" errors that occur when Metaflow reuses a process that
previously had an event loop.

Usage inside a Metaflow step:
    from flows._async_bridge import run_async
    from app.services.gemini_service import score_resume_against_jd

    result = run_async(score_resume_against_jd(parsed_resume, job_title, ...))

Design notes:
  - Never share a loop between steps; each step subprocess starts fresh.
  - For CPU-bound scoring (scoring_service.py), call functions directly —
    no bridge needed, they are synchronous.
  - Do NOT use asyncio.run() here: it raises RuntimeError if an event loop is
    already running in the same thread (e.g. in tests). new_event_loop() +
    run_until_complete() + close() is safer in subprocess contexts.
"""
from __future__ import annotations

import asyncio
from typing import Any, Coroutine, TypeVar

_T = TypeVar("_T")


def run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run *coro* synchronously in a fresh event loop and return its result.

    Args:
        coro: An unawaited coroutine object (e.g. ``my_async_fn(arg1, arg2)``).

    Returns:
        Whatever the coroutine returns.

    Raises:
        Any exception raised inside the coroutine propagates unchanged.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        # Best-effort cleanup of any dangling tasks before closing.
        try:
            pending = asyncio.all_tasks(loop)
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
        finally:
            loop.close()
