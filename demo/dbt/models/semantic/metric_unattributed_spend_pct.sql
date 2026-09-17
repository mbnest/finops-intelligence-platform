-- metric_unattributed_spend_pct: effective cost with no resolved APM ID, as a share of total spend. Weighted by dollars.
select
    billing_period,
    coalesce(sum(effective_cost) filter (where apm_id is null), 0) as unattributed_spend,
    sum(effective_cost) as total_spend,
    coalesce(sum(effective_cost) filter (where apm_id is null), 0) / nullif(sum(effective_cost), 0) as unattributed_spend_pct
from {{ ref('fact_cost_daily') }}
group by all
