"""
HR Analytics & Smart Hiring Platform â€“ FastAPI Backend
Azure OpenAI powered | Port: 8000
"""
import time as _boot_time

_BOOT_T0 = _boot_time.perf_counter()


def _boot_mark(label: str, message: str) -> None:
    elapsed_ms = (_boot_time.perf_counter() - _BOOT_T0) * 1000.0
    epoch_ms = int(_boot_time.time() * 1000.0)
    print(
        f"[BOOT] {label} epoch_ms={epoch_ms} elapsed_ms={elapsed_ms:.3f} msg={message}",
        flush=True,
    )


_boot_mark("T0", "process start")

# BUG #10 FIX (HIGH): load_dotenv() MUST run before any local imports that call
# os.getenv() at module level. Previously it was called AFTER all local imports,
# meaning any module reading env vars at import-time got stale/None values.
from dotenv import load_dotenv
load_dotenv()
_boot_mark("T1", "after load_dotenv")
import os
from app.logging_config import configure_logging
configure_logging(os.getenv("APP_ENV", "development"))
_boot_mark("T3", "after configure_logging")

# â”€â”€â”€ Standard library â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
import logging
import traceback
import asyncio
import uuid
import sys
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote

# â”€â”€â”€ Third-party â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
import structlog
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.websockets import WebSocketDisconnect
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import inspect as sa_inspect, text
from structlog.contextvars import bind_contextvars, clear_contextvars

# â”€â”€â”€ Local application â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
from app.config import settings
_boot_mark("T4", "after settings loaded")
from app.limiter import (
    enforce_limiter_backend_or_503,
    limiter,
    limiter_backend_state,
    validate_limiter_runtime_config,
)
from app.routers import (
    auth, jd, resumes, quiz,
    analytics, admin, candidate_portal, notifications, agent,
    token_monitor,
)
from app.routers import settings_router
_boot_mark("T2", "after all imports complete")

# â”€â”€â”€ Logger â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
logger = logging.getLogger(__name__)
_FIRST_HEALTH_MARKED = False


