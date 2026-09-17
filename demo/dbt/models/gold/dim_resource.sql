-- One row per resource seen in billing data, with ownership from tags and the dates it was first and last billed.
select
    resource_id,
    any_value(provider) as provider,
    any_value(account_id) as account_id,
    any_value(apm_id) as apm_id,
    any_value(environment) as environment,
    lower(any_value(service_category)) as resource_type,
    arg_max(sku_id, charge_period_start) as sku_id,
    any_value(region_id) as region,
    min(cast(charge_period_start as date)) as created_date,
    max(cast(charge_period_start as date)) as last_billed_date
from {{ ref('cost_line_items_clean') }}
where resource_id is not null and charge_category = 'Usage'
group by resource_id
