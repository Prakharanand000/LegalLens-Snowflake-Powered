# LegalLens — Outside Counsel Intelligence Platform

> AI-powered Snowflake-native analytics for Legal Operations teams.
> Built with Snowflake Cortex, dbt, Airflow, and Streamlit.

![Stack](https://img.shields.io/badge/Snowflake-Cortex-29B5E8?logo=snowflake)
![dbt](https://img.shields.io/badge/dbt-Core-FF694B?logo=dbt)
![Airflow](https://img.shields.io/badge/Airflow-2.x-017CEE?logo=apacheairflow)
![Streamlit](https://img.shields.io/badge/Streamlit-1.x-FF4B4B?logo=streamlit)

---

## What it does

LegalLens gives a General Counsel real-time visibility into three questions
the JD for this exact role names verbatim:

1. **Outside counsel spend vs. budget** — Which firms are over budget, by how
   much, and in which practice areas? Red/green waterfall by firm.
2. **Matter backlog by practice area** — Where are task backlogs building?
   Which attorneys are carrying the heaviest load? Age heatmap.
3. **Contract expiration risk** — Which outside counsel contracts expire in
   30/60/90 days without a renewal signal? Cortex sentiment on contract notes
   flags at-risk relationships before they lapse.

A fourth tab, **Ask LegalLens**, lets any user ask plain-English questions
(e.g. "Which firms are over budget in M&A?") and get data-grounded answers
via Snowflake Cortex COMPLETE — no SQL required.

---

## Architecture

```
Python generator
      |
      v
Snowflake RAW (MATTERS, INVOICES, CONTRACTS)
      |
      v  [Airflow DAG: legallens_pipeline]
      |
      v
dbt staging layer (STAGING schema — views)
  stg_matters.sql       — clean types, compute days_open
  stg_invoices.sql      — validate grain, flag over-budget
  stg_contracts.sql     — Cortex SENTIMENT() on notes field
      |
      v
dbt mart layer (MARTS schema — tables)
  fct_outside_counsel_spend.sql   — spend vs. budget by vendor + practice area
  fct_matter_backlog.sql          — backlog age + attorney workload score
      |
      v
Streamlit dashboard
  Tab 1: Spend vs. Budget
  Tab 2: Matter Backlog
  Tab 3: Contract Risk + Cortex Sentiment
  Tab 4: Ask LegalLens (Snowflake Cortex COMPLETE)
      |
      v
Snowflake access controls
  Row-level security policy  — practice area isolation
  Secure view (invoices)     — dollar amounts masked for analyst role
  Secure view (contracts)    — notes field restricted to GC role
```

---

## Snowflake features used

| Feature | Where |
|---------|-------|
| `SNOWFLAKE.CORTEX.SENTIMENT()` | `stg_contracts.sql` — scores contract notes |
| `SNOWFLAKE.CORTEX.COMPLETE()` | `app.py` Tab 4 — natural language Q&A |
| Row Access Policy | `setup_access_controls.sql` — practice area RLS |
| Secure Views | `setup_access_controls.sql` — amount masking + notes restriction |
| Auto-suspend warehouse | `generate_data.py` — X-Small, suspends after 60s |
| dbt-snowflake adapter | `dbt_project.yml` + `profiles.yml` |

---

## Project structure

```
legallens/
├── data_generator/
│   └── generate_data.py        # Synthetic data generator + Snowflake loader
├── dbt_project/
│   ├── dbt_project.yml
│   ├── profiles.yml            # Copy to ~/.dbt/profiles.yml
│   └── models/
│       ├── staging/
│       │   ├── sources.yml     # Source declarations + dbt tests
│       │   ├── stg_matters.sql
│       │   ├── stg_invoices.sql
│       │   └── stg_contracts.sql   # Cortex SENTIMENT() here
│       └── marts/
│           ├── fct_outside_counsel_spend.sql
│           └── fct_matter_backlog.sql
├── airflow/
│   └── dags/
│       └── legallens_pipeline.py   # 3-task DAG: load -> dbt run -> dbt test
├── streamlit/
│   └── app.py                  # 4-tab Streamlit dashboard
└── docs/
    └── setup_access_controls.sql  # Snowflake roles, RLS, secure views
```

---

## Setup (one day)

### Step 1 — Snowflake free trial (30 min)

1. Sign up at [trial.snowflake.com](https://trial.snowflake.com) — choose AWS US East
2. Note your **account identifier** (format: `abc12345.us-east-1`)
3. Create `.env` in the project root:

```env
SNOWFLAKE_ACCOUNT=abc12345.us-east-1
SNOWFLAKE_USER=your_username
SNOWFLAKE_PASSWORD=your_password
SNOWFLAKE_WAREHOUSE=LEGALLENS_WH
SNOWFLAKE_DATABASE=LEGALLENS_DB
SNOWFLAKE_SCHEMA=RAW
```

### Step 2 — Install dependencies (10 min)

```bash
pip install snowflake-connector-python[pandas] faker pandas python-dotenv \
            dbt-snowflake streamlit plotly \
            apache-airflow apache-airflow-providers-snowflake
```

### Step 3 — Generate data and load to Snowflake (5 min)

```bash
cd data_generator
python generate_data.py
# Expected output:
# MATTERS:   600 rows
# INVOICES:  1200 rows
# CONTRACTS: 80 rows
# All tables loaded to LEGALLENS_DB.RAW
```

### Step 4 — Configure dbt (5 min)

```bash
cp dbt_project/profiles.yml ~/.dbt/profiles.yml
# Edit ~/.dbt/profiles.yml with your Snowflake credentials
```

### Step 5 — Run dbt (10 min)

```bash
cd dbt_project
dbt deps          # install packages if any
dbt build         # runs all models + tests in one command
# Expected: 5 models pass, all tests green
```

### Step 6 — Start Airflow (15 min)

```bash
export AIRFLOW_HOME=~/airflow
airflow db init
airflow users create --username admin --password admin --role Admin \
    --email admin@legallens.com --firstname Legal --lastname Lens
cp airflow/dags/legallens_pipeline.py ~/airflow/dags/
airflow webserver --port 8080 &
airflow scheduler &
# Open http://localhost:8080, toggle legallens_pipeline ON, trigger manually
```

### Step 7 — Launch dashboard (5 min)

```bash
cd streamlit
streamlit run app.py
# Opens at http://localhost:8501
```

### Step 8 — Access controls (10 min)

```bash
# In Snowflake web UI (Worksheets), run:
# docs/setup_access_controls.sql
# Applies row-level security, secure views, and role-based access.
```

---

## Data model

### RAW.MATTERS
| Column | Type | Description |
|--------|------|-------------|
| MATTER_ID | VARCHAR | Primary key |
| PRACTICE_AREA | VARCHAR | M&A, Litigation, IP, Employment, Regulatory, Real Estate, Tax |
| STATUS | VARCHAR | Open, Closed, On Hold, In Review |
| OPEN_DATE | DATE | Matter opened |
| CLOSE_DATE | DATE | Matter closed (nullable) |
| LEAD_ATTORNEY | VARCHAR | Assigned internal attorney |
| LEAD_FIRM | VARCHAR | Outside counsel firm |
| PRIORITY | VARCHAR | High, Medium, Low |

### RAW.INVOICES
| Column | Type | Description |
|--------|------|-------------|
| INVOICE_ID | VARCHAR | Primary key |
| MATTER_ID | VARCHAR | Foreign key to MATTERS |
| VENDOR | VARCHAR | Law firm name |
| AMOUNT | NUMBER | Invoice amount USD |
| BUDGET_ALLOCATED | NUMBER | Per-invoice budget allocation |
| STATUS | VARCHAR | Approved, Pending, Disputed |

### RAW.CONTRACTS
| Column | Type | Description |
|--------|------|-------------|
| CONTRACT_ID | VARCHAR | Primary key |
| VENDOR | VARCHAR | Law firm name |
| END_DATE | DATE | Contract expiry date |
| RENEWAL_FLAG | VARCHAR | Yes / No |
| NOTES | VARCHAR | Free-text contract notes (Cortex SENTIMENT applied here) |

---

## Resume bullet

> Built a Snowflake-native legal analytics platform end to end: designed 4 dbt
> data models over synthetic matter management and outside counsel spend data,
> orchestrated load-to-transform via Airflow, and shipped a Streamlit
> conversational analytics dashboard using Snowflake Cortex SENTIMENT and
> COMPLETE for natural language Q&A on spend vs. budget and contract expiration
> risk; implemented secure views and row-level access policies for privileged
> legal data.

**Keywords hit:** Snowflake, Snowflake Cortex, dbt, Airflow, Streamlit,
data models, conversational analytics, outside counsel spend, matter management,
contract expiration, secure views, row-level security, privileged legal data,
data quality, stakeholder analytics.
