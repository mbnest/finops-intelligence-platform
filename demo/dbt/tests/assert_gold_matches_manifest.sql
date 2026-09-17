-- Gold totals per provider and billing period match the generator's independently computed expected totals
-- for the latest delivery (data/manifest.json).
with expected as (
    select unnest(expected_totals, recursive := true)
    from read_json_auto('{{ var("data_dir") }}/manifest.json')
),

actual as (
    select provider, billing_period, sum(billed_cost) as billed_cost, sum(effective_cost) as effective_cost,
        sum(list_cost) as list_cost, sum(contracted_cost) as contracted_cost
    from {{ ref('fact_cost_daily') }}
    group by all
)

select e.provider, e.billing_period, a.provider is null as missing_in_gold
from expected as e
left join actual as a on a.provider = e.provider and a.billing_period = e.billing_period
where a.provider is null
    or abs(a.billed_cost - e.BilledCost) > 0.01
    or abs(a.effective_cost - e.EffectiveCost) > 0.01
    or abs(a.list_cost - e.ListCost) > 0.01
    or abs(a.contracted_cost - e.ContractedCost) > 0.01
