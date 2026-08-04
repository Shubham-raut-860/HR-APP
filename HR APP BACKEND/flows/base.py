"""
flows/base.py — Metaflow local-dev bootstrap helper
====================================================

Call `configure_local_metaflow()` at the top of every flow script BEFORE
importing `metaflow`. This ensures Metaflow writes all state (run database,
artifacts, logs) under Backend/flows/.metaflow/ instead of the user-global
~/.metaflow/ directory.

Why this matters in dev:
  - Keeps all Metaflow state scoped to *this* project/virtualenv.
  - Makes `git clean -fd flows/.metaflow/` a reliable way to wipe state.
  - No changes needed when running multiple projects locally.

Production upgrade path:
  When PostgreSQL + S3 are available, replace the env vars here with the
  cloud-backed Metaflow profile (configured in ~/.metaflowconfig/<profile>)
  and set METAFLOW_PROFILE=<cloud-profile-name> in .env.
"""
from __future__ import annotations

import os
import sys
import json

# ─── Windows Compatibility Hack for Metaflow ──────────────────────────────────
# Metaflow's AWS/Sidecar plugins import `fcntl` and `os.O_NONBLOCK`, which are
# Unix-only. We mock them here so Metaflow can run natively on Windows devs.
if sys.platform == "win32":
    if not hasattr(os, "O_NONBLOCK"):
        os.O_NONBLOCK = 0
    if "fcntl" not in sys.modules:
        import types
        _fcntl = types.ModuleType("fcntl")
        _fcntl.F_GETFL = 0
        _fcntl.F_SETFL = 0
        _fcntl.fcntl = lambda fd, cmd, arg=0: 0
        sys.modules["fcntl"] = _fcntl


def configure_local_metaflow() -> None:
    """Set Metaflow environment variables for local-filesystem-only operation.

    Must be called before `import metaflow` so the Metaflow client picks up
    the correct profile and home directory.
    """
    # Resolve the .metaflow/ directory relative to THIS file so it always
    # lands inside Backend/flows/.metaflow/, regardless of where the flow
    # script is invoked from.
    _flows_dir = os.path.dirname(os.path.abspath(__file__))
    _metaflow_home = os.path.join(_flows_dir, ".metaflow")

    os.makedirs(_metaflow_home, exist_ok=True)
    
    config_file = os.path.join(_metaflow_home, "config_local.json")
    if not os.path.exists(config_file):
        with open(config_file, "w") as f:
            json.dump({}, f)

    # METAFLOW_HOME controls where the local run DB and artifact blobs live.
    os.environ.setdefault("METAFLOW_HOME", _metaflow_home)

    # METAFLOW_PROFILE selects the named config in METAFLOW_HOME/config_<profile>.json.
    # "local" is Metaflow's built-in no-cloud profile.
    os.environ.setdefault("METAFLOW_PROFILE", "local")


def ensure_backend_on_path() -> None:
    """Add the Backend/ root to sys.path so `from app.* import ...` works
    inside Metaflow step subprocesses, which start with a minimal sys.path.

    Call this at the top of each flow script after configure_local_metaflow().
    """
    _backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _backend_root not in sys.path:
        sys.path.insert(0, _backend_root)
