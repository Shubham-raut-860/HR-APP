"""
HR Analytics & Smart Hiring Platform – FastAPI Backend
Azure OpenAI powered | Port: 8000
"""
# BUG #10 FIX (HIGH): load_dotenv() MUST run before any local imports that call
# os.getenv() at module level. Previously it was called AFTER all local imports,
# meaning any module reading env vars at import-time got stale/None values.
from dotenv import load_dotenv
load_dotenv()

# ─── Standard library ─────────────────────────────────────────────────────────
import logging
import traceback
import asyncio
import uuid
import os
import sys
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from urllib.parse import unquote, urlparse

# ─── Third-party ──────────────────────────────────────────────────────────────
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.websockets import WebSocketDisconnect
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import inspect as sa_inspect
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig


def _normalize_harness_env_raw(value: str | None) -> str:
    env = (value or "").strip().lower()
    if env in {"prod", "production"}:
        return "prod"
    if env in {"staging", "stage"}:
        return "staging"
    return "dev"


def _normalize_azure_openai_base_url(endpoint: str | None) -> str:
    """
    Convert Azure endpoint to OpenAI-compatible v1 base URL expected by AsyncOpenAI.
    Example:
      https://my-resource.openai.azure.com -> https://my-resource.openai.azure.com/openai/v1/
    """
    raw = (endpoint or "").strip()
    if not raw:
        return ""
    base = raw.rstrip("/")
    if base.endswith("/openai/v1"):
        return f"{base}/"
    if base.endswith("/openai/v1/"):
        return base
    return f"{base}/openai/v1/"


def _configure_harness_runtime_env_from_os() -> None:
    """
    Configure harness env before vendored harness imports/mounting.
    This avoids stale vendor settings cache with wrong Redis values.
    """
    secret = (os.getenv("HARNESS_JWT_SECRET_KEY") or os.getenv("SECRET_KEY") or "").strip()
    if secret:
        os.environ["JWT_SECRET_KEY"] = secret

    redis_url = (os.getenv("REDIS_URL") or "").strip()
    if redis_url:
        os.environ["REDIS_URL"] = redis_url
        os.environ["redis_url"] = redis_url
        try:
            parsed = urlparse(redis_url)
            if parsed.hostname:
                os.environ["REDIS_HOST"] = parsed.hostname
            if parsed.port:
                os.environ["REDIS_PORT"] = str(parsed.port)
        except Exception:
            pass

    if not os.getenv("ENVIRONMENT"):
        raw_env = os.getenv("HARNESS_ENVIRONMENT") or os.getenv("APP_ENV") or "development"
        os.environ["ENVIRONMENT"] = _normalize_harness_env_raw(raw_env)

    # Azure OpenAI -> OpenAI-compatible env bridge for vendored HarnessAgent.
    azure_key = (os.getenv("AZURE_OPENAI_API_KEY") or "").strip()
    azure_endpoint = (os.getenv("AZURE_OPENAI_ENDPOINT") or "").strip()
    azure_api_version = (os.getenv("AZURE_OPENAI_API_VERSION") or "").strip()
    azure_deployment = (
        os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
        or os.getenv("AZURE_CHAT_DEPLOYMENT")
        or os.getenv("AZURE_MINI_DEPLOYMENT")
        or ""
    ).strip()
    azure_base_url = _normalize_azure_openai_base_url(azure_endpoint)

    if azure_key:
        os.environ.setdefault("OPENAI_API_KEY", azure_key)
    if azure_base_url:
        os.environ.setdefault("OPENAI_BASE_URL", azure_base_url)
        os.environ.setdefault("OPENAI_API_BASE", azure_base_url)
    if azure_api_version:
        os.environ.setdefault("OPENAI_API_VERSION", azure_api_version)
    if azure_deployment:
        os.environ.setdefault("OPENAI_API_DEPLOYMENT", azure_deployment)
        os.environ.setdefault("OPENAI_MODELS", azure_deployment)
        os.environ.setdefault("DEFAULT_MODEL", azure_deployment)
    if azure_key and azure_base_url:
        os.environ.setdefault("OPENAI_API_TYPE", "azure")

    # Harness defaults workspace_base_path to "/workspaces", which resolves to
    # "\\workspaces" on Windows and is not writable in local dev.
    if not os.getenv("WORKSPACE_BASE_PATH"):
        configured_workspace = (
            os.getenv("HARNESS_WORKSPACE_BASE_PATH")
            or os.getenv("APP_WORKSPACE_BASE_PATH")
            or str((Path(__file__).resolve().parents[1] / "harness_workspaces").resolve())
        )
        os.environ["WORKSPACE_BASE_PATH"] = configured_workspace


