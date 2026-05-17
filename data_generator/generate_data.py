"""
LegalLens — Synthetic Legal Operations Data Generator
Generates MATTERS, INVOICES, and CONTRACTS tables and loads them to Snowflake.

Usage:
    pip install snowflake-connector-python faker pandas python-dotenv
    python generate_data.py

Requires a .env file in the same directory:
    SNOWFLAKE_ACCOUNT=your_account_identifier
    SNOWFLAKE_USER=your_username
    SNOWFLAKE_PASSWORD=your_password
    SNOWFLAKE_WAREHOUSE=LEGALLENS_WH
    SNOWFLAKE_DATABASE=LEGALLENS_DB
    SNOWFLAKE_SCHEMA=RAW
"""

import os
import random
import platform
from datetime import datetime, timezone, timedelta

# ── Patch: fix Snowflake connector bug on Windows Microsoft Store Python ──────
# snowflake-connector-python 4.x calls platform.libc_ver() which fails on
# Windows Store Python because the exe path is a stub. Monkey-patch it.
original_libc_ver = platform.libc_ver
def _safe_libc_ver(executable=None):
    try:
        return original_libc_ver(executable)
    except OSError:
        return ('', '')
platform.libc_ver = _safe_libc_ver

import pandas as pd
import snowflake.connector
from dotenv import load_dotenv
from faker import Faker

load_dotenv()
fake = Faker()
random.seed(42)

def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC for Snowflake

# ── Constants ────────────────────────────────────────────────────────────────

LAW_FIRMS = [
    "Kirkland & Ellis LLP",
    "Latham & Watkins LLP",
    "Skadden Arps LLP",
    "Sullivan & Cromwell LLP",
    "Cleary Gottlieb LLP",
    "Weil Gotshal LLP",
    "Gibson Dunn LLP",
    "Paul Weiss LLP",
    "Cravath Swaine LLP",
    "Simpson Thacher LLP",
]

PRACTICE_AREAS = [
    "M&A",
    "Litigation",
    "IP",
    "Employment",
    "Regulatory",
    "Real Estate",
    "Tax",
]

MATTER_STATUSES = ["Open", "Closed", "On Hold", "In Review"]

ATTORNEYS = [
    "Sarah Chen", "Marcus Williams", "Priya Patel",
    "James O'Brien", "Leila Hassan", "David Park",
    "Natasha Kovacs", "Carlos Rivera", "Emma Thornton", "Raj Mehta",
]

CONTRACT_NOTE_TEMPLATES = [
    "Annual retainer agreement. Auto-renews unless 60 days notice given. Relationship in good standing.",
    "Rate card agreed for FY2025. No disputes outstanding. Preferred panel firm.",
    "Matter closed. Final invoice pending. Consider off-panel for future work.",
    "Billing dispute unresolved from Q3. Escalated to GC review. Rates above market.",
    "New engagement letter required before next matter opens. Previous terms expired.",
    "Strong performance on M&A mandates. Rate increase requested for renewal consideration.",
    "Under review following partner departure. Relationship continuity uncertain.",
    "Preferred vendor. Volume discount applies above $500K annual spend threshold.",
    "Contract expired. Operating on holdover terms. Renewal negotiations delayed.",
    "Diversity scorecard requirements not met. Remediation plan requested.",
]


# ── Data generators ──────────────────────────────────────────────────────────

def generate_matters(n=600):
    """Generate MATTERS table with realistic legal matter data."""
    rows = []
    start_date_pool = datetime(2022, 1, 1)
    end_date_pool = datetime(2025, 12, 31)

    for i in range(1, n + 1):
        status = random.choices(
            MATTER_STATUSES, weights=[45, 35, 10, 10]
        )[0]

        open_date = fake.date_between(start_date=start_date_pool, end_date=end_date_pool)

        if status == "Closed":
            close_date = open_date + timedelta(days=random.randint(30, 540))
            close_date = min(close_date, datetime(2025, 12, 31).date())
        else:
            close_date = None

        rows.append({
            "MATTER_ID": f"MTR-{i:04d}",
            "MATTER_NAME": f"{random.choice(PRACTICE_AREAS)} Matter {i:04d}",
            "PRACTICE_AREA": random.choice(PRACTICE_AREAS),
            "STATUS": status,
            "OPEN_DATE": open_date,
            "CLOSE_DATE": close_date,
            "LEAD_ATTORNEY": random.choice(ATTORNEYS),
            "LEAD_FIRM": random.choice(LAW_FIRMS),
            "PRIORITY": random.choices(["High", "Medium", "Low"], weights=[20, 50, 30])[0],
            "CREATED_AT": now_utc(),
        })

    return pd.DataFrame(rows)


