-- Build Specification §2: silver holds exactly one delivery per (provider, billing account, billing period).
select provider, billing_account, billing_period, count(distinct delivery_id) as deliveries
from {{ ref('cost_line_items_clean') }}
group by all
having count(distinct delivery_id) > 1
