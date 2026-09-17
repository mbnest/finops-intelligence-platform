-- Cost basis: on usage rows for a resource, effective <= contracted <= list. Discounts can only lower cost.
select *
from {{ ref('cost_line_items_clean') }}
where charge_category = 'Usage'
    and resource_id is not null
    and (effective_cost > contracted_cost + 0.000001 or contracted_cost > list_cost + 0.000001)
