# FinOps Platform Demo Slice

A small, runnable slice of the architecture in [`docs/`](../docs). It is not a small version of the whole platform. Each piece exists to prove one design claim in working code:

1. **The cost data model is right**: FOCUS data with four cost columns that really differ, and restated billing periods replaced, not duplicated.
2. **The anomaly detector is judged against ground truth**, not just claimed to work.
3. **Governed automation separates workflow from policy**: Temporal runs the workflow, OPA decides the risk tier.
4. **MCP tools enforce who can do what in code**, not in a prompt.

Build progress, decisions, and data rules are in [PLAN.md](PLAN.md).

## What stands in for what

| In the design | In this demo |
|---|---|
| Snowflake, Iceberg tables, Snowflake Tasks | DuckDB, with dbt run by hand or in CI |
| Snowflake Semantic Views | dbt metric models plus a YAML metric catalog |
| Snowpark ML batch scoring | Python scoring against DuckDB |
| Provider billing exports | FOCUS files generated from a declarative spec (`data_generator/spec.yaml`) |
| IDP, CMP, Terraform execution | A fake executor that writes an audit row |
| Cloud Workbench agent | Any MCP client |

The dbt models and Python are the parts the design treats as portable (Data Foundations ADR-003). Everything Snowflake-specific is a stand-in.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/).

```bash
cd demo
uv sync
uv run python -m data_generator.generate
uv run dbt build --project-dir dbt --profiles-dir dbt
```

Then print the queries below with their results:

```bash
uv run python tour.py
```

Score the anomaly detector against injected anomalies it never sees:

```bash
uv run python -m core_intelligence.anomaly
uv run python -m core_intelligence.eval_gate
uv run pytest
```

Start the two services the action layer needs, then check the Guardrail Engine's policies (OPA is a Go
binary, so it is not installable with uv):

```bash
docker compose up -d
./run_policy_tests.sh -v
```

Run every idle-resource proposal through the governed harness:

```bash
uv run python -m governed_automation.run_demo
uv run pytest
```

Later steps add commands here as they land.

## What to look for

Four things worth a reviewer's attention, all from `tour.py`.

**1. The four cost columns answer different questions.** For a resource the savings plan covers only partly, on one day:

| pricing_category | list_cost | contracted_cost | billed_cost | effective_cost |
|---|---|---|---|---|
| Committed | 279.62 | 262.84 | 0.00 | 189.25 |
| Standard | 86.96 | 81.74 | 81.74 | 81.74 |

The committed share bills nothing, because the commitment fee is billed separately, but it still costs something once amortized. Collapsing this into one `cost` column is the most common reason FinOps numbers don't reconcile.

**2. A restated billing period is replaced, not merged.** Azure delivers 2026-05 twice. Bronze keeps both deliveries for audit; silver keeps only the latest, so nothing is double counted:

| layer | delivery_id | rows | billed_cost |
|---|---|---|---|
| bronze | azure/2026-05/1 | 356 | 6635.49 |
| bronze | azure/2026-05/2 | 356 | 6535.63 |
| silver | azure/2026-05/2 | 356 | 6535.63 |

Provider line item IDs aren't stable across deliveries, so rows are never upserted. A dbt unit test and `dq_check_single_delivery_per_period` both fail if that logic is removed.

**3. Coverage and utilization are different questions.** A covered VM is removed on 2026-05-15, so part of the Azure reservation is paid for and unused from then on:

| billing_period | commitment | used_cost | unused_cost | utilization |
|---|---|---|---|---|
| 2026-04 | ri-az-vm-001 | 2700.00 | 0.00 | 1.000 |
| 2026-05 | ri-az-vm-001 | 2676.52 | 113.48 | 0.959 |
| 2026-06 | ri-az-vm-001 | 2478.71 | 221.29 | 0.918 |

**4. "Why did my bill change?" gets a real answer.** The month-over-month change is split into causes that sum exactly to it (a dbt test asserts that), so no residual is hidden:

| billing_period | vertical | spend_change | new_resources | removed_resources | usage_change | price_change | other_change |
|---|---|---|---|---|---|---|---|
| 2026-06 | investments | 4960.0 | 5142.0 | 0.0 | -338.1 | 48.3 | 107.8 |
| 2026-06 | project_mgmt | -73.6 | 0.0 | -250.6 | 134.8 | 42.2 | 0.0 |

