-- models/marts/fct_matter_backlog.sql
--
-- Matter backlog fact model.
-- Surfaces open matter volume, age, and attorney workload
-- so practice area leads can see where task backlogs are building.

with matters as (

    select * from {{ ref('stg_matters') }}

),

invoices as (

    select
        matter_id,
        sum(amount)         as total_invoiced,
        max(invoice_date)   as last_invoice_date
    from {{ ref('stg_invoices') }}
    group by 1

),

joined as (

    select
        m.matter_id,
        m.matter_name,
        m.practice_area,
        m.status,
        m.priority,
        m.lead_attorney,
        m.lead_firm,
        m.open_date,
        m.close_date,
        m.days_open,
        m.is_active,
        coalesce(i.total_invoiced, 0)       as total_invoiced,
        i.last_invoice_date

    from matters m
    left join invoices i on m.matter_id = i.matter_id

),

backlog_summary as (

    select
        practice_area,
        status,
        priority,
        lead_attorney,

        count(matter_id)                                    as matter_count,
        sum(case when is_active then 1 else 0 end)          as active_matter_count,

        -- Backlog age buckets
        sum(case when days_open > 365 then 1 else 0 end)    as matters_over_1yr,
        sum(case when days_open between 180 and 365
                 then 1 else 0 end)                         as matters_6mo_to_1yr,
        sum(case when days_open < 180 then 1 else 0 end)    as matters_under_6mo,

        round(avg(days_open), 0)                            as avg_days_open,
        max(days_open)                                      as max_days_open,

        sum(total_invoiced)                                 as total_invoiced,
        round(avg(total_invoiced), 2)                       as avg_invoiced_per_matter

    from joined
    group by 1, 2, 3, 4

)

select
    *,

    -- Workload intensity score (higher = more overloaded attorney)
    round(
        (active_matter_count * 1.0) + (matters_over_1yr * 0.5),
        1
    )                                                       as workload_score,

    -- Flag stale matters for partner review
    -- Note: status here refers to the grouped status value from backlog_summary
    case
        when avg_days_open > 270 and status = 'Open'
        then true else false
    end                                                     as flag_stale,

    -- Convenience flag: is this group actively open?
    case when status in ('Open', 'In Review') then true else false end
                                                            as is_active

from backlog_summary
order by practice_area, priority desc, avg_days_open desc
