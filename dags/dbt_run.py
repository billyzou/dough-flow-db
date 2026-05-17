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
    wait_for_ingest = ExternalTaskSensor(
        task_id='wait_for_ingest',
        external_dag_id='daily_ingest_plaid',
        external_task_id='run_ingest',
        timeout=3600,
    )

    dbt_run = BashOperator(
        task_id='dbt_run',
        bash_command=f'dbt run --project-dir {REPO_ROOT}/dough_flow_db --profiles-dir {REPO_ROOT}/dough_flow_db',
    )

    wait_for_ingest >> dbt_run
