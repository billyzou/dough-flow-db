from airflow import DAG
from datetime import datetime
from airflow.operators.bash import BashOperator
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

with DAG(
    dag_id = 'daily_ingest_plaid',
    schedule = '0 10 * * *',
    start_date = datetime(2026, 5, 3),
    catchup = False
) as dag: 
    BashOperator(
        task_id = 'run_ingest', 
        bash_command = f'{REPO_ROOT}/.venv/bin/python3 {REPO_ROOT}/scripts/ingest_plaid.py'
    )

