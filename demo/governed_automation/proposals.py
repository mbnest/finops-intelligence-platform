"""Find idle resources and turn them into proposed actions.

An anomaly is investigated, not acted on, so the demo's proposals come from idle resources: cheap to
judge, reversible to fix, and the case automation exists for. Everything a policy needs to classify
the action travels with the proposal.
"""

from pathlib import Path

import yaml

from governed_automation import storage

CONFIG_PATH = Path(__file__).parent / "config.yaml"

IDLE_SQL = """
with utilization as (
    select resource_id, avg(cpu_avg_pct) as avg_cpu, count(*) as days
    from read_csv('data/reference/utilization_daily.csv', header = true)
    where date >= (select max(date) from gold.fact_cost_daily) - interval ($lookback) day
    group by resource_id
),

spend as (
    select resource_id, sum(effective_cost) / count(distinct date) as daily_cost
    from gold.fact_cost_daily
    where resource_id is not null and date >= (select max(date) from gold.fact_cost_daily) - interval ($lookback) day
    group by resource_id
)

select r.resource_id, r.apm_id, r.environment, r.account_id, a.vertical_id,
    round(u.avg_cpu, 1) as avg_cpu, round(s.daily_cost * 30, 2) as estimated_monthly_savings
from gold.dim_resource as r
join utilization as u using (resource_id)
join spend as s using (resource_id)
join gold.dim_account as a on a.account_id = r.account_id
where u.avg_cpu < $cpu_threshold and s.daily_cost >= $min_daily_cost
order by estimated_monthly_savings desc
"""


def load_config(path=CONFIG_PATH):
    return yaml.safe_load(Path(path).read_text())


def find_idle_resources(config=None):
    """Proposals to stop resources that have been running idle, one per resource."""
    config = config or load_config()
    rows = storage.cursor().execute(IDLE_SQL, {
        "lookback": config["idle"]["lookback_days"],
        "cpu_threshold": config["idle"]["cpu_threshold_pct"],
        "min_daily_cost": config["idle"]["min_daily_cost"],
    }).fetchall()
    return [{
        "proposal_id": f"PROP-idle-{resource_id}",
        "origin": "core_intelligence",
        "action": {"type": "stop", "snapshot_available": True},
        "target": {"resource_id": resource_id, "apm_id": apm_id, "environment": environment,
                   "account_id": account_id, "vertical_id": vertical_id, "blast_radius": 1},
        "evidence": {"avg_cpu_pct": avg_cpu, "estimated_monthly_savings": savings},
    } for resource_id, apm_id, environment, account_id, vertical_id, avg_cpu, savings in rows]
