#!/bin/bash
export AIRFLOW_HOME="/mnt/d/shubham/HR APP/Backend/ops/airflow"
export PATH="/home/shubham/jobora_venv/bin:$PATH"

# Kill existing Airflow processes
pkill -f airflow || true
sleep 2

# Start components in background
nohup airflow scheduler > "$AIRFLOW_HOME/airflow_scheduler.log" 2>&1 &
nohup airflow dag-processor > "$AIRFLOW_HOME/airflow_dag_processor.log" 2>&1 &
nohup airflow triggerer > "$AIRFLOW_HOME/airflow_triggerer.log" 2>&1 &
nohup airflow api-server --host 0.0.0.0 --port 8080 > "$AIRFLOW_HOME/airflow_api_server.log" 2>&1 &

echo "Airflow services started in background."
