"""Workflow tests for the Orchestrator, against the Temporal dev server in docker-compose.

Covers the branches that make governed automation trustworthy: what runs by itself, what waits, what
an owner can stop, and what a kill switch stops mid-flight. The last test replays a recorded history
to catch non-deterministic workflow changes, which is what breaks running workflows in production.

Needs: docker compose up -d
"""

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from temporalio.client import Client
from temporalio.service import RPCError
from temporalio.worker import Replayer, Worker

from governed_automation import storage
from governed_automation.proposals import load_config
from governed_automation.run_demo import ACTIVITIES
from governed_automation.workflow import ProposeAction

TIMERS = {"opt_out_window_seconds": 1, "approval_timeout_seconds": 5}


@pytest.fixture
async def client():
    try:
        return await Client.connect(load_config()["temporal_address"])
    except (RPCError, RuntimeError, OSError) as error:
        pytest.skip(f"Temporal dev server not reachable, run `docker compose up -d` ({error})")


@pytest.fixture
async def worker(client):
    """A worker on its own task queue, so tests can't pick up each other's work."""
    queue = f"test-{uuid.uuid4()}"
    with ThreadPoolExecutor(max_workers=4) as pool:
        async with Worker(client, task_queue=queue, workflows=[ProposeAction],
                          activities=ACTIVITIES, activity_executor=pool):
            yield queue


@pytest.fixture(autouse=True)
def reset_controls():
    """Every test starts with automation on globally and no exclusions."""
    storage.connection()
    storage.cursor().execute("delete from automation_controls where scope_type != 'global'")
    storage.set_automation_enabled("global", None, True, "test reset")
    storage.cursor().execute("delete from automation_exclusions")
    yield


def proposal(resource_id="aws-ec2-facilities-dev", apm_id="APM-1003", environment="nonprod",
             action_type="stop", blast_radius=1, vertical_id="workplace"):
    return {
        "proposal_id": f"PROP-{uuid.uuid4()}",
        "origin": "core_intelligence",
        "action": {"type": action_type, "snapshot_available": True},
        "target": {"resource_id": resource_id, "apm_id": apm_id, "environment": environment,
                   "account_id": "acct", "vertical_id": vertical_id, "blast_radius": blast_radius},
        "evidence": {"estimated_monthly_savings": 100.0},
        "timers": TIMERS,
    }


async def start(client, queue, payload):
    return await client.start_workflow(ProposeAction.run, payload, id=payload["proposal_id"], task_queue=queue)


async def wait_for_stage(handle, stage, timeout=10):
    async with asyncio.timeout(timeout):
        while await handle.query(ProposeAction.stage) != stage:
            await asyncio.sleep(0.05)


async def test_low_risk_action_under_a_live_contract_executes(client, worker):
    result = await (await start(client, worker, proposal())).result()
    assert (result["risk_tier"], result["outcome"]) == ("LOW", "executed")


async def test_a_dry_run_contract_executes_nothing(client, worker):
    """APM-1007's contract is signed but in dry-run: every step runs, the action does not."""
    result = await (await start(client, worker, proposal(
        resource_id="az-vm-projecttracker-test", apm_id="APM-1007", vertical_id="project_mgmt"))).result()
    assert result["outcome"] == "dry_run"
    assert result["dry_run"] is True


async def test_an_application_without_a_contract_stays_advisory(client, worker):
    result = await (await start(client, worker, proposal(
        resource_id="gcp-gce-portfolio-sandbox", apm_id="APM-1005", vertical_id="investments"))).result()
    assert result["outcome"] == "advisory"
    assert "no active automation contract for APM-1005" in result["reasons"]


async def test_high_risk_action_waits_and_then_executes_on_approval(client, worker):
    handle = await start(client, worker, proposal(
        resource_id="aws-ec2-valuation-legacy", apm_id="APM-1002", environment="prod", vertical_id="advisory"))
    await wait_for_stage(handle, "awaiting_approval")
    await handle.signal(ProposeAction.approve, "owner.1002@example.com")
    result = await handle.result()
    assert (result["risk_tier"], result["outcome"]) == ("HIGH", "executed")


async def test_a_rejected_high_risk_action_does_not_execute(client, worker):
    handle = await start(client, worker, proposal(
        resource_id="aws-ec2-valuation-legacy", apm_id="APM-1002", environment="prod", vertical_id="advisory"))
    await wait_for_stage(handle, "awaiting_approval")
    await handle.signal(ProposeAction.reject, "owner.1002@example.com")
    result = await handle.result()
    assert result["outcome"] == "rejected"


async def test_an_unanswered_approval_expires_instead_of_executing(client, worker):
    result = await (await start(client, worker, proposal(
        resource_id="aws-ec2-valuation-legacy", apm_id="APM-1002", environment="prod", vertical_id="advisory"))).result()
    assert result["outcome"] == "expired"


async def test_medium_risk_executes_when_the_opt_out_window_passes(client, worker):
    result = await (await start(client, worker, proposal(
        resource_id="aws-ec2-valuation-legacy", apm_id="APM-1002", vertical_id="advisory", blast_radius=3))).result()
    assert (result["risk_tier"], result["outcome"]) == ("MEDIUM", "executed")


async def test_the_owning_team_can_opt_out_during_the_window(client, worker):
    handle = await start(client, worker, proposal(
        resource_id="aws-ec2-valuation-legacy", apm_id="APM-1002", vertical_id="advisory", blast_radius=3))
    await wait_for_stage(handle, "awaiting_opt_out")
    await handle.signal(ProposeAction.opt_out, "batch job runs on this fleet tonight")
    result = await handle.result()
    assert result["outcome"] == "cancelled_by_owner"
    assert result["reasons"] == ["batch job runs on this fleet tonight"]


async def test_the_kill_switch_stops_an_action_that_was_already_approved(client, worker):
    """The switch is checked again before execution, because waits last hours or days."""
    handle = await start(client, worker, proposal(
        resource_id="aws-ec2-valuation-legacy", apm_id="APM-1002", environment="prod", vertical_id="advisory"))
    await wait_for_stage(handle, "awaiting_approval")
    storage.set_automation_enabled("global", None, False, "incident in progress")
    await handle.signal(ProposeAction.approve, "owner.1002@example.com")
    result = await handle.result()
    assert result["outcome"] == "advisory"
    assert result["reasons"] == ["automation was disabled during the wait"]


async def test_an_excluded_resource_is_never_executed(client, worker):
    storage.add_exclusion("APM-1003", "aws-ec2-facilities-dev", "owner opted out during migration")
    result = await (await start(client, worker, proposal())).result()
    assert result["outcome"] == "advisory"
    assert any("excluded from automation" in reason for reason in result["reasons"])


def test_the_audit_row_is_written_once_per_workflow():
    """Activities retry, so writing the same audit row twice must be impossible."""
    row = {"workflow_id": f"wf-{uuid.uuid4()}", "proposal_id": "PROP-1", "action_type": "stop",
           "resource_id": "r1", "apm_id": "APM-1003", "vertical_id": "workplace", "outcome": "executed"}
    assert storage.record_audit(row) is True
    assert storage.record_audit(row) is False


async def test_the_workflow_replays_cleanly(client, worker):
    """A recorded history must replay against the current code, or running workflows would break."""
    handle = await start(client, worker, proposal())
    await handle.result()
    await Replayer(workflows=[ProposeAction]).replay_workflow(await handle.fetch_history())
