-- Build Specification §2: silver's billed cost for a period equals bronze's total for the delivery silver kept.
with silver as (
    select provider, billing_account, billing_period, delivery_id, count(*) as row_count, sum(billed_cost) as billed_cost
    from {{ ref('cost_line_items_clean') }}
    group by all
),

bronze as (
    select delivery_id, count(*) as row_count, sum(cast(BilledCost as double)) as billed_cost
    from {{ ref('cost_line_items_raw') }}
    group by all
)

select s.*, b.row_count as bronze_row_count, b.billed_cost as bronze_billed_cost
from silver as s
join bronze as b using (delivery_id)
where s.row_count != b.row_count or abs(s.billed_cost - b.billed_cost) > 0.005
