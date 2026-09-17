-- metric_spend_variance_mom: the components explain the whole change, with nothing left over.
select *
from {{ ref('metric_spend_variance_mom') }}
where abs(spend_change - (new_resources + removed_resources + usage_change + price_change + other_change)) > 0.01
