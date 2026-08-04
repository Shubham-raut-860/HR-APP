"""Canonical password policy used across auth request paths."""

from __future__ import annotations

import re

MAX_BYTES = 72
MIN_CHARS = 8
PATTERN = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^\w\s]).{8,}$")


def validate_password(password: str) -> str:
    """Validate password policy and return the original value on success."""
    if len(password.encode("utf-8")) > MAX_BYTES:
        raise ValueError(f"Password must not exceed {MAX_BYTES} UTF-8 bytes")
    if len(password) < MIN_CHARS:
        raise ValueError(f"Password must be at least {MIN_CHARS} characters")
    if not PATTERN.match(password):
        raise ValueError(
            "Password must contain uppercase, lowercase, digit, and special character"
        )
    return password

