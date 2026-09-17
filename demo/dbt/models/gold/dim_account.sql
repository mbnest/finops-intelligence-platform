select account_id, vertical_id, provider, billing_account, account_name
from {{ ref('account_metadata') }}
