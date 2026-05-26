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
    run_ingest = BashOperator(
        task_id = 'run_ingest',
        bash_command = f'python3 {REPO_ROOT}/scripts/ingest_plaid.py'
    )

    clean_sensitive = BashOperator(
        task_id = 'clean_sensitive_transactions',
        bash_command = (
            'python3 -c "'
            'import os, psycopg2; '
            'merchants = [m.strip() for m in os.environ.get(\"MERCHANTS_TO_DELETE\", \"\").split(\",\") if m.strip()]; '
            'conn = psycopg2.connect(host=os.environ[\"DB_HOST\"], port=os.environ[\"DB_PORT\"], dbname=os.environ[\"DB_NAME\"], user=os.environ[\"DB_USER\"], password=os.environ[\"DB_PASSWORD\"]); '
            'cur = conn.cursor(); '
            'cur.execute(\"DELETE FROM transactions WHERE merchant ILIKE ANY(%s)\", (merchants,)); '
            'print(f\"Deleted {cur.rowcount} sensitive transactions\"); '
            'conn.commit(); conn.close()'
            '"'
        )
    )

    run_ingest >> clean_sensitive

