# Detailed Build Specification: FinOps Intelligence Platform

Companion to three solution architecture documents, each covering a phase from `FinOps Solution Overview.md`: `Solution_Architecture_Data_Foundations.md` (§1–4 below), `Solution_Architecture_Self_Serve_Foundations.md` — Cloud Workbench (§5, §7), and `Solution_Architecture_Governed_Automation.md` (§6). §8–9 are cross-cutting infrastructure and observability shared across all three. Those documents establish the architecture and decisions; this one goes one level deeper, naming the actual components, schemas, interfaces, and policy artifacts precisely enough that a single IC could take this and build the full stack without having to invent structure themselves. **No implementation code is included by design**, this specifies what must exist and its contract, not how it's written. Names below are illustrative and consistent, not confirmed the organization naming conventions, adapt to actual org standards if this were real.

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

## 2. Bronze & Silver: Ingestion and Mediation (Databricks, Delta Lake)

Mediation is implemented here, as the bronze-to-silver transform within the lakehouse — not as a separate staging system. Bronze and silver live in the same `finops_platform` catalog as gold (Section 3); this section covers the jobs that populate both.

**Databricks Workflows / Spark jobs**:

| Job | Name | Input | Output | Purpose |
|---|---|---|---|---|
| Bronze ingest | `job_bronze_ingest_cost` | Raw landing zone (`raw/{provider}/...`) | `bronze.cost_line_items_raw` | Loads provider-native line items as-received into Delta, one-to-one with the landing zone — no transformation, still per-provider field names |
| Normalize | `spark_job_normalize_billing` | `bronze.cost_line_items_raw` | `silver.stg_{provider}_billing` | Field renaming, currency/unit conformance per provider (a lighter step where a FOCUS-compliant export is used — see the Data Foundations doc §4.2) |
| Reconcile tags | `spark_job_reconcile_tags` | Staged per-provider silver tables | `silver.stg_tags_reconciled` | Maps provider-specific tag keys to canonical tag taxonomy |
| Deduplicate + business rules | `spark_job_dedupe_line_items` (a.k.a. `job_silver_transform_cost`) | Reconciled staged data | `silver.cost_line_items_clean` | Removes duplicate line items from overlapping export windows, applies business rules — this is the lakehouse's silver transform |
| Data quality | `spark_job_dq_checks` | `silver.cost_line_items_clean` | DQ result log + quarantine table | Runs validation rules before promotion to gold (Section 3) |

**Silver staging schema (illustrative)**:

| Table | Key columns (illustrative) | Notes |
|---|---|---|
| `silver.stg_aws_billing` | `line_item_id`, `resource_id`, `raw_cost`, `currency`, `usage_start`, `usage_end` | Provider-native field names, post-normalization pass |
| `silver.stg_azure_billing` | (Azure-native equivalents) | Same pattern |
| `silver.stg_gcp_billing` | (GCP-native equivalents) | Same pattern |
| `silver.cost_line_items_clean` | `line_item_id` (PK), `resource_id`, `account_id`, `vertical_id`, `cost_usd`, `usage_date`, `canonical_tags` (variant/JSON) | Canonical, cross-provider, deduplicated schema; feeds gold aggregation (Section 3) |
| `silver.dq_results` | `run_id`, `check_name`, `status`, `failed_row_count`, `run_timestamp` | Data quality audit trail |

**Data quality checks (named rules, applied by `spark_job_dq_checks`)**:
- `dq_check_null_resource_id` — fails if `resource_id` is null on a non-tax line item
- `dq_check_currency_valid` — fails if `currency` isn't in the supported set
- `dq_check_cost_non_negative` — flags (not fails) negative costs for manual review, credits are legitimate but rare
- `dq_check_duplicate_line_item` — fails if the same `line_item_id` appears more than once post-dedupe

**Idempotency requirement**: every job in this stage must be safely re-runnable for the same date partition without producing duplicate rows, enforced via `MERGE`/upsert semantics keyed on `line_item_id`, not append-only writes.

---

## 3. Governed Lakehouse: Gold Layer & Catalog (Databricks, Delta Lake, Medallion)

**Catalog structure**: `finops_platform` (catalog) → `bronze` / `silver` / `gold` (schemas) — bronze and silver are populated by the jobs in Section 2; this section covers gold and the governance layer spanning all three.

**Databricks Workflows jobs**:

| Job | Name | Trigger | Purpose |
|---|---|---|---|
| Gold aggregate | `job_gold_aggregate_cost` | Downstream of `spark_job_dq_checks` (Section 2) | Build fact/dimension tables from `silver.cost_line_items_clean` → `gold.*` |
| Lineage sync | `job_lineage_catalog_sync` | Post gold job | Registers lineage/tags in the governance catalog |

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

