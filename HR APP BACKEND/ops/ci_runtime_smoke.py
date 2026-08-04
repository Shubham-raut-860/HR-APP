"""
Minimal runtime smoke for CI release gate.

Validates that a fresh backend process can:
1) start and report healthy
2) register/login an HR user
3) create a JD row
4) fetch ops runtime alerts with HR auth
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "HR APP BACKEND"
BASE_URL = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000")
PASSWORD = os.getenv("SMOKE_PASSWORD", "Qa!Pass2026A")


def _request(method: str, path: str, *, timeout: float = 15.0, **kwargs: Any) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        res = requests.request(method, f"{BASE_URL}{path}", timeout=timeout, **kwargs)
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        payload: Any
        try:
            payload = res.json()
        except Exception:
            payload = {"raw": (res.text or "")[:500]}
        return {
            "ok": res.ok,
            "status": int(res.status_code),
            "elapsed_ms": elapsed_ms,
            "payload": payload,
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "error": repr(exc),
        }


def _wait_for_ready(timeout_s: float = 240.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {"ok": False, "detail": "not_started"}
    while time.time() < deadline:
        last = _request("GET", "/health", timeout=3.0)
        if last.get("status") == 200:
            payload = last.get("payload") or {}
            if isinstance(payload, dict) and payload.get("startup_complete") is True:
                return last
        time.sleep(1.0)
    return last


def _start_backend() -> subprocess.Popen[str]:
    env = os.environ.copy()
    env.setdefault("APP_ENV", "development")
    env.setdefault("HARNESS_MOUNT_ENABLED", "true")
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=str(BACKEND_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def _stop_backend(proc: subprocess.Popen[str] | None) -> None:
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=20)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def main() -> int:
    report: dict[str, Any] = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_url": BASE_URL,
        "checks": {},
        "pass": False,
    }
    proc: subprocess.Popen[str] | None = None

    try:
        proc = _start_backend()
        ready = _wait_for_ready()
        report["checks"]["health_ready"] = ready
        if ready.get("status") != 200:
            print(json.dumps(report, indent=2))
            return 1

        seed = int(time.time())
        email = f"ci.smoke.hr.{seed}@example.com"

        reg = _request(
            "POST",
            "/auth/register",
            json={
                "full_name": f"CI Smoke HR {seed}",
                "email": email,
                "password": PASSWORD,
                "role": "hr",
            },
            timeout=20.0,
        )
        report["checks"]["register_hr"] = reg
        if reg.get("status") not in (201, 409):
            print(json.dumps(report, indent=2))
            return 1

        login = _request(
            "POST",
            "/auth/login",
            json={"email": email, "password": PASSWORD},
            timeout=20.0,
        )
        report["checks"]["login_hr"] = login
        token = ((login.get("payload") or {}) if isinstance(login.get("payload"), dict) else {}).get("access_token")
        if login.get("status") != 200 or not token:
            print(json.dumps(report, indent=2))
            return 1

        jd = _request(
            "POST",
            "/jd/",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "title": f"CI Smoke JD {seed}",
                "role": "Backend Engineer",
                "location": "Remote",
                "employment_type": "Full-time",
                "experience_min": 2,
                "experience_max": 6,
                "must_have_skills": ["Python", "FastAPI", "SQL"],
                "good_to_have_skills": ["Redis"],
                "description": "CI runtime smoke JD",
                "resume_weight": 60,
                "quiz_weight": 40,
                "pass_threshold": 65,
            },
            timeout=25.0,
        )
        report["checks"]["jd_create"] = jd
        if jd.get("status") not in (200, 201):
            print(json.dumps(report, indent=2))
            return 1

        ops = _request(
            "GET",
            "/ops/runtime-alerts",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
        )
        report["checks"]["ops_runtime_alerts"] = ops
        if ops.get("status") != 200:
            print(json.dumps(report, indent=2))
            return 1

        report["pass"] = True
        print(json.dumps(report, indent=2))
        return 0
    finally:
        _stop_backend(proc)


if __name__ == "__main__":
    raise SystemExit(main())

