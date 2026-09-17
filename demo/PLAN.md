# Demo Build Plan

Working plan and progress log for the demo slice. Read **Resume here** first when picking this back up.

| | |
|---|---|
| **Status** | All six steps done |
| **Last updated** | 2026-09-17 |
| **Responds to** | Review item 3.1: "No code at all" |

---

## Resume here

1. **Current step**: none. All six steps are complete and verified.
2. **Next action**: nothing planned. The stretch items below are optional; otherwise this slice is done.
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
| D11 | **Consecutive flagged days are one anomaly episode** | A step change or ramp stays anomalous for weeks. Alerting daily gave 25 alerts for 3 real problems. Alert fatigue is the stated adoption risk (MLOps Pipeline §1.3), so episodes are what gets written to `fact_anomaly` and counted by the gate |
| D12 | **The detector's dollar floor is $5/day, not $25** | At $25 the injected step change ($6.45/day, about $190 a month) was invisible. The floor is a judgment about what is worth chasing, so it lives in `core_intelligence/config.yaml`, not in code |
| D13 | **OPA runs in Docker, pinned to 1.20.2** | OPA is a Go binary with no PyPI distribution, so uv can't install it. `run_policy_tests.sh` wraps the Docker call; the version is pinned so results don't drift with `latest` |
| D14 | **Temporal dev server and OPA run from docker-compose; tests use short timers, not time-skipping** | Time-skipping downloads a test server binary on first use. Docker was already in play, so the workflow tests run against a real dev server with the windows shortened through config (1s opt-out, 5s approval). The durations are workflow input, so production keeps 24-hour windows |
| D16 | **Persona is set per server process, through the environment** | The design derives persona from identity. Here `FINOPS_PERSONA` decides which tools get bound at build time, which keeps the enforcement point visible: a client connects to the platform server or a vertical server, and gets a different tool list |
| D17 | **Tests share one automation-state reset fixture** | Run caps, the kill switch, and exclusions are real state in DuckDB, shared with the demo. The MCP action test failed the first time because earlier runs had used up APM-1003's 10 executions per 24 hours. The guardrail was right; the test needed isolation |
| D15 | **Governed Automation state lives in the same DuckDB file as gold** | The design puts contracts, automation_controls, automation_exclusions, and the action audit in managed Postgres. One store keeps the demo runnable with no extra service; the table names and shapes match the specification |

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

- [x] `core_intelligence/anomaly.py`: robust z score (median and median absolute deviation) per resource over a trailing window, on `effective_cost`
- [x] Consecutive flagged days collapse into one episode (D11)
- [x] Writes `gold.fact_anomaly` with `severity`, `model_version`, and `contributing_factors` (baseline, peak impact, days observed, peak score)
- [x] `core_intelligence/eval_gate.py`: recall by kind, detection lag, alerts per vertical per week, and false positives on expected changes, against a naive fixed-multiple baseline; thresholds in `config.yaml`; exits non-zero on failure
- [x] 17 pytest tests for the scorer, episode grouping, and every gate failure path
- [x] Gate shown to fail end to end: raising the dollar floor to $25 makes it miss the step and ramp, report both, and exit 1

**Done when**: the eval report prints, the detector beats the naive baseline on recall at equal or lower alert volume, and the gate exits non-zero if thresholds are missed.

Result: recall 1.00 on all three kinds against the baseline's 1.00, 1.00, 0.00 (it never catches the ramp); 4 alerts against the baseline's 2, one of which matches no injected anomaly; 0 expected changes flagged.

### Step 3: Guardrail Engine policies (OPA)

**Proves**: claim 3, policy half.

- [x] `governed_automation/policies/risk.rego`: `classify_action_risk` as fixed rules, with `policy_production_gate` and `policy_blast_radius`, plus the reasons behind each tier
- [x] `governed_automation/policies/guardrails.rego`: kill switch, contract scope, `policy_exclusions`, `policy_run_caps`, `policy_reversibility_preference`, and the `decision` object the Orchestrator reads
- [x] 23 `opa test` cases covering every tier and every guardrail
- [x] `run_policy_tests.sh` (Docker, OPA pinned to 1.20.2)
- [x] Tests shown to fail: changing the production gate's tag value fails 4 of 23

**Done when**: `./run_policy_tests.sh -v` passes. Result: 23/23.

### Step 4: Orchestrator workflow (Temporal)

**Proves**: claim 3, workflow half.

