-- With no-upfront commitments, amortization moves cost between rows but not between periods:
-- total billed cost equals total effective cost for each provider and billing period.
select provider, billing_period, sum(billed_cost) as billed_cost, sum(effective_cost) as effective_cost
from {{ ref('fact_cost_daily') }}
group by all
having abs(sum(billed_cost) - sum(effective_cost)) > 0.01
