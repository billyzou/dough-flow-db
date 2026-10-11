from airflow import DAG
from datetime import datetime
from airflow.operators.bash import BashOperator
from airflow.sensors.external_task import ExternalTaskSensor
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

with DAG(
    dag_id='dbt_run',
    schedule='0 10 * * *',
    start_date=datetime(2026, 5, 3),
    catchup=False,
) as dag:
    # Wait for the purge too: silver is tables, so building before it would keep private rows until tomorrow
    wait_for_ingest = ExternalTaskSensor(
        task_id='wait_for_ingest',
        external_dag_id='daily_ingest_plaid',
        external_task_id='clean_sensitive_transactions',
        timeout=3600,
    )

    dbt_run = BashOperator(
        task_id='dbt_run',
        bash_command=f'dbt --log-path /tmp/dbt_logs seed --project-dir {REPO_ROOT}/dough_flow_db --profiles-dir {REPO_ROOT}/dough_flow_db --target-path /tmp/dbt_target && '
                     f'dbt --log-path /tmp/dbt_logs run --project-dir {REPO_ROOT}/dough_flow_db --profiles-dir {REPO_ROOT}/dough_flow_db --target-path /tmp/dbt_target',
    )

    wait_for_ingest >> dbt_run
