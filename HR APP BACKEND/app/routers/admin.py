"""
Admin router – user management, audit logs
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
from app.database import get_db
from app.models import User, AuditLog, UserRole
from app.schemas import UserOut, AuditLogOut
from app.services.auth_service import require_admin

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/users", response_model=List[UserOut])
async def list_users(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    res = await db.execute(
        select(User).order_by(User.created_at.desc()).offset(skip).limit(limit)
    )
    return res.scalars().all()


@router.patch("/users/{user_id}/toggle", response_model=UserOut)
async def toggle_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    # FIX: Prevent admin from deactivating their own account
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot toggle your own account")
    # FIX: SELECT ... FOR UPDATE to prevent race conditions when two admins
    # toggle the same user simultaneously (both read is_active=True, both write False).
    res = await db.execute(
        select(User).where(User.id == user_id).with_for_update()
    )
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # BUG-16 FIX: Prevent deactivating the last remaining active admin.
    # Without this, an admin could deactivate the only other admin, leaving
    # zero active admins with no recovery mechanism.
    if user.is_active and user.role == UserRole.admin:
        active_admin_count = (await db.execute(
            select(func.count()).select_from(User).where(
                User.role == UserRole.admin,
                User.is_active == True,
            )
        )).scalar_one()
        if active_admin_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot deactivate the last active admin account"
            )

    user.is_active = not user.is_active
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/audit-logs", response_model=List[AuditLogOut])
async def get_audit_logs(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    resource: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    query = select(AuditLog).order_by(AuditLog.created_at.desc())
    if resource:
        # Validate against known resource types to prevent enumeration of
        # sensitive audit categories (e.g. auth logs containing IP addresses).
        _ALLOWED_RESOURCES = {
            "auth", "jd", "resume", "quiz", "candidate", "admin", "settings", "job_description",
        }
        if resource not in _ALLOWED_RESOURCES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid resource filter. Allowed: {sorted(_ALLOWED_RESOURCES)}",
            )
        query = query.where(AuditLog.resource == resource)
    query = query.offset(skip).limit(limit)
    res = await db.execute(query)
    return res.scalars().all()