**Governance/RBAC (Unity Catalog-equivalent)**:
- Row-level security policy `rls_policy_vertical_scope` on `gold.fact_cost_daily` and `gold.fact_anomaly`, filtering by `vertical_id` against the requesting user/service principal's assigned vertical(s)
- Access roles: `role_vertical_{name}_reader` (read own vertical only), `role_platform_admin` (cross-vertical read), `role_ml_pipeline_svc` (write access to `fact_anomaly`/`fact_recommendation` only)
- Column-level tagging: `cost_usd` and `estimated_savings_usd` tagged `sensitivity:financial` for downstream policy enforcement

**Optional BI serving path (Data Foundations ADR-003)**:

| Component | Name | Purpose |
|---|---|---|
| Share | `share_gold_bi_readonly` | A Delta Share (or Snowflake external-table/Iceberg-catalog equivalent) exposing `gold.*` read-only to Snowflake |
| Snowflake database | `FINOPS_BI` | Read-only Snowflake database mounted against the share — no independent ETL, no copy, no independently-maintained schema |

Row-level security and column-level tagging above apply identically on the Snowflake side of the share — this is the same governed data through a second query engine, not a second governance model.

---

## 4. Semantic Layer, Ontology, and Knowledge Graph

**Semantic layer** (metric definitions, implemented as a metrics config, e.g. dbt semantic layer YAML or equivalent):

| Metric name | Definition (source) | Notes |
|---|---|---|
| `metric_ec2_spend` | `SUM(cost_usd) WHERE resource_type = 'ec2' FROM gold.fact_cost_daily` | Canonical definition, single source of truth |
| `metric_monthly_burn_rate` | `SUM(cost_usd) GROUP BY MONTH(date), account_id` | |
| `metric_ri_coverage` | Derived from `fact_cost_daily` joined against RI commitment reference data | |
| `metric_anomaly_rate` | `COUNT(fact_anomaly) / COUNT(DISTINCT resource_id)` per period | |

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

**Graph store**: property graph database (e.g., a Gremlin- or Cypher-compatible store). Node labels and relationship types mirror the ontology table above directly.

**Graph population pipeline**:

| Job | Name | Trigger | Purpose |
|---|---|---|---|
| Graph sync | `job_populate_graph_from_gold` | Post gold-aggregate job | Upserts nodes/relationships from `gold.*` tables into the graph store |
| Entity resolution | `job_entity_resolution` | Within graph sync | Runs `resolve_resource_identity()` logic to merge cross-provider duplicate resource records into one node |

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

**Additional data quality checks (named rules)**:
- `dq_check_apm_id_present` — tracks the percentage of resources with a resolved APM ID (target: matching or exceeding the ~nearly all baseline); trended over time as a governance KPI, not just a pass/fail gate.
- `dq_check_owner_staleness` — flags `silver.apm_owner_history` records where `effective_start_date` exceeds a configurable staleness threshold (e.g., 6-12 months) without reconfirmation, distinct from `dq_check_apm_id_present`, this checks the volatile attribute, not the structural resource-to-app mapping.

---

## 5. AI Consumption Layer (Cloud Workbench)

**MCP server and exposed tools**:

| Tool name | Signature (spec) | Purpose |
|---|---|---|
| `get_cost_by_account` | `(account_id: str, period: DateRange) -> CostSummary` | Structured query against `gold.fact_cost_daily` |
| `get_anomalies` | `(vertical_id: str, period: DateRange, min_severity: str) -> List[Anomaly]` | Query `gold.fact_anomaly` |
| `query_graph` | `(query: GraphQuery) -> GraphResult` | Executes a scoped graph traversal |
| `search_semantic_docs` | `(query: str, top_k: int) -> List[Chunk]` | Hybrid dense (vector) + sparse (keyword/BM25) search over semantic layer documentation, returning both candidate sets for reranking (see `node_rerank`) |

**LangGraph nodes** (workflow steps, state machine):

| Node | Name | Function |
|---|---|---|
| Query rewrite | `node_query_rewrite` | Resolves conversational references, disambiguates the raw query |
| Route retrieval | `node_route_retrieval` | Decides structured/graph/vector path(s) based on query shape |
| Retrieve structured | `node_retrieve_structured` | Calls `get_cost_by_account` / `get_anomalies` |
| Retrieve graph | `node_retrieve_graph` | Calls `query_graph` for relational questions |
| Retrieve vector | `node_retrieve_vector` | Calls `search_semantic_docs` for definitional questions |
| Rerank | `node_rerank` | Cross-encoder rerank across the combined dense + sparse candidates from `search_semantic_docs` (see Self-Serve Foundations ADR-001) |
| Generate | `node_generate` | LLM call with assembled context |
| Grounding check | `node_grounding_check` | Runs `check_faithfulness()` before allowing the response through |
| Format citations | `node_format_citations` | Attaches human-readable source references |
| Route to action | `node_route_action` (conditional edge) | If the query implies an action, routes to the action-layer nodes (Section 6) |

