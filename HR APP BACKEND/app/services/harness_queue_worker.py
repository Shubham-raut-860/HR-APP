from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import redis as sync_redis
from rq import Queue, SimpleWorker

from app.config import settings
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


def _configure_harness_env_defaults() -> None:
    """Align worker env with the mounted Harness runtime expectations."""
    redis_url = (settings.REDIS_URL or os.getenv("REDIS_URL") or "redis://127.0.0.1:6379/0").strip()
    if redis_url:
        os.environ.setdefault("REDIS_URL", redis_url)
        os.environ.setdefault("redis_url", redis_url)

    harness_secret = (settings.HARNESS_JWT_SECRET_KEY or settings.SECRET_KEY or "").strip()
    if harness_secret:
        os.environ.setdefault("JWT_SECRET_KEY", harness_secret)
        os.environ.setdefault("HARNESS_JWT_SECRET_KEY", harness_secret)
        os.environ.setdefault("jwt_secret_key", harness_secret)

    env_name = (settings.HARNESS_ENVIRONMENT or "dev").strip()
    if env_name:
        os.environ.setdefault("ENVIRONMENT", env_name)
        os.environ.setdefault("environment", env_name)

    if (settings.AZURE_OPENAI_API_KEY or "").strip():
        api_key = settings.AZURE_OPENAI_API_KEY.strip()
        os.environ.setdefault("OPENAI_API_KEY", api_key)
        os.environ.setdefault("AZURE_OPENAI_API_KEY", api_key)

    if (settings.AZURE_OPENAI_ENDPOINT or "").strip():
        endpoint = settings.AZURE_OPENAI_ENDPOINT.strip().rstrip("/")
        os.environ.setdefault("OPENAI_BASE_URL", f"{endpoint}/openai/v1/")
        os.environ.setdefault("AZURE_OPENAI_ENDPOINT", endpoint)

    if (settings.AZURE_OPENAI_API_VERSION or "").strip():
        os.environ.setdefault("AZURE_OPENAI_API_VERSION", settings.AZURE_OPENAI_API_VERSION.strip())

    if (settings.AZURE_CHAT_DEPLOYMENT or "").strip():
        deployment = settings.AZURE_CHAT_DEPLOYMENT.strip()
        os.environ.setdefault("OPENAI_MODELS", deployment)
        os.environ.setdefault("AZURE_OPENAI_DEPLOYMENT", deployment)

    # On Windows local runs, Harness may default to "/workspaces", which is
    # not writable and causes queued jobs to fail after dequeue.
    if os.name == "nt":
        workspace_base = str(Path(__file__).resolve().parents[2] / "workspaces")
        os.environ.setdefault("WORKSPACE_BASE_PATH", workspace_base)
        os.environ.setdefault("workspace_base_path", workspace_base)


def _ensure_harness_vendor_path() -> Path:
    vendor_src = Path(__file__).resolve().parents[2] / "vendor" / "HarnessAgent-main" / "src"
    if vendor_src.exists():
        vendor_src_str = str(vendor_src)
        if vendor_src_str not in sys.path:
            sys.path.insert(0, vendor_src_str)
    return vendor_src


def main() -> None:
    configure_logging(settings.APP_ENV)
    _configure_harness_env_defaults()
    vendor_src = _ensure_harness_vendor_path()
    if not vendor_src.exists():
        raise RuntimeError(f"Vendored HarnessAgent path missing: {vendor_src}")

    from app.agents.harness_plugins import HR_AGENT_TYPES, _HR_AGENT_FACTORY
    from harness.workers.agent_worker import register_agent, start_worker

    # Register Jobora-specific harness agent implementations for worker jobs.
    for agent_type, agent_cls in _HR_AGENT_FACTORY.items():
        register_agent(agent_type, agent_cls)

    base_queues = ["default", "agent", "sql", "code"]
    extra_hr_queues = sorted(q for q in HR_AGENT_TYPES if q not in base_queues)
    worker_queues = [*base_queues, *extra_hr_queues]
    redis_url = settings.REDIS_URL or os.getenv("REDIS_URL") or "redis://127.0.0.1:6379/0"

    logger.info(
        "Starting harness queue worker (redis=%s, queues=%s)",
        redis_url,
        ",".join(worker_queues),
    )

    # RQ's default Worker uses os.fork(), which is unavailable on Windows.
    # Keep Linux/macOS behavior unchanged by delegating to Harness start_worker.
    if os.name == "nt":
        conn = sync_redis.from_url(redis_url, decode_responses=False)
        queue_objects = [Queue(q, connection=conn) for q in worker_queues]
        logger.info("Windows detected; starting RQ SimpleWorker (non-forking mode)")
        worker = SimpleWorker(queue_objects, connection=conn)
        worker.work(with_scheduler=True)
        return

    start_worker(queues=worker_queues, redis_url=redis_url)


if __name__ == "__main__":
    main()
