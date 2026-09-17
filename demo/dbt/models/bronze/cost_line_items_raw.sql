-- Every delivery exactly as landed. Provider, billing period, and delivery come from the landing path.
select
    *,
    provider || '/' || billing_period || '/' || delivery as delivery_id,
    now() as ingested_at
from read_csv(
    '{{ var("data_dir") }}/landing/focus/*/*/*/focus.csv',
    hive_partitioning = true,
    filename = true,
    all_varchar = true
)
