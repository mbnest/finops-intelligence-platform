select apm_id, name as application_name, vertical_id, owner, secondary_approver
from {{ ref('apm_application_metadata') }}
