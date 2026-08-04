# PostgreSQL Migration And Release Gate Plan

## Current State

- Local development uses `sqlite+aiosqlite:///./hr_platform.db`.
- Production must use PostgreSQL through `postgresql+asyncpg://...`.
- KYC data must use a production database URL as well; do not keep it in a local SQLite file.

## Migration Steps

1. Provision managed PostgreSQL with automated backups, point-in-time recovery, TLS, and a private network route from the API runtime.
2. Create separate databases or schemas for primary app data and KYC data.
3. Create least-privilege app users for staging and production.
4. Set `DATABASE_URL` and `KYC_DATABASE_URL` to PostgreSQL URLs in the deployment secret manager.
5. Run Alembic migrations against an empty staging database:
   `alembic upgrade head`
6. Run a SQLite-to-PostgreSQL data migration only after taking a cold backup of `hr_platform.db` and `candidate_kyc.db`.
7. Verify all unique indexes and foreign keys after migration:
   - users email uniqueness
   - job owner relationships
   - candidate-to-job relationships
   - quiz attempt token hashes
   - refresh token indexes
8. Run recruiter, candidate, assessment, export, email, upload, and A2A smoke tests against staging PostgreSQL.
9. Run the 4-hour soak against staging PostgreSQL before production cutover.

## Release Gate

The release is blocked unless:

- `/health/ready` returns `ready=true`.
- `/health.redis.reachable=true`.
- `/health.redis.limiter_backend_degraded=false`.
- `APP_ENV=production` settings validation passes.
- Redis, PostgreSQL, SMTP, AI provider, and persistent file storage are reachable from the deployed runtime.
- The 4-hour soak has no stuck jobs, no SMTP send failures, no Redis connection failures, and stable memory.