def _env_flag_true(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _configure_harness_env_defaults() -> None:
    """
    Configure env vars expected by the vendored HarnessAgent runtime.
    This must run before importing harness modules.
    """
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

    # Optional OpenAI compatibility for harness internals.
    # Set both generic OpenAI and Azure-specific keys so vendored HarnessAgent
    # can resolve whichever provider wiring is enabled.
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


def _add_vendored_harness_to_syspath() -> Path:
    vendor_src = Path(__file__).resolve().parents[1] / "vendor" / "HarnessAgent-main" / "src"
    if vendor_src.exists():
        vendor_src_str = str(vendor_src)
        if vendor_src_str not in sys.path:
            sys.path.insert(0, vendor_src_str)
    return vendor_src


def _mount_original_harness_app(app: FastAPI) -> None:
    if not settings.HARNESS_MOUNT_ENABLED:
        logger.info("Harness mount disabled by config (HARNESS_MOUNT_ENABLED=false).")
        return

    try:
        vendor_src = _add_vendored_harness_to_syspath()
        if not vendor_src.exists():
            raise RuntimeError(f"Vendored HarnessAgent path missing: {vendor_src}")

        # Override harness auth deps before app/router creation.
        from app.services.harness_auth_bridge import (
            harness_get_current_tenant,
            harness_get_current_user,
        )
        from harness.api import deps as harness_deps

        from app.agents.harness_plugins import HR_AGENT_TYPES
        from harness.api.routes import runs as harness_runs
        from harness.api.main import create_app as create_harness_app

        allowed_agent_types = getattr(harness_runs, "_ALLOWED_AGENT_TYPES", None)
        if isinstance(allowed_agent_types, set):
            allowed_agent_types.update(HR_AGENT_TYPES)
        else:
            logger.warning(
                "Harness runs allow-list was not mutable; HR agent types were not injected"
            )

        # Optional: register plugin classes for worker mode compatibility.
        try:
            from app.agents.harness_plugins import _HR_AGENT_FACTORY  # type: ignore[attr-defined]
            from harness.workers.agent_worker import register_agent

            for agent_type, cls in _HR_AGENT_FACTORY.items():
                register_agent(agent_type, cls)
        except Exception as reg_exc:
            logger.debug("Harness worker plugin registration skipped: %s", reg_exc)

        harness_app = create_harness_app()
        harness_app.dependency_overrides[harness_deps.get_current_tenant] = harness_get_current_tenant
        harness_app.dependency_overrides[harness_deps.get_current_user] = harness_get_current_user
        app.mount("/harness", harness_app)
        logger.info(
            "Mounted Pradip HarnessAgent at /harness with %d HR agent types",
            len(HR_AGENT_TYPES),
        )
    except Exception as exc:
        if settings.is_production:
            raise RuntimeError(f"Harness mount failed in production: {exc}") from exc
        logger.warning("Harness mount unavailable in %s mode: %s", settings.APP_ENV, exc)


def _run_startup_migrations() -> None:
    project_root = Path(__file__).resolve().parents[1]
    # Production deployments should run migrations as a pre-deploy step.
    # Startup migration fallback remains best-effort for non-production/local.
    alembic_env = os.environ.copy()
    alembic_env.setdefault("PGCONNECT_TIMEOUT", "5")
    cmd = [sys.executable, "-m", "alembic", "upgrade", "head"]
    completed = subprocess.run(
        cmd,
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=120,
        env=alembic_env,
    )
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(
            f"Alembic startup migration failed with exit code {completed.returncode}. {details}"
        )


def _resolve_runtime_sqlite_path(database_url: str) -> Path | None:
    lower = (database_url or "").strip().lower()
    if not lower.startswith("sqlite"):
        return None
    if ":///" not in database_url:
        return None
    raw_path = database_url.split(":///", 1)[1]
    decoded_path = unquote(raw_path).strip()
    if not decoded_path:
        return None
    candidate = Path(decoded_path)
    if candidate.is_absolute():
        return candidate.resolve()
    if decoded_path.startswith("./"):
        return (Path(__file__).resolve().parents[1] / decoded_path[2:]).resolve()
    return (Path(__file__).resolve().parents[1] / decoded_path).resolve()


def _warn_on_duplicate_local_sqlite_dbs(runtime_db: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    sqlite_files = sorted(
        [*project_root.glob("*.db"), *project_root.glob("*.sqlite")],
        key=lambda p: p.name.lower(),
    )
    duplicates = [p.resolve() for p in sqlite_files if p.resolve() != runtime_db.resolve()]
    if duplicates:
        logger.warning(
            "Detected multiple local SQLite files. Runtime DB=%s | Other DB files=%s",
            runtime_db,
            ", ".join(str(p) for p in duplicates),
        )


async def _assert_candidate_quiz_columns_present() -> None:
    from app.database import engine

    required = {"quiz_score", "quiz_max", "quiz_pct"}

    async with engine.connect() as conn:
        def _inspect_columns(sync_conn):
            inspector = sa_inspect(sync_conn)
            table_names = set(inspector.get_table_names())
            if "candidates" not in table_names:
                raise RuntimeError("Schema check failed: candidates table is missing.")
            candidate_columns = {
                c["name"] for c in inspector.get_columns("candidates")
            }
            missing = sorted(required - candidate_columns)
            return missing

        missing_columns = await conn.run_sync(_inspect_columns)

    if missing_columns:
        raise RuntimeError(
            "Schema check failed: candidates missing columns after migration: "
            + ", ".join(missing_columns)
        )


async def _run_startup_schema_guard() -> None:
    runtime_sqlite_path = _resolve_runtime_sqlite_path(settings.DATABASE_URL)
    if runtime_sqlite_path is not None:
        logger.info("Runtime SQLite database path: %s", runtime_sqlite_path)
        _warn_on_duplicate_local_sqlite_dbs(runtime_sqlite_path)

    _boot_mark("T5", "after Alembic migration check starts")
    skip_migrations_default = settings.is_production
    if settings.is_production and os.getenv("SKIP_STARTUP_MIGRATIONS") is None:
        logger.warning(
            "APP_ENV=production defaulting SKIP_STARTUP_MIGRATIONS=true. "
            "Run migrations separately as a pre-deploy job."
        )

    if _env_flag_true("SKIP_STARTUP_MIGRATIONS", default=skip_migrations_default):
        logger.warning("SKIP_STARTUP_MIGRATIONS=true - skipping automatic Alembic upgrade.")
    else:
        logger.info("Applying Alembic migrations to head at startup.")
        try:
            await asyncio.wait_for(asyncio.to_thread(_run_startup_migrations), timeout=8.0)
        except asyncio.TimeoutError:
            logger.warning(
                "Startup Alembic migration exceeded 8s timeout; continuing startup. "
                "Run migrations as a separate pre-deploy job."
            )
        except Exception as mig_exc:
            logger.warning(
                "Startup Alembic migration failed non-fatal: %s. "
                "Run migrations as a separate pre-deploy job.",
                mig_exc,
            )
    _boot_mark("T6", "after Alembic migration check completes")

    await _assert_candidate_quiz_columns_present()


async def _run_startup_database_health_checks() -> None:
    from app.database import _check_schema_drift, engine, verify_pgvector_registration

    async def _check_pgvector() -> None:
        try:
            # PostgreSQL must have pgvector driver registration + extension availability.
            await asyncio.wait_for(verify_pgvector_registration(engine), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("pgvector_registration_check_timed_out non_fatal=true")
        except Exception as exc:
            logger.warning("pgvector_registration_check_failed non_fatal=true error=%s", exc)
        finally:
            _boot_mark("T8", "after pgvector registration check")

    async def _check_drift() -> None:
        try:
            await asyncio.wait_for(_check_schema_drift(engine), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("schema_drift_check_timed_out non_fatal=true")
        except Exception as drift_err:
            logger.warning("schema_drift_check_failed non_fatal=true error=%s", drift_err)
        finally:
            _boot_mark("T9", "after schema drift check")

    await asyncio.gather(_check_pgvector(), _check_drift())


async def _run_mlflow_startup_init() -> None:
    # MLflow self-configures from env vars via mlflow_service.py.
    mlflow_env_uri = (os.environ.get("MLFLOW_TRACKING_URI") or "").strip()
    if mlflow_env_uri:
        try:
            # Hard timeout around the entire thread invocation.
            _mlflow_available = await asyncio.wait_for(
                asyncio.to_thread(
                    lambda: __import__("app.services.mlflow_service", fromlist=["_init_mlflow"])._init_mlflow()
                ),
                timeout=5.0,
            )
        except Exception as _e:
            logger.debug("Failed to initialize MLflow service: %s", _e)
            _mlflow_available = False
        if not _mlflow_available:
            logger.warning(
                "MLflow tracking server not reachable - set MLFLOW_TRACKING_URI in .env "
                "or start: mlflow server --host 127.0.0.1 --port 5000"
            )
    else:
        logger.info("MLflow init skipped: MLFLOW_TRACKING_URI is not explicitly set in environment.")
    _boot_mark("T10", "after MLflow init attempt")


async def _warm_database_pool_fast_path() -> None:
    try:
        from app.database import engine

        async def _ping_once() -> None:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

        await asyncio.wait_for(_ping_once(), timeout=2.0)
    except Exception as exc:
        logger.warning("startup_db_pool_warmup_non_fatal=true error=%s", exc)


def _mount_optional_eval_router(app: FastAPI) -> None:
    if not settings.EVALS_ENABLED:
        logger.info("Evals router disabled by config (EVALS_ENABLED=false).")
        return
    try:
        from app.routers import evals as evals_router
        app.include_router(evals_router.router)
    except Exception as exc:
        logger.warning("Evals router mount skipped non_fatal=true error=%s", exc)


def _mount_optional_metaflow_router(app: FastAPI) -> None:
    if not settings.ENABLE_METAFLOW:
        return
    try:
        from app.routers import flows_router as _flows_router
        app.include_router(_flows_router.router)
        logger.info("Metaflow batch scoring endpoint registered (/admin/flows/batch-score)")
    except ImportError as _e:
        logger.warning(
            "ENABLE_METAFLOW=True but Metaflow is not installed: %s. "
            "Run: pip install metaflow>=2.12", _e,
        )


async def _run_post_startup_init(app: FastAPI) -> None:
    try:
        await _run_startup_schema_guard()
        _boot_mark("T7", "after DB schema guard completes")
        await _run_startup_database_health_checks()

        try:
            recovered_jobs = await resumes.recover_stale_bulk_upload_jobs()
            if recovered_jobs:
                logger.warning("Recovered %d stale async bulk upload jobs at startup.", recovered_jobs)
        except Exception as recover_exc:
            logger.warning("bulk_job_recovery_failed non_fatal=true error=%s", recover_exc)
        _boot_mark("T11", "after bulk job recovery")

        await _run_mlflow_startup_init()

        try:
            _mount_original_harness_app(app)
        except Exception as mount_exc:
            logger.warning("harness_mount_background_failed non_fatal=true error=%s", mount_exc)

        _mount_optional_eval_router(app)
        _mount_optional_metaflow_router(app)
    except Exception as exc:
        app.state.startup_error = str(exc)
        logger.exception("background_startup_init_failed non_fatal=true error=%s", exc)
    finally:
        app.state.startup_complete = True
        app.state.startup_completed_at = time.time()
        structlog.get_logger(__name__).info(
            "startup_complete",
            app_env=settings.APP_ENV,
            version=app.version,
            host=settings.APP_HOST,
            port=settings.APP_PORT,
            docs_enabled=not settings.is_production,
            workers="gunicorn" if settings.is_production else "uvicorn-dev",
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # BUG #2 FIX (CRITICAL): Validate ENCRYPTION_KEY at startup, not at first
    # file-upload time. Without this, dev/staging with missing ENCRYPTION_KEY
    # starts fine but crashes with an unhandled RuntimeError on every upload.
    if not settings.ENCRYPTION_KEY or len(settings.ENCRYPTION_KEY) < 32:
        logger.error(
            "ENCRYPTION_KEY is missing or too short (< 32 chars). "
            "File uploads and resume downloads WILL FAIL. "
            "Set ENCRYPTION_KEY in your .env file."
        )
        if settings.is_production:
            raise RuntimeError(
                "ENCRYPTION_KEY must be at least 32 characters in production. "
                "Set it in your .env file."
            )

    # BUG-02 FIX: enforce supported embedding dimensions at startup.
    assert settings.EMBEDDING_DIM in (1536, 3072), (
        f"Unsupported EMBEDDING_DIM={settings.EMBEDDING_DIM}. Expected 1536 or 3072."
    )

    # Validate proxy trust configuration for safe limiter client IP derivation.
    validate_limiter_runtime_config()

    # Fast path startup: bring app online quickly.
    app.state.startup_complete = False
    app.state.startup_started_at = time.time()
    app.state.startup_task = None
    app.state.startup_error = None

    await _warm_database_pool_fast_path()
    app.state.startup_task = asyncio.create_task(_run_post_startup_init(app))

    try:
        yield
    finally:
        startup_task = getattr(app.state, "startup_task", None)
        if startup_task is not None:
            await asyncio.gather(startup_task, return_exceptions=True)

        if resumes._background_tasks:
            await asyncio.gather(*list(resumes._background_tasks), return_exceptions=True)
        try:
            if settings.ENABLE_METAFLOW:
                from app.routers import flows_router as _flows_router
                if getattr(_flows_router, "_flow_background_tasks", None):
                    await asyncio.gather(*list(_flows_router._flow_background_tasks), return_exceptions=True)
        except Exception as _shutdown_exc:
            logger.warning(
                "Flow background task cleanup error during shutdown: %s",
                _shutdown_exc,
                exc_info=True,
            )


# â”€â”€â”€ App Factory â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_configure_harness_env_defaults()

app = FastAPI(
    title="HR Analytics & Smart Hiring Platform",
    description="AI-Powered HR Platform API",
    version="2.0.0",
    # Disable interactive docs in production to limit attack surface
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    lifespan=lifespan,
)


# â”€â”€â”€ Rate limiting â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        bind_contextvars(request_id=request_id)
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        finally:
            clear_contextvars()
        response.headers["X-Request-ID"] = request_id
        return response


class RequestMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = int(response.status_code)
            return response
        except Exception:
            status_code = 500
            raise
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "request_complete method=%s path=%s status=%s duration_ms=%s request_id=%s",
                request.method,
                request.url.path,
                status_code,
                elapsed_ms,
                getattr(request.state, "request_id", "-"),
            )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'; "
            "font-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none';"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


class LimiterBackendGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Keep health endpoints reachable for diagnostics even when limiter backend is degraded.
        if request.url.path in {"/health", "/"}:
            return await call_next(request)
        try:
            enforce_limiter_backend_or_503(request)
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=exc.headers or {},
            )
        return await call_next(request)


app.add_middleware(RequestIDMiddleware)
app.add_middleware(RequestMetricsMiddleware)
app.add_middleware(LimiterBackendGuardMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# â”€â”€â”€ CORS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    # In development we allow all request headers to avoid browser preflight
    # stalls from ad-hoc/custom headers added by tooling/extensions/frontends.
    # Production retains explicit allow-listing.
    allow_headers=(
        ["*"]
        if not settings.is_production
        else [
            "Authorization",
            "Content-Type",
            "Accept",
            "X-Quiz-Token",
            "X-Session-Id",
            "X-Skip-Auth-Refresh",
            "X-Client-Request-Id",
        ]
    ),
    expose_headers=["Content-Disposition", "X-Session-Id"],
)

# â”€â”€â”€ MLflow Session Middleware â€” tags each request with session_id for Sessions tab â”€â”€â”€


# Paths that should skip MLflow session tagging (health checks, docs, preflight).
_MLFLOW_SKIP_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json", "/"})


class MLflowSessionMiddleware(BaseHTTPMiddleware):
    """Tags every incoming HTTP request with a unique session_id in MLflow."""

    async def dispatch(self, request: Request, call_next):
        # Skip non-API paths and OPTIONS preflights â€” they have no MLflow trace.
        if request.url.path in _MLFLOW_SKIP_PATHS or request.method == "OPTIONS":
            return await call_next(request)

        session_id = request.headers.get("X-Session-Id") or str(uuid.uuid4())
        request.state.session_id = session_id
        try:
            from app.services.mlflow_service import tag_trace_with_session
            tag_trace_with_session(session_id)
        except Exception as _mlflow_exc:
            logger.debug("MLflow session tag skipped: %s", _mlflow_exc)
        response = await call_next(request)
        response.headers["X-Session-Id"] = session_id
        return response


app.add_middleware(MLflowSessionMiddleware)


# â”€â”€â”€ Exception Handlers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=jsonable_encoder({"detail": exc.errors(), "message": "Validation error"}),
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError):
    statement = getattr(exc, "statement", None)
    statement_preview = (str(statement)[:500] + "...") if statement and len(str(statement)) > 500 else statement
    logger.exception(
        "Database error on %s %s statement=%s",
        request.method,
        request.url.path,
        statement_preview,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "A database error occurred. Please try again later."},
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    # EDGE-CASE FIX: WebSocketDisconnect is a normal lifecycle event, not a server
    # error. Re-raise it so Starlette's WS machinery handles it cleanly instead of
    # returning a JSON 500 response on a WebSocket connection.
    if isinstance(exc, WebSocketDisconnect):
        raise exc

    # Pass StarletteHTTPExceptions through unchanged so that 401/403/404 responses
    # preserve their status codes and headers (e.g. WWW-Authenticate: Bearer on 401).
    if isinstance(exc, StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=dict(exc.headers) if exc.headers else None,
        )

    # Always log the full traceback so production errors are debuggable.
    logger.exception("Unhandled server error on %s %s", request.method, request.url.path)

    origin = request.headers.get("origin", "")
    headers = {}
    if origin in settings.cors_origins_list or "*" in settings.cors_origins_list:
        headers["Access-Control-Allow-Origin"] = origin
    
    if (settings.APP_ENV or "").strip().lower() == "development":
        # SECURITY: never expose raw exception strings/tracebacks to clients.
        # Keep full details in server logs only.
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error. Check server logs for details."},
            headers=headers,
        )
    return JSONResponse(
        # STYLE FIX: consistent status constant here too
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error. Check server logs for details."},
        headers=headers,
    )


# â”€â”€â”€ Routers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

app.include_router(auth.router)
app.include_router(jd.router)
app.include_router(resumes.router)
app.include_router(quiz.router)
app.include_router(analytics.router)
app.include_router(admin.router)
app.include_router(candidate_portal.router)
app.include_router(notifications.router)
app.include_router(agent.router)
app.include_router(settings_router.router)
app.include_router(token_monitor.router)



# â”€â”€â”€ Health Check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async def _check_backend_redis_health() -> dict:
    limiter_state = limiter_backend_state()
    impact = (
        "rate limiting uses in-memory fallback; harness Redis queuing disabled/fallback to in-process runtime"
    )
    if not settings.REDIS_URL:
        return {
            "configured": False,
            "reachable": False,
            "warning": True,
            "impact": impact,
            "limiter_backend_degraded": bool(limiter_state.get("backend_degraded")),
        }

    try:
        import redis.asyncio as aioredis  # type: ignore

        client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
        )
        try:
            await client.ping()
            return {
                "configured": True,
                "reachable": True,
                "warning": False,
                "impact": "none",
                "limiter_backend_degraded": bool(limiter_state.get("backend_degraded")),
            }
        finally:
            await client.aclose()
    except Exception:
        return {
            "configured": True,
            "reachable": False,
            "warning": True,
            "impact": impact,
            "limiter_backend_degraded": bool(limiter_state.get("backend_degraded")),
        }


