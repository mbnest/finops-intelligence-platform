"""Run every idle-resource proposal through the governed harness and print what happened.

Start the services first: docker compose up -d

Four idle resources, four different outcomes, decided by policy and contract rather than by the code
path taken: automatic execution, a dry run, advisory because no contract exists, and a HIGH-tier
action that waits for a person.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from temporalio.client import Client
from temporalio.worker import Worker

from governed_automation import storage
from governed_automation.activities import (
    check_automation_enabled,
    check_contract_exists,
    classify_action_risk,
    execute_action,
    record_action_audit,
)
from governed_automation.proposals import find_idle_resources, load_config
from governed_automation.workflow import ProposeAction

ACTIVITIES = [check_automation_enabled, check_contract_exists, classify_action_risk, execute_action, record_action_audit]


async def run_proposal(client, proposal, timers, run_id):
    """Start one workflow; approve it if it turns out to need approval."""
    handle = await client.start_workflow(
        ProposeAction.run, {**proposal, "timers": timers},
        id=f"{proposal['proposal_id']}-{run_id}", task_queue=load_config()["task_queue"])

    async def approve_when_waiting():
        """Stand in for an approver clicking the Teams card, once the workflow is actually waiting."""
        while await handle.query(ProposeAction.stage) != "awaiting_approval":
            await asyncio.sleep(0.2)
        await handle.signal(ProposeAction.approve, "owner.1002@example.com")

    approver = asyncio.create_task(approve_when_waiting())
    try:
        result = await handle.result()
    finally:
        approver.cancel()
    return result


async def main():
    config = load_config()
    storage.connection()  # create the control, exclusion, and audit tables before the worker starts
    client = await Client.connect(config["temporal_address"])
    timers = {"opt_out_window_seconds": config["opt_out_window_seconds"],
              "approval_timeout_seconds": config["approval_timeout_seconds"]}
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

    with ThreadPoolExecutor(max_workers=8) as pool:
        async with Worker(client, task_queue=config["task_queue"], workflows=[ProposeAction],
                          activities=ACTIVITIES, activity_executor=pool):
            proposals = find_idle_resources(config)
            print(f"{len(proposals)} idle resources proposed for stopping\n")
            results = await asyncio.gather(*(run_proposal(client, p, timers, run_id) for p in proposals))

    print(f"{'resource':<32}{'apm':<10}{'tier':<7}{'outcome':<20}why")
    for result in sorted(results, key=lambda r: r["resource_id"]):
        why = "; ".join(result["reasons"]) if result["reasons"] else ""
        print(f"{result['resource_id']:<32}{result['apm_id']:<10}{str(result['risk_tier']):<7}{result['outcome']:<20}{why}")


if __name__ == "__main__":
    asyncio.run(main())
