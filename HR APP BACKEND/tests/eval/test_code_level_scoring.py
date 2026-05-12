"""
Code-level evaluation tests â€” NO LLM CALLS, NO API KEYS NEEDED.

These are deterministic, fast, and can run in CI without any credentials.
They test the correctness of the scoring_service.py functions themselves,
not the LLM-generated outputs.

Run with:
    pytest tests/eval/test_code_level_scoring.py -v

Design:
  - Each test asserts a property that must ALWAYS hold (invariant).
  - Failures mean a bug was introduced in the scoring logic.
"""

from __future__ import annotations

import math
import pytest
from app.constants.scoring import (
    DEFAULT_SHORTLIST_THRESHOLD,
    STRONG_SHORTLIST_THRESHOLD,
    TIER_FRESHER_MAX_YEARS,
    TIER_MID_MAX_YEARS,
)
from app.services.scoring_service import (
    compute_resume_score,
    compute_resume_score_with_ai_override,
    compute_final_score,
    compute_quiz_score,
    detect_candidate_tier,
    assign_tag,
    _TIER_WEIGHTS,
)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# DIMENSION 1 â€” Code-level: Weight table correctness (invariant)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

class TestTierWeights:

    def test_all_tier_weights_sum_to_one(self):
        """
        INVARIANT: Every tier's weights must sum to exactly 1.0.
        If a weight is added or removed, this fails immediately.
        """
        for tier, w in _TIER_WEIGHTS.items():
            total = sum(w.values())
            assert abs(total - 1.0) < 1e-6, (
                f"Tier '{tier}' weights sum to {total:.6f}, expected 1.0. "
                f"Weights: {w}"
            )

    def test_all_weights_non_negative(self):
        """No weight should be negative."""
        for tier, w in _TIER_WEIGHTS.items():
            for component, val in w.items():
                assert val >= 0.0, (
                    f"Tier '{tier}' component '{component}' has negative weight {val}"
                )

    def test_fresher_education_weight_higher_than_senior(self):
        """
        Freshers should be evaluated more on education than senior candidates.
        This is a design invariant of the HR scoring model.
        """
        assert _TIER_WEIGHTS["fresher"]["education"] > _TIER_WEIGHTS["senior"]["education"], (
            "Fresher education weight should be higher than senior education weight."
        )


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# DIMENSION 2 â€” Code-level: Score range clamp (invariant)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

class TestScoreRangeClamp:

    @pytest.mark.parametrize("skill,exp,proj,edu,vec,loc,exp_years", [
        (100, 100, 100, 100, 1.0, 100, 10),   # All maxed
        (0, 0, 0, 0, 0.0, 0, 0),             # All zeroed
        (150, 200, 300, 50, 2.0, 110, 5),    # Out-of-range inputs â†’ still 0-100
        (-10, -20, 80, 50, 0.5, 50, 3),      # Negative inputs
    ])
    def test_compute_resume_score_always_0_to_100(
        self, skill, exp, proj, edu, vec, loc, exp_years
    ):
        """INVARIANT: compute_resume_score must always return 0.0â€“100.0."""
        score = compute_resume_score(skill, exp, proj, edu, vec, loc, exp_years)
        assert 0.0 <= score <= 100.0, (
            f"compute_resume_score({skill},{exp},{proj},{edu},{vec},{loc},{exp_years})"
            f" returned {score}, outside [0, 100]"
        )

    @pytest.mark.parametrize("resume_score,quiz_score,quiz_max", [
        (100, 36, 36),
        (0, 0, 36),
        (50, 18, 36),
        (75, 0, 0),      # quiz_max=0 should not divide by zero
    ])
    def test_final_score_always_0_to_100(self, resume_score, quiz_score, quiz_max):
        """INVARIANT: final_score must be within [0, 100]."""
        score = compute_final_score(resume_score, quiz_score, quiz_max)
        assert 0.0 <= score <= 100.0, (
            f"compute_final_score({resume_score},{quiz_score},{quiz_max}) = {score}"
        )


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# DIMENSION 3 â€” Code-level: Final score formula correctness
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

class TestFinalScoreFormula:

    def test_50_50_split_is_average(self):
        """When resume_weight=50 quiz_weight=50, final_score = average of both %."""
        # resume=80, quiz=18/36=50% â†’ final = (80*0.5) + (50*0.5) = 65
        score = compute_final_score(80, 18, 36, resume_weight=50, quiz_weight=50)
        assert abs(score - 65.0) < 0.01, f"Expected 65.0, got {score}"

    def test_100_resume_weight_ignores_quiz(self):
        """When resume_weight=100 and quiz_weight=0, quiz is irrelevant."""
        score = compute_final_score(72.5, 0, 36, resume_weight=100, quiz_weight=0)
        assert abs(score - 72.5) < 0.01, f"Expected 72.5, got {score}"

    def test_quiz_max_zero_treated_as_max_score(self):
        """quiz_max=0 should use the default MAX_SCORE constant (36)."""
        score_with_default = compute_final_score(70, 18, 0)
        score_explicit     = compute_final_score(70, 18, 36)
        assert abs(score_with_default - score_explicit) < 0.01, (
            f"quiz_max=0 should default to MAX_SCORE=36. "
            f"Got {score_with_default} vs {score_explicit}"
        )


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# DIMENSION 4 â€” Code-level: Quiz scoring math
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

