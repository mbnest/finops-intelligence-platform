# Demo Build Plan

Working plan and progress log for the demo slice. Read **Resume here** first when picking this back up.

| | |
|---|---|
| **Status** | Step 1 done; step 2 next |
| **Last updated** | 2026-09-17 |
| **Responds to** | Review item 3.1: "No code at all" |

---

## Resume here

1. **Current step**: 2 (anomaly detector and eval gate). Step 1 is complete and verified.
2. **Next action**: whatever is the first unchecked box in the current step.
3. **How to verify where things stand**: run the step's "Done when" commands. Anything that passes is done, whatever the checklist says.
4. **Log**: the Progress Log at the bottom records what changed each session and anything left half-finished.

---

## What the demo proves

A thin, runnable slice of the design, not a small version of the whole platform. Each piece exists to prove one claim a reviewer is likely to doubt:

1. **The cost data model is right.** FOCUS data with four cost columns that really differ (commitments, negotiated discounts, unused commitment), and restated billing periods replaced, not duplicated.
2. **The anomaly detector is judged, not just claimed.** It is scored against injected anomalies whose labels it never sees.
3. **Governed automation separates workflow from policy.** Temporal runs the workflow; OPA decides the risk tier; neither does the other's job.
4. **MCP tools enforce who can do what in code.** A Vertical caller sees only its own data and never gets `propose_action`.

Anything that doesn't serve one of these stays out.

## Decisions

| # | Decision | Why |
|---|---|---|
| D1 | **DuckDB with dbt-duckdb stands in for Snowflake** | Anyone can clone and run it in minutes with no account or credentials. dbt models and Python are the portable parts of the design (Data Foundations ADR-003). The README states the substitution |
| D2 | **dbt covers a minimal bronze and silver, then gold and the metric layer** | Gold and metrics are the focus. Bronze is one model reading the landing files as delivered, and silver is one model that keeps the latest delivery per billing period. Without that, the restated period can't be shown, and it is the most credible data point in the slice. No per-provider normalization or tag reconciliation models: the generated data is already FOCUS |
| D3 | **Semantic layer as dbt metric models plus a YAML metric catalog** | Snowflake Semantic Views don't run locally. `metrics.yml` is what `get_metric_definition` reads (step 5), so the "define once, every consumer reads it" idea is shown without MetricFlow's setup |
| D4 | **Generation rules live in a declarative spec, not in generator code** | `data_generator/spec.yaml` holds the seed, catalog, prices, discounts, commitments, restatement, and every injected anomaly. The data is reproducible, the rules are reviewable in one file, and the eval labels come from the same source as the data |
| D5 | **Ground truth is written to a separate file the detector never reads** | Mirrors the eval gate design (MLOps Pipeline §2.4): injected anomalies with known labels, because real labels don't exist |
| D6 | **Idle resources, not anomalies, are the source of proposed actions** | An anomaly is investigated, not acted on. Idle non-prod resources under a contract are a realistic LOW-tier action; an idle prod resource is HIGH |
| D7 | **No custom pydantic-graph agent in the first version** | Any MCP client (MCP Inspector, Claude Desktop, Claude Code) can act as the agent against the MCP server. The custom agent is the most expensive piece and proves least beyond that. Possible stretch step |
| D8 | **Action execution is a fake that writes an audit row** | No real cloud calls. The workflow, policy, and guardrails are what's being shown |
| D9 | **Names match the Build Specification** | `fact_cost_daily`, `cost_line_items_clean`, `metric_ri_coverage`, `propose_action`, `classify_action_risk`, and so on, so code and docs visibly describe the same system |
| D10 | **Python 3.13 with uv; latest package versions** | Per repository standards. `uv add`, `uv run` only |

## Stand-ins

| Design (docs) | Demo | Stated in README |
|---|---|---|
| Snowflake, Iceberg tables, Snowflake Tasks | DuckDB file, dbt run by hand or by CI | Yes |
| Snowflake Semantic Views | dbt metric models plus `metrics.yml` | Yes |
| Snowpark ML batch scoring | Python scoring reading and writing DuckDB | Yes |
| Real provider exports | Generated FOCUS files from `spec.yaml` | Yes |
| Temporal Cloud, OPA sidecar on CMP | Temporal dev server and OPA binary locally, or `docker compose` | Yes |
| IDP, CMP, Terraform PR execution | Fake executor writing `fact_action_audit` | Yes |
| Cloud Workbench agent | Off-the-shelf MCP client | Yes |
| Row access policy `rap_vertical_scope` | Persona and vertical scoping in the MCP server's query layer | Yes |

