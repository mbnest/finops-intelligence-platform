-- metric_total_spend: SUM(effective_cost) by vertical, account, and billing period (amortized cost basis).
select
    billing_period,
    provider,
    vertical_id,
    account_id,
    sum(effective_cost) as total_spend
from {{ ref('fact_cost_daily') }}
group by all
