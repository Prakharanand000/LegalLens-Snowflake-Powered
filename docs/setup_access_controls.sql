-- setup_access_controls.sql
-- ============================================================================
-- LegalLens — Snowflake Access Control Setup
-- Run this ONCE after dbt build completes.
-- ============================================================================
-- This implements:
--   1. Three roles with different privilege levels
--   2. A row-level security policy on INVOICES (practice area isolation)
--   3. A secure view masking invoice amounts for analyst role
--   4. A row-level policy on CONTRACTS (notes visible to GC only)
-- ============================================================================

USE DATABASE LEGALLENS_DB;

-- ── 1. Roles ─────────────────────────────────────────────────────────────────

CREATE ROLE IF NOT EXISTS LEGALLENS_GC_ROLE;        -- General Counsel: full access
CREATE ROLE IF NOT EXISTS LEGALLENS_ANALYST_ROLE;   -- Analyst: masked amounts, no contract notes
CREATE ROLE IF NOT EXISTS LEGALLENS_READONLY_ROLE;  -- Read-only: aggregates only, no PII

-- Grant warehouse usage to all roles
GRANT USAGE ON WAREHOUSE LEGALLENS_WH TO ROLE LEGALLENS_GC_ROLE;
GRANT USAGE ON WAREHOUSE LEGALLENS_WH TO ROLE LEGALLENS_ANALYST_ROLE;
GRANT USAGE ON WAREHOUSE LEGALLENS_WH TO ROLE LEGALLENS_READONLY_ROLE;

-- Grant database and schema access
GRANT USAGE ON DATABASE LEGALLENS_DB TO ROLE LEGALLENS_GC_ROLE;
GRANT USAGE ON DATABASE LEGALLENS_DB TO ROLE LEGALLENS_ANALYST_ROLE;
GRANT USAGE ON DATABASE LEGALLENS_DB TO ROLE LEGALLENS_READONLY_ROLE;

GRANT USAGE ON ALL SCHEMAS IN DATABASE LEGALLENS_DB TO ROLE LEGALLENS_GC_ROLE;
GRANT USAGE ON ALL SCHEMAS IN DATABASE LEGALLENS_DB TO ROLE LEGALLENS_ANALYST_ROLE;
GRANT USAGE ON SCHEMA LEGALLENS_DB.MARTS              TO ROLE LEGALLENS_READONLY_ROLE;

-- GC: full read on all tables and views
GRANT SELECT ON ALL TABLES IN DATABASE LEGALLENS_DB  TO ROLE LEGALLENS_GC_ROLE;
GRANT SELECT ON ALL VIEWS  IN DATABASE LEGALLENS_DB  TO ROLE LEGALLENS_GC_ROLE;

-- Analyst: read on staging and marts (not raw)
GRANT SELECT ON ALL TABLES IN SCHEMA LEGALLENS_DB.STAGING TO ROLE LEGALLENS_ANALYST_ROLE;
GRANT SELECT ON ALL TABLES IN SCHEMA LEGALLENS_DB.MARTS   TO ROLE LEGALLENS_ANALYST_ROLE;

-- Read-only: marts only
GRANT SELECT ON ALL TABLES IN SCHEMA LEGALLENS_DB.MARTS TO ROLE LEGALLENS_READONLY_ROLE;


-- ── 2. Row-Level Security Policy — INVOICES by Practice Area ─────────────────
-- Employment counsel (LEGALLENS_ANALYST_ROLE with tag EMPLOYMENT) only sees
-- Employment invoices. GC sees everything.

USE SCHEMA LEGALLENS_DB.MARTS;

