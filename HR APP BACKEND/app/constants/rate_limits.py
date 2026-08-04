"""Shared API rate-limit buckets."""

# File upload endpoints processing one file payload.
SINGLE_FILE_UPLOAD_RATE_LIMIT = "20/minute"

# High-cost bulk operations (bulk upload/archive/restore/delete).
BULK_UPLOAD_RATE_LIMIT = "5/minute"

# AI scoring/ranking operations outside harness endpoints.
AI_SCORING_RANKING_RATE_LIMIT = "10/minute"

# Harness/evaluation endpoints.
HARNESS_EVAL_RATE_LIMIT = "30/minute"