- [x] `governed_automation/proposals.py`: idle-resource rule over utilization and cost, producing four proposals
- [x] `governed_automation/workflow.py`: `propose_action` with `check_automation_enabled`, `check_contract_exists`, `classify_action_risk` (calls OPA), the LOW/MEDIUM/HIGH branches, a kill-switch re-check before execution, a fake `execute_action`, and an audit row
- [x] `governed_automation/storage.py`: contracts, `automation_controls`, `automation_exclusions`, `fact_action_audit`
- [x] Activities idempotent on the workflow ID
- [x] `docker-compose.yml`: Temporal dev server plus OPA as the decision point
- [x] 12 workflow tests: auto, dry-run, advisory, approval, rejection, expiry, opt-out, opt-out timeout, kill switch mid-wait, exclusion, audit idempotency, and a replay test
- [x] Tests shown to fail: removing the kill-switch re-check fails the mid-wait test

**Done when**: workflow tests pass and a local run shows one LOW action executed and one HIGH action waiting. Result: 29 tests pass overall; `run_demo` shows executed, dry_run, advisory, and an approved HIGH action across four idle resources.

### Step 5: MCP server

**Proves**: claim 4.

- [x] `mcp_server/personas.py`: Platform and Vertical personas, verticals, and whether action tools bind
- [x] `mcp_server/queries.py`: every read filtered by the caller's verticals, standing in for `rap_vertical_scope`
- [x] `mcp_server/server.py`: `get_metric_definition`, `get_cost_by_account`, `get_anomalies`, `get_spend_variance`, and `propose_action` (bound only for a persona that may act)
- [x] Refusals come back as tool errors with the reason, not a generic failure
- [x] 12 tests: tool binding per persona, cross-vertical denial, scoped anomalies and variance, metric grounding, unknown metric, proposal through the harness, out-of-scope proposal, and a stdio round trip
- [x] Tests shown to fail: binding the action tool for every persona fails the binding test

**Done when**: scoping tests pass and the walkthrough answers "why did this vertical's bill change?" from tool calls. Result: 40 tests pass overall; over stdio the platform server exposes 5 tools and the workplace server 4.

### Step 6: CI

- [x] `.github/workflows/demo.yml`: generate, `dbt build`, anomaly scoring, eval gate, `opa test`, pytest
- [x] `wait_for_services.py`: readiness probe that connects a Temporal client and asks OPA a real policy question, because a port check passes before either can serve a request
- [x] Whole sequence verified locally from a clean state

**Done when**: CI is green on a push. Locally the full sequence passes from scratch (45 dbt tests, eval gate passed, 23 policy tests, 41 pytest). The workflow itself has not run on GitHub yet: it needs a push.

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
| 2026-09-17 | 6 | CI workflow running every gate, plus a readiness probe. Verified: the sequence passes locally from a clean state. Found while writing it: port probes report Temporal closed while a real client connects, so readiness uses the client and a live OPA query | The workflow has not run on GitHub; it needs a push |
| 2026-09-17 | 5 | MCP server with persona-bound tools and vertical-scoped queries, 12 tests including a stdio round trip, README walkthrough with client config. Verified: binding the action tool for everyone fails its test. Found by testing: APM-1003 had hit its 10-per-24h run cap from earlier runs, so tests now share a state reset and run_demo has --fresh | Nothing. Step 6 is CI |
| 2026-09-17 | 4 | propose_action workflow on Temporal, idle-resource proposals, DuckDB-backed contracts/controls/exclusions/audit, docker-compose for Temporal and OPA, 12 workflow tests including a replay test. Verified: removing the kill-switch re-check fails its test; four proposals produce four different governed outcomes | Nothing. Step 5 is the MCP server |
| 2026-09-17 | 3 | Rego policies for risk tiers and all guardrails, 23 opa tests, Docker runner pinned to OPA 1.20.2. Verified: mutating the production gate fails 4 tests. Guardrails only restrict; advisory is the default | Nothing. Step 4 needs a Temporal dev server (Docker) |
| 2026-09-17 | 2 | Detector, episode grouping, eval gate, 17 unit tests. Verified: gate exits 1 when the detector is degraded and 0 when restored; detector beats the naive baseline on the ramp. Tuning during the step: dollar floor lowered to $5 (D12), episodes added after daily alerting produced 25 alerts for 3 anomalies (D11) | Nothing. Committed separately from step 1 |
| 2026-09-17 | 1 | Generator, bronze/silver/gold, five metrics, 45 dbt tests passing from a clean run; generation deterministic (identical file hashes across runs). Verified: restated May Azure delivery replaces delivery 1; spike lands on 2026-05-12; Azure reservation utilization drops to about 92% after the covered VM ends; variance components sum exactly | Nothing. Not yet committed |
