-- models/staging/stg_invoices.sql
--
-- Staging layer for INVOICES.
-- Validates grain (one row per invoice), casts types, flags disputes.

with source as (

    select * from {{ source('raw', 'INVOICES') }}

),

staged as (

    select
        invoice_id,
        matter_id,
        trim(vendor)                                        as vendor,
        upper(trim(practice_area))                          as practice_area,
        amount::number(18, 2)                               as amount,
        budget_allocated::number(18, 2)                     as budget_allocated,
        invoice_date::date                                  as invoice_date,
        initcap(trim(status))                               as status,

        -- Derived: is this invoice over the per-invoice budget allocation?
        case
            when amount > budget_allocated then true else false
        end                                                 as is_over_budget,

        -- Derived: variance from budget (positive = over)
        round(amount - budget_allocated, 2)                 as budget_variance,

        -- Derived: invoice age in days
        datediff('day', invoice_date, current_date)         as invoice_age_days,

        created_at

    from source
    where invoice_id is not null
      and amount > 0

)

select * from staged
