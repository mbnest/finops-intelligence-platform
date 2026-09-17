-- metric_ri_sp_utilization: effective cost of used commitment over used plus unused, per commitment and billing period.
select
    billing_period,
    commitment_discount_id,
    sum(effective_cost) filter (where commitment_discount_status = 'Used') as used_cost,
    coalesce(sum(effective_cost) filter (where commitment_discount_status = 'Unused'), 0) as unused_cost,
    sum(effective_cost) filter (where commitment_discount_status = 'Used') / nullif(sum(effective_cost), 0) as utilization
from {{ ref('fact_cost_daily') }}
where charge_category = 'Usage'
    and commitment_discount_id is not null
group by all
