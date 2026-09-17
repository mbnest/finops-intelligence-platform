# Detailed Build Specification: FinOps Intelligence Platform

Companion to the solution architecture documents indexed in [FinOps Solution Overview.md](FinOps%20Solution%20Overview.md):

| Section | Document |
|---|---|
| §1–4 | [Solution_Architecture_Data_Foundations.md](Solution_Architecture_Data_Foundations.md) (Phase 1) |
| §5 | [Solution_Architecture_Cloud_Workbench.md](Solution_Architecture_Cloud_Workbench.md) (Phase 5 agent) |
| §6 | [Solution_Architecture_Governed_Automation.md](Solution_Architecture_Governed_Automation.md) and its Contract extension (Phase 3) |
| §7 | [Solution_Architecture_Self_Serve_Foundations.md](Solution_Architecture_Self_Serve_Foundations.md) (Phase 2 API and dashboards) |
| §8–9 | Infrastructure and observability shared by every phase |
| §10 | [Solution_Architecture_Bill_Verification.md](Solution_Architecture_Bill_Verification.md) (Phase 4) |
| §11 | [Solution_Architecture_PO_Auto_Draft.md](Solution_Architecture_PO_Auto_Draft.md) (Phase 5 extension) |
| §12 | [Solution_Architecture_Cloud_Workbench_Expansion.md](Solution_Architecture_Cloud_Workbench_Expansion.md) (Phase 5 extension) |

Those documents set the architecture and decisions. This one goes a level deeper and names the components, schemas, interfaces, and policies precisely enough that one engineer could build the stack without inventing structure. **It contains no implementation code on purpose**: it specifies what must exist and its contract, not how it is written. Names are illustrative and consistent, not confirmed the organization conventions; a real build would adapt them to the organization's standards.

---

## 1. Source Systems & Ingestion

**Orchestration**: Snowflake Tasks, one task graph per provider, started by data arrival, not a fixed clock (Data Foundations ADR-006). File-based exports (AWS Data Exports in FOCUS or CUR 2.0 format, Azure cost exports, and GCP billing data exported from BigQuery to Cloud Storage) load from external stages with Snowpipe auto-ingest when a file lands; `COPY INTO` is kept for backfills and manual reloads. Each provider's task graph root is a triggered task (`WHEN SYSTEM$STREAM_HAS_DATA` on that provider's bronze stream), so silver and gold refresh after each provider refresh without polling. API-based sources (invoices, provider recommendations, commitment inventory, APM, Terraform state) are pulled on a daily schedule by Snowpark procedures using Snowflake external access integrations. There is no separate orchestrator, because every later step is already a dbt model or Snowpark procedure in Snowflake (Data Foundations ADR-005).

| Component | Name | Purpose |
|---|---|---|
| Task | `task_billing_ingest_aws` | Load AWS Data Exports (FOCUS or CUR 2.0) |
| Task | `task_billing_ingest_azure` | Load Azure Cost Management exports |
| Task | `task_billing_ingest_gcp` | Load GCP Billing Export (exported from BigQuery) |
| Task | `task_invoice_ingest` | Pull provider invoices (AWS invoices, Azure EA/MCA invoices, GCP invoices) into `bronze.invoice_lines_raw`, daily and when an invoice is issued. Feeds Bill Verification (Section 10) |
| Task | `task_provider_recommendations_ingest` | Daily snapshot of provider-native recommendations and anomalies (Data Foundations §4.1): the AWS Data Exports cost optimization recommendations table (S3) and Cost Explorer `GetAnomalies`; Azure Advisor recommendations (`Category eq 'Cost'`, per subscription), Cost Management Benefit Recommendations, and Consumption reservation recommendations; the GCP Recommender BigQuery export. Loads `bronze.provider_recommendations_raw` and `bronze.provider_anomalies_raw` with `snapshot_date` |
| Task | `task_usage_telemetry_ingest` | Pull usage and utilization telemetry (all providers) |
| Landing zone | `raw/{provider}/{billing_account}/{billing_period}/{delivery_id}/` | Immutable raw landing path. Each export delivery gets its own folder, because providers rewrite the whole billing period many times (restatement) instead of appending rows |

**Raw schema per provider (fields present, not full DDL)**: each source lands with its native field names (for example AWS `lineItem/UnblendedCost`, Azure `costInUSD`, GCP `cost`). Normalization happens in the silver mediation transform (Section 2). The raw layer is kept as received for audit and replay.

---

## 2. Bronze & Silver: Ingestion and Mediation (Snowflake)

Mediation is the bronze-to-silver transform inside Snowflake, not a separate staging system. Bronze and silver are schemas in the same `finops_platform` database as gold (Section 3); this section covers the jobs that fill them.

**Orchestration**: the Snowflake task graphs from Section 1 run this stage's dbt models and Snowpark procedures in order.

| Job | Name | Input | Output | Purpose |
|---|---|---|---|---|
| Bronze ingest | `job_bronze_ingest_cost` | Raw landing zone (`raw/{provider}/...`) | `bronze.cost_line_items_raw` | Loads provider line items as received, one-to-one with the landing zone, stamped with `billing_account`, `billing_period`, `delivery_id`, and `ingested_at`. No transformation; provider field names kept. Every delivery is retained in bronze for audit and replay |
| Normalize | `dbt_model_normalize_billing` | `bronze.cost_line_items_raw` | `silver.stg_{provider}_billing` | Field renaming and currency and unit conformance per provider (a small step where the export is FOCUS; Data Foundations §4.2) |
| Reconcile tags | `dbt_model_reconcile_tags` | Staged per-provider silver tables | `silver.stg_tags_reconciled` | Maps provider tag keys to the canonical tag taxonomy |
| Select latest delivery + business rules | `snowpark_job_select_latest_delivery` (also called `job_silver_transform_cost`) | Reconciled staged data | `silver.cost_line_items_clean` | For each (`provider`, `billing_account`, `billing_period`), keeps only the latest complete delivery, drops earlier deliveries of that period, then applies business rules. This is the silver transform. Provider line item IDs aren't used for deduplication: AWS documents that CUR `identity/LineItemId` isn't consistent across report refreshes, and Azure exports have no equivalent ID |
| Data quality | `job_dq_checks` (a dbt test suite) | `silver.cost_line_items_clean` | DQ result log and quarantine table | Runs validation rules before promotion to gold (Section 3) |

**Silver staging schema (illustrative)**:

| Table | Key columns (illustrative) | Notes |
|---|---|---|
| `silver.stg_aws_billing` | `line_item_id`, `resource_id`, `raw_cost`, `currency`, `usage_start`, `usage_end` | Provider field names, after the normalization pass |
| `silver.stg_azure_billing` | (Azure equivalents) | Same pattern |
| `silver.stg_gcp_billing` | (GCP equivalents) | Same pattern |
| `silver.cost_line_items_clean` | `line_item_key` (surrogate hash, unique within a delivery only), `provider`, `billing_account`, `billing_period`, `delivery_id`, `invoice_id`, `charge_category`, `pricing_category`, `commitment_discount_id`, `service_name`, `sku_id`, `resource_id` (nullable, see `dq_check_null_resource_id`), `account_id`, `vertical_id`, `billed_cost`, `effective_cost`, `list_cost`, `contracted_cost`, `contracted_unit_price`, `list_unit_price`, `consumed_quantity`, `pricing_quantity`, `billing_currency`, `charge_period_start`, `charge_period_end`, `canonical_tags` (variant/JSON) | Canonical cross-provider schema with FOCUS-aligned column names. Holds exactly one delivery per billing period. Feeds gold (Section 3) |
| `silver.dq_results` | `run_id`, `check_name`, `status`, `failed_row_count`, `run_timestamp` | Data quality audit trail |

**Data quality checks (named rules, run by `job_dq_checks`)**:
- `dq_check_null_resource_id`: fails only if `resource_id` is null on a row with `charge_category = 'Usage'` for a service that bills per resource. Rows that legitimately have no resource (tax, support, marketplace, commitment purchases, credits, and account-level charges such as some data transfer) pass and are attributed to applications through account-level allocation rules. Their share of spend is tracked by `metric_unattributed_spend_pct` (Section 4).
- `dq_check_currency_valid`: fails if `billing_currency` isn't in the supported set.
- `dq_check_cost_non_negative`: flags negative costs for review without failing, since credits are legitimate but rare.
- `dq_check_single_delivery_per_period`: fails if `silver.cost_line_items_clean` holds rows from more than one `delivery_id` for the same (`provider`, `billing_account`, `billing_period`).
- `dq_check_delivery_total_matches`: fails if the total `billed_cost` in silver for a billing period differs from that delivery's total in bronze (nothing lost or duplicated).

