"""Regression tests for scoring math + agent hardening (BUG-46..58)."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.models import CandidateTag
from app.agents.specialized import ranking_agent, scoring_agent
from app.agents.specialized.ranking_agent import RankingAgent
from app.agents.specialized.scoring_agent import ScoringAgent
from app.services import scoring_service


def test_cosine_similarity_dim_mismatch() -> None:
    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        scoring_service.cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0])


def test_composite_similarity_nan_input() -> None:
    value, meta = scoring_service.compute_composite_vector_similarity(
        full_similarity=float("nan"),
        skills_similarity=0.5,
        experience_similarity=float("nan"),
    )
    assert value == pytest.approx(0.175, rel=1e-6)
    assert meta["components"]["full"] == 0.0
    assert meta["components"]["experience"] == 0.0


def test_experience_match_inverted_range() -> None:
    # exp_min and exp_max are intentionally inverted.
    score = scoring_service.experience_match_score(
        candidate_years=7,
        exp_min=10,
        exp_max=5,
        skill_years=None,
        required_skills=None,
    )
    assert score == 100.0


def test_relevant_exp_string_years() -> None:
    value = scoring_service.compute_relevant_experience_years(
        skill_years={"Python": "three"},
        required_skills=["Python"],
        total_years=6.0,
    )
    assert value == pytest.approx(3.6, rel=1e-6)


def test_ai_override_parse_failed() -> None:
    score, used_skill, used_exp, used_proj = scoring_service.compute_resume_score_with_ai_override(
        ai_scores={
            "skill_score": 99.0,
            "experience_score": 99.0,
            "project_score": 99.0,
            "overall": 99.0,
            "parse_failed": True,
        },
        education_pct=50.0,
        vector_sim=0.0,
        location_pct=50.0,
        experience_years=2.0,
        rule_skill_pct=40.0,
        rule_exp_pct=35.0,
        rule_proj_pct=30.0,
        critical_missing_count=0,
        has_jd_skills=True,
        total_must_have_count=1,
        vector_available=False,
    )
    assert used_skill == 40.0
    assert used_exp == 35.0
    assert used_proj == 30.0
    assert 0.0 <= score <= 100.0


def test_final_score_clamp() -> None:
    assert scoring_service.compute_final_score(105.0, None) == 100.0


def test_embedding_cache_concurrent(monkeypatch: pytest.MonkeyPatch) -> None:
    call_count = {"count": 0}

    async def _fake_embedding(_text: str) -> list[float]:
        call_count["count"] += 1
        await asyncio.sleep(0.01)
        return [0.1, 0.2, 0.3]

    scoring_agent._SECTION_EMBED_CACHE.clear()
    scoring_agent._SECTION_EMBED_IN_FLIGHT.clear()
    monkeypatch.setattr(scoring_agent.gemini_service, "get_embedding", _fake_embedding)

    async def _run() -> list[list[float]]:
        return await asyncio.gather(*[scoring_agent._get_cached_embedding("same text") for _ in range(10)])

    vectors = asyncio.run(_run())
    assert call_count["count"] == 1
    assert all(v == [0.1, 0.2, 0.3] for v in vectors)


def test_scoring_agent_vector_dim_mismatch_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = ScoringAgent()

    def _raise_dim_mismatch(_a, _b):
        raise ValueError("Embedding dimension mismatch: vec_a=3072, vec_b=1536")

    monkeypatch.setattr(scoring_service, "cosine_similarity", _raise_dim_mismatch)
    monkeypatch.setattr(scoring_service, "compute_resume_score_with_ai_override", lambda **_kwargs: (50.0, 40.0, 40.0, 40.0))
    monkeypatch.setattr(scoring_service, "assign_tag", lambda _score: CandidateTag.medium)
    monkeypatch.setattr(scoring_service, "build_phase_b_calibration", lambda **_kwargs: ({}, 0.0, {"jd_signal_strength": 1.0}))

    state = {
        "parsed_resume": {
            "normalized_skills": [],
            "experience_years": 1,
            "skill_years": {},
            "projects": [],
            "education": [],
            "location": None,
            "work_experience": [],
        },
        "parsed_job": {
            "id": "job-v",
            "title": "Role",
            "role": "Role",
            "experience_min": 1,
            "experience_max": 3,
            "must_have_skills": [],
            "good_to_have_skills": [],
            "description": "",
        },
        "embedding": [1.0, 2.0, 3.0],
        "jd_embedding": [1.0, 2.0],
        "skip_ai_scoring": True,
        "timeout_s": 2,
    }

    result = asyncio.run(agent.run(state))["score_result"]
    assert result["vector_warning"] is True
    assert result["vector_similarity_full"] == 0.0


def test_ai_score_used_flag_and_skill_list_none_field(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = ScoringAgent()

    async def _fake_ai_score(**_kwargs):
        return {
            "overall": None,
            "parse_failed": True,
            "matched_must_have": None,
            "missing_must_have": None,
            "matched_good_to_have": None,
            "missing_good_to_have": None,
            "red_flags": None,
            "standout_factors": None,
        }

    monkeypatch.setattr(scoring_agent.gemini_service, "score_resume_against_jd", _fake_ai_score)
    monkeypatch.setattr(scoring_service, "compute_resume_score_with_ai_override", lambda **_kwargs: (55.0, 50.0, 45.0, 40.0))
    monkeypatch.setattr(scoring_service, "assign_tag", lambda _score: CandidateTag.medium)
    monkeypatch.setattr(scoring_service, "build_phase_b_calibration", lambda **_kwargs: ({}, 0.0, {"jd_signal_strength": 1.0}))

    state = {
        "parsed_resume": {
            "normalized_skills": [],
            "experience_years": 1,
            "skill_years": {},
            "projects": [],
            "education": [],
            "location": None,
            "work_experience": [],
        },
        "parsed_job": {
            "id": "job-1",
            "title": "Role",
            "role": "Role",
            "experience_min": 1,
            "experience_max": 3,
            "must_have_skills": [],
            "good_to_have_skills": [],
            "description": "",
        },
        "embedding": [],
        "jd_embedding": [],
        "skip_ai_scoring": False,
        "timeout_s": 2,
    }

    result = asyncio.run(agent.run(state))["score_result"]
    assert result["ai_score_used"] is False
    assert result["matched_must_have"] == []
    assert result["missing_must_have"] == []
    assert result["matched_good_to_have"] == []
    assert result["missing_good_to_have"] == []
    assert result["red_flags"] == []
    assert result["standout_factors"] == []


def test_ai_score_used_flag_valid_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = ScoringAgent()

    async def _fake_ai_score(**_kwargs):
        return {
            "overall": 82.0,
            "parse_failed": False,
            "matched_must_have": ["Python"],
            "missing_must_have": [],
            "matched_good_to_have": [],
            "missing_good_to_have": [],
            "red_flags": [],
            "standout_factors": [],
        }

    monkeypatch.setattr(scoring_agent.gemini_service, "score_resume_against_jd", _fake_ai_score)
    monkeypatch.setattr(scoring_service, "compute_resume_score_with_ai_override", lambda **_kwargs: (82.0, 80.0, 80.0, 80.0))
    monkeypatch.setattr(scoring_service, "assign_tag", lambda _score: CandidateTag.strong)
    monkeypatch.setattr(scoring_service, "build_phase_b_calibration", lambda **_kwargs: ({}, 0.0, {"jd_signal_strength": 1.0}))

    state = {
        "parsed_resume": {
            "normalized_skills": ["Python"],
            "experience_years": 3,
            "skill_years": {"Python": 3},
            "projects": [],
            "education": [],
            "location": None,
            "work_experience": [],
        },
        "parsed_job": {
            "id": "job-2",
            "title": "Role",
            "role": "Role",
            "experience_min": 1,
            "experience_max": 4,
            "must_have_skills": ["Python"],
            "good_to_have_skills": [],
            "description": "",
        },
        "embedding": [],
        "jd_embedding": [],
        "skip_ai_scoring": False,
        "timeout_s": 2,
    }

    result = asyncio.run(agent.run(state))["score_result"]
    assert result["ai_score_used"] is True


def test_lyzr_rank_json_array(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = RankingAgent()

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"response": "[1, 2, 3]"}

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return _FakeResponse()

    monkeypatch.setattr(ranking_agent.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(ranking_agent.settings, "LYZR_AGENT_URL", "https://example.test/rank")
    monkeypatch.setattr(ranking_agent.settings, "LYZR_API_KEY", "test-key")
    monkeypatch.setattr(ranking_agent.settings, "LYZR_AGENT_ID", "agent-1")
    monkeypatch.setattr(ranking_agent.settings, "LYZR_USER_ID", "user-1")
    monkeypatch.setattr(ranking_agent.settings, "LYZR_SESSION_ID", "session-1")

    result = asyncio.run(
        agent._lyzr_rank(
            candidates=[{"name": "A", "resume_score": 70.0, "skills": [], "experience_years": 2}],
            jd={"title": "Role", "required_skills": [], "experience_min": 0, "experience_max": 5},
        )
    )
    assert result["ranking_result"]["source"] == "rule_based_lyzr_shape_fallback"


def test_skills_string_join() -> None:
    prompt = RankingAgent._build_lyzr_prompt(
        jd={"title": "Role", "required_skills": ["Python"], "experience_min": 0, "experience_max": 5},
        candidates=[{"name": "A", "skills": "Python", "experience_years": 2, "summary": "Good"}],
    )
    assert "Skills: Python" in prompt
    assert "P, y, t, h, o, n" not in prompt