---

## Build order

Each step is a commit that stands on its own. Stopping after any step still leaves something worth showing.

### Step 1: Data generator, gold, metrics, dbt tests

**Proves**: claim 1.

- [x] `demo/` uv project (`pyproject.toml`), `.gitignore` for generated data, `target/`, and the DuckDB file
- [x] `data_generator/spec.yaml`: generation rules (see Data Rules below)
- [x] `data_generator/generate.py`: reads the spec, writes landing files, reference files, and ground truth
- [x] dbt project on DuckDB with `bronze`, `silver`, `gold`, `semantic` schemas (session time zone pinned to UTC)
- [x] `bronze.cost_line_items_raw`: all deliveries as landed, with `provider`, `billing_period`, `delivery_id` from the file path; plus reference tables `account_metadata`, `apm_application_metadata`, `commitment_inventory`, `vertical_metadata`
- [x] `silver.cost_line_items_clean`: latest delivery per (`provider`, `billing_account`, `billing_period`), snake_case FOCUS columns, `vertical_id` from the account, `apm_id` and `environment` from tags
- [x] Gold: `fact_cost_daily`, `dim_account`, `dim_vertical`, `dim_application`, `dim_resource`, `dim_commitment`
- [x] Metrics: `metric_total_spend`, `metric_ri_coverage`, `metric_ri_sp_utilization`, `metric_unattributed_spend_pct`, `metric_spend_variance_mom`; catalog in `dbt/metrics.yml`
- [x] Tests (45 total, all passing):
  - [x] dbt unit test: latest-delivery selection on a restated period
  - [x] `dq_check_single_delivery_per_period`
  - [x] `dq_check_delivery_total_matches` (silver vs bronze for the selected delivery)
  - [x] `dq_check_null_resource_id`
  - [x] Cost basis invariants: `effective_cost <= contracted_cost <= list_cost` on resource usage rows; billed equals effective per period
  - [x] Gold totals match the generator's manifest
  - [x] Variance components sum to the total change
  - [x] Generic tests: keys unique and not null, accepted values, relationships to dimensions
- [x] Tests shown to fail: removing latest-delivery selection fails the unit test, and with unit tests excluded, fails `dq_check_single_delivery_per_period`
- [x] `demo/README.md` quickstart for step 1

**Done when**:

```bash
cd demo
uv run python -m data_generator.generate
uv run dbt build --project-dir dbt --profiles-dir dbt
```

both succeed, every test passes, and a query of `metric_ri_coverage` and `metric_spend_variance_mom` returns sensible numbers.

### Step 2: Anomaly detector and eval gate

**Proves**: claim 2.

- [ ] `core_intelligence/anomaly.py`: rolling median and MAD score per resource and service, on `effective_cost`
- [ ] Writes `gold.fact_anomaly` with `model_version` and `contributing_factors`
- [ ] `core_intelligence/eval_gate.py`: recall on injected anomalies by kind, alerts per vertical per week, against a naive fixed-threshold baseline; pass or fail against thresholds in config
- [ ] Tests for the scorer on small fixtures

**Done when**: the eval report prints, the detector beats the naive baseline on recall at equal or lower alert volume, and the gate exits non-zero if thresholds are missed.

### Step 3: Guardrail Engine policies (OPA)

**Proves**: claim 3, policy half.

- [ ] `governed_automation/policies/`: `classify_action_risk` (LOW/MEDIUM/HIGH from action type, environment, blast radius), `policy_run_caps`, kill switch, `automation_exclusions`
- [ ] `opa test` tables covering every tier and guardrail

**Done when**: `opa test governed_automation/policies -v` passes.

### Step 4: Orchestrator workflow (Temporal)

**Proves**: claim 3, workflow half.

- [ ] Idle-resource rule over the generated utilization data produces proposals
- [ ] `propose_action` workflow: `check_automation_enabled`, `check_contract_exists`, `classify_action_risk` (calls OPA), tier branch (LOW executes, MEDIUM opt-out timer, HIGH approval signal), fake `execute_action`, audit row
- [ ] Idempotent Activities
- [ ] Tests in Temporal's time-skipping environment: LOW runs, MEDIUM opt-out cancels, HIGH waits then approves, kill switch blocks; one replay test

**Done when**: workflow tests pass and a local run shows one LOW action executed and one HIGH action waiting.

### Step 5: MCP server

**Proves**: claim 4.

