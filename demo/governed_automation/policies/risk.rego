# classify_action_risk (Build Specification §6): the risk tier for one proposed action.
#
# This is the Guardrail Engine's half of Governed Automation. It decides how risky an action is and
# nothing else: it never sequences, executes, or retries anything. That is the Orchestrator's job
# (Governed Automation ADR-001). No model or LLM influences any rule here.
package finops.guardrails

# Actions that change or destroy something. Anything not listed is read-only and stays LOW.
destructive_actions := {"terminate", "delete_snapshot", "delete_volume"}

mutating_actions := destructive_actions | {"resize", "stop", "start", "schedule_stop"}

# policy_production_gate: a mutating action on a production target is never automatic.
policy_production_gate if {
	input.target.environment == "prod"
	input.action.type in mutating_actions
}

# policy_blast_radius: one action affecting many resources needs explicit approval.
policy_blast_radius if {
	input.target.blast_radius > 5
}

# risk_tier is a fixed rule, not a scored threshold: HIGH always means a person decides.
risk_tier := "HIGH" if {
	policy_production_gate
} else := "HIGH" if {
	policy_blast_radius
} else := "MEDIUM" if {
	input.action.type in destructive_actions
} else := "MEDIUM" if {
	input.target.blast_radius > 1
} else := "LOW"

# Why the tier came out this way, so an audit record can explain it without re-running the policy.
tier_reasons contains "mutating action on a production target" if policy_production_gate

tier_reasons contains sprintf("blast radius of %v resources", [input.target.blast_radius]) if {
	input.target.blast_radius > 1
}

tier_reasons contains sprintf("destructive action type: %v", [input.action.type]) if {
	input.action.type in destructive_actions
}
