-- Grain: one row per day, account, resource, SKU, charge category, pricing category, and commitment (Build Specification §3).
-- The four cost columns stay separate; see the cost basis table in Build Specification §3.
select
    cast(charge_period_start as date) as date,
    billing_period,
    invoice_id,
    provider,
    account_id,
    vertical_id,
    apm_id,
    resource_id,
    service_name,
    service_category,
    sku_id,
    charge_category,
    pricing_category,
    commitment_discount_id,
    commitment_discount_status,
    sum(billed_cost) as billed_cost,
    sum(effective_cost) as effective_cost,
    sum(list_cost) as list_cost,
    sum(contracted_cost) as contracted_cost,
    sum(consumed_quantity) as consumed_quantity,
    sum(pricing_quantity) as pricing_quantity
from {{ ref('cost_line_items_clean') }}
group by all
