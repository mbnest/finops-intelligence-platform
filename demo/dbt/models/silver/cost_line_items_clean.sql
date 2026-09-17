-- Keeps only the latest delivery for each (provider, billing account, billing period), then conforms to the
-- canonical schema. Earlier deliveries of a restated period are dropped, never merged row by row, because
-- provider line item IDs aren't stable across deliveries (Build Specification §2).
with deliveries as (
    select
        *,
        cast(delivery as integer) as delivery_number,
        max(cast(delivery as integer)) over (partition by provider, BillingAccountId, billing_period) as latest_delivery_number
    from {{ ref('cost_line_items_raw') }}
),

latest as (
    select * from deliveries where delivery_number = latest_delivery_number
)

select
    md5(concat_ws('|', l.delivery_id, l.ChargePeriodStart, l.SubAccountId, coalesce(l.ResourceId, ''), l.SkuId,
        l.ChargeCategory, l.PricingCategory, coalesce(l.CommitmentDiscountId, ''), coalesce(l.CommitmentDiscountStatus, ''))) as line_item_key,
    l.provider,
    l.BillingAccountId as billing_account,
    l.billing_period,
    l.delivery_id,
    l.InvoiceId as invoice_id,
    l.SubAccountId as account_id,
    a.vertical_id,
    json_extract_string(l.Tags, '$.apm_id') as apm_id,
    json_extract_string(l.Tags, '$.environment') as environment,
    l.ChargeCategory as charge_category,
    l.ChargeFrequency as charge_frequency,
    l.PricingCategory as pricing_category,
    l.CommitmentDiscountId as commitment_discount_id,
    l.CommitmentDiscountType as commitment_discount_type,
    l.CommitmentDiscountStatus as commitment_discount_status,
    l.ServiceName as service_name,
    l.ServiceCategory as service_category,
    l.SkuId as sku_id,
    l.ResourceId as resource_id,
    l.RegionId as region_id,
    cast(l.BilledCost as double) as billed_cost,
    cast(l.EffectiveCost as double) as effective_cost,
    cast(l.ListCost as double) as list_cost,
    cast(l.ContractedCost as double) as contracted_cost,
    cast(l.ListUnitPrice as double) as list_unit_price,
    cast(l.ContractedUnitPrice as double) as contracted_unit_price,
    cast(l.ConsumedQuantity as double) as consumed_quantity,
    cast(l.PricingQuantity as double) as pricing_quantity,
    l.PricingUnit as pricing_unit,
    l.BillingCurrency as billing_currency,
    cast(l.ChargePeriodStart as timestamptz) as charge_period_start,
    cast(l.ChargePeriodEnd as timestamptz) as charge_period_end,
    cast(l.Tags as json) as canonical_tags
from latest as l
left join {{ ref('account_metadata') }} as a on l.SubAccountId = a.account_id