# Apply early so vendor harness reads canonical env values.
_configure_harness_runtime_env_from_os()

# ─── Local application ────────────────────────────────────────────────────────
from app.config import settings
from app.limiter import limiter
from app.services.harness_auth_bridge import (
    harness_get_current_tenant,
    harness_get_current_user,
)
from app.routers import (
    auth, jd, resumes, quiz,
    analytics, admin, candidate_portal, notifications, agent,
    token_monitor,
)
from app.routers import settings_router
from app.routers import evals as evals_router

# ─── Logger ───────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)
_HARNESS_AVAILABLE = True
_HARNESS_SUBAPP: FastAPI | None = None


def _env_flag_true(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _current_app_env() -> str:
    return (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or settings.APP_ENV or "development").strip().lower()


def _normalize_harness_env(value: str | None) -> str:
    env = (value or "").strip().lower()
    if env in {"prod", "production"}:
        return "prod"
    if env in {"staging", "stage"}:
        return "staging"
    return "dev"


def _configure_harness_runtime_env() -> None:
    harness_secret = (settings.HARNESS_JWT_SECRET_KEY or settings.SECRET_KEY or "").strip()
    if harness_secret:
        os.environ["JWT_SECRET_KEY"] = harness_secret

    if settings.REDIS_URL:
        os.environ["REDIS_URL"] = settings.REDIS_URL
        os.environ["redis_url"] = settings.REDIS_URL
        try:
            parsed = urlparse(settings.REDIS_URL)
            if parsed.hostname:
                os.environ["REDIS_HOST"] = parsed.hostname
            if parsed.port:
                os.environ["REDIS_PORT"] = str(parsed.port)
        except Exception:
            pass

    if not os.getenv("ENVIRONMENT"):
        os.environ["ENVIRONMENT"] = _normalize_harness_env(
            settings.HARNESS_ENVIRONMENT or settings.APP_ENV
        )

    # Azure OpenAI -> OpenAI-compatible env bridge for vendored HarnessAgent.
    azure_key = (settings.AZURE_OPENAI_API_KEY or "").strip()
    azure_endpoint = (settings.AZURE_OPENAI_ENDPOINT or "").strip()
    azure_api_version = (settings.AZURE_OPENAI_API_VERSION or "").strip()
    azure_deployment = (
        str(getattr(settings, "AZURE_OPENAI_DEPLOYMENT_NAME", "") or "").strip()
        or str(getattr(settings, "AZURE_CHAT_DEPLOYMENT", "") or "").strip()
        or str(getattr(settings, "AZURE_MINI_DEPLOYMENT", "") or "").strip()
    )
    azure_base_url = _normalize_azure_openai_base_url(azure_endpoint)

    if azure_key:
        os.environ.setdefault("OPENAI_API_KEY", azure_key)
    if azure_base_url:
        os.environ.setdefault("OPENAI_BASE_URL", azure_base_url)
        os.environ.setdefault("OPENAI_API_BASE", azure_base_url)
    if azure_api_version:
        os.environ.setdefault("OPENAI_API_VERSION", azure_api_version)
    if azure_deployment:
        os.environ.setdefault("OPENAI_API_DEPLOYMENT", azure_deployment)
        os.environ.setdefault("OPENAI_MODELS", azure_deployment)
        os.environ.setdefault("DEFAULT_MODEL", azure_deployment)
    if azure_key and azure_base_url:
        os.environ.setdefault("OPENAI_API_TYPE", "azure")

    if not os.getenv("WORKSPACE_BASE_PATH"):
        os.environ["WORKSPACE_BASE_PATH"] = str(
            (Path(__file__).resolve().parents[1] / "harness_workspaces").resolve()
        )


def _run_startup_migrations() -> None:
    project_root = Path(__file__).resolve().parents[1]
    alembic_cfg = AlembicConfig(str(project_root / "alembic.ini"))
    alembic_command.upgrade(alembic_cfg, "head")


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

    if _env_flag_true("SKIP_STARTUP_MIGRATIONS", default=False):
        logger.warning("SKIP_STARTUP_MIGRATIONS=true - skipping automatic Alembic upgrade.")
    else:
        logger.info("Applying Alembic migrations to head at startup.")
        await asyncio.to_thread(_run_startup_migrations)

    await _assert_candidate_quiz_columns_present()


def _mount_original_harness_app(app: FastAPI) -> bool:
    """
    Mount the original HarnessAgent API from the vendored upstream source.
    """
    if not settings.HARNESS_MOUNT_ENABLED:
        logger.warning("HARNESS_MOUNT_ENABLED=false; /harness routes are disabled.")
        return False

    project_root = Path(__file__).resolve().parents[1]
    harness_src = project_root / "vendor" / "HarnessAgent-main" / "src"
    if not harness_src.exists():
        logger.warning("Original HarnessAgent source not found at %s", harness_src)
        return False

    src_str = str(harness_src)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)

    try:
        global _HARNESS_SUBAPP
        _configure_harness_runtime_env()
        from harness.api import deps as harness_deps
        from harness.core.config import get_config as harness_get_config
        from harness.api.main import create_app as create_harness_app
        harness_get_config.cache_clear()
        harness_app = create_harness_app()
        _HARNESS_SUBAPP = harness_app
        harness_app.dependency_overrides[harness_deps.get_current_tenant] = harness_get_current_tenant
        harness_app.dependency_overrides[harness_deps.get_current_user] = harness_get_current_user
        app.mount("/harness", harness_app)
        logger.info("Mounted original HarnessAgent API at /harness")
        return True
    except Exception:
        logger.exception("Failed to mount original HarnessAgent API")
        return False


