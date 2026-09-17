package finops.guardrails_test

import data.finops.guardrails

# Same low-risk action as risk_test: it would run automatically unless a guardrail stops it.
base_input := {
	"action": {"type": "stop", "snapshot_available": true},
	"target": {"resource_id": "aws-ec2-support-dev", "apm_id": "APM-1003", "environment": "nonprod", "blast_radius": 1},
	"contract": {"status": "active", "tier_scope": "LOW", "execution_mode": "live"},
	"controls": {"automation_enabled": true},
	"exclusions": [],
	"runs_last_24h": {"application": 0, "platform": 0},
	"caps": {"per_application": 10, "platform": 50},
}

with_key(base, key, patch) := object.union(base, {key: object.union(base[key], patch)})

test_low_risk_under_an_active_contract_runs_automatically if {
	guardrails.execution == "auto" with input as base_input
}

test_medium_risk_gets_an_opt_out_window if {
	input_medium := object.union(base_input, {
		"target": object.union(base_input.target, {"blast_radius": 3}),
		"contract": object.union(base_input.contract, {"tier_scope": "FULL"}),
	})
	guardrails.execution == "opt_out" with input as input_medium
}

test_high_risk_always_waits_for_a_person if {
	input_high := object.union(base_input, {
		"target": object.union(base_input.target, {"environment": "prod"}),
		"contract": object.union(base_input.contract, {"tier_scope": "FULL"}),
	})
	guardrails.execution == "approval" with input as input_high
}

test_kill_switch_sends_everything_back_to_advisory if {
	killed := with_key(base_input, "controls", {"automation_enabled": false})
	guardrails.execution == "advisory" with input as killed
	"automation is disabled for this scope (kill switch)" in guardrails.advisory_reasons with input as killed
}

test_no_contract_means_advisory if {
	no_contract := with_key(base_input, "contract", {"status": "draft"})
	guardrails.execution == "advisory" with input as no_contract
}

test_a_low_only_contract_cannot_pre_approve_a_medium_action if {
	over_scope := object.union(base_input, {"target": object.union(base_input.target, {"blast_radius": 3})})
	guardrails.execution == "advisory" with input as over_scope
	"contract covers LOW only, action classified MEDIUM" in guardrails.advisory_reasons with input as over_scope
}

test_an_excluded_resource_stays_advisory if {
	excluded := object.union(base_input, {"exclusions": [{
		"apm_id": "APM-1003",
		"resource_id": "aws-ec2-support-dev",
		"reason": "owner opted out during migration",
	}]})
	guardrails.execution == "advisory" with input as excluded
}

test_an_application_wide_exclusion_covers_every_resource if {
	excluded := object.union(base_input, {"exclusions": [{
		"apm_id": "APM-1003",
		"resource_id": null,
		"reason": "application-wide freeze",
	}]})
	guardrails.execution == "advisory" with input as excluded
}

test_an_exclusion_for_another_application_does_not_apply if {
	other := object.union(base_input, {"exclusions": [{
		"apm_id": "APM-1007",
		"resource_id": null,
		"reason": "different application",
	}]})
	guardrails.execution == "auto" with input as other
}

test_application_run_cap_falls_back_to_advisory if {
	capped := with_key(base_input, "runs_last_24h", {"application": 10})
	guardrails.execution == "advisory" with input as capped
}

test_platform_run_cap_falls_back_to_advisory if {
	capped := with_key(base_input, "runs_last_24h", {"platform": 50})
	guardrails.execution == "advisory" with input as capped
}

test_destructive_action_without_a_snapshot_is_advisory if {
	unsafe := with_key(base_input, "action", {"type": "terminate", "snapshot_available": false})
	guardrails.execution == "advisory" with input as unsafe
	"terminate is destructive and no snapshot is available" in guardrails.advisory_reasons with input as unsafe
}

test_dry_run_is_reported_separately_from_risk if {
	dry := with_key(base_input, "contract", {"execution_mode": "dry_run"})
	guardrails.decision.dry_run with input as dry
	guardrails.decision.execution == "auto" with input as dry
}

test_live_contracts_are_not_dry_run if {
	guardrails.decision.dry_run == false with input as base_input
}

test_decision_carries_tier_and_reasons_together if {
	killed := with_key(base_input, "controls", {"automation_enabled": false})
	decision := guardrails.decision with input as killed
	decision.risk_tier == "LOW"
	decision.execution == "advisory"
	count(decision.advisory_reasons) == 1
}