**Function signatures (specification)**:
```
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

## 6. Action Layer (IDP, CMP Integration)

**MCP action tools**:

| Tool name | Signature (spec) | Purpose |
|---|---|---|
| `idp_provision_request` | `(resource_spec: ResourceSpec, requestor: Principal) -> RequestResult` | Submits a provisioning request to IDP |
| `cmp_container_action` | `(action: ContainerAction, target: ContainerRef) -> ActionResult` | Submits a container action to CMP |

**Risk classification and approval**:
```
classify_action_risk(action_payload: ActionPayload) -> RiskTier
  Purpose: Determine LOW / MEDIUM / HIGH risk tier for a proposed action.
  Inputs considered: action type (read/flag vs. resize/terminate), whether the
  target resource is tagged production, estimated blast radius (single resource
  vs. multiple).
  Output: RiskTier enum. HIGH always requires human approval regardless of any
  other factor (hard rule, not a scored threshold).
```

| Component | Name | Purpose |
|---|---|---|
| Approval queue table | `action_approval_requests` | `request_id`, `action_payload`, `risk_tier`, `status`, `approver_id`, `decided_at` |
| Approval service | `approval_queue_service` | Exposes review/approve/reject API for MEDIUM/HIGH tier actions |

**Policy-as-code (enforced independently of agent reasoning)**:

| Policy | Name | Rule (described) |
|---|---|---|
| Blast radius | `policy_blast_radius` | Deny any single action affecting more than N resources without explicit multi-resource approval |
| Production gate | `policy_production_gate` | Deny any resize/terminate action on a `production`-tagged resource without HIGH-tier approval |
| Reversibility bias | `policy_reversibility_preference` | Require a snapshot/backup step before any destructive action where one is available |

---

## 7. API/Service Layer

**Service**: `cost-intelligence-api` (containerized, versioned independently of the Cloud Workbench conversational endpoint).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/cost/{account_id}` | Programmatic cost lookup, same underlying data as `get_cost_by_account` |
| `GET` | `/v1/anomalies` | List anomalies, filterable by vertical/severity |
| `GET` | `/v1/recommendations` | List open rightsizing recommendations |
| `POST` | `/v1/recommendations/{id}/action` | Accept/reject a recommendation (routes through the same risk/approval logic as Section 6) |

OpenAPI spec maintained at `openapi.yaml`, auto-published to an internal developer portal for self-service discovery by other teams (satisfies FR5 in the Self-Serve Foundations doc).

---

## 8. Infrastructure Layer

**Terraform modules**:

| Module | Path | Provisions |
|---|---|---|
| `modules/aks-cluster` | Reusable | The AKS cluster hosting all platform services |
| `modules/storage-account` | Reusable | Raw/landing zone storage |
| `modules/databricks-workspace` | Reusable | The lakehouse workspace hosting bronze/silver/gold jobs (Sections 2–3), including mediation compute |
| `modules/graph-store` | Reusable | Knowledge graph database instance |

**Kubernetes namespaces**: `ns-cloud-workbench-prod`, `ns-cloud-workbench-staging`, `ns-mlops-prod`, one namespace per environment/domain for RBAC and resource-quota isolation.

**Container images/Helm charts**:

| Chart | Name | Deploys |
|---|---|---|
| API service | `chart-cost-intelligence-api` | `cost-intelligence-api` service |
| MCP server | `chart-mcp-cost-server` | The MCP tool server exposing Section 5/6 tools |
| Workbench orchestrator | `chart-cloud-workbench-orchestrator` | The LangGraph-based orchestration service |

**CI/CD pipeline**: `pipeline-cloud-workbench-ci`, stages: `test` (unit/integration) → `eval-gate` (runs `eval_set_cost_queries.yaml` against any prompt/retrieval/model change) → `deploy-staging` → `canary-prod` (10/50/100 traffic increments per the staged-rollout pattern).

---

## 9. Observability & Governance

**Audit log table**:

| Table | Key columns |
|---|---|
| `audit.workbench_query_log` | `request_id`, `user_id`, `vertical_id`, `query_text`, `retrieved_refs` (JSON), `model_input`, `model_output`, `action_taken` (nullable), `risk_tier` (nullable), `timestamp` |

**Tracing**: OpenTelemetry instrumentation across every node in Section 5's LangGraph workflow and every Section 6 action call, span attributes include `request_id`, `vertical_id`, `node_name`, `duration_ms`.

**Eval gate artifact**: `eval_set_cost_queries.yaml`, a curated set of representative queries with expected answer characteristics (not exact strings, expected supporting facts), run by CI job `job_run_eval_gate` on every prompt/retrieval/model change.

**Additional policy-as-code**:

| Policy | Name | Rule (described) |
|---|---|---|
| Vertical RBAC | `policy_rbac_vertical_scope` | Enforces that a query only returns data for the requestor's assigned vertical(s), independent of application-layer logic |
| PII/sensitive data | `policy_pii_redaction` | Redacts any inadvertently retrieved PII-adjacent fields before they reach generation |

---

## 10. What This Specification Deliberately Omits

Per the framing of this artifact: no SQL DDL, no Python/Spark implementation code, no actual Terraform HCL, no LangGraph Python graph definitions. An implementing engineer would write all of that against this specification, table names, column lists, function signatures, and policy names given here should be sufficient to build consistently without inventing the structure from scratch.
