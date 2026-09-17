"""The data behind the MCP tools. Every query is scoped to the caller's verticals.

Answers come from the governed layer: metric definitions from the catalog, costs and anomalies from
gold. Nothing is computed a second way here, which is what makes a metric definition worth having.
"""

from pathlib import Path

import yaml

from governed_automation import storage

METRICS_PATH = Path(__file__).parent.parent / "dbt" / "metrics.yml"


def _scope_clause(persona, column="vertical_id"):
    if persona.sees_all_verticals():
        return "true", []
    placeholders = ", ".join("?" for _ in persona.verticals)
    return f"{column} in ({placeholders})", list(persona.verticals)


def metric_definition(metric_name):
    """The governed definition of a metric, for grounding an answer in the catalog."""
    metrics = yaml.safe_load(METRICS_PATH.read_text())["metrics"]
    for metric in metrics:
        if metric["name"] == metric_name:
            return metric
    raise KeyError(f"no metric named {metric_name}. Known metrics: {', '.join(m['name'] for m in metrics)}")


def cost_by_account(persona, account_id, billing_period=None):
    """Spend for one account, on the amortized basis every spend metric uses."""
    vertical = storage.cursor().execute(
        "select vertical_id from gold.dim_account where account_id = ?", [account_id]).fetchone()
    if vertical is None:
        raise KeyError(f"no account {account_id}")
    persona.check_vertical(vertical[0])

    clause = "and billing_period = ?" if billing_period else ""
    rows = storage.cursor().execute(f"""
        select billing_period, round(sum(effective_cost), 2) as effective_cost,
            round(sum(billed_cost), 2) as billed_cost, round(sum(list_cost), 2) as list_cost
        from gold.fact_cost_daily
        where account_id = ? {clause}
        group by billing_period order by billing_period
    """, [account_id] + ([billing_period] if billing_period else [])).fetchall()
    return {"account_id": account_id, "vertical_id": vertical[0], "cost_basis": "effective_cost (amortized)",
            "periods": [{"billing_period": p, "effective_cost": e, "billed_cost": b, "list_cost": l}
                        for p, e, b, l in rows]}


def anomalies(persona, limit=20):
    """Open anomalies the caller is allowed to see, newest first."""
    clause, params = _scope_clause(persona)
    rows = storage.cursor().execute(f"""
        select anomaly_id, detected_date, resource_id, vertical_id, severity, dollar_impact, contributing_factors
        from gold.fact_anomaly where {clause}
        order by detected_date desc limit ?
    """, params + [limit]).fetchall()
    return [{"anomaly_id": a, "detected_date": str(d), "resource_id": r, "vertical_id": v,
             "severity": s, "dollar_impact": impact, "contributing_factors": factors}
            for a, d, r, v, s, impact, factors in rows]


def spend_variance(persona, billing_period):
    """Why spend changed, split into causes that add up to the total change."""
    clause, params = _scope_clause(persona)
    rows = storage.cursor().execute(f"""
        select vertical_id, round(prior_spend, 2), round(current_spend, 2), round(spend_change, 2),
            round(new_resources, 2), round(removed_resources, 2), round(usage_change, 2),
            round(price_change, 2), round(other_change, 2)
        from semantic.metric_spend_variance_mom
        where billing_period = ? and {clause}
        order by abs(spend_change) desc
    """, [billing_period] + params).fetchall()
    keys = ["vertical_id", "prior_spend", "current_spend", "spend_change", "new_resources",
            "removed_resources", "usage_change", "price_change", "other_change"]
    return {"billing_period": billing_period, "metric": "metric_spend_variance_mom",
            "verticals": [dict(zip(keys, row)) for row in rows]}


def idle_resource(persona, resource_id):
    """The proposal for one idle resource, checked against the caller's scope."""
    from governed_automation.proposals import find_idle_resources

    for proposal in find_idle_resources():
        if proposal["target"]["resource_id"] == resource_id:
            persona.check_vertical(proposal["target"]["vertical_id"])
            return proposal
    raise KeyError(f"{resource_id} is not currently proposed for an action")