def _mount_unavailable_harness_stub(app: FastAPI) -> None:
    """
    Provide a safe /harness stub when upstream dependencies are unavailable.
    """
    stub = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @stub.get("/")
    async def harness_unavailable_root() -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Original HarnessAgent is unavailable on this deployment."},
        )

    @stub.get("/health")
    async def harness_unavailable_health() -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unavailable"},
        )

    app.mount("/harness", stub)


# ─── Lifespan ─────────────────────────────────────────────────────────────────


async def _start_harness_subapp_lifespan(exit_stack: AsyncExitStack) -> None:
    """
    Mounted sub-app lifespans are not always started automatically.
    Explicitly enter harness lifespan so Redis/agent state is initialized.
    """
    harness_app = _HARNESS_SUBAPP
    if harness_app is None:
        return

    if getattr(harness_app.state, "redis", None) is not None:
        return

    await exit_stack.enter_async_context(harness_app.router.lifespan_context(harness_app))
    logger.info("Harness sub-app lifespan started by parent app lifecycle.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as exit_stack:
        # BUG #2 FIX (CRITICAL): Validate ENCRYPTION_KEY at startup, not at first
        # file-upload time. Without this, dev/staging with missing ENCRYPTION_KEY
        # starts fine but crashes with an unhandled RuntimeError on every upload.
        if not settings.ENCRYPTION_KEY or len(settings.ENCRYPTION_KEY) < 32:
            logger.error(
                "⚠️  ENCRYPTION_KEY is missing or too short (< 32 chars). "
                "File uploads and resume downloads WILL FAIL. "
                "Set ENCRYPTION_KEY in your .env file."
            )
            if settings.APP_ENV == "production":
                raise RuntimeError(
                    "ENCRYPTION_KEY must be at least 32 characters in production. "
                    "Set it in your .env file."
                )

        # Ensure mounted HarnessAgent lifespan runs so request.app.state.redis exists.
        await _start_harness_subapp_lifespan(exit_stack)

        # Always apply pending migrations on startup and enforce required schema.
        await _run_startup_schema_guard()

        # ── MLflow self-configures from env vars via mlflow_service.py ──────────────
        # MLFLOW_TRACKING_URI and MLFLOW_EXPERIMENT_NAME are read at module import.
        # mlflow_service._init_mlflow() runs automatically and logs the result.
        # FIX: import in a thread to prevent blocking the event loop if the MLflow
        # server is unreachable (socket timeout can be ~30s by default).
        try:
            # Wrap in wait_for to prevent hang if MLflow tracking is unreachable
            _mlflow_available = await asyncio.wait_for(
                asyncio.to_thread(
                    lambda: __import__("app.services.mlflow_service", fromlist=["_init_mlflow"])._init_mlflow()
                ),
                timeout=5.0
            )
        except Exception as _e:
            logger.debug("Failed to initialize MLflow service: %s", _e)
            _mlflow_available = False
        if not _mlflow_available:
            logger.warning(
                "⚠️  MLflow tracking server not reachable — set MLFLOW_TRACKING_URI in .env "
                "or start: mlflow server --host 127.0.0.1 --port 5000"
            )

        try:
            yield
        finally:
            if resumes._background_tasks:
                await asyncio.gather(*list(resumes._background_tasks), return_exceptions=True)
            try:
                from app.routers import flows_router as _flows_router
                if getattr(_flows_router, "_flow_background_tasks", None):
                    await asyncio.gather(*list(_flows_router._flow_background_tasks), return_exceptions=True)
            except Exception:
                pass
    # MLflow runs flush automatically when the context manager exits.


# ─── App Factory ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="HR Analytics & Smart Hiring Platform",
    description="AI-Powered HR Platform API",
    version="2.0.0",
    # Disable interactive docs in production to limit attack surface
    docs_url="/docs" if settings.APP_ENV != "production" else None,
    redoc_url="/redoc" if settings.APP_ENV != "production" else None,
    lifespan=lifespan,
)