async def _check_harness_health() -> dict:
    if not settings.HARNESS_MOUNT_ENABLED:
        return {"enabled": False, "mounted": False, "status": "disabled"}
    try:
        import httpx

        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"http://127.0.0.1:{settings.APP_PORT}/harness/health")
        return {
            "enabled": True,
            "mounted": resp.status_code == 200,
            "status": "healthy" if resp.status_code == 200 else f"http_{resp.status_code}",
        }
    except Exception as exc:
        return {
            "enabled": True,
            "mounted": False,
            "status": "unreachable",
            "detail": str(exc),
        }


async def _check_database_health() -> dict:
    try:
        from app.database import engine

        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"reachable": True}
    except Exception as exc:
        return {"reachable": False, "detail": str(exc)}


def _check_ai_health() -> dict:
    try:
        from app.services import gemini_service

        return gemini_service.ai_runtime_status()
    except Exception as exc:
        return {"configured": False, "available": False, "detail": str(exc)}


@app.get("/health", tags=["Health"])
async def health_check():
    global _FIRST_HEALTH_MARKED
    startup_complete = bool(getattr(app.state, "startup_complete", False))
    if not startup_complete:
        limiter_state = limiter_backend_state()
        payload = {
            "status": "starting",
            "version": app.version,
            "startup_complete": False,
            "redis": {
                "configured": bool(settings.REDIS_URL),
                "reachable": False,
                "warning": True,
                "impact": (
                    "rate limiting uses in-memory fallback; harness Redis queuing disabled/"
                    "fallback to in-process runtime"
                ),
                "limiter_backend_degraded": bool(limiter_state.get("backend_degraded")),
            },
        }
        if not _FIRST_HEALTH_MARKED:
            _boot_mark("T12", "first health endpoint response")
            _FIRST_HEALTH_MARKED = True
        return payload

    db_status = await _check_database_health()
    redis_status = await _check_backend_redis_health()
    harness_status = await _check_harness_health()
    ai_status = _check_ai_health()
    agents_status: dict[str, dict] = {}
    orchestration_observability: dict = {"status": "unavailable"}
    try:
        from app.services.multi_agent_runtime import hr_multi_agent_runtime

        agents_status = await hr_multi_agent_runtime.health_all()
    except Exception:
        agents_status = {"runtime": {"status": "unavailable"}}
    try:
        from app.services.harness_agent_client import get_runtime_observability_snapshot

        orchestration_observability = get_runtime_observability_snapshot()
    except Exception as obs_exc:
        orchestration_observability = {"status": "unavailable", "detail": str(obs_exc)}

    overall_status = "healthy"
    if not db_status.get("reachable", False):
        overall_status = "degraded"
    elif not ai_status.get("available", False):
        overall_status = "degraded"

    payload = {
        "status": overall_status,
        "version": app.version,
        "startup_complete": True,
        "database": db_status,
        "redis": redis_status,
        "ai": ai_status,
        "harness": harness_status,
        "multi_agent": agents_status,
        "agent_orchestration": orchestration_observability,
    }
    if not _FIRST_HEALTH_MARKED:
        _boot_mark("T12", "first health endpoint response")
        _FIRST_HEALTH_MARKED = True
    return payload


@app.get("/", tags=["Root"])
async def root():
    # CORRECTNESS FIX: docs URL is conditionally None in production (lines 40-41
    # above). Unconditionally returning "/docs" here was misleading â€” callers would
    # follow the link and hit a 404. Now we only advertise the docs path when it
    # is actually active.
    docs_path = "/docs" if not settings.is_production else None
    response = {
        "message": "HR Analytics & Smart Hiring Platform API",
        "health": "/health",
    }
    if docs_path:
        response["docs"] = docs_path
    return response



