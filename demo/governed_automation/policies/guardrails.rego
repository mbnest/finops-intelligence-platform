# Guardrails (Build Specification §6, Governed Automation §3.6). Each one can send an action back to
# advisory, which is the default state of every resource. Nothing here can raise an action's
# permission level: guardrails only ever restrict.
package finops.guardrails

# The kill switch: automation_controls with automation_enabled = false, at global, vertical, or
# application scope. Checked before execution as well as at proposal time, because it may be thrown
# during an opt-out window or approval wait.
kill_switch_engaged if not input.controls.automation_enabled

active_contract if {
	input.contract.status == "active"
}

# A contract scoped to LOW only can't pre-approve a MEDIUM or HIGH action.
tier_above_contract if {
	input.contract.tier_scope == "LOW"
	risk_tier != "LOW"
}

# policy_exclusions: a resource excluded from automation stays advisory whatever its tier.
active_exclusions contains exclusion if {
	some exclusion in input.exclusions
	exclusion.apm_id == input.target.apm_id
	exclusion.resource_id == input.target.resource_id
}

active_exclusions contains exclusion if {
	some exclusion in input.exclusions
	exclusion.apm_id == input.target.apm_id
	exclusion.resource_id == null
}

# policy_reversibility_preference: never destroy something that could have been snapshotted first.
missing_snapshot if {
	input.action.type in destructive_actions
	not input.action.snapshot_available
}

# policy_run_caps: rolling 24-hour limits, per application and platform-wide. Reaching a cap falls
# back to advisory rather than failing the proposal.
application_cap_reached if {
	input.runs_last_24h.application >= input.caps.per_application
}

platform_cap_reached if {
	input.runs_last_24h.platform >= input.caps.platform
}

advisory_reasons contains "automation is disabled for this scope (kill switch)" if kill_switch_engaged

advisory_reasons contains sprintf("no active automation contract for %v", [input.target.apm_id]) if not active_contract

advisory_reasons contains sprintf("contract covers LOW only, action classified %v", [risk_tier]) if tier_above_contract

advisory_reasons contains sprintf("target excluded from automation: %v", [exclusion.reason]) if {
	some exclusion in active_exclusions
}

advisory_reasons contains sprintf("%v is destructive and no snapshot is available", [input.action.type]) if missing_snapshot

advisory_reasons contains sprintf("application run cap reached (%v in 24h)", [input.runs_last_24h.application]) if application_cap_reached

advisory_reasons contains sprintf("platform run cap reached (%v in 24h)", [input.runs_last_24h.platform]) if platform_cap_reached

# How the Orchestrator should handle this action. Advisory means recommend it to a human and stop,
# which is what every resource gets until a contract says otherwise.
execution := "advisory" if {
	count(advisory_reasons) > 0
} else := "approval" if {
	risk_tier == "HIGH"
} else := "opt_out" if {
	risk_tier == "MEDIUM"
} else := "auto"

# Dry run is a contract setting, not a risk decision: the workflow runs every step and executes nothing.
# Defaulted so that `decision` is always defined, whatever the contract says.
default dry_run := false

dry_run if input.contract.execution_mode == "dry_run"

decision := {
	"risk_tier": risk_tier,
	"execution": execution,
	"dry_run": dry_run,
	"tier_reasons": tier_reasons,
	"advisory_reasons": advisory_reasons,
}
