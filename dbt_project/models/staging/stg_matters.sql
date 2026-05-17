-- models/staging/stg_matters.sql
--
-- Staging layer for MATTERS.
-- Cleans types, standardises nulls, adds computed fields.

with source as (

    select * from {{ source('raw', 'MATTERS') }}

),

staged as (

    select
        matter_id,
        matter_name,
        upper(trim(practice_area))                          as practice_area,
        initcap(trim(status))                               as status,
        open_date::date                                     as open_date,
        close_date::date                                    as close_date,
        initcap(trim(lead_attorney))                        as lead_attorney,
        trim(lead_firm)                                     as lead_firm,
        initcap(trim(priority))                             as priority,

        -- Derived: days the matter has been open
        case
            when status = 'Closed' and close_date is not null
                then datediff('day', open_date, close_date)
            else datediff('day', open_date, current_date)
        end                                                 as days_open,

        -- Derived: is this matter still active?
        case when status in ('Open', 'In Review') then true else false end
                                                            as is_active,

        created_at

    from source
    where matter_id is not null

)

select * from staged
