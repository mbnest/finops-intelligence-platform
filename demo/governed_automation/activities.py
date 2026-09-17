"""Temporal Activities: every step that touches the outside world (Build Specification §6).

Each one is idempotent, keyed on the workflow ID, so a retry after a worker restart or timeout can't
execute an action twice. The workflow itself decides nothing about risk: it asks the Guardrail Engine.
"""

import json
import urllib.request
from datetime import datetime, timezone

from temporalio import activity

from governed_automation import storage
from governed_automation.proposals import load_config


@activity.defn
def check_automation_enabled(scope: dict) -> bool:
    """The kill switch, checked at proposal time and again before execution."""
    return storage.automation_enabled(scope["apm_id"], scope["vertical_id"])


@activity.defn
def check_contract_exists(apm_id: str) -> dict:
    """The application's automation contract. No contract means advisory, the default state."""
    return storage.get_contract(apm_id)


@activity.defn
def classify_action_risk(payload: dict) -> dict:
    """Ask OPA for the risk tier and guardrail decision. The workflow never classifies anything itself."""
    config = load_config()
    apm_id = payload["target"]["apm_id"]
    opa_input = {"input": {
        "action": payload["action"],
        "target": payload["target"],
        "contract": payload["contract"],
        "controls": {"automation_enabled": storage.automation_enabled(apm_id, payload["target"]["vertical_id"])},
        "exclusions": storage.exclusions_for(apm_id),
        "runs_last_24h": storage.runs_last_24h(apm_id),
        "caps": config["caps"],
    }}
    request = urllib.request.Request(
        config["opa_decision_url"], data=json.dumps(opa_input).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)["result"]


@activity.defn
def execute_action(payload: dict) -> dict:
    """Stand-in for the IDP or CMP call that would stop the resource.

    Nothing outside this process changes. What matters for the demo is that execution happens only
    after the Orchestrator has a decision, and that it is recorded once.
    """
    return {"status": "executed", "resource_id": payload["target"]["resource_id"],
            "executed_at": datetime.now(timezone.utc).isoformat()}


@activity.defn
def record_action_audit(row: dict) -> bool:
    """Write the audit row. Returns False when this workflow already wrote one."""
    return storage.record_audit(row)
