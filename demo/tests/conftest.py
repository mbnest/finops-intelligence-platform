"""Shared fixtures.

Governed Automation keeps real state: the kill switch, exclusions, and an audit trail that the rolling
run caps count. Tests share that state with the demo, so each test starts from a known position.
"""

import pytest

from core_intelligence import anomaly
from governed_automation import storage


@pytest.fixture(scope="session", autouse=True)
def detected_anomalies():
    """Make sure anomalies have been scored.

    Regenerating the dataset rebuilds the warehouse, and gold.fact_anomaly is written by the detector
    rather than by dbt, so a suite run straight after `dbt build` would otherwise test an empty table.
    """
    con = storage.cursor()
    exists = con.execute("""
        select count(*) from information_schema.tables
        where table_schema = 'gold' and table_name = 'fact_anomaly'
    """).fetchone()[0]
    if not exists or con.execute("select count(*) from gold.fact_anomaly").fetchone()[0] == 0:
        config = anomaly.load_config()
        episodes = anomaly.to_episodes(
            anomaly.detect(anomaly.daily_series(con), config), config["detector"]["episode_gap_days"])
        anomaly.write_fact_anomaly(con, episodes, config["model_version"])
    yield


@pytest.fixture(autouse=True)
def clean_automation_state():
    """Automation on globally, no exclusions, and an empty audit so run caps start from zero."""
    storage.connection()
    con = storage.cursor()
    con.execute("delete from automation_controls where scope_type != 'global'")
    storage.set_automation_enabled("global", None, True, "test reset")
    con.execute("delete from automation_exclusions")
    con.execute("delete from fact_action_audit")
    yield