def generate_invoices(matters_df, n=1200):
    """Generate INVOICES table — multiple invoices per matter, some over budget."""
    rows = []
    matter_ids = matters_df["MATTER_ID"].tolist()

    # Assign a budget per matter
    matter_budgets = {
        mid: round(random.uniform(25_000, 750_000), 2)
        for mid in matter_ids
    }

    invoice_num = 1
    for matter_id in matter_ids:
        budget = matter_budgets[matter_id]
        num_invoices = random.randint(1, 4)
        matter_row = matters_df[matters_df["MATTER_ID"] == matter_id].iloc[0]
        firm = matter_row["LEAD_FIRM"]
        practice_area = matter_row["PRACTICE_AREA"]

        # Occasionally spike to create over-budget scenarios (30% of matters)
        overage_multiplier = random.uniform(1.1, 1.6) if random.random() < 0.30 else 1.0
        total_spend = budget * overage_multiplier

        spend_split = sorted(
            [random.random() for _ in range(num_invoices - 1)] + [0, 1]
        )
        amounts = [
            round((spend_split[j + 1] - spend_split[j]) * total_spend, 2)
            for j in range(num_invoices)
        ]

        open_date = matter_row["OPEN_DATE"]
        for k, amount in enumerate(amounts):
            invoice_date = open_date + timedelta(days=random.randint(15, 90) * (k + 1))
            rows.append({
                "INVOICE_ID": f"INV-{invoice_num:05d}",
                "MATTER_ID": matter_id,
                "VENDOR": firm,
                "PRACTICE_AREA": practice_area,
                "AMOUNT": amount,
                "BUDGET_ALLOCATED": round(budget / num_invoices, 2),
                "INVOICE_DATE": invoice_date,
                "STATUS": random.choices(
                    ["Approved", "Pending", "Disputed"],
                    weights=[70, 20, 10]
                )[0],
                "CREATED_AT": now_utc(),
            })
            invoice_num += 1

    return pd.DataFrame(rows[:n])


def generate_contracts(n=80):
    """Generate CONTRACTS table — one contract per firm, mix of expiry windows."""
    rows = []
    today = now_utc().date()

    for i, firm in enumerate(LAW_FIRMS):
        # Create 7-9 contracts per firm spanning different years
        num_contracts = random.randint(7, 9)
        for j in range(num_contracts):
            # Stagger start dates going back 3 years
            start_date = today - timedelta(days=random.randint(90, 1100))
            duration_days = random.choice([365, 365, 730])  # 1 or 2 year terms
            end_date = start_date + timedelta(days=duration_days)

            # Force some contracts into expiry windows for demo value
            if j == 0:
                end_date = today + timedelta(days=random.randint(1, 29))    # <30 days
            elif j == 1:
                end_date = today + timedelta(days=random.randint(30, 59))   # 30-60 days
            elif j == 2:
                end_date = today + timedelta(days=random.randint(60, 90))   # 60-90 days

            renewal_flag = "Yes" if random.random() > 0.35 else "No"
            notes = random.choice(CONTRACT_NOTE_TEMPLATES)

            rows.append({
                "CONTRACT_ID": f"CON-{i:02d}{j:02d}",
                "VENDOR": firm,
                "PRACTICE_AREA": random.choice(PRACTICE_AREAS),
                "START_DATE": start_date,
                "END_DATE": end_date,
                "ANNUAL_VALUE": round(random.uniform(50_000, 2_000_000), 2),
                "RENEWAL_FLAG": renewal_flag,
                "NOTES": notes,
                "CREATED_AT": now_utc(),
            })

    return pd.DataFrame(rows[:n])


# ── Snowflake loader ─────────────────────────────────────────────────────────

def get_snowflake_conn():
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "LEGALLENS_WH"),
        database=os.environ.get("SNOWFLAKE_DATABASE", "LEGALLENS_DB"),
        schema=os.environ.get("SNOWFLAKE_SCHEMA", "RAW"),
    )