**Idempotency requirement**: every job here must be safe to re-run for the same billing period without duplicate rows. This is done by replacing the whole billing period, never by upserting rows: in one transaction, delete every silver (and downstream gold) row for that (`provider`, `billing_account`, `billing_period`) and insert the latest complete delivery. Re-running with the same delivery gives the same result. Providers restate closed periods (late credits, refunds, corrections), so the job runs for every period that receives a new delivery, not only the current month.

---

## 3. Governed Snowflake Platform: Gold Layer & Catalog (medallion-layered schemas)

**Database structure**: `finops_platform` (Snowflake database) with `bronze`, `silver`, and `gold` schemas. Every table in the three layers is a Snowflake-managed Iceberg table (`CATALOG = 'SNOWFLAKE'`) on the external volume `ev_finops_iceberg`, backed by a organization-owned Azure storage account with soft delete and blob versioning enabled (Data Foundations §4.3, ADR-003). Section 2's jobs fill bronze and silver; this section covers gold and the governance across all three.

**Jobs (dbt models, orchestrated as in Section 2)**:

| Job | Name | Trigger | Purpose |
|---|---|---|---|
| Gold aggregate | `job_gold_aggregate_cost` (a dbt model) | After `job_dq_checks` (Section 2) | Builds fact and dimension tables from `silver.cost_line_items_clean` into `gold.*` |
| Governance tagging | `job_governance_tag_sync` | After the gold job | Applies Snowflake object tags (below) to new or changed gold objects |

**Gold-layer schema (consumption-ready)**:

