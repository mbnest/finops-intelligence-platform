"""State for Governed Automation: the tables the design keeps in managed Postgres (Build Specification §6).

Here they live in the same DuckDB file as gold, which keeps the demo to one store. The shapes and names
match the specification: contracts, automation_controls, automation_exclusions, and the action audit.
"""

import json
import threading
from datetime import datetime, timedelta, timezone

import duckdb

DB_PATH = "data/warehouse.duckdb"
_connection = None
_lock = threading.Lock()


def _init(con):
    con.sql("""
        create table if not exists automation_controls (
            control_id varchar, scope_type varchar, scope_id varchar, automation_enabled boolean,
            set_by varchar, reason varchar, set_at timestamp
        );
        create table if not exists automation_exclusions (
            exclusion_id varchar, apm_id varchar, resource_id varchar, tag_match varchar,
            reason varchar, requested_by varchar, expires_at timestamp, created_at timestamp
        );
        create table if not exists fact_action_audit (
            workflow_id varchar, proposal_id varchar, action_type varchar, resource_id varchar,
            apm_id varchar, vertical_id varchar, risk_tier varchar, execution varchar, outcome varchar,
            dry_run boolean, reasons json, estimated_monthly_savings double, recorded_at timestamp
        );
        create or replace table contracts as select * from read_csv('data/reference/contracts.csv', header = true);
    """)
    if con.sql("select count(*) from automation_controls where scope_type = 'global'").fetchone()[0] == 0:
        set_automation_enabled("global", None, True, "seeded", con=con)


def connection():
    """One read-write connection for the process; activities use short-lived cursors off it."""
    global _connection
    with _lock:
        if _connection is None:
            _connection = duckdb.connect(DB_PATH)
            _connection.sql("set TimeZone = 'UTC'")
            _init(_connection)
    return _connection


def cursor():
    return connection().cursor()


def set_automation_enabled(scope_type, scope_id, enabled, reason, con=None):
    """The kill switch (Governed Automation §3.6). Scope is global, vertical, or application."""
    con = con or cursor()
    con.execute("delete from automation_controls where scope_type = ? and scope_id is not distinct from ?",
                [scope_type, scope_id])
    con.execute("insert into automation_controls values (?, ?, ?, ?, ?, ?, ?)",
                [f"CTRL-{scope_type}-{scope_id}", scope_type, scope_id, enabled,
                 "demo", reason, datetime.now(timezone.utc)])


def automation_enabled(apm_id, vertical_id):
    """True only when no scope covering this application has automation switched off."""
    rows = cursor().execute("""
        select automation_enabled from automation_controls
        where scope_type = 'global'
           or (scope_type = 'vertical' and scope_id = ?)
           or (scope_type = 'application' and scope_id = ?)
    """, [vertical_id, apm_id]).fetchall()
    return all(enabled for (enabled,) in rows)


def get_contract(apm_id):
    """The application's automation contract, or None when it has never signed one."""
    row = cursor().execute(
        "select apm_id, allowed_max_tier, execution_mode, status from contracts where apm_id = ?", [apm_id]
    ).fetchone()
    if row is None:
        return {"status": "none", "tier_scope": "LOW", "execution_mode": "dry_run"}
    return {"apm_id": row[0], "tier_scope": row[1], "execution_mode": row[2], "status": row[3]}


def exclusions_for(apm_id):
    rows = cursor().execute("""
        select apm_id, resource_id, reason from automation_exclusions
        where apm_id = ? and (expires_at is null or expires_at > now())
    """, [apm_id]).fetchall()
    return [{"apm_id": a, "resource_id": r, "reason": reason} for a, r, reason in rows]


def add_exclusion(apm_id, resource_id, reason, expires_at=None):
    cursor().execute("insert into automation_exclusions values (?, ?, ?, null, ?, 'demo', ?, ?)",
                     [f"EXCL-{apm_id}-{resource_id}", apm_id, resource_id, reason, expires_at,
                      datetime.now(timezone.utc)])


def runs_last_24h(apm_id):
    """Executed actions in the rolling window, for policy_run_caps."""
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    application, platform = cursor().execute("""
        select count(*) filter (where apm_id = ?), count(*)
        from fact_action_audit where outcome = 'executed' and recorded_at >= ?
    """, [apm_id, since]).fetchone()
    return {"application": application, "platform": platform}


def record_audit(row):
    """Write one audit row, once. Re-running the same workflow must not double count."""
    con = cursor()
    if con.execute("select count(*) from fact_action_audit where workflow_id = ?", [row["workflow_id"]]).fetchone()[0]:
        return False
    con.execute("insert into fact_action_audit values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [row["workflow_id"], row["proposal_id"], row["action_type"], row["resource_id"], row["apm_id"],
                 row["vertical_id"], row.get("risk_tier"), row.get("execution"), row["outcome"],
                 row.get("dry_run", False), json.dumps(row.get("reasons", [])),
                 row.get("estimated_monthly_savings", 0.0), datetime.now(timezone.utc)])
    return True


def audit_for(workflow_id):
    row = cursor().execute("""
        select workflow_id, resource_id, apm_id, risk_tier, execution, outcome, dry_run, reasons
        from fact_action_audit where workflow_id = ?
    """, [workflow_id]).fetchone()
    if row is None:
        return None
    keys = ["workflow_id", "resource_id", "apm_id", "risk_tier", "execution", "outcome", "dry_run", "reasons"]
    return dict(zip(keys, row))
