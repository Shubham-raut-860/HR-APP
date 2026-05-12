from slowapi import Limiter
from starlette.requests import Request
import os

# PERF FIX: compute trusted_proxies ONCE at import time, not on every request.
# The previous implementation did a settings import, string split, and set()
# allocation inside _get_real_ip(), which runs on every single HTTP request.
# Sentinel for requests with no client connection info (WebSocket upgrades,
# lifespan events, health-check probes). Using a clearly-invalid IP ensures
# these never collide with real user rate-limit buckets.
_NO_CLIENT_SENTINEL = "__no_client__"

try:
    from app.config import settings as _settings
    _TRUSTED_PROXIES: frozenset[str] = frozenset(
        ip.strip()
        for ip in (getattr(_settings, "TRUSTED_PROXY_IPS", "") or "").split(",")
        if ip.strip()
    )
    # Number of trusted proxies between the client and this app.
    # Controls which entry in X-Forwarded-For is treated as the real client IP.
    #   1 (default) → Client ─► Proxy ─► App   →  xff[-1] is the real IP
    #   2            → Client ─► CDN ─► LB ─► App  →  xff[-2] is the real IP
    # FOLLOW-UP: add PROXY_DEPTH: int = 1  to app/config.py Settings class.
    _PROXY_DEPTH: int = max(1, int(getattr(_settings, "PROXY_DEPTH", 1)))
    _REDIS_URL: str = (getattr(_settings, "REDIS_URL", "") or "").strip()
    if not _REDIS_URL:
        _REDIS_URL = (os.getenv("REDIS_URL", "") or "").strip()
except Exception:
    _TRUSTED_PROXIES = frozenset()
    _PROXY_DEPTH = 1
    _REDIS_URL = (os.getenv("REDIS_URL", "") or "").strip()


def _get_real_ip(request: Request) -> str:
    """
    Return the true client IP, even when the app runs behind a reverse proxy.

    Only reads X-Forwarded-For / X-Real-IP when the direct connection comes from
    a known trusted proxy IP (set via TRUSTED_PROXY_IPS env var). This prevents
    clients from spoofing headers to bypass rate limits.

    X-Forwarded-For selection uses PROXY_DEPTH to pick the correct entry
    from the right side of the header, avoiding the leftmost entry which
    is attacker-controllable in multi-proxy chains.
    """
    direct_ip: str = (
        request.client.host if request.client else _NO_CLIENT_SENTINEL
    )

    if direct_ip in _TRUSTED_PROXIES:
        xff = request.headers.get("X-Forwarded-For")
        if xff:
            parts = [p.strip() for p in xff.split(",") if p.strip()]
            # Security hardening: never trust XFF chains shorter than the configured
            # proxy depth. Falling back to direct_ip prevents attacker-controlled
            # short headers from bypassing rate limiting under misconfiguration.
            if len(parts) < _PROXY_DEPTH:
                return direct_ip
            # Pick the entry added by the outermost trusted proxy.
            # Index from the right: depth=1 → parts[-1], depth=2 → parts[-2].
            # At this point we have already verified len(parts) >= _PROXY_DEPTH.
            return parts[-_PROXY_DEPTH]
        x_real = request.headers.get("X-Real-IP")
        if x_real:
            return x_real.strip()

    return direct_ip


if _REDIS_URL:
    limiter = Limiter(key_func=_get_real_ip, storage_uri=_REDIS_URL)
else:
    limiter = Limiter(key_func=_get_real_ip)
    # WARNING: in-memory only - not safe for multi-instance deployments
