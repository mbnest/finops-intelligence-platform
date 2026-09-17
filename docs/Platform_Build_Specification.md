# Detailed Build Specification: FinOps Intelligence Platform

Companion to four solution architecture documents, each covering a phase from [FinOps Solution Overview.md](FinOps%20Solution%20Overview.md): [Solution_Architecture_Data_Foundations.md](Solution_Architecture_Data_Foundations.md) (§1–4 below), [Solution_Architecture_Self_Serve_Foundations.md](Solution_Architecture_Self_Serve_Foundations.md) — Phase 2's API/dashboards (§7), [Solution_Architecture_Governed_Automation.md](Solution_Architecture_Governed_Automation.md) (§6), and [Solution_Architecture_Cloud_Workbench.md](Solution_Architecture_Cloud_Workbench.md) — Phase 5's agentic interface (§5). §8–9 are cross-cutting infrastructure and observability shared across all four. Those documents establish the architecture and decisions; this one goes one level deeper, naming the actual components, schemas, interfaces, and policy artifacts precisely enough that a single IC could take this and build the full stack without having to invent structure themselves. **No implementation code is included by design**, this specifies what must exist and its contract, not how it's written. Names below are illustrative and consistent, not confirmed the organization naming conventions, adapt to actual org standards if this were real.

---

## 1. Source Systems & Ingestion

**Orchestration**: Airflow (or Azure Data Factory equivalent), one DAG per provider, daily schedule aligned to each provider's billing export cadence.

| Component | Name | Purpose |
|---|---|---|
| DAG | `dag_billing_ingest_aws` | Pull AWS Cost and Usage Report (CUR) exports |
| DAG | `dag_billing_ingest_azure` | Pull Azure Cost Management API exports |
| DAG | `dag_billing_ingest_gcp` | Pull GCP Billing Export (BigQuery-sourced) |
| DAG | `dag_usage_telemetry_ingest` | Pull near-real-time usage/telemetry feeds (all providers) |
| Landing zone | `raw/{provider}/{export_type}/{date}/` | Immutable raw landing path per provider, partitioned by ingestion date |

**Raw schema note per provider (fields present, not full DDL)**: each lands with provider-native field names intact (e.g., AWS `lineItem/UnblendedCost`, Azure `costInUSD`, GCP `cost`), normalization happens in the silver-layer mediation transform (Section 2), not here, raw layer is preserved as-received for audit/replay.

---

## 2. Bronze & Silver: Ingestion and Mediation (Snowflake)

Mediation is implemented here, as the bronze-to-silver transform within Snowflake — not as a separate staging system. Bronze and silver live in the same `finops_platform` Snowflake database as gold (Section 3), as separate schemas; this section covers the jobs that populate both.

**Orchestration**: the Airflow DAGs from Section 1 (or native Snowflake Tasks) trigger this stage's dbt models and Snowpark procedures in sequence — no separate workflow engine for in-warehouse steps.

| Job | Name | Input | Output | Purpose |
|---|---|---|---|---|
| Bronze ingest | `job_bronze_ingest_cost` | Raw landing zone (`raw/{provider}/...`) | `bronze.cost_line_items_raw` | Loads provider-native line items as-received into Snowflake, one-to-one with the landing zone — no transformation, still per-provider field names |
| Normalize | `dbt_model_normalize_billing` | `bronze.cost_line_items_raw` | `silver.stg_{provider}_billing` | Field renaming, currency/unit conformance per provider (a lighter step where a FOCUS-compliant export is used — see the Data Foundations doc §4.2) |
| Reconcile tags | `dbt_model_reconcile_tags` | Staged per-provider silver tables | `silver.stg_tags_reconciled` | Maps provider-specific tag keys to canonical tag taxonomy |
| Deduplicate + business rules | `snowpark_job_dedupe_line_items` (a.k.a. `job_silver_transform_cost`) | Reconciled staged data | `silver.cost_line_items_clean` | Removes duplicate line items from overlapping export windows, applies business rules — this is the platform's silver transform; done in Snowpark rather than dbt/SQL because the dedup logic is more naturally a stateful pass than a set-based query |
| Data quality | `job_dq_checks` (a dbt test suite) | `silver.cost_line_items_clean` | DQ result log + quarantine table | Runs validation rules before promotion to gold (Section 3) |

**Silver staging schema (illustrative)**:

