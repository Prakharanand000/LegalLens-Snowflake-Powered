"""
LegalLens Airflow DAG
=====================
Orchestrates the full LegalLens pipeline:
    Task 1: generate_and_load  — runs generate_data.py to load raw tables to Snowflake
    Task 2: dbt_run            — runs all dbt models (staging + marts)
    Task 3: dbt_test           — runs all dbt data quality tests

Schedule: daily at 6am UTC (adjust as needed)

Setup:
    pip install apache-airflow apache-airflow-providers-snowflake
    export AIRFLOW_HOME=~/airflow
    airflow db init
    airflow users create --username admin --password admin --role Admin \
        --email admin@legallens.com --firstname Legal --lastname Lens
    airflow webserver --port 8080 &
    airflow scheduler &

    # Then open http://localhost:8080 and toggle the DAG on.
"""

import subprocess
import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator

# ── DAG default args ──────────────────────────────────────────────────────────

default_args = {
    "owner": "legallens",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

# ── Paths — update these to match your local environment ─────────────────────

PROJECT_ROOT = os.path.expanduser("~/legallens")
DATA_GEN_DIR = os.path.join(PROJECT_ROOT, "data_generator")
DBT_PROJECT_DIR = os.path.join(PROJECT_ROOT, "dbt_project")

# ── Task functions ────────────────────────────────────────────────────────────

def run_data_generator():
    """
    Runs the Python data generator to (re)populate Snowflake RAW tables.
    In production you'd swap this for an incremental load or an external
    trigger (S3 event, Fivetran sync, etc.).
    """
    result = subprocess.run(
        ["python", "generate_data.py"],
        cwd=DATA_GEN_DIR,
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        raise RuntimeError(f"Data generator failed:\n{result.stderr}")
    print("Data generator completed successfully.")


# ── DAG definition ────────────────────────────────────────────────────────────

with DAG(
    dag_id="legallens_pipeline",
    default_args=default_args,
    description="LegalLens: load raw legal ops data and run dbt transformations",
    schedule_interval="0 6 * * *",      # Daily at 6am UTC
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["legallens", "legal-ops", "snowflake", "dbt"],
) as dag:

    # Task 1: Generate synthetic data and load to Snowflake RAW schema
    generate_and_load = PythonOperator(
        task_id="generate_and_load_raw",
        python_callable=run_data_generator,
        doc_md="""
        **Generate & Load**
        Runs generate_data.py to create synthetic matter, invoice, and contract
        records and load them into LEGALLENS_DB.RAW in Snowflake.
        """,
    )

    # Task 2: Run all dbt models (staging views + mart tables)
    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=f"cd {DBT_PROJECT_DIR} && dbt run --profiles-dir . --target dev",
        doc_md="""
        **dbt Run**
        Executes all dbt models in dependency order:
        - stg_matters, stg_invoices, stg_contracts (STAGING schema, views)
        - fct_outside_counsel_spend, fct_matter_backlog (MARTS schema, tables)
        Snowflake Cortex SENTIMENT() is called inside stg_contracts.
        """,
    )

    # Task 3: Run all dbt data quality tests
    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command=f"cd {DBT_PROJECT_DIR} && dbt test --profiles-dir . --target dev",
        doc_md="""
        **dbt Test**
        Runs all schema tests defined in sources.yml:
        - unique + not_null on primary keys
        - accepted_values on status/practice_area columns
        Fails the DAG if any test fails so data quality gates are enforced.
        """,
    )

    # ── Dependencies ──────────────────────────────────────────────────────────
    generate_and_load >> dbt_run >> dbt_test
