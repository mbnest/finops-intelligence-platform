"""The propose_action workflow: the Orchestrator half of Governed Automation.

One workflow per proposed action, whatever proposed it (Governed Automation §3.3). It sequences the
steps, waits out opt-out windows and approvals, and calls the executor. It never decides risk; every
classification comes from the Guardrail Engine through classify_action_risk.
"""

import asyncio
from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from governed_automation.activities import (
        check_automation_enabled,
        check_contract_exists,
        classify_action_risk,
        execute_action,
        record_action_audit,
    )

ACTIVITY_TIMEOUT = timedelta(seconds=30)


@workflow.defn(name="propose_action")
class ProposeAction:
    """Sequencing only. Risk decisions belong to the policy engine, execution to IDP or CMP."""

    def __init__(self):
        self._opt_out_reason = None
        self._approval = None
        self._stage = "starting"

    @workflow.signal
    def opt_out(self, reason: str) -> None:
        """The owning team declines a MEDIUM-tier action during its window."""
        self._opt_out_reason = reason

    @workflow.signal
    def approve(self, approver: str) -> None:
        self._approval = {"approved": True, "by": approver}

    @workflow.signal
    def reject(self, approver: str) -> None:
        self._approval = {"approved": False, "by": approver}

    @workflow.query
    def stage(self) -> str:
        """What the workflow is doing now, so a caller can tell waiting from working."""
        return self._stage

    @workflow.run
    async def run(self, proposal: dict) -> dict:
        target = proposal["target"]
        scope = {"apm_id": target["apm_id"], "vertical_id": target["vertical_id"]}
        timers = proposal.get("timers", {})

        if not await self._activity(check_automation_enabled, scope):
            return await self._finish(proposal, outcome="advisory",
                                      reasons=["automation is disabled for this scope (kill switch)"])

        contract = await self._activity(check_contract_exists, target["apm_id"])
        decision = await self._activity(classify_action_risk, {**proposal, "contract": contract})

        if decision["execution"] == "advisory":
            return await self._finish(proposal, decision=decision, outcome="advisory",
                                      reasons=decision["advisory_reasons"])

        if decision["execution"] == "approval":
            approved = await self._wait_for_approval(timers)
            if approved is None:
                return await self._finish(proposal, decision=decision, outcome="expired",
                                          reasons=["no approval before the deadline"])
            if not approved["approved"]:
                return await self._finish(proposal, decision=decision, outcome="rejected",
                                          reasons=[f"rejected by {approved['by']}"])

        if decision["execution"] == "opt_out":
            await self._wait_out_opt_out_window(timers)
            if self._opt_out_reason:
                return await self._finish(proposal, decision=decision, outcome="cancelled_by_owner",
                                          reasons=[self._opt_out_reason])

        # The switch may have been thrown while this workflow waited, so it is checked again here.
        if not await self._activity(check_automation_enabled, scope):
            return await self._finish(proposal, decision=decision, outcome="advisory",
                                      reasons=["automation was disabled during the wait"])

        if decision["dry_run"]:
            return await self._finish(proposal, decision=decision, outcome="dry_run",
                                      reasons=["contract is in dry-run mode; nothing was executed"])

        self._stage = "executing"
        await self._activity(execute_action, proposal)
        return await self._finish(proposal, decision=decision, outcome="executed", reasons=[])

    async def _wait_for_approval(self, timers):
        """HIGH tier waits for a person. A deadline exists only so the demo terminates."""
        self._stage = "awaiting_approval"
        try:
            await workflow.wait_condition(
                lambda: self._approval is not None,
                timeout=timedelta(seconds=timers.get("approval_timeout_seconds", 60)))
        except asyncio.TimeoutError:
            return None
        return self._approval

    async def _wait_out_opt_out_window(self, timers):
        """MEDIUM tier runs after a durable window unless the owning team opts out."""
        self._stage = "awaiting_opt_out"
        try:
            await workflow.wait_condition(
                lambda: self._opt_out_reason is not None,
                timeout=timedelta(seconds=timers.get("opt_out_window_seconds", 10)))
        except asyncio.TimeoutError:
            pass

    async def _activity(self, fn, arg):
        return await workflow.execute_activity(fn, arg, start_to_close_timeout=ACTIVITY_TIMEOUT)

    async def _finish(self, proposal, outcome, reasons, decision=None):
        target = proposal["target"]
        row = {
            "workflow_id": workflow.info().workflow_id,
            "proposal_id": proposal["proposal_id"],
            "action_type": proposal["action"]["type"],
            "resource_id": target["resource_id"],
            "apm_id": target["apm_id"],
            "vertical_id": target["vertical_id"],
            "risk_tier": (decision or {}).get("risk_tier"),
            "execution": (decision or {}).get("execution"),
            "outcome": outcome,
            "dry_run": (decision or {}).get("dry_run", False),
            "reasons": reasons,
            "estimated_monthly_savings": proposal.get("evidence", {}).get("estimated_monthly_savings", 0.0),
        }
        await self._activity(record_action_audit, row)
        return {k: row[k] for k in ("workflow_id", "resource_id", "apm_id", "risk_tier", "outcome", "dry_run", "reasons")}