| Table | Key columns (illustrative) | Notes |
|---|---|---|
| `silver.stg_aws_billing` | `line_item_id`, `resource_id`, `raw_cost`, `currency`, `usage_start`, `usage_end` | Provider-native field names, post-normalization pass |
| `silver.stg_azure_billing` | (Azure-native equivalents) | Same pattern |
| `silver.stg_gcp_billing` | (GCP-native equivalents) | Same pattern |
| `silver.cost_line_items_clean` | `line_item_id` (PK), `resource_id`, `account_id`, `vertical_id`, `cost_usd`, `usage_date`, `canonical_tags` (variant/JSON) | Canonical, cross-provider, deduplicated schema; feeds gold aggregation (Section 3) |
| `silver.dq_results` | `run_id`, `check_name`, `status`, `failed_row_count`, `run_timestamp` | Data quality audit trail |

**Data quality checks (named rules, applied by `job_dq_checks`)**:
- `dq_check_null_resource_id` — fails if `resource_id` is null on a non-tax line item
- `dq_check_currency_valid` — fails if `currency` isn't in the supported set
- `dq_check_cost_non_negative` — flags (not fails) negative costs for manual review, credits are legitimate but rare
- `dq_check_duplicate_line_item` — fails if the same `line_item_id` appears more than once post-dedupe

**Idempotency requirement**: every job in this stage must be safely re-runnable for the same date partition without producing duplicate rows, enforced via `MERGE`/upsert semantics keyed on `line_item_id`, not append-only writes.

---

## 3. Governed Snowflake Platform: Gold Layer & Catalog (medallion-layered schemas)

**Database structure**: `finops_platform` (Snowflake database) → `bronze` / `silver` / `gold` (schemas) — bronze and silver are populated by the jobs in Section 2; this section covers gold and the governance layer spanning all three.

**Jobs (dbt models, orchestrated per Section 2)**:

