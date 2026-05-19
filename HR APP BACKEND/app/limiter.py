from __future__ import annotations

import logging
import os
import socket
from urllib.parse import urlparse

from fastapi import HTTPException
from slowapi import Limiter
from starlette.requests import Request

logger = logging.getLogger(__name__)

_NO_CLIENT_SENTINEL = "__no_client__"
_FALLBACK_WARN_EVERY = 250
_fallback_request_counter = 0


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


try:
    from app.config import settings as _settings

    _TRUSTED_PROXIES: frozenset[str] = frozenset(
        ip.strip()
        for ip in (getattr(_settings, "TRUSTED_PROXY_IPS", "") or "").split(",")
        if ip.strip()
    )
    _FORWARDED_ALLOW_IPS: str = (
        getattr(_settings, "FORWARDED_ALLOW_IPS", "") or ""
    ).strip()
    _PROXY_DEPTH: int = max(1, int(getattr(_settings, "PROXY_DEPTH", 1)))
    _REDIS_URL: str = (getattr(_settings, "REDIS_URL", "") or "").strip()
    _STRICT_MODE: bool = bool(getattr(_settings, "LIMITER_STRICT_MODE", False))
    _IS_PRODUCTION: bool = bool(getattr(_settings, "is_production", False))
except Exception:
    _TRUSTED_PROXIES = frozenset(
        ip.strip() for ip in (os.getenv("TRUSTED_PROXY_IPS", "") or "").split(",") if ip.strip()
    )
    _FORWARDED_ALLOW_IPS = (os.getenv("FORWARDED_ALLOW_IPS") or "").strip()
    _PROXY_DEPTH = 1
    _REDIS_URL = (os.getenv("REDIS_URL", "") or "").strip()
    _STRICT_MODE = _env_bool("LIMITER_STRICT_MODE", default=False)
    _IS_PRODUCTION = (os.getenv("APP_ENV", "").strip().lower() == "production")


def _proxy_headers_expected() -> bool:
    raw = (_FORWARDED_ALLOW_IPS or "").strip()
    if not raw:
        return False
    normalized = {part.strip().lower() for part in raw.split(",") if part.strip()}
    if not normalized:
        return False
    if normalized == {"none"}:
        return False
    return True


def validate_limiter_runtime_config() -> None:
    """Validate proxy trust settings for safe rate-limit key derivation."""
    if _proxy_headers_expected() and not _TRUSTED_PROXIES:
        message = (
            "TRUSTED_PROXY_IPS is empty while FORWARDED_ALLOW_IPS indicates reverse-proxy deployment. "
            "Client IP derivation will collapse to proxy IP and break fair rate limiting."
        )
        logger.warning(message)
        if _IS_PRODUCTION:
            raise RuntimeError(message)


def _get_real_ip(request: Request) -> str:
    """Return the effective client IP for rate-limit bucketing."""
    direct_ip: str = request.client.host if request.client else _NO_CLIENT_SENTINEL

    if direct_ip in _TRUSTED_PROXIES:
        xff = request.headers.get("X-Forwarded-For")
        if xff:
            parts = [p.strip() for p in xff.split(",") if p.strip()]
            if len(parts) >= _PROXY_DEPTH:
                return parts[-_PROXY_DEPTH]
            return direct_ip

        x_real = request.headers.get("X-Real-IP")
        if x_real:
            return x_real.strip()

    return direct_ip


_LIMITER_BACKEND_DEGRADED = False
_LIMITER_BACKEND_REASON: str | None = None


def _build_limiter() -> Limiter:
    global _LIMITER_BACKEND_DEGRADED
    global _LIMITER_BACKEND_REASON

    if not _REDIS_URL:
        _LIMITER_BACKEND_DEGRADED = True
        _LIMITER_BACKEND_REASON = "REDIS_URL is not configured"
        if _STRICT_MODE:
            logger.error(
                "Rate limiter strict mode is active but Redis is unavailable (%s). "
                "Requests will fail with 503 until Redis is restored.",
                _LIMITER_BACKEND_REASON,
            )
        else:
            logger.info(
                "Rate limiter using in-memory fallback (%s).",
                _LIMITER_BACKEND_REASON,
            )
        return Limiter(key_func=_get_real_ip)

    use_redis = True
    try:
        parsed = urlparse(_REDIS_URL)
        redis_host = parsed.hostname
        redis_port = int(parsed.port or 6379)
        if redis_host:
            with socket.create_connection((redis_host, redis_port), timeout=0.5):
                pass
        else:
            use_redis = False
    except Exception:
        use_redis = False

    if use_redis:
        _LIMITER_BACKEND_DEGRADED = False
        _LIMITER_BACKEND_REASON = None
        return Limiter(key_func=_get_real_ip, storage_uri=_REDIS_URL)

    _LIMITER_BACKEND_DEGRADED = True
    _LIMITER_BACKEND_REASON = f"Redis storage unavailable at {_REDIS_URL}"
    if _STRICT_MODE:
        logger.error(
            "Rate limiter strict mode is active but Redis is unavailable (%s). "
            "Requests will fail with 503 until Redis is restored.",
            _LIMITER_BACKEND_REASON,
        )
    else:
        logger.info(
            "Rate limiter using in-memory fallback (%s).",
            _LIMITER_BACKEND_REASON,
        )
    return Limiter(key_func=_get_real_ip)


limiter = _build_limiter()


def enforce_limiter_backend_or_503(request: Request) -> None:
    """Fail closed in strict mode and emit periodic warnings in fallback mode."""
    global _fallback_request_counter

    if not _LIMITER_BACKEND_DEGRADED:
        return

    if _STRICT_MODE:
        raise HTTPException(
            status_code=503,
            detail="Rate limiter backend unavailable. Please retry shortly.",
            headers={"Retry-After": "60"},
        )

    _fallback_request_counter += 1
    if _fallback_request_counter % _FALLBACK_WARN_EVERY == 0:
        logger.debug(
            "Rate limiter fallback still active after %d requests. reason=%s",
            _fallback_request_counter,
            _LIMITER_BACKEND_REASON,
        )


def limiter_backend_state() -> dict[str, object]:
    return {
        "strict_mode": _STRICT_MODE,
        "backend_degraded": _LIMITER_BACKEND_DEGRADED,
        "reason": _LIMITER_BACKEND_REASON,
        "trusted_proxy_count": len(_TRUSTED_PROXIES),
    }