class TestQuizScoring:

    QUESTIONS = [
        {"id": "q1", "difficulty": "easy",   "skill_tag": "python", "correct_answer": 1},
        {"id": "q2", "difficulty": "medium", "skill_tag": "python", "correct_answer": 2},
        {"id": "q3", "difficulty": "hard",   "skill_tag": "sql",    "correct_answer": 3},
    ]
    # Max possible: easy=1, medium=2, hard=3 â†’ total = 6

    def test_all_correct(self):
        answers = {"q1": 1, "q2": 2, "q3": 3}
        score, _, _ = compute_quiz_score(self.QUESTIONS, answers)
        assert score == 6.0

    def test_all_wrong(self):
        answers = {"q1": 99, "q2": 99, "q3": 99}
        score, _, _ = compute_quiz_score(self.QUESTIONS, answers)
        assert score == 0.0

    def test_partial_correct_weights_applied(self):
        """Only easy (weight=1) answered correctly â†’ score == 1."""
        answers = {"q1": 1}
        score, _, _ = compute_quiz_score(self.QUESTIONS, answers)
        assert score == 1.0

    def test_skill_breakdown_pct_correct(self):
        """Python skill: q1(easy=1) + q2(medium=2) â†’ max=3. q1 only correct â†’ 33.33%"""
        answers = {"q1": 1}
        _, skill_bd, _ = compute_quiz_score(self.QUESTIONS, answers)
        assert skill_bd["python"]["max"] == 3
        assert skill_bd["python"]["score"] == 1
        assert abs(skill_bd["python"]["pct"] - 33.33) < 0.1


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# DIMENSION 5 â€” Code-level: Candidate tier detection
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

class TestCandidateTier:

    @pytest.mark.parametrize("years,expected_tier", [
        # Boundaries from scoring_service/schema fallback:
        # < TIER_FRESHER_MAX_YEARS fresher, < TIER_MID_MAX_YEARS mid, else senior
        (0, "fresher"),
        (0.5, "fresher"),
        (TIER_FRESHER_MAX_YEARS - 0.01, "fresher"),
        (TIER_FRESHER_MAX_YEARS, "mid"),
        (1, "mid"),
        (2, "mid"),
        (TIER_MID_MAX_YEARS - 0.01, "mid"),
        (TIER_MID_MAX_YEARS, "senior"),
        (5, "senior"),
        (20, "senior"),
    ])
    def test_tier_boundaries(self, years, expected_tier):
        tier = detect_candidate_tier(years)
        assert tier == expected_tier, (
            f"detect_candidate_tier({years}) = '{tier}', expected '{expected_tier}'"
        )



# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# DIMENSION 6 â€” Code-level: Tag assignment thresholds
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

class TestTagAssignment:

    @pytest.mark.parametrize("score,expected", [
        # CandidateTag enum uses title-case values: 'Strong', 'Medium', 'Reject'
        (STRONG_SHORTLIST_THRESHOLD, "Strong"),
        (80.0, "Strong"),
        (STRONG_SHORTLIST_THRESHOLD - 0.1, "Medium"),
        (DEFAULT_SHORTLIST_THRESHOLD, "Medium"),
        (DEFAULT_SHORTLIST_THRESHOLD - 0.1, "Reject"),
        (0.0,  "Reject"),
    ])
    def test_tag_thresholds(self, score, expected):
        tag = assign_tag(score)
        assert tag.value == expected, (
            f"assign_tag({score}) = '{tag.value}', expected '{expected}'"
        )


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# DIMENSION 7 â€” Code-level: AI override score sanity
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

class TestAIOverrideScore:

    BASE_ARGS = dict(
        education_pct=70.0,
        vector_sim=0.7,
        location_pct=80.0,
        experience_years=5.0,
        rule_skill_pct=60.0,
        rule_exp_pct=55.0,
        rule_proj_pct=50.0,
    )

    def test_strong_no_hire_caps_at_32(self):
        ai = {"skill_score": 90, "experience_score": 90, "project_score": 90,
              "hire_recommendation": "strong_no_hire", "red_flags": []}
        score, _, _, _ = compute_resume_score_with_ai_override(ai, **self.BASE_ARGS)
        assert score <= 32.0, f"strong_no_hire should cap at 32, got {score}"

    def test_strong_hire_gives_bonus(self):
        ai_base = {"skill_score": 80, "experience_score": 80, "project_score": 80,
                   "hire_recommendation": "maybe", "red_flags": []}
        ai_strong = {**ai_base, "hire_recommendation": "strong_hire"}
        s_base,  _, _, _ = compute_resume_score_with_ai_override(ai_base, **self.BASE_ARGS)
        s_bonus, _, _, _ = compute_resume_score_with_ai_override(ai_strong, **self.BASE_ARGS)
        assert s_bonus > s_base, "strong_hire should give a score bonus"

    def test_different_domain_caps_skill_score(self):
        ai = {"skill_score": 90, "experience_score": 90, "project_score": 90,
              "domain_fit": "different", "hire_recommendation": "maybe", "red_flags": []}
        score, used_skill, _, _ = compute_resume_score_with_ai_override(ai, **self.BASE_ARGS)
        assert used_skill <= 38.0, (
            f"domain_fit=different should cap skill_pct at 38, got {used_skill}"
        )

    def test_two_red_flags_penalise_score(self):
        ai_clean = {"skill_score": 75, "experience_score": 75, "project_score": 75,
                    "hire_recommendation": "maybe", "red_flags": []}
        ai_flags = {**ai_clean, "red_flags": ["short tenure", "unexplained gap"]}
        s_clean, _, _, _ = compute_resume_score_with_ai_override(ai_clean, **self.BASE_ARGS)
        s_flags, _, _, _ = compute_resume_score_with_ai_override(ai_flags, **self.BASE_ARGS)
        assert s_flags < s_clean, "2 red flags should penalise the final score"

    def test_fallback_when_ai_scores_missing(self):
        """When ai_scores is None, rule-based fallback must work and return valid range."""
        score, _, _, _ = compute_resume_score_with_ai_override(None, **self.BASE_ARGS)
        assert 0.0 <= score <= 100.0
