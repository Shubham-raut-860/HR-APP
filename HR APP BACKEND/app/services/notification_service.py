"""
notification_service.py - helpers to push notifications into the DB.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import insert, select
from app.models import Notification, NotificationType, User, UserRole


async def push_notification(
    db: AsyncSession,
    user_id: str,
    title: str,
    message: str,
    ntype: NotificationType = NotificationType.system,
    related_id: str | None = None,
) -> Notification:
    notif = Notification(
        user_id=user_id,
        title=title,
        message=message,
        type=ntype,
        related_id=related_id,
    )
    db.add(notif)
    return notif


async def push_to_all_candidates(
    db: AsyncSession,
    title: str,
    message: str,
    ntype: NotificationType = NotificationType.job_posted,
    related_id: str | None = None,
) -> int:
    # BUG-22 FIX: Use server-side streaming instead of .scalars().all()
    # to avoid loading the entire user table into RAM at once.
    result = await db.stream(
        select(User.id).where(User.role == UserRole.candidate, User.is_active == True)
    )
    count = 0
    async for partition in result.partitions(200):
        rows = [
            {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "title": title,
                "message": message,
                "type": ntype,
                "related_id": related_id,
                "is_read": False,
                "is_dismissed": False,
                "created_at": datetime.now(timezone.utc),
            }
            for (user_id,) in partition
        ]
        if rows:
            await db.execute(insert(Notification), rows)
            count += len(rows)
    return count


async def push_to_candidate_by_email(
    db: AsyncSession,
    email: str,
    title: str,
    message: str,
    ntype: NotificationType = NotificationType.system,
    related_id: str | None = None,
) -> bool:
    res = await db.execute(
        select(User).where(User.email == email.lower(), User.role == UserRole.candidate)
    )
    u = res.scalar_one_or_none()
    if u:
        db.add(Notification(
            user_id=u.id,
            title=title,
            message=message,
            type=ntype,
            related_id=related_id,
        ))
        return True
    return False


async def push_to_hr_users(
    db: AsyncSession,
    title: str,
    message: str,
    ntype: NotificationType = NotificationType.system,
    related_id: str | None = None,
) -> int:
    """Broadcast a notification to every active HR/Admin user."""
    result = await db.stream(
        select(User.id).where(User.role.in_([UserRole.hr, UserRole.admin]), User.is_active == True)
    )
    count = 0
    async for partition in result.partitions(200):
        rows = [
            {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "title": title,
                "message": message,
                "type": ntype,
                "related_id": related_id,
                "is_read": False,
                "is_dismissed": False,
                "created_at": datetime.now(timezone.utc),
            }
            for (user_id,) in partition
        ]
        if rows:
            await db.execute(insert(Notification), rows)
            count += len(rows)
    return count
