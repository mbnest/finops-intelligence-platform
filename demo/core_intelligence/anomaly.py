"""Cost anomaly detection: a robust z score against each resource's own trailing baseline.

Deliberately simple and explainable (MLOps Pipeline ADR-002): a day is flagged when it sits far from
the median of that resource's recent days, measured in median absolute deviations, and the dollar
difference is large enough to be worth someone's time. Every flag carries the numbers behind it.

In the design this runs as a Snowpark batch job writing gold.fact_anomaly. Here it is Python over DuckDB.
"""

import json
from dataclasses import dataclass, field
from datetime import date
from statistics import median
from pathlib import Path

import duckdb
import yaml

CONFIG_PATH = Path(__file__).parent / "config.yaml"
DB_PATH = "data/warehouse.duckdb"
MAD_TO_SIGMA = 0.6745  # scales the median absolute deviation to a standard-deviation-like number


@dataclass
class Episode:
    """Consecutive flagged days for one resource, reported as a single anomaly."""

    resource_id: str
    start_date: date
    end_date: date
    days: int
    total_impact: float
    peak_impact: float
    peak_robust_z: float
    baseline_cost: float
    account_id: str
    vertical_id: str
    service_name: str

    @property
    def severity(self):
        if self.peak_robust_z >= 10 or self.total_impact >= 1000:
            return "high"
        return "medium" if self.peak_robust_z >= 6 or self.total_impact >= 250 else "low"

    @property
    def contributing_factors(self):
        return {
            "baseline_cost": round(self.baseline_cost, 2), "peak_dollar_impact": round(self.peak_impact, 2),
            "total_dollar_impact": round(self.total_impact, 2), "days_observed": self.days,
            "peak_robust_z": None if self.peak_robust_z == float("inf") else round(self.peak_robust_z, 2),
            "last_observed_date": str(self.end_date),
        }


@dataclass
class Flag:
    """One flagged day for one resource."""

    resource_id: str
    detected_date: date
    observed_cost: float
    baseline_cost: float
    robust_z: float
    dollar_impact: float
    account_id: str = ""
    vertical_id: str = ""
    service_name: str = ""
    contributing_factors: dict = field(default_factory=dict)


def load_config(path=CONFIG_PATH):
    return yaml.safe_load(Path(path).read_text())


def daily_series(con):
    """Daily effective cost per resource, with the attributes a flag needs."""
    rows = con.sql("""
        select resource_id, date, sum(effective_cost) as cost,
            any_value(account_id) as account_id, any_value(vertical_id) as vertical_id,
            any_value(service_name) as service_name
        from gold.fact_cost_daily
        where resource_id is not null and charge_category = 'Usage'
        group by resource_id, date
        order by resource_id, date
    """).fetchall()
    series = {}
    for resource_id, day, cost, account_id, vertical_id, service_name in rows:
        series.setdefault(resource_id, []).append(
            {"date": day, "cost": cost, "account_id": account_id, "vertical_id": vertical_id, "service_name": service_name}
        )
    return series


def robust_z(observed, history):
    """Robust z score of observed against history, and the baseline it was compared with.

    Uses the median absolute deviation instead of a standard deviation, so one earlier spike in the
    window can't hide the next one. When history is perfectly flat, any difference is treated as
    infinitely surprising and the dollar threshold decides whether it gets flagged.
    """
    baseline = median(history)
    mad = median([abs(x - baseline) for x in history])
    if mad == 0:
        return (float("inf") if observed != baseline else 0.0), baseline
    return (observed - baseline) * MAD_TO_SIGMA / mad, baseline


def detect(series, config):
    """Flag days whose cost is far from the resource's trailing baseline and materially expensive."""
    settings = config["detector"]
    flags = []
    for resource_id, points in series.items():
        for i, point in enumerate(points):
            history = [p["cost"] for p in points[max(0, i - settings["window_days"]):i]]
            if len(history) < settings["min_history_days"]:
                continue
            score, baseline = robust_z(point["cost"], history)
            impact = point["cost"] - baseline
            if score >= settings["min_robust_z"] and impact >= settings["min_dollar_impact"]:
                flags.append(Flag(
                    resource_id=resource_id, detected_date=point["date"], observed_cost=point["cost"],
                    baseline_cost=baseline, robust_z=score, dollar_impact=impact,
                    account_id=point["account_id"], vertical_id=point["vertical_id"], service_name=point["service_name"],
                    contributing_factors={
                        "baseline_cost": round(baseline, 2), "observed_cost": round(point["cost"], 2),
                        "robust_z": None if score == float("inf") else round(score, 2),
                        "dollar_impact": round(impact, 2), "window_days": settings["window_days"],
                    },
                ))
    return flags