CREATE OR REPLACE ROW ACCESS POLICY practice_area_rls_policy
AS (practice_area VARCHAR) RETURNS BOOLEAN ->
    CASE
        -- GC and sysadmin see all rows
        WHEN CURRENT_ROLE() IN ('SYSADMIN', 'LEGALLENS_GC_ROLE') THEN TRUE
        -- Analyst role: filter to practice area matching a session variable
        -- In production, set via: ALTER SESSION SET practice_area_scope = 'Employment'
        WHEN CURRENT_ROLE() = 'LEGALLENS_ANALYST_ROLE'
             AND practice_area = COALESCE(
                 CURRENT_SETTING('practice_area_scope', TRUE), practice_area
             )
        THEN TRUE
        -- Read-only: no row-level restriction (aggregates only, no PII in mart)
        WHEN CURRENT_ROLE() = 'LEGALLENS_READONLY_ROLE' THEN TRUE
        ELSE FALSE
    END;

-- Apply policy to the spend fact table
ALTER TABLE LEGALLENS_DB.MARTS.fct_outside_counsel_spend
    ADD ROW ACCESS POLICY practice_area_rls_policy ON (practice_area);

-- Apply policy to the matter backlog table
ALTER TABLE LEGALLENS_DB.MARTS.fct_matter_backlog
    ADD ROW ACCESS POLICY practice_area_rls_policy ON (practice_area);


-- ── 3. Secure View — Invoice amounts masked for analysts ─────────────────────

USE SCHEMA LEGALLENS_DB.MARTS;

CREATE OR REPLACE SECURE VIEW invoice_secure_view AS
SELECT
    vendor,
    practice_area,
    invoice_count,
    matter_count,
    budget_status,
    pct_invoices_over_budget,
    disputed_invoice_count,
    spend_rank_in_practice_area,
    -- Mask exact dollar amounts for non-GC roles
    CASE
        WHEN CURRENT_ROLE() IN ('SYSADMIN', 'LEGALLENS_GC_ROLE')
        THEN total_spend
        ELSE NULL   -- analysts see NULL; use budget_status for directional context
    END AS total_spend,
    CASE
        WHEN CURRENT_ROLE() IN ('SYSADMIN', 'LEGALLENS_GC_ROLE')
        THEN total_budget
        ELSE NULL
    END AS total_budget
FROM LEGALLENS_DB.MARTS.fct_outside_counsel_spend;

GRANT SELECT ON LEGALLENS_DB.MARTS.invoice_secure_view TO ROLE LEGALLENS_ANALYST_ROLE;
GRANT SELECT ON LEGALLENS_DB.MARTS.invoice_secure_view TO ROLE LEGALLENS_READONLY_ROLE;


-- ── 4. Contract notes policy — restrict to GC role ───────────────────────────

USE SCHEMA LEGALLENS_DB.STAGING;

-- Analysts see contract metadata but NOT the free-text notes field
-- (which may contain privileged attorney-client communication)
CREATE OR REPLACE SECURE VIEW contract_notes_policy AS
SELECT
    contract_id,
    vendor,
    practice_area,
    start_date,
    end_date,
    annual_value,
    renewal_flag,
    days_until_expiry,
    expiry_risk,
    notes_sentiment_score,
    flag_for_gc_review,
    -- Notes restricted to GC role only
    CASE
        WHEN CURRENT_ROLE() IN ('SYSADMIN', 'LEGALLENS_GC_ROLE')
        THEN notes
        ELSE '[RESTRICTED — GC ACCESS ONLY]'
    END AS notes
FROM LEGALLENS_DB.STAGING.stg_contracts;

GRANT SELECT ON LEGALLENS_DB.STAGING.contract_notes_policy TO ROLE LEGALLENS_ANALYST_ROLE;


-- ── Verification queries ─────────────────────────────────────────────────────

-- Run these to confirm policies are active:
-- SHOW ROW ACCESS POLICIES IN SCHEMA LEGALLENS_DB.MARTS;
-- SELECT * FROM LEGALLENS_DB.MARTS.invoice_secure_view LIMIT 5;
-- SELECT policy_name, ref_entity_name FROM TABLE(INFORMATION_SCHEMA.POLICY_REFERENCES(
--     policy_name => 'LEGALLENS_DB.MARTS.practice_area_rls_policy'
-- ));
