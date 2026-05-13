from __future__ import annotations

from fastapi import Depends, Request

from app.models import User
from app.services.auth_service import require_hr


def _role_to_str(role: object) -> str:
    value = getattr(role, "value", role)
    return str(value)


async def harness_get_current_tenant(
    request: Request,
    user: User = Depends(require_hr),
) -> str:
    # One-tenant-per-HR-user mapping for mounted /harness routes.
    return str(user.id)


async def harness_get_current_user(
    request: Request,
    user: User = Depends(require_hr),
) -> dict:
    user_id = str(user.id)
    return {
        "sub": user_id,
        "tenant_id": user_id,
        "role": _role_to_str(user.role),
        "email": str(user.email or ""),
    }
