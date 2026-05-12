from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_serializer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.database import get_db
from app.models import Notification, User
from app.services.auth_service import get_current_user

router = APIRouter(prefix="/notifications", tags=["Notifications"])


class NotifOut(BaseModel):
    id: str
    title: str
    message: str
    type: str
    is_read: bool
    is_dismissed: bool
    related_id: Optional[str]
    created_at: datetime
    model_config = {"from_attributes": True}

    @field_serializer("created_at")
    def serialize_created_at(self, v: datetime) -> str:
        # Always emit as UTC ISO-8601 with a Z suffix so that JavaScript's
        # Date constructor parses it as UTC, not local time.  Without this,
        # naive datetimes (no tzinfo) are treated as local time by JS, making
        # a notification created "just now" appear as hours old in non-UTC zones.
        if v.tzinfo is None:
            return v.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
        return v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"


class PrefsRequest(BaseModel):
    snooze_until: Optional[str] = None
    blocked_types: Optional[List[str]] = None


def _is_snoozed(user: User) -> bool:
    prefs = user.preferences or {}
    snooze_until = prefs.get("snooze_until")
    if not snooze_until:
        return False
    try:
        until = datetime.fromisoformat(snooze_until).replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < until
    except Exception:
        return False


@router.get("/")
async def get_my_notifications(
    page: int = Query(1, ge=1),
    limit: int = Query(60, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    prefs = user.preferences or {}
    blocked_types = prefs.get("blocked_types", [])

    offset = (page - 1) * limit
    res = await db.execute(
        select(Notification)
        .where(Notification.user_id == user.id, Notification.is_dismissed == False)
        .order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    all_notifs = res.scalars().all()

    visible_notifs = [n for n in all_notifs if n.type not in blocked_types]
    unread = sum(1 for n in visible_notifs if not n.is_read)

    return {
        "notifications": [NotifOut.model_validate(n) for n in visible_notifs],
        "unread_count": unread,
        "is_snoozed": _is_snoozed(user),
        "snooze_until": prefs.get("snooze_until"),
        "blocked_types": blocked_types
    }


@router.put("/{notif_id}/read")
async def mark_read(notif_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    res = await db.execute(select(Notification).where(Notification.id == notif_id, Notification.user_id == user.id))
    notif = res.scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    notif.is_read = True
    await db.commit()
    return {"message": "Marked"}

# FIX (Bug Audit #11): Changed from POST to PUT for consistency with
# PUT /{notif_id}/read — both are idempotent update operations.


@router.put("/read-all")
async def mark_all_read(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await db.execute(update(Notification).where(Notification.user_id == user.id, Notification.is_dismissed == False).values(is_read=True))
    await db.commit()
    return {"message": "All read"}


@router.delete("/")
async def clear_all(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    # FIX (Bug #1 - CRITICAL): This route MUST be defined before DELETE /{notif_id}.
    # FastAPI/Starlette registers routes in declaration order; when the parameterised
    # route /{notif_id} came first, a DELETE /notifications/ request (trailing slash,
    # empty segment) could be swallowed by that route, leaving notif_id="" and
    # making the query return nothing — so nothing was ever cleared.
    await db.execute(update(Notification).where(Notification.user_id == user.id).values(is_dismissed=True, is_read=True))
    await db.commit()
    return {"message": "Cleared"}


@router.delete("/{notif_id}")
async def dismiss_one(notif_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    res = await db.execute(select(Notification).where(Notification.id == notif_id, Notification.user_id == user.id))
    notif = res.scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    notif.is_dismissed = True
    await db.commit()
    return {"message": "Dismissed"}


@router.put("/preferences")
async def update_prefs(body: PrefsRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    # BUG FIX: get_current_user uses its own db session. Mutating `user` from that
    # session and calling flag_modified/commit on a *different* `db` session is an
    # async SQLAlchemy anti-pattern — the ORM change tracker on `db` has no
    # knowledge of the object, so changes silently do not persist (DetachedInstanceError
    # under stricter engine configs). Re-fetch the user inside this request's session.
    db_user = await db.get(User, user.id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    prefs = dict(db_user.preferences or {})
    if body.snooze_until is not None:
        if body.snooze_until == "":
            prefs.pop("snooze_until", None)
        else:
            prefs["snooze_until"] = body.snooze_until

    if body.blocked_types is not None:
        prefs["blocked_types"] = body.blocked_types

    db_user.preferences = prefs
    flag_modified(db_user, "preferences")
    await db.commit()
    return {"message": "Preferences updated", "preferences": prefs}
