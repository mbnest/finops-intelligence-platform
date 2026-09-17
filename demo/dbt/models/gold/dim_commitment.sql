-- Commitment inventory with expiry dates (Build Specification §3). Input to RI/SP planning.
select
    commitment_discount_id,
    provider,
    billing_account,
    commitment_type,
    scope,
    cast(term_months as integer) as term_months,
    payment_option,
    cast(daily_commitment as double) / 24 as hourly_commitment,
    cast(start_date as date) as start_date,
    cast(end_date as date) as end_date
from {{ ref('commitment_inventory') }}
