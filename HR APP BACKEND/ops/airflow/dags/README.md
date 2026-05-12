# Airflow DAGs — Future Production Integration
# =============================================

# THIS DIRECTORY IS A STUB.
# No DAG files are implemented here yet. Airflow integration is deferred until
# the production environment (PostgreSQL + S3 + Airflow cluster) is available.

## When to come back here

Implement Airflow DAGs when ALL of the following are true:
- PostgreSQL is running (not SQLite)
- Metaflow is configured with an S3/Azure Blob profile (not local filesystem)
- An Airflow deployment is available (Docker Compose, managed, or Kubernetes)

---

## Planned DAG: `nightly_rescore.py`

**Trigger:** Daily cron at 02:00 UTC (after low-traffic window)  
**Purpose:** Re-score all active candidates for all active jobs using the
             BatchScoringFlow with LLM scoring enabled.

### Pseudo-code

```python
# ops/airflow/dags/nightly_rescore.py  (FUTURE)

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta

with DAG(
    dag_id="hireai_nightly_rescore",
    schedule_interval="0 2 * * *",      # 02:00 UTC daily
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
        "owner": "hireai-platform",
    },
    tags=["hireai", "scoring", "metaflow"],
) as dag:

    # Step 1: Fetch all active job IDs from the DB
    fetch_jobs = PythonOperator(
        task_id="fetch_active_jobs",
        python_callable=_get_active_job_ids,  # queries DB, returns list
    )

    # Step 2: For each job, dispatch a Metaflow batch scoring run
    # (In production, use a DynamicTaskMapping or a for-each pattern)
    rescore = BashOperator(
        task_id="batch_rescore",
        bash_command=(
            "cd /app/Backend && "
            "python flows/batch_scoring_flow.py run "
            "--job_id {{ task_instance.xcom_pull('fetch_active_jobs') }} "
            "--limit 0 "          # no limit in production
            "--use_llm true "     # LLM scoring in production
        ),
        env={
            "METAFLOW_PROFILE": "production",   # points to S3 + Postgres profile
            "DATABASE_URL": "{{ var.value.DATABASE_URL }}",
        },
    )

    fetch_jobs >> rescore
```

---

## Trigger Contract (API-side integration)

When the Airflow DAG is deployed, remove the `POST /admin/flows/batch-score`
subprocess endpoint and replace with an Airflow DAG trigger:

```
POST https://airflow.internal/api/v1/dags/hireai_nightly_rescore/dagRuns
{
  "conf": { "job_id": "<uuid>" }
}
```

---

## What Changes for Production (summary)

| Component | Dev | Production |
| :--- | :--- | :--- |
| Metaflow storage | `Backend/flows/.metaflow/` (local) | S3 bucket via named profile |
| Metaflow metadata | Local JSON files | PostgreSQL metadata DB |
| Trigger mechanism | CLI / uvicorn subprocess | Airflow BashOperator |
| LLM scoring | `--use_llm false` (default) | `--use_llm true` |
| DB URL (sync) | `sqlite:///hr_platform.db` | `postgresql+psycopg2://...` |

> No code changes to `batch_scoring_flow.py` are needed for production —
> only environment variable changes and the Airflow DAG file above.