def baseline_detect(series, config):
    """The naive comparison: flag any day above a fixed multiple of the trailing mean."""
    settings = config["baseline"]
    flags = []
    for resource_id, points in series.items():
        for i, point in enumerate(points):
            history = [p["cost"] for p in points[max(0, i - settings["window_days"]):i]]
            if not history:
                continue
            mean = sum(history) / len(history)
            if point["cost"] > mean * settings["multiple"] and point["cost"] - mean >= settings["min_dollar_impact"]:
                flags.append(Flag(
                    resource_id=resource_id, detected_date=point["date"], observed_cost=point["cost"],
                    baseline_cost=mean, robust_z=0.0, dollar_impact=point["cost"] - mean,
                    account_id=point["account_id"], vertical_id=point["vertical_id"], service_name=point["service_name"],
                ))
    return flags


def to_episodes(flags, gap_days):
    """Collapse consecutive flagged days into one episode per resource.

    A step change or a ramp stays anomalous for weeks. Alerting every day would bury the team,
    which is the failure mode the alert-volume gate exists to catch, so a continuing condition is
    one anomaly that keeps accumulating impact.
    """
    episodes = []
    for resource_id in sorted({f.resource_id for f in flags}):
        for flag in sorted([f for f in flags if f.resource_id == resource_id], key=lambda f: f.detected_date):
            open_episode = episodes[-1] if episodes and episodes[-1].resource_id == resource_id else None
            if open_episode and (flag.detected_date - open_episode.end_date).days <= gap_days:
                open_episode.end_date = flag.detected_date
                open_episode.days += 1
                open_episode.total_impact += flag.dollar_impact
                open_episode.peak_impact = max(open_episode.peak_impact, flag.dollar_impact)
                open_episode.peak_robust_z = max(open_episode.peak_robust_z, flag.robust_z)
            else:
                episodes.append(Episode(
                    resource_id=resource_id, start_date=flag.detected_date, end_date=flag.detected_date, days=1,
                    total_impact=flag.dollar_impact, peak_impact=flag.dollar_impact, peak_robust_z=flag.robust_z,
                    baseline_cost=flag.baseline_cost, account_id=flag.account_id, vertical_id=flag.vertical_id,
                    service_name=flag.service_name,
                ))
    return episodes


def write_fact_anomaly(con, episodes, model_version):
    """Replace gold.fact_anomaly for this model version, the way a batch scoring job would."""
    con.sql("""
        create table if not exists gold.fact_anomaly (
            anomaly_id varchar, resource_id varchar, account_id varchar, vertical_id varchar,
            service_name varchar, detected_date date, severity varchar, dollar_impact double,
            model_version varchar, contributing_factors json,
            disposition varchar, dispositioned_by varchar, dispositioned_at timestamp
        )
    """)
    con.execute("delete from gold.fact_anomaly where model_version = ?", [model_version])
    con.executemany(
        "insert into gold.fact_anomaly values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, null, null, null)",
        [[f"ANOM-{e.resource_id}-{e.start_date}", e.resource_id, e.account_id, e.vertical_id, e.service_name,
          e.start_date, e.severity, round(e.total_impact, 2), model_version, json.dumps(e.contributing_factors)]
         for e in episodes],
    )


def main():
    config = load_config()
    con = duckdb.connect(DB_PATH)
    con.sql("set TimeZone = 'UTC'")
    episodes = to_episodes(detect(daily_series(con), config), config["detector"]["episode_gap_days"])
    write_fact_anomaly(con, episodes, config["model_version"])
    print(f"{len(episodes)} anomalies written to gold.fact_anomaly (model_version {config['model_version']})")
    for e in sorted(episodes, key=lambda e: e.start_date):
        print(f"  {e.start_date} to {e.end_date}  {e.resource_id:<32} {e.severity:<6} "
              f"{e.days:>2}d  impact ${e.total_impact:,.0f}")


if __name__ == "__main__":
    main()
