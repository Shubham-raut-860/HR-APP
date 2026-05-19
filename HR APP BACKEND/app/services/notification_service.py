"""
notification_service.py - helpers to push notifications into the DB.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import insert, select, func
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


async def push_to_candidates_by_emails(
    db: AsyncSession,
    emails: list[str],
    title: str,
    message: str,
    ntype: NotificationType = NotificationType.system,
    related_id: str | None = None,
) -> list[str]:
    normalized_emails: list[str] = []
    seen: set[str] = set()
    for raw_email in emails:
        lowered = (raw_email or "").strip().lower()
        if lowered and lowered not in seen:
            normalized_emails.append(lowered)
            seen.add(lowered)

    if not normalized_emails:
        return []

    res = await db.execute(
        select(User.id, User.email).where(
            func.lower(User.email).in_(normalized_emails),
            User.role == UserRole.candidate,
        )
    )
    matched_users = res.all()
    if not matched_users:
        return []

    now = datetime.now(timezone.utc)
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
            "created_at": now,
        }
        for user_id, _email in matched_users
    ]
    await db.execute(insert(Notification), rows)
    return [email for _user_id, email in matched_users]


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
