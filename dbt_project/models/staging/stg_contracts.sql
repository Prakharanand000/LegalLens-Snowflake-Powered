-- models/staging/stg_contracts.sql
--
-- Staging layer for CONTRACTS.
-- Computes expiry windows and uses Snowflake Cortex SENTIMENT()
-- to score contract notes — negative sentiment flags at-risk renewals.

with source as (

    select * from {{ source('raw', 'CONTRACTS') }}

),

staged as (

    select
        contract_id,
        trim(vendor)                                        as vendor,
        upper(trim(practice_area))                          as practice_area,
        start_date::date                                    as start_date,
        end_date::date                                      as end_date,
        annual_value::number(18, 2)                         as annual_value,
        upper(trim(renewal_flag))                           as renewal_flag,
        trim(notes)                                         as notes,

        -- Days until expiry (negative = already expired)
        datediff('day', current_date, end_date)             as days_until_expiry,

        -- Expiry risk bucket
        case
            when datediff('day', current_date, end_date) < 0
                then 'Expired'
            when datediff('day', current_date, end_date) <= 30
                then 'Critical (< 30 days)'
            when datediff('day', current_date, end_date) <= 60
                then 'High (30-60 days)'
            when datediff('day', current_date, end_date) <= 90
                then 'Medium (60-90 days)'
            else 'Low (> 90 days)'
        end                                                 as expiry_risk,

        -- Snowflake Cortex: sentiment score on contract notes
        -- Returns a value between -1.0 (very negative) and 1.0 (very positive)
        snowflake.cortex.sentiment(notes)                   as notes_sentiment_score,

        -- Derived flag: flag contracts with negative note sentiment for GC review
        case
            when snowflake.cortex.sentiment(notes) < -0.1 then true
            else false
        end                                                 as flag_for_gc_review,

        created_at

    from source
    where contract_id is not null

)

select * from staged
