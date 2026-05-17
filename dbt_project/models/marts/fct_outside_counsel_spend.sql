-- models/marts/fct_outside_counsel_spend.sql
--
-- Core fact model for outside counsel spend analytics.
-- Aggregates spend vs. budget by vendor + practice area.
-- Powers the GC spend dashboard and Snowflake Cortex Q&A.

with invoices as (

    select * from {{ ref('stg_invoices') }}

),

spend_by_vendor_practice as (

    select
        vendor,
        practice_area,

        -- Volume
        count(distinct invoice_id)              as invoice_count,
        count(distinct matter_id)               as matter_count,

        -- Spend
        sum(amount)                             as total_spend,
        sum(budget_allocated)                   as total_budget,
        sum(budget_variance)                    as total_budget_variance,

        -- Over-budget metrics
        sum(case when is_over_budget then 1 else 0 end)
                                                as over_budget_invoice_count,
        round(
            100.0 * sum(case when is_over_budget then 1 else 0 end)
            / nullif(count(*), 0), 1
        )                                       as pct_invoices_over_budget,

        -- Disputed invoices
        sum(case when status = 'Disputed' then 1 else 0 end)
                                                as disputed_invoice_count,
        sum(case when status = 'Disputed' then amount else 0 end)
                                                as disputed_amount,

        -- Efficiency
        round(sum(amount) / nullif(count(distinct matter_id), 0), 2)
                                                as avg_spend_per_matter,

        -- Latest activity
        max(invoice_date)                       as latest_invoice_date

    from invoices
    group by 1, 2

),

with_flags as (

    select
        *,

        -- Spend vs budget ratio
        round(total_spend / nullif(total_budget, 0), 3)     as spend_budget_ratio,

        -- Traffic light status
        case
            when total_spend / nullif(total_budget, 0) > 1.15  then 'Over Budget'
            when total_spend / nullif(total_budget, 0) > 1.00  then 'At Risk'
            when total_spend / nullif(total_budget, 0) > 0.85  then 'On Track'
            else 'Under Budget'
        end                                                  as budget_status,

        -- Rank by total spend within each practice area
        rank() over (
            partition by practice_area
            order by total_spend desc
        )                                                    as spend_rank_in_practice_area

    from spend_by_vendor_practice

)

select * from with_flags
order by practice_area, total_spend desc
