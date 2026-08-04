"""Regression tests for config security and validation hardening (BUG-09..13)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings


def _base_settings_kwargs() -> dict[str, object]:
    """Provide safe defaults for deterministic Settings() construction in tests."""
    return {
        "APP_ENV": "development",
        "SECRET_KEY": "K9zP2L1m4N8q7R3s6T5u0V1w2X3y4Z5a6B7c8D9e",
        "ENCRYPTION_KEY": "M4n7Q2r8S1t6U3v9W5x0Y2z4A6b8C1d3E5f7G9h",
        "AZURE_OPENAI_API_KEY": "azk_9f2A7cB1K3mQ8zX4pR6v",
        "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com",
        "DATABASE_URL": "postgresql+asyncpg://user:[email-redacted]:5432/hrdb",
        "CORS_ORIGINS": "https://app.example.com",
        "SMTP_USERNAME": "mailer",
        "SMTP_PASSWORD": "mailer-password",
    }


def _build_settings(**overrides: object) -> Settings:
    payload = _base_settings_kwargs()
    payload.update(overrides)
    return Settings(_env_file=None, **payload)


@pytest.mark.parametrize(
    ("app_env", "expected"),
    [
        ("Production", True),
        ("PRODUCTION", True),
        ("production", True),
        ("staging", False),
    ],
)
def test_is_production(app_env: str, expected: bool) -> None:
    cfg = _build_settings(APP_ENV=app_env)
    assert cfg.is_production is expected


def test_cors_json_array() -> None:
    cfg = _build_settings(CORS_ORIGINS='["https://a.com","https://b.com"]')
    assert cfg.cors_origins_list == ["https://a.com", "https://b.com"]


def test_cors_csv() -> None:
    cfg = _build_settings(CORS_ORIGINS="https://a.com, https://b.com")
    assert cfg.cors_origins_list == ["https://a.com", "https://b.com"]


def test_frontend_url_defaults_to_active_local_frontend() -> None:
    cfg = _build_settings()
    assert cfg.FRONTEND_URL == "http://127.0.0.1:3000"


@pytest.mark.parametrize("frontend_url", ["", "   ", "localhost:3000", "not-a-url"])
def test_frontend_url_must_be_absolute_http_url(frontend_url: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _build_settings(FRONTEND_URL=frontend_url)

    assert "FRONTEND_URL" in str(exc_info.value)


def test_frontend_url_is_normalized_without_trailing_slash() -> None:
    cfg = _build_settings(FRONTEND_URL="http://127.0.0.1:3000/")
    assert cfg.FRONTEND_URL == "http://127.0.0.1:3000"


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("ACCESS_TOKEN_EXPIRE_MINUTES", 0),
        ("ACCESS_TOKEN_EXPIRE_MINUTES", -5),
        ("REFRESH_TOKEN_EXPIRE_DAYS", 0),
        ("REFRESH_TOKEN_EXPIRE_DAYS", -3),
    ],
)
def test_token_expiry_validation(field_name: str, value: int) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _build_settings(**{field_name: value})

    assert field_name in str(exc_info.value)


@pytest.mark.parametrize("placeholder", ["changeme", "dummy", "example", "sample", "test"])
def test_placeholder_detection_rejects_in_production(placeholder: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _build_settings(APP_ENV="production", ENCRYPTION_KEY=placeholder)

    message = str(exc_info.value)
    assert "ENCRYPTION_KEY appears to be a placeholder secret." in message


def test_vite_alias_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VITE_LYZR_API_KEY", "frontend-only-key")
    monkeypatch.delenv("LYZR_API_KEY", raising=False)

    cfg = Settings(_env_file=None, **_base_settings_kwargs())
    assert cfg.LYZR_API_KEY == ""
