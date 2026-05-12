from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AliasChoices, Field, model_validator
from typing import List
import json
import secrets
import sys
import warnings


def _looks_placeholder(value: str) -> bool:
    """Best-effort guard against placeholder secrets in production."""
    if not value:
        return True
    normalized = value.strip().lower()
    placeholder_tokens = (
        "change_this",
        "changeme",
        "replace_me",
        "your_",
        "example",
        "set_in_env",
        "placeholder",
        "<",
        ">",
    )
    return any(token in normalized for token in placeholder_tokens)


class Settings(BaseSettings):
    # ─── Azure OpenAI — Chat (LLM) ───────────────────────────────────────────
    # Base endpoint WITHOUT the /openai/v1 path suffix.
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_API_VERSION: str = "2025-04-01-preview"
    # Your chat deployment name in Azure AI Foundry
    AZURE_CHAT_DEPLOYMENT: str = "gpt-4o"
    AZURE_MINI_DEPLOYMENT: str = "gpt-4o-mini"
    AZURE_REASONING_DEPLOYMENT: str = "o4-mini"
    AGENT_MODEL_MAP_JSON: str = (
        '{"scoring_agent":"chat","resume_parser_agent":"mini",'
        '"jd_parser_agent":"mini","jd_generator_agent":"chat",'
        '"quiz_agent_generate":"chat","quiz_agent_evaluate":"mini",'
        '"quiz_agent_parse_document":"mini","code_evaluation_agent":"reasoning",'
        '"cover_letter_agent":"chat","resume_enhancer_agent":"chat",'
        '"resume_builder_agent":"mini","notification_agent":"mini",'
        '"score_resume":"chat","parse_resume":"mini",'
        '"parse_jd_from_document":"mini","generate_jd":"chat",'
        '"generate_quiz":"chat","parse_quiz":"mini",'
        '"normalize_skills":"mini","generate_hr_email":"mini",'
        '"evaluate_code":"reasoning","enhance_resume":"chat",'
        '"build_resume":"mini","generate_cover_letter":"chat",'
        '"analyze_career_path":"chat"}'
    )
    LYZR_AGENT_URL: str = Field(
        default="",
        validation_alias=AliasChoices("LYZR_AGENT_URL", "VITE_LYZR_AGENT_URL"),
    )
    LYZR_API_KEY: str = Field(
        default="",
        validation_alias=AliasChoices("LYZR_API_KEY", "VITE_LYZR_API_KEY"),
    )
    LYZR_AGENT_ID: str = Field(
        default="",
        validation_alias=AliasChoices("LYZR_AGENT_ID", "VITE_LYZR_AGENT_ID"),
    )
    LYZR_USER_ID: str = Field(
        default="",
        validation_alias=AliasChoices("LYZR_USER_ID", "VITE_LYZR_USER_ID"),
    )
    LYZR_SESSION_ID: str = Field(
        default="",
        validation_alias=AliasChoices("LYZR_SESSION_ID", "VITE_LYZR_SESSION_ID"),
    )

    # ─── Azure OpenAI — Embeddings ───────────────────────────────────────────
    # Supported embedding models (deploy ONE in Azure AI Foundry):
    #   text-embedding-ada-002   → 1536-dim, cheapest, good baseline
    #   text-embedding-3-small   → 1536-dim, better quality, cheap  ← recommended
    #   text-embedding-3-large   → 3072-dim, best quality, higher cost
    # Override with AZURE_EMBEDDING_DEPLOYMENT env var in .env
    AZURE_EMBEDDING_DEPLOYMENT: str = "text-embedding-3-small"

    # ─── AI Score Cache ───────────────────────────────────────────────────────
    # When True, AI scores for a resume+job pair are stored in score_breakdown
    # and reused on re-uploads of the same file (same SHA-256 hash).
    AI_SCORE_CACHE_ENABLED: bool = True
    # Global kill-switch for AI JD scoring calls (LLM). Keep enabled by default;
    # bulk upload can still force fast rule-only mode.
    AI_SCORING_ENABLED: bool = True
    # Fast bulk mode: skips expensive embedding + AI JD scoring during bulk upload.
    BULK_FAST_MODE: bool = False
    # Fail fast instead of waiting through long retry chains when AI is unhealthy.
    AI_FAIL_FAST_ON_UNAVAILABLE: bool = True
    AI_REQUEST_TIMEOUT_SECONDS: float = 12.0
    AI_RETRY_MAX_ATTEMPTS: int = 2
    AI_RETRY_BACKOFF_SECONDS: float = 0.35
    AI_CIRCUIT_BREAKER_SECONDS: int = 30
    AI_CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 2
    AI_TRANSIENT_STATUS_CODES: str = "408,409,425,429,500,502,503,504"
    BULK_USE_HARNESS_PIPELINE: bool = False
    BULK_ASYNC_MAX_CONCURRENT_JOBS: int = 2
    BULK_EXTRACT_CONCURRENCY: int = 8
    BULK_PARSE_CONCURRENCY: int = 16
    BULK_SCORE_CONCURRENCY: int = 16
    RECRUITER_UPLOAD_SLO_MS: int = 15000
    RECRUITER_BULK_API_SLO_MS: int = 3000
    # Dynamic tag calibration (job-cohort relative ranking).
    # Helps prevent "everyone is Strong" when JD signal quality varies.
    DYNAMIC_TAGGING_ENABLED: bool = True
    DYNAMIC_TAG_MIN_COHORT: int = 20
    DYNAMIC_STRONG_PERCENTILE: float = 0.85
    DYNAMIC_MEDIUM_PERCENTILE: float = 0.55
    DYNAMIC_STRONG_FLOOR: float = 72.0
    DYNAMIC_MEDIUM_FLOOR: float = 55.0
    # Phase C scoring guardrails: confidence/evidence-based bounded post-calibration.
    PHASE_C_SCORING_ENABLED: bool = True

    # ─── Database ─────────────────────────────────────────────────────────────
    # FIX [DB-2]: Default changed from sqlite+aiosqlite to postgresql+asyncpg.
    # SQLite cannot handle concurrent writes (quiz submissions, bulk resume
    # uploads) without serialising them, causing lock contention at load.
    # Set DATABASE_URL in your .env:
    #   sqlite (dev only): sqlite+aiosqlite:///./hr_platform.db
    #   postgres (staging/prod): postgresql+asyncpg://user:pass@host:5432/dbname
    DATABASE_URL: str = "postgresql+asyncpg://hireai:hireai@localhost:5432/hireai"

    # ─── Auth ─────────────────────────────────────────────────────────────────
    SMTP_SERVER: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "noreply@hireai.local"

    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    BCRYPT_ROUNDS: int = 12
    # BUG 10 FIX: 480 min (8 hours) is too long for a stolen JWT to remain
    # valid with no revocation path. Reduced to 60 min. Long-term: add a
    # RefreshToken DB table + POST /auth/refresh so HR users aren't forced
    # to re-login every hour while stolen tokens expire quickly.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ─── App ──────────────────────────────────────────────────────────────────
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    # Default is development for local runs. Set APP_ENV=production explicitly in production.
    APP_ENV: str = "development"
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173"
    FRONTEND_URL: str = "http://localhost:5173"

    # ─── Rate limiting ────────────────────────────────────────────────────────
    # BUG 9 FIX: comma-separated list of trusted reverse-proxy IPs.
    # The rate limiter only reads X-Forwarded-For / X-Real-IP when the direct
    # connection comes from one of these IPs. Empty = no trusted proxies (safe
    # for local dev). In production, set this to your Nginx/LB instance IPs.
    # Example: TRUSTED_PROXY_IPS=10.0.0.1,10.0.0.2
    TRUSTED_PROXY_IPS: str = ""
    PROXY_DEPTH: int = 1
    REDIS_URL: str = ""

    # ─── Files ────────────────────────────────────────────────────────────────
    UPLOAD_DIR: str = "uploads"
    MAX_FILE_SIZE_MB: int = 20
    # Capped at 50 to prevent OOM - scale via queue if higher volume needed.
    BULK_UPLOAD_MAX_FILES: int = 50
    # Backward-compatible alias used by older async bulk paths.
    MAX_BULK_FILES: int = 50
    ALLOWED_RESUME_EXTENSIONS: str = ".pdf,.doc,.docx,.png,.jpg,.jpeg,.webp,.tiff,.tif,.bmp,.gif"

    # ─── Scoring ──────────────────────────────────────────────────────────────
    DEFAULT_RESUME_WEIGHT: int = 50
    DEFAULT_QUIZ_WEIGHT: int = 50
    DEFAULT_PASS_THRESHOLD: int = 60

    # ─── Quiz ─────────────────────────────────────────────────────────────────
    QUIZ_DURATION_MINUTES: int = 30
    QUIZ_TOTAL_QUESTIONS: int = 20
    QUIZ_EASY_COUNT: int = 8
    QUIZ_MEDIUM_COUNT: int = 8
    QUIZ_HARD_COUNT: int = 4

    # ─── MLflow Tracking ──────────────────────────────────────────────────────
    # Self-hosted: run `mlflow server --host 127.0.0.1 --port 5000` locally.
    # Remote: set to your managed MLflow URI (e.g. Databricks, AWS, etc.).
    # Leave as the default to write runs to a local ./mlruns directory.
    MLFLOW_TRACKING_URI: str = "http://127.0.0.1:5000"
    MLFLOW_EXPERIMENT_NAME: str = "hr_evals"

    # ─── DeepEval ─────────────────────────────────────────────────────────────
    # Optional: set DEEPEVAL_API_KEY to push results to Confident AI dashboard.
    # Leave blank to run evaluations locally only.
    DEEPEVAL_API_KEY: str = ""
    # Toggle eval execution per-operation (set to "false" to skip in production)
    EVALS_ENABLED: bool = True

    # ─── Metaflow (optional — local dev only) ────────────────────────────────
    # EXPERIMENTAL: disabled by default. Set ENABLE_METAFLOW=True in .env
    # to explicitly activate the batch scoring pipeline.
    # METAFLOW_PROFILE=local keeps all run state on the local filesystem under
    # Backend/flows/.metaflow/ — no S3 or external cluster is required in dev.
    # In production (Postgres + S3), set METAFLOW_PROFILE to the named profile
    # configured in ~/.metaflowconfig/ that points to your cloud datastore.
    ENABLE_METAFLOW: bool = False
    METAFLOW_PROFILE: str = "local"

    # Internal token/cost monitoring
    TOKEN_MONITOR_ENABLED: bool = True
    TOKEN_MONITOR_MAX_EVENTS: int = 5000
    TOKEN_MONITOR_DEFAULT_TOKEN_BUDGET: int = 8000
    TOKEN_MONITOR_TASK_BUDGETS_JSON: str = (
        '{"parse_resume":12000,"score_resume":5000,"parse_jd_from_document":4000,'
        '"generate_jd":3500,"generate_quiz":7000,"normalize_skills":1500,'
        '"generate_hr_email":2000,"evaluate_code":2500,"enhance_resume":10000,'
        '"build_resume_from_form":7000,"generate_cover_letter":4500,'
        '"analyze_career_path":5000,"resume_to_builder_data":4500}'
    )
    TOKEN_MONITOR_WARN_MULTIPLIER: float = 1.20
    TOKEN_MONITOR_MAX_COST_USD_PER_CALL: float = 0.25

    # ─── Encryption ───────────────────────────────────────────────────────────
    ENCRYPTION_KEY: str = ""

    # ─── Startup validation ───────────────────────────────────────────────────
    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.APP_ENV == "production":
            normalized_secret_key = (self.SECRET_KEY or "").strip().lower()
            known_default_secret_values = {
                "changeme",
                "change_me",
                "change-me",
                "secret",
                "dev",
                "default",
            }
            if normalized_secret_key in known_default_secret_values:
                raise RuntimeError(
                    "CRITICAL SECURITY ERROR: SECRET_KEY is using a known default/placeholder value in production."
                )

            if _looks_placeholder(self.SECRET_KEY):
                raise RuntimeError("CRITICAL SECURITY ERROR: Insecure or missing SECRET_KEY in production.")
            if len(self.SECRET_KEY) < 32:
                raise ValueError(
                    "SECRET_KEY must be at least 32 characters long in production.")

            database_url = (self.DATABASE_URL or "").strip()
            if not database_url:
                raise RuntimeError(
                    "CRITICAL CONFIG ERROR: DATABASE_URL must be set in production."
                )
            database_url_lower = database_url.lower()
            if database_url_lower.startswith("sqlite") or (
                ":///" in database_url_lower and
                (".db" in database_url_lower or ".sqlite" in database_url_lower)
            ):
                raise RuntimeError(
                    "CRITICAL CONFIG ERROR: DATABASE_URL cannot point to a local .db/.sqlite file in production."
                )

            if _looks_placeholder(self.ENCRYPTION_KEY):
                raise ValueError("ENCRYPTION_KEY must be set in production.")
            if _looks_placeholder(self.AZURE_OPENAI_API_KEY):
                raise ValueError("AZURE_OPENAI_API_KEY must be set in production.")
            if _looks_placeholder(self.AZURE_OPENAI_ENDPOINT):
                raise ValueError(
                    "AZURE_OPENAI_ENDPOINT must be set in production.")
            cors_list = [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
            unsafe = [o for o in cors_list if "localhost" in o or "127.0.0.1" in o]
            if unsafe:
                raise ValueError(
                    f"CORS_ORIGINS contains localhost entries in production: {unsafe}")
            if not self.SMTP_USERNAME or not self.SMTP_PASSWORD:
                warnings.warn(
                    "SMTP_USERNAME / SMTP_PASSWORD are empty in production. "
                    "Password-reset and notification emails will silently fail.",
                    stacklevel=2,
                )
        return self

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    _cached_extensions: list[str] | None = None
    _cached_agent_model_map: dict[str, str] | None = None

    @property
    def allowed_extensions_list(self) -> List[str]:
        if self._cached_extensions is None:
            configured = {e.strip().lower() for e in self.ALLOWED_RESUME_EXTENSIONS.split(",") if e.strip()}
            # Keep OCR-capable baseline always enabled even if env overrides are incomplete.
            required = {
                ".pdf", ".doc", ".docx", ".txt",
                ".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp", ".gif",
            }
            self._cached_extensions = sorted(configured | required)
        return self._cached_extensions

    @property
    def MAX_FILE_SIZE_BYTES(self) -> int:
        return max(0, int(self.MAX_FILE_SIZE_MB)) * 1024 * 1024

    @property
    def agent_model_map(self) -> dict[str, str]:
        if self._cached_agent_model_map is None:
            parsed: dict[str, str] = {}
            raw = self.AGENT_MODEL_MAP_JSON
            if raw:
                try:
                    loaded = json.loads(raw)
                    if isinstance(loaded, dict):
                        for key, value in loaded.items():
                            k = str(key).strip()
                            v = str(value).strip()
                            if k and v:
                                alias = v.lower()
                                if alias in {"chat", "default", "primary"}:
                                    parsed[k] = self.AZURE_CHAT_DEPLOYMENT
                                elif alias in {"mini", "fast"}:
                                    parsed[k] = self.AZURE_MINI_DEPLOYMENT or self.AZURE_CHAT_DEPLOYMENT
                                elif alias in {"reasoning", "o4", "smart"}:
                                    parsed[k] = self.AZURE_REASONING_DEPLOYMENT or self.AZURE_CHAT_DEPLOYMENT
                                else:
                                    parsed[k] = v
                except json.JSONDecodeError:
                    warnings.warn(
                        "AGENT_MODEL_MAP_JSON is invalid JSON; default chat deployment will be used.",
                        stacklevel=2,
                    )
            self._cached_agent_model_map = parsed
        return self._cached_agent_model_map

    # Load local overrides first, then fallback to .env.
    # This keeps committed templates safe while preserving local development ergonomics.
    model_config = SettingsConfigDict(env_file=(".env.local", ".env"), extra="ignore")


try:
    settings = Settings()
except Exception as e:
    print(f"\n❌ FATAL: Failed to load configuration.\n   {e}\n"
          f"   → Check your .env file and environment variables.\n",
          file=sys.stderr)
    raise