| Job | Name | Trigger | Purpose |
|---|---|---|---|
| Gold aggregate | `job_gold_aggregate_cost` (a dbt model) | Downstream of `job_dq_checks` (Section 2) | Build fact/dimension tables from `silver.cost_line_items_clean` → `gold.*` |
| Governance tagging | `job_governance_tag_sync` | Post gold job | Applies Snowflake object tags (Section 3's tagging below) to new/changed gold objects |

**Gold-layer schema (consumption-ready)**:

| Table | Type | Key columns | Notes |
|---|---|---|---|
| `gold.fact_cost_daily` | Fact | `date`, `account_id`, `resource_id`, `cost_usd`, `usage_qty` | Grain: one row per resource per day |
| `gold.dim_account` | Dimension | `account_id` (PK), `vertical_id`, `provider`, `account_name` | |
| `gold.dim_resource` | Dimension | `resource_id` (PK), `resource_type`, `region`, `created_date` | |
| `gold.dim_vertical` | Dimension | `vertical_id` (PK), `vertical_name`, `cost_center` | |
| `gold.dim_tag` | Dimension | `tag_key`, `tag_value`, `resource_id` (FK) | Supports metadata filtering |
| `gold.fact_anomaly` | Fact | `anomaly_id`, `resource_id`, `detected_date`, `severity`, `model_version`, `contributing_factors` (JSON) | Written by Core Intelligence (MLOps Pipeline doc) |
| `gold.fact_recommendation` | Fact | `recommendation_id`, `resource_id`, `type`, `estimated_savings_usd`, `status`, `model_version` | Written by Core Intelligence |
| `gold.dim_rate_card` | Dimension | `rate_card_id` (PK), `provider`, `resource_type`, `contracted_unit_rate`, `effective_start_date`, `effective_end_date` | Ingested vendor rate data, not derived — source system not yet confirmed with the organization (Data Foundations §4.1) |
| `gold.fact_bill_verification` | Fact | `verification_id`, `cost_fact_id` (FK), `confidence_score`, `evidence` (JSON), `status`, `model_version` | Written by Bill Verification's reconciliation model |

**Governance/RBAC (Snowflake Horizon)**:
- Row access policy `rap_vertical_scope` on `gold.fact_cost_daily` and `gold.fact_anomaly`, filtering by `vertical_id` against the requesting user/service principal's assigned vertical(s)
- Access roles: `role_vertical_{name}_reader` (read own vertical only), `role_platform_admin` (cross-vertical read), `role_ml_pipeline_svc` (write access to `fact_anomaly`/`fact_recommendation` only)
- Object tagging: `cost_usd` and `estimated_savings_usd` tagged `sensitivity:financial` via Snowflake tag-based classification, with a masking policy attached for any role without an explicit financial-data grant

**BI access is a native grant, not a separate system.** Power BI connects with `role_vertical_{name}_reader` or `role_platform_admin` against the Semantic Views (Section 4) for anything with a governed metric definition; the same roles grant fallback access directly against `gold` schema views for ad hoc analyst SQL not yet expressible as a metric (Data Foundations ADR-002, ADR-003). No share object, no second database, no independently-maintained copy either way. The row access policy and tagging above apply to every consumer — Semantic Views included, since they're computed from these same `gold` tables — by construction, rather than as a second governance model to keep in sync.

---

## 4. Semantic Layer, Ontology, and Knowledge Graph

**Semantic layer** (metric definitions, implemented as Snowflake Semantic Views, optionally authored via dbt's semantic layer config and published into Snowflake):

| Metric name | Definition (source) | Notes |
|---|---|---|
| `metric_ec2_spend` | `SUM(cost_usd) WHERE resource_type = 'ec2' FROM gold.fact_cost_daily` | Canonical definition, single source of truth |
| `metric_total_spend` | `SUM(cost_usd)` from `gold.fact_cost_daily`, by vertical/account/period | |
| `metric_spend_variance_mom` | Period-over-period delta on `metric_total_spend`, decomposed into new/terminated resources vs. usage change vs. price change | |
| `metric_spend_by_resource_type` | `SUM(cost_usd) GROUP BY resource_type` | |
| `metric_spend_by_environment` | `SUM(cost_usd) GROUP BY environment` tag | |
| `metric_unattributed_spend_pct` | `SUM(cost_usd)` where APM ID is unresolved, as % of total spend | Dollar-weighted; distinct from `dq_check_apm_id_present`'s resource-count-weighted version (Section 2) |
| `metric_monthly_burn_rate` | `SUM(cost_usd) GROUP BY MONTH(date), account_id` | |
| `metric_forecast_vs_budget_variance` | Projected month-end spend (run-rate extrapolation of `metric_monthly_burn_rate`) vs. budget reference data | Budget reference data source not yet defined — placeholder, per `FinOps Opportunities.md` |
| `metric_utilization_rate` | Consumed vs. allocated compute/memory/storage, per resource | Reused as a feature input by MLOps Pipeline (rightsizing), not recomputed there — see MLOps Pipeline ADR-001 |
| `metric_idle_resource_spend` | `SUM(cost_usd)` where `metric_utilization_rate` is below a configurable near-zero threshold | |
| `metric_open_recommendation_savings` | `SUM(estimated_savings_usd)` from `gold.fact_recommendation` where `status = 'open'` | |
| `metric_recommendation_realization_rate` | % of recommendations moved to an "implemented" status within N days of being raised | |
| `metric_ri_coverage` | Derived from `fact_cost_daily` joined against RI commitment reference data | |
| `metric_ri_sp_utilization` | Committed capacity actually consumed, vs. purchased | Reused as a feature input by MLOps Pipeline (RI/SP modeling), not recomputed there — see MLOps Pipeline ADR-001 |
| `metric_anomaly_rate` | `COUNT(fact_anomaly) / COUNT(DISTINCT resource_id)` per period | |
| `metric_anomaly_dollar_impact` | `SUM(cost_usd)` attributable to line items flagged by `fact_anomaly` | |
| `metric_chargeback_amount` | `metric_total_spend` rolled up to vertical, one month in arrears | Matches Current State's existing chargeback cadence |
| `metric_peer_percentile_rank` | Percentile rank of a rate metric (e.g. `metric_utilization_rate`) against an anonymized peer set | Rate-based only, per `FinOps Opportunities.md` §2b |

**Ontology (entity/relationship definitions)**:

| Entity | Key attributes | Relationships |
|---|---|---|
| `Account` | account_id, provider, name | `BELONGS_TO → Vertical` |
| `Vertical` | vertical_id, name, cost_center | `HAS_MANY → Account` |
| `Resource` | resource_id, type, region | `BELONGS_TO → Account`, `TAGGED_WITH → Tag` |
| `Tag` | key, value | `APPLIED_TO → Resource` |
| `CostLineItem` | line_item_id, date, cost | `REFERENCES → Resource` |
| `Anomaly` | anomaly_id, severity | `DETECTED_ON → Resource` |
| `Recommendation` | recommendation_id, type | `TARGETS → Resource` |
| `RateCard` | rate_card_id, provider, resource_type, contracted_unit_rate | `PRICES → CostLineItem` |
| `BillVerification` | verification_id, confidence_score, status | `RECONCILES → CostLineItem` |

**Graph store**: Neo4j (Data Foundations ADR-004) — a dedicated property-graph database, not implemented in Snowflake. Node labels and relationship types mirror the ontology table above directly (`Resource`, `Account`, `Vertical`, `Tag`, `CostLineItem`, `Anomaly`, `Recommendation`, `RateCard`, `BillVerification`).

**Graph population pipeline**:

| Job | Name | Trigger | Purpose |
|---|---|---|---|
| Graph sync | `job_populate_graph_from_gold` | Post gold-aggregate job (Section 3) | Upserts nodes/relationships into Neo4j — gold remains the system of record, Neo4j is a resynced derivative. Static node attributes read from `gold.*` tables directly; any computed node property reads from the corresponding Snowflake Semantic View metric (Section 4's semantic layer) rather than being recalculated independently in this job (Data Foundations ADR-004) |
| Entity resolution | `job_entity_resolution` (Snowpark) | Within `job_gold_aggregate_cost`, ahead of graph sync | Runs `resolve_resource_identity()` logic to merge cross-provider duplicate resource records into one row in `gold.dim_resource`, before that row is synced into Neo4j as a single node |

**Function signature (specification, not implementation)**:
```
resolve_resource_identity(candidate_records: List[ResourceRecord]) -> ResolvedEntity
  Purpose: Determine whether multiple resource records (potentially from different
  providers/tagging schemes) refer to the same underlying entity, and merge if so.
  Input: list of resource records with provider-native identifiers and attributes.
  Output: a single resolved entity reference plus a confidence score.
  Priority order: match on APM ID first if present (authoritative, organization-level
  key), fall back to fuzzy cross-cloud tag matching only for unresolved records.
  Must log: which records were merged, which method resolved them (APM ID vs. fuzzy
  tag match), confidence score, for audit.
```

**APM (Application Portfolio Management) ingestion**:

| Component | Name | Purpose |
|---|---|---|
| Ingestion job | `job_apm_metadata_sync` | Pulls application metadata from the APM tool, scheduled daily |
| Table | `bronze.apm_application_metadata` | `apm_id` (PK), `app_name`, `classification`, `owner_current`, `technical_contact_current` |
| SCD Type 2 table | `silver.apm_owner_history` | `apm_id`, `owner`, `technical_contact`, `effective_start_date`, `effective_end_date` (null = current) |

**Terraform state ingestion** (Data Foundations §4.1):

| Component | Name | Purpose |
|---|---|---|
| Ingestion job | `job_terraform_state_sync` | Pulls resolved resource config from the organization's Terraform state backend (Terraform Cloud/Enterprise API, or a state file backend), scheduled on module-apply events where available, otherwise daily |
| Table | `gold.dim_resource_iac_state` | `resource_id` (PK/FK to `gold.dim_resource`), `managed_by_iac` (bool), `declared_config` (JSON), `last_apply_timestamp`, `config_drift` (bool, computed against the resource's current observed config) |

**Additional data quality checks (named rules)**:
- `dq_check_apm_id_present` — tracks the percentage of resources with a resolved APM ID (target: matching or exceeding the ~nearly all baseline); trended over time as a governance KPI, not just a pass/fail gate.
- `dq_check_owner_staleness` — flags `silver.apm_owner_history` records where `effective_start_date` exceeds a configurable staleness threshold (e.g., 6-12 months) without reconfirmation, distinct from `dq_check_apm_id_present`, this checks the volatile attribute, not the structural resource-to-app mapping.

---

## 5. AI Consumption Layer (Cloud Workbench, Phase 5)

**Redis: retrieval cache + session memory** (Cloud Workbench ADR-003, ADR-009), two logically separate key spaces on one instance.

| Component | Name | Purpose |
|---|---|---|
| Cache instance | `redis-cloud-workbench-cache` | Self-hosted on AKS, alongside the platform's other AKS-hosted services |
| Retrieval cache key | `ctx:{vertical_id}:{account_id}:{time_range}:{query_shape_hash}` | Resolved parameters only, never the raw natural-language question. TTL short enough to bound staleness against Data Foundations' refresh cadence |
| Session memory key | `session:{session_id}` | Last few turns of the active conversation, TTL'd to session lifetime. Read at the start of `node_query_rewrite`, appended to after `node_format_citations` (Cloud Workbench ADR-009) |

No vector store in this design — Postgres/pgvector was removed (Cloud Workbench ADR-006); definitional questions are answered via `get_metric_definition` below, a direct Snowflake lookup, not embedding-based search.

**MCP server and exposed tools**:

| Tool name | Signature (spec) | Purpose |
|---|---|---|
| `get_cost_by_account` | `(account_id: str, period: DateRange) -> CostSummary` | Structured query against `gold.fact_cost_daily`, RBAC-scoped to the requestor's own vertical(s) regardless of persona — the core "why is this thing so expensive" lookup, available to both personas |
| `get_anomalies` | `(vertical_id: str, period: DateRange, min_severity: str) -> List[Anomaly]` | Query `gold.fact_anomaly`, RBAC-scoped to the requestor's own vertical(s) regardless of persona |
| `get_peer_benchmark` | `(metric_name: str, vertical_id: str) -> BenchmarkResult` | Returns `metric_peer_percentile_rank` (Data Foundations §4.4) for a rate-based metric only. **Platform persona only** — not in the Vertical tool set (Cloud Workbench ADR-007) |
| `query_graph` | `(query: GraphQuery) -> GraphResult` | Executes a scoped Cypher graph traversal against Neo4j (Section 4) |
| `get_metric_definition` | `(name_or_synonym: str) -> MetricDefinition` | Direct SQL/`SEARCH` lookup against Snowflake Semantic View metadata (Section 4) by name or synonym — no embedding, no vector index. Called both by `node_query_rewrite` (grounding, Cloud Workbench ADR-008) and directly for purely definitional questions |

**Persona-to-tool-set mapping** (enforced by `node_resolve_persona`, below; Cloud Workbench ADR-007):

| Persona | Tools available |
|---|---|
| Platform (FinOps/platform team) | All tools in this section, unrestricted by persona (still RBAC-scoped by vertical/account where applicable) |
| Vertical (a business vertical) | `get_cost_by_account`, `get_anomalies`, `query_graph`, `get_metric_definition` — **not** `get_peer_benchmark` (cross-vertical comparison, an enrichment beyond explaining one's own bill, Platform-only for now) and **not** `propose_action` (Section 6) |

**pydantic-graph nodes** (workflow steps, state machine):

| Node | Name | Function |
|---|---|---|
| Resolve persona | `node_resolve_persona` | First node in the graph. Resolves Platform/Vertical from auth context, binds the persona-scoped tool set (above) and system-prompt variant for the rest of the request (Cloud Workbench ADR-007) |
| Query rewrite | `node_query_rewrite` | Loads session memory (Redis `session:{session_id}`) for coreference resolution, then grounds the query — metric references via `get_metric_definition`, entity references against `resolve_resource_identity()`, relative time expressions against a concrete `DateRange` — rather than passing free text downstream (Cloud Workbench ADR-008, ADR-009) |
| Check cache | `node_check_cache` | Looks up `node_query_rewrite`'s resolved parameters in Redis's retrieval-cache key space (Cloud Workbench ADR-003); on hit, skips straight to `node_generate` |
| Route retrieval | `node_route_retrieval` | Cache miss only. If the question is purely definitional, the definition is already resolved (`node_query_rewrite`) and this routes straight to `node_populate_cache`. Otherwise decides structured/graph path(s) based on query shape, from the tool set `node_resolve_persona` bound |
| Retrieve structured | `node_retrieve_structured` | Calls `get_cost_by_account` / `get_anomalies` |
| Retrieve graph | `node_retrieve_graph` | Calls `query_graph` for relational questions |
| Populate cache | `node_populate_cache` | Writes the retrieved context to Redis under `node_query_rewrite`'s resolved-parameter key (Cloud Workbench ADR-003) |
| Generate | `node_generate` | LLM call with assembled context (from cache or from `node_populate_cache`) |
| Grounding check | `node_grounding_check` | Runs `check_faithfulness()` before allowing the response through |
| Format citations | `node_format_citations` | Attaches human-readable source references, appends this turn to session memory (Redis `session:{session_id}`, Cloud Workbench ADR-009) |
| Route to action | `node_route_action` (conditional edge) | If the query implies an action, calls `propose_action` (Section 6) — the only action-layer tool exposed to this agent; it never calls `idp_provision_request`/`cmp_container_action` directly |

**Function signatures (specification)**:
```
rewrite_query(raw_query: str, conversation_context: ConversationContext, persona: Persona) -> ResolvedQuery  [node_query_rewrite]
  Purpose: Resolve conversational references, then ground the query against
  sources this platform already governs — not left to retrieval or generation
  to interpret independently (Cloud Workbench ADR-008).
  Output: ResolvedQuery {
    disambiguated_text: str,
    canonical_metrics: List[str]       # Semantic View metric names (Section 4)
    resolved_entities: List[EntityRef] # vertical_id / APM ID via resolve_resource_identity() (Section 4)
    resolved_time_range: DateRange,
  }
  On unresolvable entity or metric reference: pass the unresolved term through
  to node_route_retrieval flagged as ungrounded, rather than failing the
  request outright.

get_metric_definition(name_or_synonym: str) -> MetricDefinition
  Purpose: Direct lookup against Snowflake Semantic View metadata by name or
  synonym (Cloud Workbench ADR-001, ADR-006) — no embedding, no vector index.
  Output: MetricDefinition { canonical_name, description, computed_from } or
  not-found if no name/synonym match clears the fuzzy-match threshold.

check_faithfulness(answer: str, retrieved_context: List[Chunk]) -> FaithfulnessResult
  Purpose: Verify each claim in the answer is supported by retrieved context.
  Output: pass/fail plus list of unsupported claims, if any.
  On fail: response is blocked; node_generate is retried once with a stricter
  prompt, or the system abstains with a "not enough information" response.

check_confidence_threshold(retrieval_scores: List[float]) -> bool
  Purpose: Determine whether retrieval quality is sufficient to attempt generation at all.
  Output: True (proceed) / False (abstain before generation).
```

**API endpoint (external-facing, versioned)**:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/workbench/query` | Submit a natural-language query; returns answer, citations, request_id |
| `GET` | `/v1/workbench/query/{request_id}` | Retrieve a prior query's full result, including trace reference |

---

## 6. Action Layer / Orchestrator & Guardrail Engine (IDP, CMP Integration)

**Agent-facing tool — the single entry point (Governed Automation §3.2)**:

| Tool name | Signature (spec) | Purpose |
|---|---|---|
| `propose_action` | `(action_type: str, target: ResourceRef, params: dict, origin: Literal["core_intelligence","cloud_workbench"]) -> ProposalResult` | The only action-layer tool exposed to Core Intelligence or Cloud Workbench. Starts a Temporal workflow (below); `ProposalResult` is queued/executed/denied, never a direct execution result |

**Internal execution tools — never exposed to an agent, called only by the Temporal workflow's `execute_action` Activity**:

| Tool name | Signature (spec) | Purpose |
|---|---|---|
| `idp_provision_request` | `(resource_spec: ResourceSpec, requestor: Principal) -> RequestResult` | Submits a provisioning request to IDP |
| `cmp_container_action` | `(action: ContainerAction, target: ContainerRef) -> ActionResult` | Submits a container action to CMP |

**Orchestration: Temporal workflow (Governed Automation §3.3)**. One workflow instance per `propose_action` call, running as Activities/Timers/Signals on the Temporal cluster (AKS):

```
classify_action_risk(action_payload: ActionPayload) -> RiskTier   [Activity]
  Purpose: Determine LOW / MEDIUM / HIGH risk tier for a proposed action.
  Evaluates OPA policy rules (below) against: action type (read/flag vs.
  resize/terminate), whether the target resource is tagged production,
  estimated blast radius (single resource vs. multiple).
  Output: RiskTier enum. HIGH always requires human approval regardless of any
  other factor (hard rule, not a scored threshold).

check_iac_managed(action_payload: ActionPayload) -> IacStatus     [Activity]
  Purpose: Determine whether the target resource is Terraform-managed
  (Data Foundations §4.1's Terraform state reference table), before
  execute_action runs. Runs ahead of execute_action, not inside it.
  Output: IacStatus { managed_by_iac: bool, drifted: bool }.

execute_action(action_payload: ActionPayload, iac_status: IacStatus) -> ActionResult  [Activity]
  Purpose: If iac_status.managed_by_iac, call open_terraform_pr or
  trigger_terraform_run instead of IDP/CMP. Otherwise call
  idp_provision_request or cmp_container_action depending on action type.
  Retried per Temporal's built-in retry policy on transient failure;
  exhausted retries hand off to alert_teams.

open_terraform_pr(action_payload) -> PrResult                     [Activity]
trigger_terraform_run(action_payload) -> RunResult                [Activity]
  Purpose: Execute an approved action against a Terraform-managed resource
  through the IaC pipeline rather than IDP/CMP directly (Governed
  Automation ADR-004) — a PR against the owning module, or a triggered
  Terraform Cloud/Enterprise run, depending on which VCS/CI integration
  the module uses.

alert_teams(action_payload, failure_reason) -> None               [Activity]
ROLLBACK: rollback_from_snapshot(action_payload) -> RollbackResult [Activity]
```

| Component | Name | Purpose |
|---|---|---|
| Approval queue table (Postgres) | `action_approval_requests` | `request_id` (PK), `workflow_id` (Temporal workflow/run ID — an approve/reject decision Signals this specific workflow, so it has to be stored, not just implied), `origin` (`core_intelligence` \| `cloud_workbench` \| `self_serve_api`), `apm_id` (scopes which team's approvers can see/act on this request), `action_payload`, `risk_tier`, `contract_id` (FK → `contracts`, Governed Automation §3.4 — nullable until that entity exists), `status`, `approver_id`, `requested_at`, `decided_at` — operational state, not Snowflake (Governed Automation ADR-003) |
| Approval service | `approval_queue_service` | Exposes review/approve/reject API for MEDIUM/HIGH tier actions; an approve/reject call sends a Temporal Signal to the corresponding workflow |
| Contract table (Postgres) | `contracts` | **Illustrative — the contract entity itself is not yet designed (Governed Automation §3.4)**; a lightweight starting model, not a final one: `contract_id` (PK), `apm_id`, `tier_scope` (LOW-only vs. full MEDIUM/HIGH, per §3.4's tiered-contract note), `pre_approved_actions`, `notification_requirements`, `change_window`, `rollback_guarantee`, `escalation_path`, `signed_by`, `signed_at`, `status` (active/expired/revoked). Same OLTP access pattern as the approval queue (checked before allowing automation), so Postgres by the same ADR-003 reasoning, not Snowflake |
| Audit table (Snowflake gold) | `gold.fact_action_audit` | `request_id`, `action_payload`, `risk_tier`, `origin`, `contract_id`, `outcome`, `executed_at`, `rolled_back` (bool) — synced from Postgres/Temporal history once a workflow completes, for cross-platform reporting (Governed Automation ADR-003); `contract_id` added so FR4's audit trail actually links to "the agreement that authorized it," not just the APM ID |

**Policy-as-code (Open Policy Agent, enforced independently of agent reasoning)**:

| Policy | Name | Rule (described) |
|---|---|---|
| Blast radius | `policy_blast_radius` | Deny any single action affecting more than N resources without explicit multi-resource approval |
| Production gate | `policy_production_gate` | Deny any resize/terminate action on a `production`-tagged resource without HIGH-tier approval |
| Reversibility bias | `policy_reversibility_preference` | Require a snapshot/backup step before any destructive action where one is available |

---

## 7. API/Service Layer (Phase 2)

**Service**: `cost-intelligence-api` (containerized, versioned independently of Phase 5's Cloud Workbench conversational endpoint).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/cost/{account_id}` | Programmatic cost lookup, same underlying data as `get_cost_by_account` |
| `GET` | `/v1/anomalies` | List anomalies, filterable by vertical/severity |
| `GET` | `/v1/recommendations` | List open rightsizing recommendations |
| `POST` | `/v1/recommendations/{id}/action` | Accept/reject a recommendation (routes through the same risk/approval logic as Section 6) |

OpenAPI spec maintained at `openapi.yaml`, auto-published to an internal developer portal for self-service discovery by other teams (satisfies FR1 in the Self-Serve Foundations doc).

---

## 8. Infrastructure Layer

**Terraform modules**:

| Module | Path | Provisions |
|---|---|---|
| `modules/aks-cluster` | Reusable | The AKS cluster hosting all platform services |
| `modules/storage-account` | Reusable | Raw/landing zone storage |
| `modules/snowflake-platform` | Reusable | The Snowflake account objects hosting bronze/silver/gold (Sections 2–3): databases, schemas, virtual warehouses (sized separately for ingestion/transform vs. ML training vs. BI serving), roles, row access policies, and masking policies |
| `modules/graph-store` | Reusable | The Neo4j instance backing the knowledge graph (Section 4, Data Foundations ADR-004) |
| `modules/postgres` | Reusable | A Postgres instance provisioning the action-approval/workflow operational state (Section 6, Governed Automation ADR-003). No longer shared with a documentation vector index — that use was removed, Cloud Workbench ADR-006 |
| `modules/temporal-cluster` | Reusable | The Temporal cluster running the Orchestrator — Governed Automation's proposed-action workflows (Section 6, Governed Automation ADR-002) |
| `modules/opa-policy-engine` | Reusable | The OPA (Open Policy Agent) instance running the Guardrail Engine — the policy-decision point the Orchestrator consults for risk classification (Section 6, Governed Automation §3.1). Previously had no infrastructure module of its own |
| `modules/redis-cache` | Reusable | The Redis instance backing Cloud Workbench's retrieval-context cache and session memory (Section 5, Cloud Workbench ADR-003, ADR-009) |

**Kubernetes namespaces**: `ns-cloud-workbench-prod`, `ns-cloud-workbench-staging`, `ns-mlops-prod`, `ns-governed-automation-prod`, `ns-governed-automation-staging` (hosts both the Orchestrator and the Guardrail Engine), one namespace per environment/domain for RBAC and resource-quota isolation.

**Container images/Helm charts**:

| Chart | Name | Deploys |
|---|---|---|
| API service | `chart-cost-intelligence-api` | `cost-intelligence-api` service |
| MCP server | `chart-mcp-cost-server` | The MCP tool server exposing Section 5/6 tools |
| Workbench orchestrator | `chart-cloud-workbench-orchestrator` | The pydantic-graph-based orchestration service |
| Orchestrator | `chart-guardrail-orchestrator` | Governed Automation's Temporal-workflow-based durable orchestration service (Section 6) — previously had no deployable of its own, only the `modules/temporal-cluster` infra module above |
| Guardrail Engine | `chart-guardrail-engine` | The OPA-based policy-decision service (Section 6) the Orchestrator calls for risk classification — previously had no deployable or infra module at all |

**CI/CD pipeline**: `pipeline-cloud-workbench-ci`, stages: `test` (unit/integration) → `eval-gate` (runs `eval_set_cost_queries.yaml` against any prompt/retrieval/model change) → `deploy-staging` → `canary-prod` (10/50/100 traffic increments per the staged-rollout pattern).

---

## 9. Observability & Governance

**Audit log table**:

| Table | Key columns |
|---|---|
| `audit.workbench_query_log` | `request_id`, `session_id`, `user_id`, `vertical_id`, `query_text`, `retrieved_refs` (JSON), `model_input`, `model_output`, `action_taken` (nullable), `risk_tier` (nullable), `timestamp` |

Governed Automation's action-level audit trail is separate: Temporal's own workflow history captures every state transition for a proposed action as it happens, and `gold.fact_action_audit` (Section 6) is the queryable, reportable copy synced once a workflow completes — this table logs the query/generation side of Cloud Workbench, not action execution.

This table also serves as Cloud Workbench's long-term memory (Cloud Workbench ADR-009, §4.1) — `session_id` and `user_id` scope a lookup when a user references a prior conversation, reusing this table's existing retention policy and RBAC rather than a second durable store.

**Tracing**: OpenTelemetry instrumentation, exported to Datadog APM (Data Foundations §4.5), across every node in Section 5's pydantic-graph workflow and every Section 6 action call, span attributes include `request_id`, `vertical_id`, `node_name`, `duration_ms`.

**Eval gate artifact**: `eval_set_cost_queries.yaml`, a curated set of representative queries with expected answer characteristics (not exact strings, expected supporting facts), run by CI job `job_run_eval_gate` on every prompt/retrieval/model change.

**Additional policy-as-code**:

| Policy | Name | Rule (described) |
|---|---|---|
| Vertical RBAC | `policy_rbac_vertical_scope` | Enforces that a query only returns data for the requestor's assigned vertical(s), independent of application-layer logic |
| PII/sensitive data | `policy_pii_redaction` | Redacts any inadvertently retrieved PII-adjacent fields before they reach generation |

---

## 10. What This Specification Deliberately Omits

Per the framing of this artifact: no SQL DDL, no dbt model SQL or Snowpark Python implementation code, no actual Terraform HCL, no pydantic-graph Python node/edge definitions. An implementing engineer would write all of that against this specification, table names, column lists, function signatures, and policy names given here should be sufficient to build consistently without inventing the structure from scratch.
