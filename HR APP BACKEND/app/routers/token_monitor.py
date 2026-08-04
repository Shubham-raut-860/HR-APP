"""
Token monitoring endpoints.

These endpoints expose rolling token/cost usage gathered from LLM calls.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.models import User
from app.services.auth_service import require_hr
from app.services.token_monitor_service import get_token_monitor

router = APIRouter(prefix="/monitoring/tokens", tags=["Token Monitoring"])


@router.get("/summary")
async def token_summary(
    window_minutes: int = Query(default=60, ge=1, le=1440),
    _: User = Depends(require_hr),
):
    monitor = get_token_monitor()
    return monitor.summary(window_minutes=window_minutes)


@router.get("/recent")
async def token_recent(
    limit: int = Query(default=100, ge=1, le=1000),
    _: User = Depends(require_hr),
):
    monitor = get_token_monitor()
    return {"events": monitor.recent(limit=limit)}


@router.get("/hotspots")
async def token_hotspots(
    top_n: int = Query(default=10, ge=1, le=100),
    window_minutes: int = Query(default=60, ge=1, le=1440),
    _: User = Depends(require_hr),
):
    monitor = get_token_monitor()
    return {"hotspots": monitor.hotspots(top_n=top_n, window_minutes=window_minutes)}


@router.get("/budgets")
async def token_budgets(_: User = Depends(require_hr)):
    monitor = get_token_monitor()
    return monitor.budgets()


@router.get("/models")
async def token_models(
    window_minutes: int = Query(default=60, ge=1, le=1440),
    _: User = Depends(require_hr),
):
    monitor = get_token_monitor()
    return {"models": monitor.model_efficiency(window_minutes=window_minutes)}


@router.get("/recommendations")
async def token_recommendations(
    window_minutes: int = Query(default=60, ge=1, le=1440),
    min_calls: int = Query(default=8, ge=1, le=1000),
    _: User = Depends(require_hr),
):
    monitor = get_token_monitor()
    return monitor.recommendations(window_minutes=window_minutes, min_calls=min_calls)
