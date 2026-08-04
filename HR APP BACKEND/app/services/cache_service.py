"""
Semantic Caching Service
Caches LLM generations to save time and API costs.

NOTE: This is an in-memory cache per-process. With multiple uvicorn workers
(production), each worker has its own independent cache. Upgrade to a Redis
vector store before running with workers > 1.
"""
import time
from typing import Optional
from collections import deque
from app.services.scoring_service import cosine_similarity

MAX_CACHE_SIZE = 500
JD_CACHE_TTL_SECONDS = 3600  # 1 hour TTL
_jd_cache: deque = deque(maxlen=MAX_CACHE_SIZE)


def _evict_expired() -> None:
    """Remove TTL-expired entries in O(n) via a single-pass filter.

    The previous approach called deque.remove(item) inside a for-loop over a
    list() copy, making TTL eviction O(n²) — deque.remove() scans from the
    head each time. On a 500-entry cache this is 125,000 comparisons per
    request. The new approach rebuilds the deque in a single pass: O(n).
    """
    now = time.time()
    fresh = [item for item in _jd_cache if now <= item["expires_at"]]
    _jd_cache.clear()
    _jd_cache.extend(fresh)


def get_cached_jd(query_embedding: list[float], threshold: float = 0.95) -> Optional[dict]:
    """Find a semantically identical JD in the cache."""
    _evict_expired()

    best_score = 0.0
    best_match = None

    for item in _jd_cache:
        try:
            score = cosine_similarity(query_embedding, item["embedding"])
        except ValueError:
            # Ignore cache entries that were embedded with a different model dimension.
            continue
        if score > best_score:
            best_score = score
            best_match = item["data"]
            # Short-circuit: a perfect (1.0) match can't be beaten.
            if best_score >= 1.0:
                break

    if best_score >= threshold:
        return best_match
    return None


def cache_jd(embedding: list[float], data: dict) -> None:
    """Store generated JD in memory."""
    _jd_cache.append({
        "embedding": embedding,
        "data": data,
        "expires_at": time.time() + JD_CACHE_TTL_SECONDS,
    })
