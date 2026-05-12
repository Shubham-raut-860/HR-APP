"""
NotificationAgent — dispatches in-app notifications and emails.

Operations (set `state["operation"]`):
  - "push"           — push in-app notification to a specific user
  - "push_email"     — push in-app notification to user found by email
  - "push_hr"        — broadcast to all active HR/Admin users
  - "push_all_candidates" — broadcast to all candidates (streamed, no RAM spike)
  - "email"          — send SMTP email (async, via send_email_async)
  - "hr_email_draft" — use AI to draft an email body, then send it
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.services import notification_service, email_service, gemini_service
from app.models import NotificationType

logger = logging.getLogger(__name__)


class NotificationAgent(BaseAgent):
    name = "notification_agent"
    model_key = "notification_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        operation = state.get("operation", "push")
        db = state.get("db")

        if operation == "push":
            return await self._push(state, db)
        elif operation == "push_email":
            return await self._push_email(state, db)
        elif operation == "push_hr":
            return await self._push_hr(state, db)
        elif operation == "push_all_candidates":
            return await self._push_all_candidates(state, db)
        elif operation == "email":
            return await self._send_email(state)
        elif operation == "hr_email_draft":
            return await self._hr_email_draft(state)
        else:
            raise ValueError(f"NotificationAgent: unknown operation '{operation}'")

    async def _push(self, state: dict, db) -> dict[str, Any]:
        if db is None:
            logger.warning("NotificationAgent[push]: no DB session, skipping")
            return {"notification_sent": False}
        await notification_service.push_notification(
            db=db,
            user_id=state["user_id"],
            title=state.get("title", "Notification"),
            message=state.get("message", ""),
            ntype=NotificationType[state.get("ntype", "system")],
            related_id=state.get("related_id"),
        )
        return {"notification_sent": True}

    async def _push_email(self, state: dict, db) -> dict[str, Any]:
        if db is None:
            return {"notification_sent": False}
        sent = await notification_service.push_to_candidate_by_email(
            db=db, email=state["email"],
            title=state.get("title", "Notification"),
            message=state.get("message", ""),
            ntype=NotificationType[state.get("ntype", "system")],
            related_id=state.get("related_id"),
        )
        return {"notification_sent": sent}

    async def _push_hr(self, state: dict, db) -> dict[str, Any]:
        if db is None:
            return {"notification_sent": False, "count": 0}
        count = await notification_service.push_to_hr_users(
            db=db,
            title=state.get("title", "Notification"),
            message=state.get("message", ""),
            ntype=NotificationType[state.get("ntype", "system")],
            related_id=state.get("related_id"),
        )
        return {"notification_sent": True, "count": count}

    async def _push_all_candidates(self, state: dict, db) -> dict[str, Any]:
        if db is None:
            return {"notification_sent": False, "count": 0}
        count = await notification_service.push_to_all_candidates(
            db=db,
            title=state.get("title", "Notification"),
            message=state.get("message", ""),
            ntype=NotificationType[state.get("ntype", "job_posted")],
            related_id=state.get("related_id"),
        )
        return {"notification_sent": True, "count": count}

    async def _send_email(self, state: dict) -> dict[str, Any]:
        to_email: str = state.get("to_email", "")
        subject: str = state.get("subject", "")
        body: str = state.get("email_body", "")
        if not to_email:
            raise ValueError("NotificationAgent[email]: 'to_email' is required")
        try:
            await email_service.send_email_async(to_email, subject, body)
            return {"email_sent": True, "to": to_email}
        except email_service.EmailSendError as exc:
            logger.warning("NotificationAgent[email]: %s", exc)
            return {"email_sent": False, "error": str(exc)}

    async def _hr_email_draft(self, state: dict) -> dict[str, Any]:
        """AI-drafts and then sends an HR communication email."""
        model = self.resolve_model(state)
        draft = await gemini_service.generate_hr_email(
            email_type=state.get("email_type", "general"),
            candidate_name=state.get("candidate_name", "Candidate"),
            job_title=state.get("job_title", "Role"),
            resume_score=float(state.get("resume_score", 0)),
            quiz_score=float(state.get("quiz_score", 0)),
            model=model,
        )
        subject = draft.get("subject", "Update from Hiring Team")
        body = draft.get("body", "")

        to_email: str = state.get("to_email", "")
        if to_email:
            try:
                await email_service.send_email_async(to_email, subject, body)
                return {"email_sent": True, "to": to_email, "subject": subject, "draft": draft}
            except email_service.EmailSendError as exc:
                logger.warning("NotificationAgent[hr_email_draft] send failed: %s", exc)
                return {"email_sent": False, "draft": draft, "error": str(exc)}

        return {"email_sent": False, "draft": draft, "note": "to_email not provided, draft only"}

    async def health(self) -> dict[str, Any]:
        return {"agent": self.name, "status": "ok"}