June's jump in investments is a new GPU resource, not a price rise. Project management's drop is a removed resource, partly offset by usage growth elsewhere. `other_change` is charges with no resource, here the unused commitment above.

**5. The anomaly detector is scored, not trusted.** A FinOps practice that has never scored its own alerts has no labels, so the eval gate does what the design calls for: inject anomalies of known kind and size, and measure against them. The detector never reads the answer key.

| metric | detector | naive baseline |
|---|---|---|
| recall: spike | 1.00 | 1.00 |
| recall: step | 1.00 | 1.00 |
| recall: ramp | 1.00 | 0.00 |
| alerts raised | 4 | 2 |
| alerts per vertical per week | 0.06 | 0.03 |
| expected changes wrongly flagged | 0 | 0 |

The baseline (any day above 1.5x the trailing mean) catches the spike and the step but never the slow ramp, because the mean drifts up with it. The detector compares each day with the median of its own recent history, measured in median absolute deviations, so a gradual climb still stands out.

Two things the gate checks beyond recall:

- **Alert volume.** A step change stays anomalous for weeks. Alerting daily would produce 25 alerts for 3 real problems, so consecutive days collapse into one anomaly that accumulates impact. Alert fatigue is the main adoption risk, so it is a gate, not a footnote.
- **Expected changes.** A new GPU resource and a removed VM are real cost changes, not anomalies. Flagging either fails the gate.

The gate exits non-zero when a threshold is missed, so CI can block the change. Raising the dollar threshold so the detector misses the step and the ramp makes it exit 1 and name both misses.

**6. Risk classification is policy, not code in the workflow.** The Guardrail Engine is Rego evaluated by OPA, separate from the Orchestrator that will run the workflow in step 4. It decides how risky an action is and nothing else, so no component both proposes an action and rules on whether it is safe.

The same idle non-production VM gets a different answer as the situation changes:

| situation | tier | what the Orchestrator does |
|---|---|---|
| Idle non-prod VM, active contract | LOW | runs automatically |
| Same action on a production target | HIGH | waits for a person, always |
| Affects several resources at once | MEDIUM | opt-out window first |
| Kill switch thrown | any | advisory only |
| Resource excluded, or run cap reached | any | advisory only |
| Terminate with no snapshot available | any | advisory only |

Guardrails only ever restrict: nothing in the policy can raise an action's permission level, and advisory is where every resource starts. 23 policy tests cover each tier and each guardrail; changing the production gate to look for the wrong tag value fails four of them.

**7. The same proposal gets four different answers.** Four idle resources, one code path, outcomes decided by policy and contract:

```
resource                        apm       tier   outcome     why
aws-ec2-facilities-dev          APM-1003  LOW    executed
aws-ec2-valuation-legacy        APM-1002  HIGH   executed    after an approver signed
az-vm-projecttracker-test       APM-1007  LOW    dry_run     contract is in dry-run mode
gcp-gce-portfolio-sandbox       APM-1005  LOW    advisory    no active automation contract
```

The Orchestrator (Temporal) sequences the work and waits; the Guardrail Engine (OPA) decides risk. Neither does the other's job, which is what makes letting LOW-tier actions run unattended defensible.

Three behaviours the tests pin down, because they are what a reviewer should be skeptical about:

- **An owner can stop a MEDIUM action** during its opt-out window, and the reason is recorded.
- **The kill switch is re-checked before execution**, not only at proposal time. An action approved during an incident still does not run. Removing that second check fails the test.
- **A recorded workflow history replays against the current code**, which is how non-deterministic changes get caught before they break workflows that are mid-approval.

Activities are idempotent on the workflow ID, so a retried worker cannot execute or double count an action. Nothing here calls a cloud API: the executor is a stand-in, because what is being shown is the decision path around it.

## How the data is made

`data_generator/spec.yaml` holds every rule: the seed, the resource catalog and prices, negotiated discounts, commitment sizing, the restatement, injected anomalies, and utilization. `generate.py` only applies those rules, so the dataset is reproducible and reviewable in one file. Injected anomalies are written to `data/ground_truth/anomalies.csv`, which the detector in step 2 never reads: it is the eval gate's answer key.
