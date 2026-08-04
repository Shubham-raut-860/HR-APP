"""Shared scoring thresholds and tier boundary constants.

Centralized here to prevent drift across services, routers, schemas, and tests.
"""

# Shortlisting / tagging thresholds
HIGH_THRESHOLD = 75.0
MEDIUM_THRESHOLD = 55.0
LOW_THRESHOLD = MEDIUM_THRESHOLD
DEFAULT_SHORTLIST_THRESHOLD = MEDIUM_THRESHOLD
SCORING_PASS_THRESHOLD = MEDIUM_THRESHOLD
STRONG_SHORTLIST_THRESHOLD = HIGH_THRESHOLD

# Shared neutral baseline used when a rubric dimension is unknown / not provided.
NEUTRAL_MATCH_SCORE = 50.0

# Fast parser clamp for unrealistic resume-extracted experience values.
MAX_RESUME_EXPERIENCE_YEARS = 50.0

# Candidate tier boundaries
TIER_FRESHER_MAX_YEARS = 0.75
TIER_MID_MAX_YEARS = 2.75


def candidate_tier_from_years(experience_years: float) -> str:
    """Shared tier classification helper used across schemas and scoring."""
    try:
        years = float(experience_years)
    except (TypeError, ValueError):
        years = 0.0
    if years < TIER_FRESHER_MAX_YEARS:
        return "fresher"
    if years < TIER_MID_MAX_YEARS:
        return "mid"
    return "senior"

# Smooth weight interpolation boundaries
TIER_BLEND_MID_END_YEARS = 3.0
TIER_BLEND_SENIOR_START_YEARS = 3.5
TIER_BLEND_SENIOR_END_YEARS = 7.5

# Schema defaults / validation tolerances
JD_DEFAULT_PASS_THRESHOLD = 60
SHORTLIST_WEIGHT_SUM_TOLERANCE_MIN = 0.95
SHORTLIST_WEIGHT_SUM_TOLERANCE_MAX = 1.05

# Quiz submission payload guardrail.
# Requests with >200 answer entries are rejected at schema level.
MAX_QUIZ_QUESTIONS = 200
