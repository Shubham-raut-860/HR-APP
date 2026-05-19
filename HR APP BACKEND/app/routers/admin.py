"""
Admin router - user management, audit logs
"""

import html
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from jose import jwt
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.limiter import limiter
from app.models import AuditLog, User, UserRole
from app.schemas import AuditLogOut, UserOut
from app.services.auth_service import hash_password, require_admin
from app.services.email_service import send_email_async

router = APIRouter(prefix="/admin", tags=["Admin"])


class AdminCreateUserRequest(BaseModel):
    email: EmailStr
    full_name: str
    role: Literal["hr"] = "hr"


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


@router.post("/users", response_model=UserOut, status_code=201)
@limiter.limit("10/minute")
async def create_hr_user(
    request: Request,
    body: AdminCreateUserRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    email = body.email.lower()
    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    provisional_password = secrets.token_urlsafe(24)
    user = User(
        email=email,
        hashed_password=hash_password(provisional_password),
        full_name=body.full_name.strip(),
        role=UserRole.hr,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    expire = datetime.now(timezone.utc) + timedelta(hours=24)
    reset_payload = {
        "sub": user.email,
        "exp": expire,
        "type": "reset",
        "jti": str(uuid.uuid4()),
    }
    dynamic_secret = f"{settings.SECRET_KEY}{user.hashed_password}"
    reset_token = jwt.encode(reset_payload, dynamic_secret, algorithm=settings.ALGORITHM)

    base_url = settings.FRONTEND_URL.rstrip("/")
    reset_link = f"{base_url}/reset-password/{reset_token}"
    safe_link = html.escape(reset_link, quote=True)
    html_body = (
        "<p>Your HR account has been created by an administrator.</p>"
        "<p>Set your password using the secure link below (expires in 24 hours):</p>"
        f"<p><a href='{safe_link}'>Set Password</a></p>"
    )
    background_tasks.add_task(
        send_email_async,
        user.email,
        "You're invited to HireAI (HR account)",
        html_body,
    )
    return user


@router.patch("/users/{user_id}/toggle", response_model=UserOut)
async def toggle_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    # Prevent admin from deactivating their own account.
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot toggle your own account")

    # SELECT ... FOR UPDATE avoids concurrent toggle races.
    res = await db.execute(select(User).where(User.id == user_id).with_for_update())
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Prevent deactivating the last active admin account.
    if user.is_active and user.role == UserRole.admin:
        active_admin_count = (
            await db.execute(
                select(func.count()).select_from(User).where(
                    User.role == UserRole.admin,
                    User.is_active == True,
                )
            )
        ).scalar_one()
        if active_admin_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot deactivate the last active admin account",
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
        allowed_resources = {
            "auth",
            "jd",
            "resume",
            "quiz",
            "candidate",
            "admin",
            "settings",
            "job_description",
        }
        if resource not in allowed_resources:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid resource filter. Allowed: {sorted(allowed_resources)}",
            )
        query = query.where(AuditLog.resource == resource)

    query = query.offset(skip).limit(limit)
    res = await db.execute(query)
    return res.scalars().all()
