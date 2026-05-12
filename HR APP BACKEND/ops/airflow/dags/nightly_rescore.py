"""
ops/airflow/dags/nightly_rescore.py — Production Orchestration
==============================================================

AIRFLOW DAG to schedule nightly candidate re-scoring for the HireAi platform.
This DAG fetches the current default Job ID (or all active jobs) and triggers
the Metaflow BatchScoringFlow with LLM scoring enabled.

Tracking is automatically handled in MLflow via the --triggered_by tag.
"""
from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta
import os

# Configuration (In production, these would be Airflow Variables)
PYTHON_PATH = "/home/shubham/hireai_venv/bin/python"
PROJECT_ROOT = "/mnt/d/shubham/HR APP/Backend"
DEFAULT_JOB_ID = "acb7b34c-141d-4149-9f73-aac0e0c96d3b" # The one we've been testing

default_args = {
    "owner": "hireai-admin",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    "hireai_nightly_batch_scoring",
    default_args=default_args,
    description="Nightly ML-powered candidate scoring (Airflow -> Metaflow -> MLflow)",
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["hireai", "ml_pipeline"],
) as dag:

    # The actual integration point:
    # We call the Metaflow script and pass the 'airflow' tag so it shows up in MLflow.
    run_batch_scoring = BashOperator(
        task_id="trigger_metaflow_scoring",
        bash_command=f'cd "{PROJECT_ROOT}" && {PYTHON_PATH} flows/batch_scoring_flow.py run --job_id {DEFAULT_JOB_ID} --use_llm false --triggered_by "airflow_nightly"',
    )

    run_batch_scoring
