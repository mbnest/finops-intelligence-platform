"""Print the queries from the README's "What to look for" section, with their results.

Run after `dbt build`: uv run python tour.py
"""

import duckdb

QUERIES = [
    ("1. Four cost columns, one commitment-covered resource",
     "This resource is partly covered by the savings plan. The Committed row bills nothing and carries "
     "amortized cost; the Standard row bills what it costs. List is public price, contracted is after the "
     "negotiated discount. One cost column could not answer all of these.",
     """
     select date, pricing_category, commitment_discount_status,
         round(list_cost, 2) as list_cost, round(contracted_cost, 2) as contracted_cost,
         round(billed_cost, 2) as billed_cost, round(effective_cost, 2) as effective_cost
     from gold.fact_cost_daily
     where resource_id = 'aws-ec2-pricing-workers' and date = '2026-05-12'
     order by pricing_category
     """),
    ("2. A restated billing period keeps one delivery",
     "Azure delivered 2026-05 twice. Bronze keeps both for audit; silver keeps only delivery 2, "
     "so gold reflects the corrected rates.",
     """
     select 'bronze' as layer, delivery_id, count(*) as rows, round(sum(cast(BilledCost as double)), 2) as billed_cost
     from bronze.cost_line_items_raw
     where provider = 'azure' and billing_period = '2026-05'
     group by all
     union all
     select 'silver', delivery_id, count(*), round(sum(billed_cost), 2)
     from silver.cost_line_items_clean
     where provider = 'azure' and billing_period = '2026-05'
     group by all
     order by layer, delivery_id
     """),
    ("3. Commitment coverage and utilization",
     "The Azure reservation is fully used until a covered VM is removed on 2026-05-15, then part of it "
     "is paid for and unused. That is the difference between coverage and utilization.",
     """
     select billing_period, commitment_discount_id,
         round(used_cost, 2) as used_cost, round(unused_cost, 2) as unused_cost,
         round(utilization, 3) as utilization
     from semantic.metric_ri_sp_utilization
     order by commitment_discount_id, billing_period
     """),
    ("4. Why did this vertical's bill change?",
     "The month-over-month change is split into causes that sum exactly to it: a new GPU resource in "
     "finance in June, a removed resource in project management, usage change, and price change "
     "(the May restatement).",
     """
     select billing_period, vertical_id,
         round(prior_spend, 0) as prior_spend, round(current_spend, 0) as current_spend,
         round(spend_change, 1) as spend_change, round(new_resources, 1) as new_resources,
         round(removed_resources, 1) as removed_resources, round(usage_change, 1) as usage_change,
         round(price_change, 1) as price_change, round(other_change, 1) as other_change
     from semantic.metric_spend_variance_mom
     where vertical_id in ('finance', 'delivery')
     order by billing_period, vertical_id
     """),
]


def main():
    con = duckdb.connect("data/warehouse.duckdb", read_only=True)
    con.sql("set TimeZone = 'UTC'")
    for title, note, sql in QUERIES:
        print(f"\n{title}\n{note}\n")
        con.sql(sql).show(max_width=200)


if __name__ == "__main__":
    main()
