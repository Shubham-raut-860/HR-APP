from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import threading
import time
from typing import Any


@dataclass
class _ReqRecord:
    ts: float
    method: str
    path: str
    status: int
    duration_ms: float
    request_id: str
    run_id: str
    error_type: str


_MAX_RECORDS = 5000
_REQS: deque[_ReqRecord] = deque(maxlen=_MAX_RECORDS)
_LOCK = threading.Lock()


def record_request(
    method: str,
    path: str,
    status: int,
    duration_ms: float,
    request_id: str | None = None,
    run_id: str | None = None,
    error_type: str | None = None,
) -> None:
    with _LOCK:
        _REQS.append(
            _ReqRecord(
                ts=time.time(),
                method=str(method or "").upper(),
                path=str(path or ""),
                status=int(status),
                duration_ms=float(duration_ms),
                request_id=str(request_id or ""),
                run_id=str(run_id or ""),
                error_type=str(error_type or ""),
            )
        )


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int(round((len(ordered) - 1) * pct))
    idx = max(0, min(len(ordered) - 1, idx))
    return float(ordered[idx])


def snapshot(window_seconds: int = 900) -> dict[str, Any]:
    now = time.time()
    with _LOCK:
        rows = [r for r in _REQS if (now - r.ts) <= max(1, int(window_seconds))]

    total = len(rows)
    if total == 0:
        return {
            "window_seconds": int(window_seconds),
            "requests_total": 0,
            "request_count": 0,
            "errors_5xx": 0,
            "error_5xx_count": 0,
            "error_rate_pct": 0.0,
            "error_rate_5xx": 0.0,
            "latency_ms": {"p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0},
            "latency_p95_ms": 0.0,
            "hot_paths": [],
            "timeout_like_count": 0,
            "timeout_like_rate_pct": 0.0,
            "error_types": [],
            "recent_failures": [],
            "slowest_requests": [],
        }

    errors_5xx = sum(1 for r in rows if int(r.status) >= 500)
    timeout_like_count = sum(
        1
        for r in rows
        if int(r.status) in {408, 504}
        or str(r.error_type).lower().endswith("timeout")
        or "timeout" in str(r.error_type).lower()
    )
    durations = [float(r.duration_ms) for r in rows]

    path_counts: dict[str, int] = {}
    for r in rows:
        key = f"{r.method} {r.path}"
        path_counts[key] = int(path_counts.get(key, 0)) + 1
    hot_paths = sorted(path_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]

    error_type_counts: dict[str, int] = {}
    for r in rows:
        if int(r.status) < 500 and not r.error_type:
            continue
        et = r.error_type or f"http_{int(r.status)}"
        error_type_counts[et] = int(error_type_counts.get(et, 0)) + 1
    top_error_types = sorted(error_type_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]

    failed_rows = sorted(
        (r for r in rows if int(r.status) >= 500 or r.error_type),
        key=lambda r: r.ts,
        reverse=True,
    )[:20]
    recent_failures = [
        {
            "ts": round(r.ts, 3),
            "age_sec": round(now - r.ts, 3),
            "method": r.method,
            "path": r.path,
            "status": int(r.status),
            "duration_ms": round(float(r.duration_ms), 2),
            "request_id": r.request_id or None,
            "run_id": r.run_id or None,
            "error_type": r.error_type or None,
        }
        for r in failed_rows
    ]

    slowest = sorted(rows, key=lambda r: float(r.duration_ms), reverse=True)[:10]
    slowest_requests = [
        {
            "method": r.method,
            "path": r.path,
            "status": int(r.status),
            "duration_ms": round(float(r.duration_ms), 2),
            "request_id": r.request_id or None,
            "run_id": r.run_id or None,
        }
        for r in slowest
    ]

    return {
        "window_seconds": int(window_seconds),
        "requests_total": total,
        "request_count": total,
        "errors_5xx": errors_5xx,
        "error_5xx_count": errors_5xx,
        "error_rate_pct": round((errors_5xx / total) * 100.0, 2),
        "error_rate_5xx": round((errors_5xx / total) * 100.0, 2),
        "timeout_like_count": timeout_like_count,
        "timeout_like_rate_pct": round((timeout_like_count / total) * 100.0, 2),
        "latency_ms": {
            "p50": round(_percentile(durations, 0.50), 2),
            "p95": round(_percentile(durations, 0.95), 2),
            "p99": round(_percentile(durations, 0.99), 2),
            "max": round(max(durations), 2),
        },
        "latency_p95_ms": round(_percentile(durations, 0.95), 2),
        "hot_paths": [{"route": route, "count": count} for route, count in hot_paths],
        "error_types": [{"type": et, "count": count} for et, count in top_error_types],
        "recent_failures": recent_failures,
        "slowest_requests": slowest_requests,
    }


def alerts(window_seconds: int = 900) -> dict[str, Any]:
    data = snapshot(window_seconds=window_seconds)
    warns: list[str] = []
    if data["error_rate_pct"] >= 2.0:
        warns.append(
            f"5xx error rate is high ({data['error_rate_pct']}%) in the last {data['window_seconds']}s."
        )
    if data["latency_ms"]["p95"] >= 2000.0:
        warns.append(
            f"p95 latency is high ({data['latency_ms']['p95']}ms) in the last {data['window_seconds']}s."
        )
    if data["timeout_like_rate_pct"] >= 1.0:
        warns.append(
            f"timeout-like request rate is high ({data['timeout_like_rate_pct']}%) in the last {data['window_seconds']}s."
        )

    return {
        "status": "warn" if warns else "ok",
        "alerts": warns,
        "metrics": data,
    }
