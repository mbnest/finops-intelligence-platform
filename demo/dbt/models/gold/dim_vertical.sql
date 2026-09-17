select vertical_id, vertical_name, cost_center
from {{ ref('vertical_metadata') }}
