"""
DeduplicationAgent — detects duplicate candidates via file_hash and email.

Returns:
  - `is_duplicate`: True if this candidate already exists for the job
  - `duplicate_reason`: 'file_hash' | 'email' | None
  - `existing_candidate_id`: ID of the existing record if found
"""
from __future__ import annotations
import hashlib
from typing import Any

from app.agents.base import BaseAgent


class DeduplicationAgent(BaseAgent):
    name = "deduplication_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        content: bytes | None = state.get("content") or state.get("file_bytes")
        email: str | None = state.get("candidate_email")
        job_id: str | None = state.get("job_id")
        db = state.get("db")

        if not job_id:
            # No job context — skip dedup silently
            return {"is_duplicate": False, "duplicate_reason": None, "file_hash": None}

        file_hash: str | None = None
        if content:
            file_hash = hashlib.sha256(content).hexdigest()

        if db is None:
            # No DB session — can't check, assume not duplicate
            return {"is_duplicate": False, "duplicate_reason": None, "file_hash": file_hash}

        from sqlalchemy import select
        from app.models import Candidate

        # Check by file_hash first (strongest signal — same bytes)
        if file_hash:
            existing = (await db.execute(
                select(Candidate.id).where(
                    Candidate.job_id == job_id,
                    Candidate.file_hash == file_hash,
                )
            )).scalar_one_or_none()
            if existing:
                return {
                    "is_duplicate": True,
                    "duplicate_reason": "file_hash",
                    "existing_candidate_id": existing,
                    "file_hash": file_hash,
                }

        # Then by email
        if email:
            existing = (await db.execute(
                select(Candidate.id).where(
                    Candidate.job_id == job_id,
                    Candidate.email == email.lower(),
                )
            )).scalar_one_or_none()
            if existing:
                return {
                    "is_duplicate": True,
                    "duplicate_reason": "email",
                    "existing_candidate_id": existing,
                    "file_hash": file_hash,
                }

        return {"is_duplicate": False, "duplicate_reason": None, "file_hash": file_hash}

    async def health(self) -> dict[str, Any]:
        return {"agent": self.name, "status": "ok"}