| Table | Type | Key columns | Notes |
|---|---|---|---|
| `gold.fact_cost_daily` | Fact | `date`, `billing_period`, `invoice_id`, `account_id`, `resource_id` (nullable), `service_name`, `sku_id`, `charge_category`, `pricing_category`, `commitment_discount_id`, `commitment_discount_status`, `billed_cost`, `effective_cost`, `list_cost`, `contracted_cost`, `consumed_quantity` | Grain: one row per day, account, resource, SKU, charge category, pricing category, and commitment. Charge and pricing categories stay in the grain so commitment coverage and bill verification can be computed from gold. See **Cost basis** below |
| `gold.dim_account` | Dimension | `account_id` (PK), `vertical_id`, `provider`, `account_name` | |
| `gold.dim_resource` | Dimension | `resource_id` (PK), `resource_type`, `region`, `created_date` | |
| `gold.dim_vertical` | Dimension | `vertical_id` (PK), `vertical_name`, `cost_center` | |
| `gold.dim_tag` | Dimension | `tag_key`, `tag_value`, `resource_id` (FK) | Supports metadata filtering |
| `gold.fact_anomaly` | Fact | `anomaly_id`, `resource_id`, `detected_date`, `severity`, `model_version`, `contributing_factors` (JSON), `disposition` (`true_anomaly`/`expected_change`/`false_positive`, nullable), `dispositioned_by`, `dispositioned_at` | Written by Core Intelligence (MLOps Pipeline). Disposition columns are synced from `anomaly_dispositions` (Section 7) and are the anomaly detector's labels (MLOps Pipeline §2.4) |
| `gold.fact_provider_recommendation` | Fact | `snapshot_date`, `provider`, `source` (`cost_optimization_hub`/`advisor`/`benefit_recommendations`/`reservation_recommendations`/`recommender`), `provider_recommendation_id`, `recommendation_type` (`rightsize`/`idle`/`savings_plan`/`reservation`/`committed_use`/`other`), `resource_id` (nullable for purchase recommendations), `account_id`, `current_config`, `recommended_config`, `estimated_monthly_savings`, `lookback_days`, `raw` (variant) | One row per recommendation per daily snapshot, since provider APIs return current state only. Baseline for Core Intelligence's eval gates (MLOps Pipeline §2.4, ADR-007) |
| `gold.fact_provider_anomaly` | Fact | `snapshot_date`, `provider`, `provider_anomaly_id`, `account_id`, `service_name`, `anomaly_start_date`, `anomaly_end_date`, `expected_spend`, `actual_spend`, `total_impact`, `root_causes` (variant), `provider_feedback` (AWS `YES`/`NO`/`PLANNED_ACTIVITY`, nullable) | AWS only today (Data Foundations §4.1). AWS feedback the team has set is imported as extra anomaly labels (MLOps Pipeline §2.4) |
| `gold.dim_commitment` | Dimension | `commitment_discount_id` (PK), `provider`, `billing_account`, `commitment_type` (reservation/savings plan/committed use), `scope` (family, region, or spend-based), `term_months`, `payment_option`, `hourly_commitment`, `start_date`, `end_date` | Inventory of owned commitments with expiry dates, from each provider's reservations, savings plans, and commitments APIs. Input to RI/SP planning (MLOps Pipeline ADR-006) |
| `gold.fact_recommendation` | Fact | `recommendation_id`, `resource_id`, `type`, `estimated_savings_usd`, `status`, `model_version` | Written by Core Intelligence |
| `gold.fact_invoice_line` | Fact | `invoice_line_id` (PK), `invoice_id`, `provider`, `billing_account`, `billing_period`, `invoice_date`, `charge_type` (`usage`/`tax`/`support`/`marketplace`/`commitment_purchase`/`credit`), `service_name`, `invoiced_amount`, `billing_currency` | Provider invoice lines, the unit Bill Verification verifies. Joined to `fact_cost_daily` on `invoice_id` and charge type (Data Foundations §4.1) |
| `gold.dim_rate_card` | Dimension | `rate_card_id` (PK), `provider`, `billing_account`, `term_type` (`enterprise_discount`/`private_pricing`/`commitment_program`/`credit`), `service_scope` (service, SKU, or all), `discount_pct` (nullable), `contracted_unit_price` (nullable, only where the FOCUS export doesn't carry it), `commitment_amount` (nullable), `effective_start_date`, `effective_end_date` | the organization's contract terms, ingested, not derived (Data Foundations §4.1) |
| `gold.fact_bill_verification` | Fact | `verification_id`, `invoice_line_id` (FK), `confidence_score`, `evidence` (JSON), `status`, `model_version` | Written by Bill Verification |

**Cost basis.** The four cost columns follow FOCUS definitions and are never collapsed into a single `cost` column, because each answers a different question:

| Column | Meaning | Used for |
|---|---|---|
| `billed_cost` | What the provider invoices for the row. Commitment purchases appear in full when paid; usage covered by a commitment shows zero | Bill verification (Section 10), reconciling to invoices |
| `effective_cost` | Amortized cost: upfront commitment fees spread over the usage they cover, with unused commitment as its own row | Every spend, trend, anomaly, and chargeback metric (Section 4) |
| `list_cost` | Cost at public list price | Savings achieved (`list_cost - effective_cost`) |
| `contracted_cost` | Cost at the organization's negotiated price, before commitment discounts | Checking that negotiated pricing was applied (Section 10) |

**Assumption**: today's chargeback uses amortized cost. If it uses billed cost, only `metric_chargeback_amount` changes; the other metrics stay on `effective_cost`.

**Governance and access (Snowflake Horizon)**:
- Row access policy `rap_vertical_scope` on `gold.fact_cost_daily` and `gold.fact_anomaly`, filtering by `vertical_id` against the requesting user's or service principal's assigned verticals.
- Access roles: `role_vertical_{name}_reader` (own vertical only), `role_platform_admin` (all verticals), `role_ml_pipeline_svc` (write access to `fact_anomaly` and `fact_recommendation` only).
- Object tagging: `billed_cost`, `effective_cost`, `list_cost`, `contracted_cost`, and `estimated_savings_usd` tagged `sensitivity:financial` through tag-based classification, with a masking policy for any role without an explicit financial-data grant.

**BI access is a role grant, not a separate system.** Power BI connects as `role_vertical_{name}_reader` or `role_platform_admin` to the Semantic Views (Section 4) for anything with a governed metric, and the same roles allow fallback queries against `gold` views for ad hoc SQL not yet modeled as a metric (Data Foundations ADR-002, ADR-003). There is no share object, second database, or separate copy. The row access policy and tags apply to every consumer, Semantic Views included, because they are built on the same gold tables.

---

## 4. Semantic Layer, Ontology, and Knowledge Graph

**Semantic layer** (metric definitions as Snowflake Semantic Views, optionally authored in dbt's semantic layer configuration and published to Snowflake):

| Metric name | Definition (source) | Notes |
|---|---|---|
| `metric_ec2_spend` | `SUM(effective_cost) WHERE resource_type = 'ec2' FROM gold.fact_cost_daily` | Canonical definition |
| `metric_total_spend` | `SUM(effective_cost)` from `gold.fact_cost_daily`, by vertical/account/period | Amortized, per the cost basis in Section 3 |
| `metric_spend_variance_mom` | Period-over-period change in `metric_total_spend`, split into new/terminated resources, usage change, and price change | |
| `metric_spend_by_resource_type` | `SUM(effective_cost) GROUP BY resource_type` | |
| `metric_spend_by_environment` | `SUM(effective_cost) GROUP BY environment` tag | |
| `metric_unattributed_spend_pct` | `SUM(effective_cost)` where the APM ID is unresolved (including rows with no `resource_id`), as % of total spend | Weighted by dollars, unlike `dq_check_apm_id_present`, which counts resources (below) |
| `metric_monthly_burn_rate` | `SUM(effective_cost) GROUP BY MONTH(date), account_id` | |
| `metric_forecast_vs_budget_variance` | Projected month-end spend (run-rate extrapolation of `metric_monthly_burn_rate`) vs. budget reference data | Budget data source not yet defined; placeholder |
| `metric_utilization_rate` | Consumed vs. allocated compute, memory, and storage, per resource | Reused as a rightsizing input by MLOps Pipeline, not recomputed (MLOps Pipeline ADR-001) |
| `metric_idle_resource_spend` | `SUM(effective_cost)` where `metric_utilization_rate` is below a configurable near-zero threshold | |
| `metric_open_recommendation_savings` | `SUM(estimated_savings_usd)` from `gold.fact_recommendation` where `status = 'open'` | |
| `metric_recommendation_realization_rate` | % of recommendations marked implemented within N days of being raised | |
| `metric_ri_coverage` | `SUM(effective_cost) WHERE pricing_category = 'Committed'` / `SUM(effective_cost)` over commitment-eligible usage rows (`charge_category = 'Usage'`) | Computed from FOCUS commitment columns in gold, with no separate commitment reference join |
| `metric_ri_sp_utilization` | `effective_cost` of rows with `commitment_discount_status = 'Used'` / all rows with a `commitment_discount_id` (used plus unused) | Reused as an RI/SP planning input by MLOps Pipeline, not recomputed (MLOps Pipeline ADR-001) |
| `metric_anomaly_rate` | `COUNT(fact_anomaly) / COUNT(DISTINCT resource_id)` per period | |
| `metric_anomaly_dollar_impact` | `SUM(effective_cost)` attributable to line items flagged by `fact_anomaly` | |
| `metric_chargeback_amount` | `metric_total_spend` rolled up to vertical, one month in arrears | Matches the current chargeback cadence. Amortized basis assumed (Section 3) |
| `metric_commitment_savings` | `SUM(list_cost - effective_cost)` by vertical/period | Savings from negotiated pricing and commitments |
| `metric_peer_percentile_rank` | Percentile rank of a rate metric (such as `metric_utilization_rate`) against an anonymized peer set | Rates only, per `FinOps Opportunities.md` §2b |

**Ontology (entity and relationship definitions)**: a versioned file, `ontology/finops-ontology.ttl` (RDFS/OWL in Turtle syntax), in the platform repository and reviewed like code. The table below summarizes it. The graph schema, Semantic View entity names, and Cloud Workbench's entity grounding all follow this file (Data Foundations §4.4).

| Entity | Key attributes | Relationships |
|---|---|---|
| `Account` | account_id, provider, name | `BELONGS_TO → Vertical` |
| `Vertical` | vertical_id, name, cost_center | `HAS_MANY → Account` |
| `Resource` | resource_id, type, region | `BELONGS_TO → Account`, `TAGGED_WITH → Tag` |
| `Tag` | key, value | `APPLIED_TO → Resource` |
| `CostLineItem` | line_item_key, date, charge_category, billed_cost, effective_cost | `REFERENCES → Resource` (optional; not every charge has a resource), `BILLED_ON → InvoiceLine` |
| `Anomaly` | anomaly_id, severity | `DETECTED_ON → Resource` |
| `Recommendation` | recommendation_id, type | `TARGETS → Resource` |
| `InvoiceLine` | invoice_line_id, invoice_id, charge_type, invoiced_amount | `ISSUED_TO → Account` |
| `RateCard` | rate_card_id, provider, term_type, discount_pct | `APPLIES_TO → CostLineItem` |
| `BillVerification` | verification_id, confidence_score, status | `RECONCILES → InvoiceLine` |

**Graph implementation, in two stages** (Data Foundations ADR-004). Both stages implement the ontology file above instead of defining the ontology themselves.

1. **Stage 1: ontology views (Snowflake).** An `ontology` schema in `finops_platform` with one view per entity (`ontology.resource`, `ontology.account`, `ontology.vertical`, `ontology.tag`, `ontology.cost_line_item`, `ontology.invoice_line`, `ontology.anomaly`, `ontology.recommendation`, `ontology.rate_card`, `ontology.bill_verification`) and one per relationship (`ontology.belongs_to`, `ontology.tagged_with`, `ontology.references`, `ontology.billed_on`, `ontology.detected_on`, `ontology.targets`, `ontology.applies_to`, `ontology.reconciles`). Built as dbt models over gold and inheriting gold's row access policies. `query_graph` (Section 5) runs SQL, including recursive CTEs, against these views.
2. **Stage 2: managed graph database, when a trigger is met.** the organization's own graph platform if one exists, otherwise Neo4j AuraDB; never self-hosted. Node labels and relationship types match the ontology views exactly (`Resource`, `Account`, `Vertical`, `Tag`, `CostLineItem`, `InvoiceLine`, `Anomaly`, `Recommendation`, `RateCard`, `BillVerification`). `query_graph` switches to Cypher against it.

**Graph population pipeline** (Stage 2 only):

| Job | Name | Trigger | Purpose |
|---|---|---|---|
| Graph sync | `job_populate_graph_from_gold` (Snowpark procedure with external access to the graph database) | After the gold aggregate job (Section 3), enabled only once a Stage 2 trigger is met | Upserts nodes and relationships from the `ontology` views into the graph database. Gold stays the system of record; the graph is a re-syncable copy. Static node attributes come from `gold.*` tables; any computed node property comes from the matching Semantic View metric, never a separate calculation in this job (Data Foundations ADR-004) |
| Entity resolution | `job_entity_resolution` (Snowpark) | Inside `job_gold_aggregate_cost`, before graph sync | Runs `resolve_resource_identity()` to merge duplicate resource records into one row in `gold.dim_resource`, so each resource appears once in the `ontology` views (and, in Stage 2, as one graph node) |

**Function signature (specification, not implementation)**:
```
resolve_resource_identity(candidate_records: List[ResourceRecord]) -> ResolvedEntity
  Purpose: Decide whether several resource records (possibly from different
  providers or tagging schemes) refer to the same entity, and merge them if so.
  Input: resource records with provider identifiers and attributes.
  Output: one resolved entity reference plus a confidence score.
  Priority: match on APM ID first if present (authoritative, organization-level
  key); use fuzzy cross-cloud tag matching only for records still unresolved.
  Must log: which records were merged, which method resolved them (APM ID or
  fuzzy tag match), and the confidence score, for audit.
```

**APM (Application Portfolio Management) ingestion**:

| Component | Name | Purpose |
|---|---|---|
| Ingestion job | `job_apm_metadata_sync` | Pulls application metadata from the APM tool daily |
| Table | `bronze.apm_application_metadata` | `apm_id` (PK), `app_name`, `classification`, `owner_current`, `technical_contact_current`, `secondary_approver_current` |
| SCD Type 2 table | `silver.apm_owner_history` | `apm_id`, `owner`, `technical_contact`, `secondary_approver`, `effective_start_date`, `effective_end_date` (null = current) |

**Terraform state ingestion** (Data Foundations §4.1):

| Component | Name | Purpose |
|---|---|---|
| Ingestion job | `job_terraform_state_sync` | Pulls resolved resource configuration from the organization's Terraform state backend (Terraform Cloud/Enterprise API, or a state file backend), on module-apply events where available, otherwise daily |
| Table | `gold.dim_resource_iac_state` | `resource_id` (PK/FK to `gold.dim_resource`), `managed_by_iac` (bool), `declared_config` (JSON), `last_apply_timestamp`, `config_drift` (bool, compared with the resource's current observed configuration) |

**Additional data quality checks (named rules)**:
- `dq_check_apm_id_present`: tracks the share of resources with a resolved APM ID (target: at or above the ~nearly all baseline), trended over time as a governance KPI as well as a pass/fail gate.
- `dq_check_owner_staleness`: flags `silver.apm_owner_history` records (owner, technical contact, or secondary approver) whose `effective_start_date` is older than a configurable threshold (for example 6–12 months) without reconfirmation. Unlike `dq_check_apm_id_present`, it checks the changing attributes, not the resource-to-application mapping. The Governed Automation Contract approval flow checks it before sending an approval request to either signer.

---

## 5. AI Consumption Layer (Cloud Workbench, Phase 5)

**Session memory** (Cloud Workbench ADR-009), in the platform's managed Postgres instance (Section 8). No retrieval cache at launch (Cloud Workbench ADR-003).

| Component | Name | Purpose |
|---|---|---|
| Session memory table (Postgres) | `workbench_session_turns` | `session_id`, `turn_number`, `user_id`, `resolved_query` (JSON), `response_summary`, `created_at`. The last few turns of an active conversation; rows are deleted when the session expires. Read at the start of `node_query_rewrite` and appended to after `node_format_citations` |

There is no vector store (Cloud Workbench ADR-006). Definitional questions are answered with `get_metric_definition` below, a direct Snowflake lookup.

**MCP tools** (served by `cost-intelligence-api`, Section 7):

| Tool name | Signature (spec) | Purpose |
|---|---|---|
| `get_cost_by_account` | `(account_id: str, period: DateRange) -> CostSummary` | Structured query over `gold.fact_cost_daily`, limited to the requester's own verticals by access policy regardless of persona. The core "why is this so expensive" lookup, available to both personas |
| `get_anomalies` | `(vertical_id: str, period: DateRange, min_severity: str) -> List[Anomaly]` | Query over `gold.fact_anomaly`, limited to the requester's own verticals regardless of persona |
| `get_peer_benchmark` | `(metric_name: str, vertical_id: str) -> BenchmarkResult` | Returns `metric_peer_percentile_rank` (Data Foundations §4.4) for a rate metric only. **Platform persona only in chat**; not in the Vertical chat tool set (Cloud Workbench ADR-007) |
| `query_graph` | `(query: GraphQuery) -> GraphResult` | Runs a scoped relational traversal over the ontology (Section 4). Stage 1 backend: SQL, including recursive CTEs, over the `ontology` views. Stage 2 backend: Cypher against the graph database. `GraphQuery` is expressed in ontology terms (entity types, relationship names, filters, maximum depth), not SQL or Cypher, so the contract and every caller stay the same when the backend changes |
| `get_metric_definition` | `(name_or_synonym: str) -> MetricDefinition` | Direct SQL/`SEARCH` lookup against Semantic View metadata (Section 4) by name or synonym, with no embeddings or vector index. Called by `node_query_rewrite` for grounding (Cloud Workbench ADR-008) and directly for definitional questions |

**Persona tool sets in chat** (enforced by `node_resolve_persona`, below; Cloud Workbench ADR-007):

| Persona | Tools available |
|---|---|
| Platform (FinOps/platform team) | All tools in this section, still limited by vertical and account access where applicable |
| Vertical (a business vertical) | `get_cost_by_account`, `get_anomalies`, `query_graph`, `get_metric_definition`. **Not** `get_peer_benchmark` (cross-vertical comparison goes beyond explaining one's own bill) and **not** `propose_action` (Section 6) |

**pydantic-graph nodes** (workflow steps):

| Node | Name | Function |
|---|---|---|
| Resolve persona | `node_resolve_persona` | First node. Resolves Platform or Vertical from identity and binds the persona's tool set (above) and system prompt for the rest of the request (Cloud Workbench ADR-007) |
| Query rewrite | `node_query_rewrite` | Loads session memory (Postgres `workbench_session_turns`) to resolve references, then grounds the query: metric references through `get_metric_definition`, entity references through `resolve_resource_identity()`, and relative time expressions into a concrete `DateRange` (Cloud Workbench ADR-008, ADR-009) |
| Route retrieval | `node_route_retrieval` | For a purely definitional question, the definition is already resolved in `node_query_rewrite`, so this goes straight to `node_generate`. Otherwise it picks structured and/or graph retrieval based on the question, from the tools `node_resolve_persona` bound |
| Retrieve structured | `node_retrieve_structured` | Calls `get_cost_by_account` / `get_anomalies` |
| Retrieve graph | `node_retrieve_graph` | Calls `query_graph` for relational questions |
| Generate | `node_generate` | LLM call with the context from the retrieve nodes (or the definition resolved in `node_query_rewrite`) |
| Grounding check | `node_grounding_check` | Runs `check_faithfulness()` before the response is released |
| Format citations | `node_format_citations` | Adds readable source references and appends this turn to session memory (Postgres `workbench_session_turns`, Cloud Workbench ADR-009) |
| Route to action | `node_route_action` (conditional edge) | If the query implies an action, calls `propose_action` (Section 6), the only action tool this agent has. It never calls `idp_provision_request` or `cmp_container_action` |

**Function signatures (specification)**:
```
rewrite_query(raw_query: str, conversation_context: ConversationContext, persona: Persona) -> ResolvedQuery  [node_query_rewrite]
  Purpose: Resolve conversational references, then ground the query against
  sources the platform already governs, so retrieval and generation don't
  interpret terms on their own (Cloud Workbench ADR-008).
  Output: ResolvedQuery {
    disambiguated_text: str,
    canonical_metrics: List[str]       # Semantic View metric names (Section 4)
    resolved_entities: List[EntityRef] # vertical_id / APM ID via resolve_resource_identity() (Section 4)
    resolved_time_range: DateRange,
  }
  If an entity or metric reference can't be resolved: pass the term on to
  node_route_retrieval flagged as ungrounded, instead of failing the request.

get_metric_definition(name_or_synonym: str) -> MetricDefinition
  Purpose: Direct lookup against Snowflake Semantic View metadata by name or
  synonym (Cloud Workbench ADR-001, ADR-006). No embeddings, no vector index.
  Output: MetricDefinition { canonical_name, description, computed_from }, or
  not-found if no name or synonym clears the fuzzy-match threshold.

check_faithfulness(answer: str, retrieved_context: List[Chunk]) -> FaithfulnessResult
  Purpose: Verify that each claim in the answer is supported by retrieved context.
  Output: pass/fail, plus the list of unsupported claims if any.
  On fail: the response is blocked; node_generate retries once with a stricter
  prompt, and if that fails the system abstains ("not enough information").

check_retrieval_sufficiency(resolved_query: ResolvedQuery, retrieved_context: RetrievedContext) -> SufficiencyResult
  Purpose: Decide whether there is enough grounded context to attempt generation
  at all. Deterministic, not a similarity score, since this design has no
  scored (embedding-based) retrieval (Cloud Workbench ADR-001, ADR-006).
  Abstain before generation when any of these hold:
    - a metric or entity the question depends on was flagged ungrounded by
      node_query_rewrite (no Semantic View or ontology match)
    - a structured or graph retrieval the question needs returned no rows
    - the resolved time range falls outside loaded data (e.g., before backfill)
  Output: SufficiencyResult { proceed: bool, reasons: List[str] }. On abstain,
  the reasons are shown to the user ("no data loaded before March 2025")
  instead of a generic refusal.
```

**API endpoints (external, versioned)**:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/workbench/query` | Submit a natural-language query; returns the answer, citations, and `request_id` |
| `GET` | `/v1/workbench/query/{request_id}` | Retrieve a previous query's full result, including its trace reference |

---

## 6. Action Layer / Orchestrator & Guardrail Engine (IDP, CMP Integration)

**Agent-facing tool: the single entry point (Governed Automation §3.2)**:

| Tool name | Signature (spec) | Purpose |
|---|---|---|
| `propose_action` | `(action_type: str, target: ResourceRef, params: dict, origin: Literal["core_intelligence","self_serve_api","cloud_workbench","what_if_workbench"]) -> ProposalResult` | The only action tool, for every proposal source: Core Intelligence, the Self-Serve API's accept-recommendation endpoint (Section 7), Cloud Workbench chat (Platform persona only), and the what-if workbench (Section 12; the only path for Vertical users). `origin` is recorded for audit; classification never uses it. Starts a Temporal workflow (below). `ProposalResult` is queued, executed, or denied, never a direct execution result |

**Internal execution tools: never exposed to an agent, called only by the Temporal workflow's `execute_action` Activity**:

| Tool name | Signature (spec) | Purpose |
|---|---|---|
| `idp_provision_request` | `(resource_spec: ResourceSpec, requestor: Principal) -> RequestResult` | Submits a provisioning request to IDP |
| `cmp_container_action` | `(action: ContainerAction, target: ContainerRef) -> ActionResult` | Submits a container action to CMP |

**Orchestration: Temporal workflow (Governed Automation §3.3)**. One workflow instance per `propose_action` call, built from Activities, Timers, and Signals on **Temporal Cloud** (managed). The workflow workers run as one container on CMP, with OPA as a sidecar in the same pod (Section 8, Governed Automation ADR-002). Every Activity is idempotent, keyed on the workflow ID and Activity name, so a retry after a worker restart or timeout can't execute an action twice:

```
classify_action_risk(action_payload: ActionPayload) -> RiskTier   [Activity]
  Purpose: Determine the LOW / MEDIUM / HIGH risk tier for a proposed action.
  Evaluates the OPA policies (below) against: action type (read/flag vs.
  resize/terminate), whether the target resource is tagged production, and
  estimated blast radius (one resource vs. several).
  Output: RiskTier enum. HIGH always requires human approval, whatever else
  is true (a fixed rule, not a scored threshold).

check_iac_managed(action_payload: ActionPayload) -> IacStatus     [Activity]
  Purpose: Determine whether the target resource is Terraform-managed
  (Data Foundations §4.1's Terraform state table). Runs before
  execute_action, not inside it.
  Output: IacStatus { managed_by_iac: bool, drifted: bool }.

execute_action(action_payload: ActionPayload, iac_status: IacStatus) -> ActionResult  [Activity]
  Purpose: If the contract's execution_mode is dry_run, write the would-be
  action to gold.fact_action_audit (outcome = 'dry_run') and return without
  calling anything. Otherwise, if iac_status.managed_by_iac, call
  open_terraform_pr or trigger_terraform_run instead of IDP/CMP. Otherwise
  call idp_provision_request or cmp_container_action depending on action type.
  Retried under Temporal's retry policy on transient failure; when retries
  are exhausted, hands off to alert_teams.

open_terraform_pr(action_payload) -> PrResult                     [Activity]
trigger_terraform_run(action_payload) -> RunResult                [Activity]
  Purpose: Execute an approved action on a Terraform-managed resource through
  the IaC pipeline instead of IDP/CMP (Governed Automation ADR-004): a PR
  against the owning module, or a Terraform Cloud/Enterprise run, depending
  on the module's VCS and CI integration.

check_automation_enabled(scope: AutomationScope) -> bool          [Activity]
  Purpose: Kill switch check (Governed Automation §3.6) across global,
  vertical, and application (APM ID) scope in automation_controls.
  Runs at workflow start and again just before execute_action.
  Output: False if any enclosing scope is off; the workflow records
  'halted' and ends as advisory.

evaluate_circuit_breaker(scope: AutomationScope) -> BreakerResult  [Activity]
  Purpose: After each execution outcome, count failed or rolled-back
  actions in the trailing window (defaults: 2 in 24h per application;
  platform-wide rollback rate above 5% over 7 days). If tripped, write an
  automation_controls row with automation_enabled = false and
  set_by = 'circuit_breaker', then call alert_teams.

alert_teams(action_payload, failure_reason) -> None               [Activity]
ROLLBACK: rollback_from_snapshot(action_payload) -> RollbackResult [Activity]
```

| Component | Name | Purpose |
|---|---|---|
| Approval queue table (Postgres) | `action_approval_requests` | `request_id` (PK), `workflow_id` (the Temporal workflow and run ID; an approve or reject decision Signals this specific workflow, so it must be stored), `origin` (`core_intelligence` \| `self_serve_api` \| `cloud_workbench` \| `what_if_workbench`), `apm_id` (limits which team's approvers can see and act on the request), `action_payload`, `risk_tier`, `contract_id` (FK to `contracts`, Governed Automation §3.4), `status`, `approver_id`, `requested_at`, `decided_at`. Operational state in Postgres, not Snowflake (Governed Automation ADR-003) |
| Approval service | `approval_queue_service` | Review, approve, and reject API for MEDIUM and HIGH tier actions; an approve or reject call sends a Temporal Signal to the matching workflow. Also exposes the kill switch (`POST /v1/automation/controls`, limited by role: the FinOps team for any scope, an application's Owner or Secondary Approver for that application) and exclusions (`POST /v1/automation/exclusions`) |
| Contract table (Postgres) | `contracts` | Defined by the Governed Automation Contract document: `contract_id` (PK), `apm_id`, `tier_scope` (LOW-only or full MEDIUM/HIGH), `pre_approved_actions`, `notification_requirements`, `change_window`, `rollback_guarantee`, `escalation_path`, `review_cadence`, `owner_signed_by`, `owner_signed_at`, `secondary_approver_signed_by`, `secondary_approver_signed_at`, `execution_mode` (`dry_run`/`live`, default `dry_run`; moves to `live` only after dry-run review, Governed Automation §3.6), `status` (`draft`/`active`/`amended`/`revoked`/`expired`, Contract doc §3.1). The two signature pairs come from each approver's Teams identity on the approval card (Contract doc §3.2), not a cryptographic signature, and both are required before `active`. Postgres for the same reason as the approval queue: `check_contract_exists` (Governed Automation §3.3, step 1) does a transactional lookup on every proposal |
| Finding escalation table (Postgres) | `finding_escalations` | Contract doc §3.6 (FR7, ADR-5): `escalation_id` (PK), `finding_id` (FK to `gold.fact_recommendation` or `gold.fact_anomaly`), `finding_source` (`core_intelligence`/`cloud_workbench_expansion_push`/`what_if_proposal`), `apm_id`, `threshold_type` (`dollar`/`risk_severity`), `threshold_value`, `surfaced_at`, `sla_deadline`, `status` (`pending_disposition`/`escalation_review`/`escalation_approved`/`escalation_declined`/`cr_generated`/`dispositioned`), `reviewed_by`, `reviewed_at`, `cr_reference` (the CAB/ITSM system's CR number, set only after `escalation_approved`). Postgres for the same transactional reason as `contracts` and `action_approval_requests` |
| Automation controls (Postgres) | `automation_controls` | `control_id` (PK), `scope_type` (`global`/`vertical`/`application`), `scope_id` (null for global, else `vertical_id` or `apm_id`), `automation_enabled` (bool), `set_by` (user ID or `circuit_breaker`), `reason`, `set_at`. The kill switch (Governed Automation §3.6). The latest row per scope wins; history is kept |
| Automation exclusions (Postgres) | `automation_exclusions` | `exclusion_id` (PK), `apm_id`, `resource_id` (nullable), `tag_match` (nullable), `reason`, `requested_by`, `expires_at`, `created_at`. Resources excluded from automation without leaving the program (Governed Automation §3.6) |
| Audit table (Snowflake gold) | `gold.fact_action_audit` | `request_id`, `action_payload`, `risk_tier`, `origin`, `contract_id`, `outcome` (`executed`/`dry_run`/`halted`/`capped`/`excluded`/`denied`/`failed`), `executed_at`, `rolled_back` (bool). Synced from Postgres and Temporal history when a workflow completes, for reporting (Governed Automation ADR-003). `contract_id` links each action to the agreement that authorized it (Governed Automation FR4) |

**Policy-as-code (Open Policy Agent, enforced independently of any agent's reasoning)**:

| Policy | Name | Rule (described) |
|---|---|---|
| Blast radius | `policy_blast_radius` | Deny any single action affecting more than N resources without explicit multi-resource approval |
| Production gate | `policy_production_gate` | Deny any resize or terminate action on a `production`-tagged resource without HIGH-tier approval |
| Run caps | `policy_run_caps` | Deny execution once a scope reaches its rolling 24-hour limit on executed actions or total estimated monthly spend change (defaults: 10 actions per application, 50 platform-wide); the action falls back to advisory (Governed Automation §3.6) |
| Exclusions | `policy_exclusions` | Classify any target listed in an active `automation_exclusions` row as advisory, whatever its tier |
| Reversibility bias | `policy_reversibility_preference` | Require a snapshot or backup step before any destructive action where one is available |

---

## 7. API/Service Layer (Phase 2)

**Service**: `cost-intelligence-api`, one containerized service on CMP that gains capabilities by phase instead of three separate deployables:

1. **Phase 2**: the REST endpoints below.
2. **Phase 3**: the `approval_queue_service` endpoints (Section 6).
3. **Phase 5**: the MCP tools (Section 5) and the Cloud Workbench query endpoints (`/v1/workbench/query`, Section 5), with the pydantic-graph orchestrator running in the same process.

With one service, the REST API and the agent's MCP tools use the same query functions, access checks, and audit logging, so programmatic and conversational consumers can't drift apart. REST versions (`/v1/...`) and the MCP tool set are versioned independently within it.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/cost/{account_id}` | Programmatic cost lookup; same data as `get_cost_by_account` |
| `GET` | `/v1/anomalies` | List anomalies, filterable by vertical and severity |
| `POST` | `/v1/anomalies/{id}/disposition` | Record the FinOps team's disposition (`true_anomaly`/`expected_change`/`false_positive`) in `anomaly_dispositions` (Postgres), synced to `gold.fact_anomaly`. `role_platform_admin` only |
| `GET` | `/v1/recommendations` | List open rightsizing recommendations |
| `POST` | `/v1/recommendations/{id}/action` | Accept or reject a recommendation; accepting goes through `propose_action` (Section 6) |

| Table | Type | Key columns | Notes |
|---|---|---|---|
| `anomaly_dispositions` (Postgres) | Operational | `anomaly_id` (PK/FK), `disposition` (`true_anomaly`/`expected_change`/`false_positive`), `dispositioned_by`, `dispositioned_at`, `note` | Written by the disposition endpoint; synced to `gold.fact_anomaly` (Section 3) as labels for the anomaly detector (MLOps Pipeline §2.4) |

The OpenAPI spec lives at `openapi.yaml` and is published automatically to an internal developer portal so other teams can discover the API (Self-Serve Foundations FR1).

---

## 8. Infrastructure Layer

**Hosting**: every long-running service runs on **CMP**, the organization's existing container management platform, not on a platform-owned Kubernetes cluster. CMP's platform team runs the cluster (upgrades, node pools, hardening); this platform owns only its deployables and namespaces. **Assumption to validate**: CMP accepts workloads from Cloud Platform Services' own team. Fallback: Azure Container Apps, also managed, not a self-run AKS cluster.

**Terraform modules**:

| Module | Path | Provisions |
|---|---|---|
| `modules/storage-account` | Reusable | Landing zone storage for file-based billing exports, and the storage account behind the `ev_finops_iceberg` external volume (soft delete and versioning enabled) |
| `modules/snowflake-platform` | Reusable | The Snowflake objects for bronze, silver, and gold (Sections 2–3): databases, schemas, virtual warehouses (sized separately for ingestion and transformation, ML training, batch scoring per model family, and BI serving, each with a resource monitor so the platform's own compute cost is tracked per workload), roles, row access and masking policies, task graphs, and external access integrations |
| `modules/graph-store` | Reusable | A managed Neo4j (AuraDB) instance for Stage 2 of the knowledge graph (Section 4, Data Foundations ADR-004). Applied only once a Stage 2 trigger is met, and not needed if the organization's graph platform is used |
| `modules/postgres` | Reusable | Azure Database for PostgreSQL (Flexible Server), the platform's one operational database: approval queue, contracts, finding escalations, automation controls and exclusions, anomaly dispositions, bill verification reviews, PO drafts, and Workbench session memory (Sections 5, 6, 7, 10, 11) |
| `modules/temporal-cloud` | Reusable | Temporal Cloud namespace, mTLS certificates, and worker connection settings for the Orchestrator (Section 6, Governed Automation ADR-002) |
| `modules/cmp-tenancy` | Reusable | CMP namespaces, resource quotas, and secrets for the platform's deployables (below) |

**CMP namespaces**: `ns-finops-platform-prod` and `ns-finops-platform-staging`, one pair for all of the platform's services, with resource quotas per deployable. There is no namespace for model scoring, because Core Intelligence and Bill Verification scoring run as batch jobs in Snowflake (MLOps Pipeline §2.5, ADR-008).

**Container images and Helm charts** (three deployables in total):

| Chart | Name | Deploys | First needed |
|---|---|---|---|
| API service | `chart-cost-intelligence-api` | `cost-intelligence-api`: REST API, approval endpoints, MCP tools, and the Cloud Workbench orchestrator (Section 7) | Phase 2 |
| Orchestrator workers | `chart-guardrail-orchestrator` | Temporal workflow workers for Governed Automation (Section 6), with **OPA as a sidecar** in the same pod. The Guardrail Engine remains a separate policy-decision point with its own policy bundle and tests; it doesn't need its own service because the workers are its only caller | Phase 3 |
| Contract approval bot | `chart-contract-approval-bot` | A Teams bot (Governed Automation Contract doc, ADR-3) that sends a dual-approval Adaptive Card to the APM Owner and Secondary Approver (`bronze.apm_application_metadata`) and records each click's Teams identity as `owner_signed_by` / `secondary_approver_signed_by` on `contracts` (Section 6). Built for this one action, not a general e-signature platform. If the organization permits Power Automate approvals with Adaptive Cards, those can replace this deployable | Phase 3 |

**Workload configuration on CMP**. CMP's platform team owns the cluster: node pools, upgrades, admission control, and cluster-wide hardening. This platform owns everything inside its namespaces, set in each Helm chart's values and checked in CI. **Assumption to validate**: CMP is Kubernetes (AKS assumed) with the Horizontal Pod Autoscaler, KEDA 2.17 or later, NetworkPolicy enforcement, Pod Security admission, and Microsoft Entra Workload ID available to tenants. Sources for the tooling below: [References.md](References.md) R17, R19–R21.

| Deployable | Replicas and autoscaling | Probes and shutdown |
|---|---|---|
| `cost-intelligence-api` | Minimum 2. Horizontal Pod Autoscaler on CPU utilization, with a maximum set from load testing (Implementation Prerequisite 1 in the Solution Overview) | Startup, readiness, and liveness probes on HTTP health endpoints. On shutdown, readiness fails first and in-flight requests drain within the termination grace period |
| `guardrail-orchestrator` | Minimum 2. KEDA Temporal scaler on the Governed Automation task queue backlog (`targetQueueSize`). Replica count controls throughput only; how much automation runs is limited by `policy_run_caps` and the circuit breaker (Section 6), not by pod count | The OPA sidecar is ready only once its policy bundle has loaded (`/health?bundles`), so no worker starts polling without policies. The worker stops polling on SIGTERM and finishes or heartbeats running Activities within a grace period longer than the longest Activity heartbeat timeout; anything cut off is retried by Temporal, which is safe because every Activity is idempotent (Section 6) |
| `contract-approval-bot` | Fixed at 2. Approval volume is too low to justify autoscaling | Readiness and liveness probes; card callbacks are idempotent on the contract ID, so a retried click is harmless |

1. **Resource governance.** Every container sets CPU and memory requests and a memory limit; CPU limits are set only if CMP policy requires them, to avoid throttling. Each namespace has a ResourceQuota and LimitRange (`modules/cmp-tenancy`). Every deployable has a PodDisruptionBudget of `minAvailable: 1`, and topology spread constraints place replicas across availability zones.
2. **Scheduling.** No GPU or dedicated node pool is needed, because model training and scoring run in Snowflake (MLOps Pipeline ADR-008). If a future model needs online or GPU inference, such as a self-hosted LLM, that is the trigger for a dedicated CMP node pool with taints and tolerations, requested from CMP's team.
3. **Pod security.** Every pod meets the Kubernetes `restricted` Pod Security Standard: `runAsNonRoot`, `readOnlyRootFilesystem`, `allowPrivilegeEscalation: false`, all capabilities dropped, and the `RuntimeDefault` seccomp profile. `automountServiceAccountToken` is false, because no deployable calls the Kubernetes API.
4. **Identity and secrets.** Each deployable has its own Kubernetes service account bound to its own Entra Workload ID identity. That identity authenticates to Snowflake (workload identity federation), Postgres (Entra authentication), Azure OpenAI, and Key Vault, so no database or platform password is stored. The few remaining secrets, such as Temporal Cloud mTLS certificates, live in Key Vault, are mounted through the Secrets Store CSI driver, and are rotated there.
5. **Network.** Default-deny NetworkPolicy for ingress and egress in both namespaces. Ingress reaches only `cost-intelligence-api` and `contract-approval-bot`, and only from CMP's ingress controller. Egress is allowlisted per deployable: Snowflake, Postgres, Temporal Cloud, the LLM provider endpoint, IDP and CMP APIs, Microsoft Teams and Bot Framework, and the Datadog agent. Private endpoints are used for Snowflake, Postgres, and Azure OpenAI where the organization's network allows.
6. **Image supply chain.** Minimal, non-root base images pinned by digest. CI generates an SBOM, scans each image, and fails on critical vulnerabilities that have a fix. Images are signed, and signatures are verified at admission if CMP enforces it. Base image and dependency updates arrive as automated pull requests.
7. **Policy checks in CI.** Rendered Helm manifests are checked with Conftest against Rego policies for items 1, 3, and 5. That reuses OPA, which the platform already runs for the Guardrail Engine, instead of adding another policy tool.

**Fallback on Azure Container Apps**: the same three deployables map directly. Autoscaling uses Container Apps' KEDA-based scale rules (HTTP for the API, a custom Temporal scale rule for the workers), managed identity replaces Workload ID, and network isolation moves from NetworkPolicy to the Container Apps environment's virtual network. The pod security settings in item 3 are managed by the platform and aren't configured.

**CI/CD pipeline**: `pipeline-platform-ci`, one pipeline for the platform repository (Solution Overview, Test Strategy), with stages:

1. `static`: lint and type checks, `terraform validate`, Helm lint, and Conftest checks on rendered manifests.
2. `test`: unit and integration tests (dbt, pytest, `opa test`, Temporal workflow and replay tests).
3. `eval-gate`: runs `eval_set_cost_queries.yaml` on any prompt, retrieval, or model change.
4. `image`: build, SBOM, vulnerability scan, and signing for each changed deployable.
5. `deploy-staging`: Terraform apply, dbt run, and Helm upgrade into staging.
6. `canary-prod`: `cost-intelligence-api` at 10%, 50%, then 100% of traffic. The workers and the bot, which serve no user traffic, roll out directly once staging checks pass.

---

## 9. Observability & Governance

**Audit log table**:

| Table | Key columns |
|---|---|
| `audit.workbench_query_log` | `request_id`, `session_id`, `user_id`, `vertical_id`, `query_text`, `retrieved_refs` (JSON), `model_input`, `model_output`, `action_taken` (nullable), `risk_tier` (nullable), `timestamp` |

Governed Automation's action audit trail is separate: Temporal's workflow history records every state transition as it happens, and `gold.fact_action_audit` (Section 6) is the reportable copy synced when a workflow completes. This table logs the query and generation side of Cloud Workbench.

It also serves as Cloud Workbench's long-term memory (Cloud Workbench ADR-009, §4.1): `session_id` and `user_id` scope a lookup when a user refers to an earlier conversation, using this table's retention and access controls instead of a second durable store.

**Tracing**: OpenTelemetry instrumentation exported to Datadog APM (Data Foundations §4.5), covering every node in Section 5's workflow and every Section 6 action call. Span attributes include `request_id`, `vertical_id`, `node_name`, and `duration_ms`.

**Model provider configuration**: `config/model_providers.yaml`, one entry per model-calling node (`node_query_rewrite`, `node_generate`, `node_draft_po`), with `provider`, `model`, `endpoint`, and `max_tokens`. The initial value for every node is Azure OpenAI. Changing an entry requires `job_run_eval_gate` to pass for that node (Cloud Workbench ADR-004). **Provider bake-off**: `job_run_provider_bakeoff` runs the eval set once per candidate provider and model per node, and writes faithfulness, correctness, tool-call validity, p95 latency, and cost per query to `audit.model_bakeoff_results`. It runs before migration step 28 and whenever a new candidate model is worth considering.

**Eval gate artifact**: `eval_set_cost_queries.yaml`, a curated set of representative queries with expected answer characteristics (the supporting facts an answer must contain, not exact strings), run by CI job `job_run_eval_gate` on every prompt, retrieval, or model change.

**Additional policy-as-code**:

| Policy | Name | Rule (described) |
|---|---|---|
| Vertical RBAC | `policy_rbac_vertical_scope` | A query returns data only for the requester's assigned verticals, independent of application logic |
| PII/sensitive data | `policy_pii_redaction` | Redacts any PII-adjacent fields retrieved by mistake before they reach generation |

---

## 10. Bill Verification (Phase 4)

Per Bill Verification ADR-1, this reuses MLOps Pipeline's feature store, model registry, eval gate, and drift monitoring. The jobs below add one model family to that pipeline.

**Jobs (Snowpark ML, run as in MLOps Pipeline §2.4–§2.6)**:

| Job | Name | Trigger | Purpose |
|---|---|---|---|
| Feature engineering | `job_build_bill_verification_features` | After `job_gold_aggregate_cost` (Section 3) | Computes Bill Verification §3.2's features (`invoice_to_billing_delta_pct`, `rate_delta_pct`, `expected_term_missing`, `historical_rate_stability`, `usage_qty_variance`, `rate_card_coverage`, `dollar_impact`) from `gold.fact_invoice_line`, `gold.fact_cost_daily` (`billed_cost`), and `gold.dim_rate_card`, and writes them to the shared Snowflake Feature Store |
| Model training | `job_train_bill_verification_model` | Scheduled retraining, enabled only once `bill_verification_reviews` holds at least 100 `reviewed_flagged` lines (Bill Verification §3.3) | Trains the confidence-scoring model on reviewed invoice lines (decision plus reason code) and registers a candidate in the Snowflake Model Registry |
| Eval gate | `job_eval_bill_verification_model` | After training, before promotion | Compares the candidate with the current scorer (rules, or the promoted model) on held-out reviewed lines, and blocks promotion if it produces more false auto-clears at the same auto-clear rate (MLOps Pipeline §2.4) |
| Scoring | `job_score_bill_verification` | New or updated rows in `gold.fact_invoice_line`, or a restated billing period in `gold.fact_cost_daily` | A Snowpark stored procedure on the `wh_scoring_bill_verification` warehouse, run by a Snowflake Task (MLOps Pipeline ADR-008). Scores each affected invoice line with the current scorer: `rules_v1` (deterministic checks, Bill Verification §3.3) until a model is promoted, then the promoted model. Calls `score_invoice_line()` (below) for each line and writes results to `bill_verification_reviews` (Postgres) |
| Drift monitoring | `job_monitor_bill_verification_drift` | Scheduled, Evidently AI | Same tooling and cadence as MLOps Pipeline's other model families (Bill Verification §3.1). Detected drift triggers `job_train_bill_verification_model` |

**Function signatures (specification, not implementation)**:
```
score_invoice_line(invoice_line: InvoiceLine, billed_rows: List[CostLineItem], contract_terms: List[RateCardEntry]) -> BillVerificationScore
  Purpose: Produce a confidence score and structured evidence for one provider
  invoice line (Bill Verification §2.1, §3.2-§3.3), compared against the
  billed_cost rows with the same invoice_id and charge type, and the contract
  terms that apply to its billing account and period.
  Output: BillVerificationScore {
    confidence_score: float,
    evidence: {invoice_to_billing_delta, terms_applied, terms_missing, usage_comparison},
    dollar_impact: float,          # gold.fact_invoice_line.invoiced_amount, not a model output
  }
  If no RATE_CARD terms apply (coverage gap): still returns a score, with the
  evidence stating the gap, instead of treating it as a missing input.

route_verification_result(score: BillVerificationScore) -> RoutingDecision
  Purpose: FR2's hard rule. Auto-clear requires high confidence AND low dollar
  impact; failing either one sends the line to human review
  (Bill Verification ADR-2).
  Output: RoutingDecision enum: AUTO_CLEAR | HUMAN_REVIEW.
```

**Tables**:

| Table | Type | Key columns | Notes |
|---|---|---|---|
| `bill_verification_reviews` (Postgres) | Operational queue | `review_id` (PK), `invoice_line_id` (FK), `confidence_score`, `dollar_impact`, `evidence` (JSON), `scorer_version` (`rules_v1` or a model version), `routing_reason` (`low_confidence`/`high_impact`/`both`/`auto_cleared`/`label_collection`), `status` (`pending_review`/`reviewed_cleared`/`reviewed_flagged`/`auto_cleared`), `review_reason_code` (`rate_mismatch`/`missing_discount`/`missing_credit`/`usage_spike`/`billing_data_mismatch`/`other`, nullable), `reviewer_id`, `requested_at`, `reviewed_at` | Postgres for the same transactional reason as `action_approval_requests` and `contracts` (Section 6). This is where the FinOps/platform team works the queue |
| `gold.fact_bill_verification` (Snowflake) | Fact | See Section 3 | The final result, one row per invoice line once resolved, synced from `bill_verification_reviews` for reporting and Cloud Workbench. Not the operational queue |

**Review service**: `bill_verification_review_service` exposes list, claim, and decide endpoints over `bill_verification_reviews` for the FinOps/platform team (Bill Verification FR3), restricted to `role_platform_admin` (Section 3). A decision writes the final row to `gold.fact_bill_verification` with `status = 'reviewed_cleared'` or `'reviewed_flagged'`, the reviewer's identity, and a timestamp. It follows the same pattern as Section 6's `approval_queue_service`, applied to a financial decision.

**Observability**: alerts go through the platform's shared Datadog, Teams, and ITSM baseline (Data Foundations §4.5), like every other model family (Bill Verification §3.1).

---

## 11. PO Auto-Draft (Phase 5 extension)

Per PO Auto-Draft ADR-1, this reuses Cloud Workbench's agentic stack (Section 5): pydantic-graph, MCP, and the shared model provider configuration (Section 9). It doesn't use Governed Automation's Orchestrator, because drafting a document isn't a risk-tiered infrastructure action.

**pydantic-graph nodes** (workflow steps):

| Node | Name | Function |
|---|---|---|
| Gather cleared records | `node_gather_cleared_records` | First node. Pulls `gold.fact_bill_verification` records for a vendor and period where `status` is `auto_cleared` or `reviewed_cleared` (FR1); never pending or flagged records |
| Draft PO | `node_draft_po` | Calls `draft_po()` (below) to fill a fixed PO schema from the gathered records (FR2, §3.2) |
| Verify draft | `node_verify_draft` | Calls `verify_po_draft()` (below); on failure, the draft never reaches `node_route_approval` (FR3, ADR-2) |
| Route for approval | `node_route_approval` | Sends a Teams Adaptive Card to the FinOps/platform team (the same mechanism as the Contract approval card, Section 6) |
| Handle decision | `node_handle_decision` | On approval, calls `post_po_to_erp()`; on rejection, falls back to manual PO entry and records the reviewer's reason (FR5, FR6, §3.4) |

**Function signatures (specification, not implementation)**:
```
draft_po(cleared_records: List[BillVerificationRecord]) -> PODraft
  Purpose: Fill a fixed PO schema from Bill Verification's cleared lines
  (PO Auto-Draft FR2, §3.2). The model fills a defined structure; it doesn't
  compose free text.
  Output: PODraft {
    vendor, billing_period, line_items: List[LineItem], total,
    cost_center, account_id,
  }

verify_po_draft(draft: PODraft) -> VerificationResult
  Purpose: Deterministic structural check. Every field must resolve to a
  specific gold.fact_bill_verification / gold.dim_rate_card / gold.dim_account
  record (PO Auto-Draft FR3, ADR-2). No second LLM pass.
  Output: VerificationResult { passed: bool, unresolved_fields: List[str] }
  On fail: the draft is never shown to a reviewer (PO Auto-Draft §3.3).

post_po_to_erp(draft: PODraft, approval: ApprovalRecord) -> PostResult
  Purpose: Submit the approved PO to the organization's procurement/ERP system through its
  API (PO Auto-Draft FR5, ADR-4).
  Output: PostResult { erp_reference: str } on success.
  If no API is available: returns a ManualEntryHandoff instead, with the
  verified draft packaged for manual entry (PO Auto-Draft §3.5).
```

**Tables**:

| Table | Type | Key columns | Notes |
|---|---|---|---|
| `po_drafts` (Postgres) | Operational | `draft_id` (PK), `vendor`, `billing_period`, `line_items` (JSON), `total`, `cost_center`, `account_id`, `verification_status` (`passed`/`failed`), `verification_detail` (JSON), `approval_status` (`pending_review`/`approved`/`rejected`), `reviewer_id`, `decided_at`, `rejection_reason`, `post_status` (`posted`/`manual_handoff`/`not_applicable`), `erp_reference` (nullable) | Postgres for the same transactional reason as `bill_verification_reviews` (Section 10) and `action_approval_requests` (Section 6) |
| `gold.fact_po_draft` (Snowflake) | Fact | `draft_id`, `vendor`, `billing_period`, `total`, `approval_status`, `post_status`, `decided_at` | Synced from `po_drafts` once a draft is resolved, for reporting; same pattern as `gold.fact_bill_verification` (Section 10) |

**Approval service**: `po_draft_approval_service` exposes list, approve, and reject endpoints over `po_drafts` for the FinOps/platform team (FR4), restricted to `role_platform_admin` (Section 3). A rejection records the reviewer's reason, which feeds the drafting template's eval set (PO Auto-Draft §3.4), the same feedback pattern Cloud Workbench uses (Section 9).

**Observability**: pending drafts and verification failures go through the platform's shared Datadog, Teams, and ITSM baseline (Data Foundations §4.5), like every other phase.

---

## 12. Cloud Workbench Expansion: Push/Pull Channels (Phase 5 extension)

**Push delivery jobs** (Cloud Workbench Expansion §3.2, ADR-1; staged by signal value):

| Job | Name | Trigger | Purpose |
|---|---|---|---|
| Push to IDP | `job_push_signals_idp` | Scheduled, after the gold aggregate job (Section 3) | Stage 1: pushes cloud-optimization signals (`gold.fact_recommendation` where type is rightsizing or RI/SP) into IDP through `push_signal()` |
| Push to CMP | `job_push_signals_cmp` | Scheduled, after the gold aggregate job | Stage 2: pushes Kubernetes and container findings (`gold.fact_anomaly` / `fact_recommendation` filtered to container resource types) into CMP |
| Push to Internal Assistant | `job_push_signals_internal_assistant` | Scheduled, enabled only once Internal Assistant's API is confirmed | Stage 3: pushes both signal types into Internal Assistant; not active yet (Cloud Workbench Expansion §3.2) |

**Function signatures (specification, not implementation)**:
```
push_signal(signal: SignalRecord, target: Literal["idp", "cmp", "internal_assistant"]) -> PushResult
  Purpose: Deliver one cost, anomaly, recommendation, or action-outcome signal
  to a target tool's API (Cloud Workbench Expansion §3.2).
  Output: PushResult { delivered: bool, target_reference: Optional[str] }
  On failure: alerts through the shared Datadog/Teams/ITSM baseline
  (Data Foundations §4.5).

run_what_if_projection(scenario: WhatIfScenario) -> ProjectionResult
  Purpose: Project a hypothetical change's impact using Core Intelligence's
  rightsizing and RI/SP logic (MLOps Pipeline §2.3) with scenario inputs
  instead of observed usage (Cloud Workbench Expansion FR3, ADR-3). Not a new
  model family.
  Input: WhatIfScenario { resource_ref, proposed_change, vertical_id }
  Output: ProjectionResult { projected_savings_usd, confidence, model_version }
  Not persisted beyond the session: it is an exploratory projection, not a
  recommendation record. Only a scenario submitted through propose_action
  becomes a stored proposal (Section 6's action_approval_requests).
```

**Pull workbench (Streamlit-in-Snowflake, Cloud Workbench Expansion ADR-2)**:

| Component | Name | Purpose |
|---|---|---|
| App | `app_cloud_workbench_whatif` | The pull surface's UI, in Streamlit-in-Snowflake |
| Projection tool | `run_what_if_projection` | MCP tool, above |
| Action-proposal binding | `propose_action` (pull-scoped, `origin = "what_if_workbench"`) | The same MCP tool as Section 6, bound into this app's own tool set (Cloud Workbench Expansion ADR-4). It doesn't change `node_resolve_persona`'s chat rules (Section 5), which still exclude Vertical chat sessions from `propose_action` |

**Tool set addition for the pull workbench** (extends Section 5's table; applies to this surface only):

| Persona | Surface | Tools available |
|---|---|---|
| Vertical | Pull workbench (`app_cloud_workbench_whatif`) | `get_peer_benchmark` (FR5, extended from Platform-only), `run_what_if_projection`, `propose_action` (pull-scoped). None of these is available to a Vertical session in Cloud Workbench chat (Section 5) |

**`finding_escalations` extension**: no new table (Cloud Workbench Expansion ADR-5). `finding_source` (Section 6) gains two values, `cloud_workbench_expansion_push` and `what_if_proposal`, alongside `core_intelligence`.

**Observability**: push failures and pull-workbench errors go through the shared Datadog, Teams, and ITSM baseline (Data Foundations §4.5).

---

## 13. What This Specification Deliberately Omits

By design, there is no SQL DDL, no dbt SQL or Snowpark Python code, no Terraform HCL, and no pydantic-graph Python node or edge code. An engineer writes those against this specification. The table names, column lists, function signatures, and policy names here are meant to be enough to build consistently without inventing the structure.
