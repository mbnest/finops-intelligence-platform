-- metric_spend_variance_mom: month-over-month change in total spend per vertical, split into
-- new resources, removed resources, usage change, price change, and charges with no resource.
-- For a resource billed in both periods: usage_change = (qty - prior_qty) * prior_unit_cost and
-- price_change = (unit_cost - prior_unit_cost) * qty, which sum exactly to its cost change.
with periods as (
    select billing_period, lag(billing_period) over (order by billing_period) as prior_period
    from (select distinct billing_period from {{ ref('fact_cost_daily') }})
),

by_resource as (
    select billing_period, vertical_id, coalesce(resource_id, '(no resource)') as resource_id,
        resource_id is null as is_other, sum(pricing_quantity) as qty, sum(effective_cost) as cost
    from {{ ref('fact_cost_daily') }}
    group by all
),

current_period as (
    select r.* from by_resource as r join periods as p using (billing_period) where p.prior_period is not null
),

prior_shifted as (
    select p.billing_period, r.vertical_id, r.resource_id, r.is_other, r.qty, r.cost
    from by_resource as r join periods as p on r.billing_period = p.prior_period
),

paired as (
    select
        coalesce(c.billing_period, pr.billing_period) as billing_period,
        coalesce(c.vertical_id, pr.vertical_id) as vertical_id,
        coalesce(c.is_other, pr.is_other) as is_other,
        c.qty, coalesce(c.cost, 0) as cost,
        pr.qty as prior_qty, coalesce(pr.cost, 0) as prior_cost,
        c.resource_id is not null as in_current,
        pr.resource_id is not null as in_prior
    from current_period as c
    full outer join prior_shifted as pr
        on c.billing_period = pr.billing_period and c.vertical_id = pr.vertical_id and c.resource_id = pr.resource_id
)

select
    billing_period,
    vertical_id,
    sum(prior_cost) as prior_spend,
    sum(cost) as current_spend,
    sum(cost) - sum(prior_cost) as spend_change,
    sum(case when not is_other and in_current and not in_prior then cost else 0 end) as new_resources,
    sum(case when not is_other and in_prior and not in_current then -prior_cost else 0 end) as removed_resources,
    sum(case when not is_other and in_current and in_prior then (qty - prior_qty) * (prior_cost / nullif(prior_qty, 0)) else 0 end) as usage_change,
    sum(case when not is_other and in_current and in_prior then (cost / nullif(qty, 0) - prior_cost / nullif(prior_qty, 0)) * qty else 0 end) as price_change,
    sum(case when is_other then cost - prior_cost else 0 end) as other_change
from paired
group by all
