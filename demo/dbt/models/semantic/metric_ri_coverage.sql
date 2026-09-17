-- metric_ri_coverage: share of commitment-eligible usage cost (compute usage on a resource) covered by a commitment.
select
    billing_period,
    provider,
    sum(effective_cost) filter (where pricing_category = 'Committed') as committed_cost,
    sum(effective_cost) as eligible_cost,
    coalesce(sum(effective_cost) filter (where pricing_category = 'Committed'), 0) / nullif(sum(effective_cost), 0) as ri_coverage
from {{ ref('fact_cost_daily') }}
where charge_category = 'Usage'
    and service_category = 'Compute'
    and resource_id is not null
group by all
