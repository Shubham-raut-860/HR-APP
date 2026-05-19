"""Regression tests for schema/auth validation contracts (BUG-14..16)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.constants.scoring import MAX_QUIZ_QUESTIONS
from app.routers.auth import _validate_new_password_or_400
from app.schemas import CandidateListOut, CandidateOut, PoolMatchOut, SubmitAnswersRequest, UserCreate
from app.utils.password_policy import validate_password


def _candidate_out_payload(email: Any) -> dict[str, Any]:
    return {
        "id": "cand-1",
        "job_id": "job-1",
        "user_id": "user-1",
        "name": "Candidate One",
        "email": email,
        "phone": "9999999999",
        "location": "Remote",
        "skills": [],
        "normalized_skills": [],
        "experience_years": 1.5,
        "education": [],
        "projects": [],
        "skill_match_pct": 0.0,
        "experience_match_pct": 0.0,
        "project_relevance_pct": 0.0,
        "education_match_pct": 0.0,
        "vector_similarity": 0.0,
        "resume_score": 0.0,
        "tag": None,
        "quiz_score": None,
        "final_score": None,
        "rank": None,
        "passed": None,
        "created_at": datetime.now(timezone.utc),
    }


def _candidate_list_payload(email: Any) -> dict[str, Any]:
    payload = _candidate_out_payload(email)
    payload["is_archived"] = False
    return payload


def _pool_match_payload(email: Any) -> dict[str, Any]:
    return {
        "id": "cand-1",
        "name": "Candidate One",
        "email": email,
        "phone": "9999999999",
        "location": "Remote",
        "skills": [],
        "normalized_skills": [],
        "experience_years": 1.5,
        "computed_resume_score": 80.0,
        "computed_skill_match_pct": 75.0,
        "computed_experience_match_pct": 70.0,
        "computed_tag": "medium",
    }


@pytest.mark.parametrize(
    ("password", "should_pass"),
    [
        ("Aa1!aaa", False),  # 7 chars
        ("abcdefgh1!", False),  # no uppercase
        ("ABCDEFGH1!", False),  # no lowercase
        ("Abcdefgh!!", False),  # no digit
        ("Abcdefgh1", False),  # no special
        ("A" + ("a" * 70) + "1!", False),  # >72 bytes
        ("Abcd1!ef", True),  # valid baseline
    ],
)
def test_password_policy(password: str, should_pass: bool) -> None:
    if should_pass:
        assert validate_password(password) == password
    else:
        with pytest.raises(ValueError):
            validate_password(password)


@pytest.mark.parametrize(
    "password",
    [
        "Aa1!aaa",  # too short
        "abcdefgh1!",  # no uppercase
        "ABCDEFGH1!",  # no lowercase
        "Abcdefgh!!",  # no digit
        "Abcdefgh1",  # no special
        "A" + ("a" * 70) + "1!",  # >72 bytes
        "Abcd1!ef",  # valid
    ],
)
def test_password_policy_consistent(password: str) -> None:
    # Register path policy (schema validator).
    try:
        UserCreate(
            email="candidate@example.com",
            password=password,
            full_name="Candidate One",
            role="candidate",
        )
        register_accepts = True
    except ValidationError:
        register_accepts = False

    # Reset/change path policy (router helper shared by both handlers).
    try:
        _validate_new_password_or_400(password)
        reset_change_accepts = True
    except HTTPException:
        reset_change_accepts = False

    assert register_accepts == reset_change_accepts


def test_candidate_email_dirty_does_not_raise_500() -> None:
    app = FastAPI()

    @app.get("/candidate", response_model=CandidateOut)
    async def get_candidate():
        return _candidate_out_payload("user@")

    client = TestClient(app)
    response = client.get("/candidate")
    assert response.status_code == 200
    assert response.json()["email"] is None


@pytest.mark.parametrize("dirty_email", ["user@", "no-at-sign", " ", None])
def test_candidate_email_dirty_normalized_to_none(dirty_email: Any) -> None:
    candidate = CandidateOut.model_validate(_candidate_out_payload(dirty_email))
    candidate_list = CandidateListOut.model_validate(_candidate_list_payload(dirty_email))
    pool_match = PoolMatchOut.model_validate(_pool_match_payload(dirty_email))

    assert candidate.email is None
    assert candidate_list.email is None
    assert pool_match.email is None


def test_submit_answers_oversized() -> None:
    app = FastAPI()

    @app.post("/submit")
    async def submit(body: SubmitAnswersRequest):
        return {"ok": True}

    client = TestClient(app)
    answers = {f"q{i}": 0 for i in range(MAX_QUIZ_QUESTIONS + 1)}
    response = client.post("/submit", json={"attempt_id": "attempt-1", "answers": answers})

    assert response.status_code == 422
    detail = str(response.json().get("detail", ""))
    assert f"answers cannot contain more than {MAX_QUIZ_QUESTIONS} items" in detail


def test_submit_answers_bad_key_type() -> None:
    with pytest.raises(ValidationError) as exc_info:
        SubmitAnswersRequest.model_validate(
            {"attempt_id": "attempt-1", "answers": {1: 0}}
        )

    assert "All answer keys must be non-empty strings" in str(exc_info.value)