def setup_snowflake(conn):
    """Create database, schema, warehouse if they don't exist."""
    cursor = conn.cursor()
    statements = [
        "CREATE DATABASE IF NOT EXISTS LEGALLENS_DB",
        "CREATE SCHEMA IF NOT EXISTS LEGALLENS_DB.RAW",
        "CREATE SCHEMA IF NOT EXISTS LEGALLENS_DB.STAGING",
        "CREATE SCHEMA IF NOT EXISTS LEGALLENS_DB.MARTS",
        """
        CREATE WAREHOUSE IF NOT EXISTS LEGALLENS_WH
            WAREHOUSE_SIZE = 'X-SMALL'
            AUTO_SUSPEND = 60
            AUTO_RESUME = TRUE
        """,
        "USE DATABASE LEGALLENS_DB",
        "USE SCHEMA RAW",
        """
        CREATE OR REPLACE TABLE MATTERS (
            MATTER_ID       VARCHAR(20) PRIMARY KEY,
            MATTER_NAME     VARCHAR(200),
            PRACTICE_AREA   VARCHAR(50),
            STATUS          VARCHAR(20),
            OPEN_DATE       DATE,
            CLOSE_DATE      DATE,
            LEAD_ATTORNEY   VARCHAR(100),
            LEAD_FIRM       VARCHAR(100),
            PRIORITY        VARCHAR(10),
            CREATED_AT      TIMESTAMP_NTZ
        )
        """,
        """
        CREATE OR REPLACE TABLE INVOICES (
            INVOICE_ID        VARCHAR(20) PRIMARY KEY,
            MATTER_ID         VARCHAR(20),
            VENDOR            VARCHAR(100),
            PRACTICE_AREA     VARCHAR(50),
            AMOUNT            NUMBER(18,2),
            BUDGET_ALLOCATED  NUMBER(18,2),
            INVOICE_DATE      DATE,
            STATUS            VARCHAR(20),
            CREATED_AT        TIMESTAMP_NTZ
        )
        """,
        """
        CREATE OR REPLACE TABLE CONTRACTS (
            CONTRACT_ID     VARCHAR(20) PRIMARY KEY,
            VENDOR          VARCHAR(100),
            PRACTICE_AREA   VARCHAR(50),
            START_DATE      DATE,
            END_DATE        DATE,
            ANNUAL_VALUE    NUMBER(18,2),
            RENEWAL_FLAG    VARCHAR(5),
            NOTES           VARCHAR(500),
            CREATED_AT      TIMESTAMP_NTZ
        )
        """,
    ]
    for stmt in statements:
        cursor.execute(stmt)
    cursor.close()
    print("Snowflake setup complete.")


def load_dataframe(conn, df, table_name):
    """Write a pandas DataFrame to Snowflake using batch insert."""
    from snowflake.connector.pandas_tools import write_pandas
    success, nchunks, nrows, _ = write_pandas(
        conn, df, table_name, database="LEGALLENS_DB", schema="RAW", auto_create_table=False
    )
    print(f"  Loaded {nrows} rows into {table_name} ({nchunks} chunks). Success={success}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("Generating synthetic legal operations data...")

    matters_df   = generate_matters(n=600)
    invoices_df  = generate_invoices(matters_df, n=1200)
    contracts_df = generate_contracts(n=80)

    print(f"  MATTERS:   {len(matters_df)} rows")
    print(f"  INVOICES:  {len(invoices_df)} rows")
    print(f"  CONTRACTS: {len(contracts_df)} rows")

    # Save local CSVs as backup
    matters_df.to_csv("matters.csv", index=False)
    invoices_df.to_csv("invoices.csv", index=False)
    contracts_df.to_csv("contracts.csv", index=False)
    print("CSV backups saved.")

    print("\nConnecting to Snowflake...")
    conn = get_snowflake_conn()
    setup_snowflake(conn)

    print("\nLoading tables...")
    load_dataframe(conn, matters_df,   "MATTERS")
    load_dataframe(conn, invoices_df,  "INVOICES")
    load_dataframe(conn, contracts_df, "CONTRACTS")

    conn.close()
    print("\nDone. All tables loaded to LEGALLENS_DB.RAW.")


if __name__ == "__main__":
    main()