- [ ] `mcp_server/`: `get_cost_by_account`, `get_metric_definition`, `get_anomalies`, `propose_action`
- [ ] Persona and vertical scoping; Vertical persona has no `propose_action`
- [ ] Tests for scoping; a short walkthrough using an MCP client

**Done when**: scoping tests pass and the walkthrough answers "why did this vertical's bill change?" from tool calls.

### Step 6: CI

- [ ] `.github/workflows/demo.yml`: generate, `dbt build`, pytest, eval gate, `opa test`, workflow tests

**Done when**: CI is green on a push.

### Stretch (not committed to)

- pydantic-graph agent over the MCP tools, with an eval set
- Ontology views and `query_graph`

---

## Data rules (summary)

The authoritative rules are in `data_generator/spec.yaml`. This summarizes what they produce and why each part exists.

| Part | Rule | Needed for |
|---|---|---|
| Time range | Three billing periods (2026-04 to 2026-06), daily charge periods | Month-over-month variance; enough history for a rolling detector |
| Providers and accounts | AWS, Azure, and GCP; one or two billing accounts each; sub-accounts mapped to verticals | Cross-provider gold; vertical scoping |
| Applications | About ten APM applications across five verticals, each with an owner and environments | `apm_id` resolution; prod vs non-prod risk tiers |
| Resources | 31 across compute, database, and storage, each with a SKU, list unit price, daily quantity, and noise | The base cost series |
| Negotiated discount | A per-provider discount applied to list price | `contracted_cost` below `list_cost` |
| Commitments | An AWS savings plan and an Azure reservation, no upfront, covering named resources up to a daily amount, one sized to leave unused commitment | `billed_cost` and `effective_cost` differ per row; coverage and utilization metrics; `dim_commitment` |
| Account-level charges | A monthly support charge with no `resource_id` | `dq_check_null_resource_id` behavior; unattributed spend |
| Untagged resources | A few resources with no `apm_id` tag | `metric_unattributed_spend_pct` |
| Lifecycle | One resource launched mid-range, one terminated | Variance split into new and removed resources |
| Restatement | May delivered twice; delivery 2 applies a rate correction to one Azure service | Latest-delivery selection and its tests |
| Injected anomalies | A one-day spike, a persistent step change, and a slow ramp, each on a named resource and date | Ground truth for the eval gate (step 2) |
| Utilization | Daily average CPU for compute resources; several idle non-prod and one idle prod resource | Proposed actions (step 4) |
| Contracts | One application with a LOW-tier automation contract, one without | `check_contract_exists` (step 4) |

**Outputs** (all under `demo/data/`, regenerated, not committed):

| Path | Contents |
|---|---|
| `landing/focus/provider=*/billing_period=*/delivery=*/focus.csv` | FOCUS rows as a provider would deliver them |
| `warehouse.duckdb` | The DuckDB database dbt builds |
| `reference/apm_applications.csv`, `accounts.csv`, `commitments.csv` | APM, account-to-vertical, and commitment inventory |
| `reference/utilization_daily.csv` | CPU utilization for step 4 |
| `reference/contracts.csv` | Automation contracts for step 4 |
| `ground_truth/anomalies.csv` | Injected anomalies; read only by the eval gate |
| `manifest.json` | Seed, spec hash, and expected totals per provider and billing period for the selected delivery |

---

## Folder structure (target)

```
demo/
├── PLAN.md                   This file
├── README.md                 What it proves, stand-ins, quickstart
├── pyproject.toml            uv project
├── data_generator/           spec.yaml, generate.py
├── data/                     Generated (ignored)
├── dbt/
│   ├── models/bronze/
│   ├── models/silver/
│   ├── models/gold/
│   ├── models/metrics/
│   ├── metrics.yml
│   └── tests/
├── core_intelligence/        Step 2
├── governed_automation/      Steps 3–4: workflows/, policies/
├── mcp_server/               Step 5
└── tests/                    pytest
```

---

## Open questions

- None blocking. Revisit whether to add the stretch agent after step 5.

## Progress log

| Date | Step | What happened | Left unfinished |
|---|---|---|---|
| 2026-09-17 | Plan | Plan written; decisions D1–D10 recorded; DuckDB chosen over a Snowflake trial | |
| 2026-09-17 | 1 | Generator, bronze/silver/gold, five metrics, 45 dbt tests passing from a clean run; generation deterministic (identical file hashes across runs). Verified: restated May Azure delivery replaces delivery 1; spike lands on 2026-05-12; Azure reservation utilization drops to about 92% after the covered VM ends; variance components sum exactly | Nothing. Not yet committed |