# ─── Rate limiting ─────────────────────────────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'"
        )
        return response


app.add_middleware(SecurityHeadersMiddleware)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ─── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Quiz-Token", "X-Session-Id"],
    expose_headers=["Content-Disposition", "X-Session-Id"],
)

# ─── MLflow Session Middleware — tags each request with session_id for Sessions tab ───


# Paths that should skip MLflow session tagging (health checks, docs, preflight).
_MLFLOW_SKIP_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json", "/"})


class MLflowSessionMiddleware(BaseHTTPMiddleware):
    """Tags every incoming HTTP request with a unique session_id in MLflow."""

    async def dispatch(self, request: Request, call_next):
        # Skip non-API paths and OPTIONS preflights — they have no MLflow trace.
        if request.url.path in _MLFLOW_SKIP_PATHS or request.method == "OPTIONS":
            return await call_next(request)

        session_id = request.headers.get("X-Session-Id") or str(uuid.uuid4())
        request.state.session_id = session_id
        try:
            from app.services.mlflow_service import tag_trace_with_session
            tag_trace_with_session(session_id)
        except Exception:
            pass
        response = await call_next(request)
        response.headers["X-Session-Id"] = session_id
        return response


app.add_middleware(MLflowSessionMiddleware)


# ─── Exception Handlers ───────────────────────────────────────────────────────────

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=jsonable_encoder({"detail": exc.errors(), "message": "Validation error"}),
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError):
    logger.exception("Database error on %s %s", request.method, request.url.path)
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
    
    if settings.APP_ENV == "development":
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


# ─── Routers ──────────────────────────────────────────────────────────────────

app.include_router(auth.router)
app.include_router(jd.router)
app.include_router(resumes.router)
app.include_router(quiz.router)
app.include_router(analytics.router)
app.include_router(admin.router)
app.include_router(candidate_portal.router)
app.include_router(notifications.router)
app.include_router(agent.router)
_harness_mounted = _mount_original_harness_app(app)
if not _harness_mounted:
    if _current_app_env() == "production":
        raise RuntimeError("Critical dependency 'harness' failed to mount in production. Aborting.")
    logger.error("Harness mount failed — stub endpoints active. NOT safe for production.")
    _mount_unavailable_harness_stub(app)
_HARNESS_AVAILABLE = _harness_mounted
app.include_router(settings_router.router)
app.include_router(evals_router.router)
app.include_router(token_monitor.router)

# ─── Optional: Metaflow batch scoring (dev-only, behind feature flag) ─────────
# The import and router are loaded ONLY when ENABLE_METAFLOW=True so that
# the metaflow package is never imported in normal production deployments.
# Set ENABLE_METAFLOW=True in .env to activate POST /admin/flows/batch-score.
if settings.ENABLE_METAFLOW:
    try:
        from app.routers import flows_router as _flows_router
        app.include_router(_flows_router.router)
        logger.info("✅ Metaflow batch scoring endpoint registered (/admin/flows/batch-score)")
    except ImportError as _e:
        logger.warning(
            "ENABLE_METAFLOW=True but Metaflow is not installed: %s. "
            "Run: pip install metaflow>=2.12", _e,
        )



# ─── Health Check ─────────────────────────────────────────────────────────────

async def _check_backend_redis_health() -> dict:
    if not settings.REDIS_URL:
        return {"configured": False, "reachable": None}

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
            return {"configured": True, "reachable": True}
        finally:
            await client.aclose()
    except Exception:
        return {"configured": True, "reachable": False}


@app.get("/health", tags=["Health"])
async def health_check():
    redis_status = await _check_backend_redis_health()
    return {
        "status": "healthy",
        # VERSION FIX: reference app.version so this never drifts from the FastAPI
        # definition above — one source of truth for the version string.
        "version": app.version,
        "harness": "available" if _HARNESS_AVAILABLE else "unavailable",
        "redis": redis_status,
        # SECURITY: environment name omitted — it's an internal infrastructure detail
        # that has no value to legitimate callers and leaks deployment layout to attackers.
    }


@app.get("/", tags=["Root"])
async def root():
    # CORRECTNESS FIX: docs URL is conditionally None in production (lines 40-41
    # above). Unconditionally returning "/docs" here was misleading — callers would
    # follow the link and hit a 404. Now we only advertise the docs path when it
    # is actually active.
    docs_path = "/docs" if settings.APP_ENV != "production" else None
    response = {
        "message": "HR Analytics & Smart Hiring Platform API",
        "health": "/health",
    }
    if docs_path:
        response["docs"] = docs_path
    return response
