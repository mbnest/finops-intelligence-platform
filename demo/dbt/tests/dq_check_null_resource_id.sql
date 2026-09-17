-- Build Specification §2: usage with no resource_id is allowed only for charges that have no resource
-- (account-level support and unused commitment).
select *
from {{ ref('cost_line_items_clean') }}
where charge_category = 'Usage'
    and resource_id is null
    and commitment_discount_status is distinct from 'Unused'
    and service_category != 'Management and Governance'
