package finops.guardrails_test

import data.finops.guardrails

# An idle non-production VM with a snapshot available: the low-risk case automation exists for.
low_risk_input := {
	"action": {"type": "stop", "snapshot_available": true},
	"target": {"resource_id": "aws-ec2-facilities-dev", "apm_id": "APM-1003", "environment": "nonprod", "blast_radius": 1},
	"contract": {"status": "active", "tier_scope": "LOW", "execution_mode": "live"},
	"controls": {"automation_enabled": true},
	"exclusions": [],
	"runs_last_24h": {"application": 0, "platform": 0},
	"caps": {"per_application": 10, "platform": 50},
}

with_action(base, patch) := object.union(base, {"action": object.union(base.action, patch)})

with_target(base, patch) := object.union(base, {"target": object.union(base.target, patch)})

test_idle_nonprod_resource_is_low if {
	guardrails.risk_tier == "LOW" with input as low_risk_input
}

test_read_only_action_on_production_is_low if {
	guardrails.risk_tier == "LOW" with input as with_target(with_action(low_risk_input, {"type": "tag"}), {"environment": "prod"})
}

test_stopping_a_production_resource_is_high if {
	guardrails.risk_tier == "HIGH" with input as with_target(low_risk_input, {"environment": "prod"})
}

test_resizing_a_production_resource_is_high if {
	guardrails.risk_tier == "HIGH" with input as with_target(with_action(low_risk_input, {"type": "resize"}), {"environment": "prod"})
}

test_large_blast_radius_is_high_even_in_nonprod if {
	guardrails.risk_tier == "HIGH" with input as with_target(low_risk_input, {"blast_radius": 6})
}

test_terminating_a_nonprod_resource_is_medium if {
	guardrails.risk_tier == "MEDIUM" with input as with_action(low_risk_input, {"type": "terminate", "snapshot_available": true})
}

test_several_resources_in_one_action_is_medium if {
	guardrails.risk_tier == "MEDIUM" with input as with_target(low_risk_input, {"blast_radius": 3})
}

test_tier_reasons_explain_a_high_classification if {
	reasons := guardrails.tier_reasons with input as with_target(low_risk_input, {"environment": "prod"})
	"mutating action on a production target" in reasons
}
