# References

| | |
|---|---|
| **Status** | Draft |
| **Author** | Matt Nestman |
| **Last checked** | 2026-09-17 |
| **Audience** | Reviewers who want to check the vendor facts the design depends on |

This document lists the vendor documentation behind the facts that drive decisions in this document set: each claim, its source, and where the design uses it. It is indexed from [FinOps Solution Overview.md](FinOps%20Solution%20Overview.md).

## What this covers, and what it doesn't

The document set draws on three kinds of source:

1. **The job posting** ([Systems Engineer Prin.md](Systems%20Engineer%20Prin.md)): the role, the expected stack, and the organization's internal platforms (IDP, CMP, Internal Assistant).
2. **An informal conversation**: the facts labeled "known" in [FinOps Current State.md](FinOps%20Current%20State.md), such as Snowflake as the organization's data platform standard, the team lead's the end of the year retirement, APM ID coverage of about nearly all, and Datadog being in use. These can't be linked.
3. **Vendor documentation**: the tables below.

Only claims a decision depends on are listed, and each was checked against the linked page on the date above. Anything not listed, including general descriptions of products like Temporal Cloud, Semantic Views, or Cortex Analyst, is working knowledge to confirm during implementation. Vendor behavior and product names change often; recheck an entry before relying on it.

---

## 1. Billing data: format, refresh, and restatement

| ID | Claim | Source | Used in |
|---|---|---|---|
| R1 | AWS Data Exports offers CUR 2.0, FOCUS 1.2 with AWS columns, and a cost optimization recommendations table as standard exports to S3 | [AWS: What is AWS Data Exports?](https://docs.aws.amazon.com/cur/latest/userguide/what-is-data-exports.html) | Data Foundations §4.1, ADR-001; Build Specification §1 |
| R2 | AWS billing and cost exports refresh up to once per day, and an overwriting export replaces the previous delivery within its billing period partition | [AWS: Creating a standard export](https://docs.aws.amazon.com/cur/latest/userguide/dataexports-create-standard.html) | Data Foundations ADR-006; Build Specification §1–2 (billing-period replacement) |
| R3 | Azure EA and MCA cost data typically arrives within 8 to 24 hours; estimated charges update six times a day; a billing period closes up to 72 hours after it ends; charges can change until about the fifth day; costs are estimates until the invoice is generated | [Microsoft: Understand Cost Management data](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/understand-cost-mgt-data) | Data Foundations ADR-006 |
| R4 | Azure Cost Management exports offer a FOCUS cost and usage dataset, daily or monthly, in Parquet, with overwrite, plus a reservation recommendations dataset | [Microsoft: Create and manage Cost Management exports](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-improved-exports) | Data Foundations §4.1, ADR-001 |
| R5 | GCP's billing export to BigQuery has no delivery or latency guarantee, and usage reporting frequency varies by service | [Google Cloud: Understand the Cloud Billing data tables in BigQuery](https://docs.cloud.google.com/billing/docs/how-to/export-data-bigquery-tables) | Data Foundations ADR-006 |
| R6 | GCP's FOCUS export to BigQuery is in preview, with documented conformance gaps | [Google Cloud: Structure of FOCUS data export](https://docs.cloud.google.com/billing/docs/how-to/export-data-bigquery-tables/focus-export) | Data Foundations §4.2, ADR-001 |

## 2. Provider recommendations and anomalies

| ID | Claim | Source | Used in |
|---|---|---|---|
| R7 | AWS Cost Optimization Hub recommendations (rightsizing, idle resource deletion, Savings Plans, Reserved Instances, consolidated from Compute Optimizer) can be exported as a Data Exports table | [AWS: Cost optimization recommendations table](https://docs.aws.amazon.com/cur/latest/userguide/table-dictionary-cor.html) | Data Foundations §4.1; MLOps Pipeline ADR-007; Solution Overview step 0b |
| R8 | AWS `GetAnomalies` returns anomalies detected by Cost Anomaly Detection, available for up to 90 days | [AWS: GetAnomalies API](https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetAnomalies.html) | Data Foundations §4.1 (saved daily because of the 90-day window); MLOps Pipeline §2.4 |
| R9 | Azure Advisor recommendations, including cost recommendations, are listed through a REST API per subscription | [Microsoft: Advisor Recommendations - List](https://learn.microsoft.com/en-us/rest/api/advisor/recommendations/list) | Data Foundations §4.1 |
| R10 | Azure savings plan purchase recommendations are listed through the Cost Management Benefit Recommendations API | [Microsoft: Benefit Recommendations - List](https://learn.microsoft.com/en-us/rest/api/cost-management/benefit-recommendations/list) | Data Foundations §4.1 |
| R11 | Azure reservation purchase recommendations are listed through the Consumption API at subscription, resource group, billing account, and billing profile scopes | [Microsoft: Reservation Recommendations - List](https://learn.microsoft.com/en-us/rest/api/consumption/reservation-recommendations/list) | Data Foundations §4.1 |
| R12 | Azure cost anomaly detection runs daily per subscription, about 36 hours after the day ends, and delivers detected anomalies as alert emails; the Scheduled Actions API creates alert rules, but no API for reading detected anomalies is documented | [Microsoft: Identify anomalies and unexpected changes in cost](https://learn.microsoft.com/en-us/azure/cost-management-billing/understand/analyze-unexpected-charges) | Data Foundations §4.1 (not ingested); Solution Overview step 0b |
| R13 | Google Cloud Recommender recommendations can be exported to BigQuery for an organization, daily by default | [Google Cloud: Export recommendations to BigQuery](https://docs.cloud.google.com/recommender/docs/bq-export/export-recommendations-to-bq) | Data Foundations §4.1; Solution Overview step 0b |

## 3. Snowflake

| ID | Claim | Source | Used in |
|---|---|---|---|
| R14 | Fail-safe isn't supported for Iceberg tables on a customer-managed external volume. Cloning is documented as unsupported for externally managed Iceberg tables, and support for Snowflake-managed tables on a customer volume still needs confirming | [Snowflake: Apache Iceberg tables](https://docs.snowflake.com/en/user-guide/tables-iceberg) | Data Foundations §4.3, ADR-003; Solution Overview Test Strategy (staging data) |
| R15 | Standard and append-only streams are supported on Snowflake-managed Iceberg tables | [Snowflake: Introduction to streams](https://docs.snowflake.com/en/user-guide/streams-intro) | Data Foundations ADR-006; Build Specification §1 |
| R16 | Triggered tasks run when a stream has new data (`WHEN SYSTEM$STREAM_HAS_DATA`), without a schedule | [Snowflake: Introduction to tasks](https://docs.snowflake.com/en/user-guide/tasks-intro) | Data Foundations ADR-006; Build Specification §1 |
| R17 | Workloads can authenticate to Snowflake with workload identity federation from Microsoft Entra ID, with no stored secret; Azure sovereign clouds aren't supported | [Snowflake: Workload identity federation](https://docs.snowflake.com/en/user-guide/workload-identity-federation) | Build Specification §8 |
| R18 | Snowpark Python has a local testing mode (version 1.18.0 or later) that runs without a Snowflake connection and works with pytest | [Snowflake: Testing Snowpark Python locally](https://docs.snowflake.com/en/developer-guide/snowpark/python/testing-locally) | Solution Overview Test Strategy |

## 4. Containers, workflows, and policy

| ID | Claim | Source | Used in |
|---|---|---|---|
| R19 | KEDA (v2.17 or later) has a Temporal scaler that scales on task queue backlog (`targetQueueSize`) and authenticates to Temporal with mTLS or an API key | [KEDA: Temporal scaler](https://keda.sh/docs/latest/scalers/temporal/) | Build Specification §8 |
| R20 | OPA's Health API accepts a `bundles` parameter and reports healthy only once all configured bundles are activated | [OPA: REST API, Health API](https://www.openpolicyagent.org/docs/rest-api#health-api) | Build Specification §8 |
| R21 | Conftest tests structured configuration, including Kubernetes manifests, with Rego policies | [Conftest](https://www.conftest.dev/) | Build Specification §8; Solution Overview Test Strategy |
| R22 | The Temporal Python SDK provides a time-skipping test environment and a `Replayer` that fails on non-deterministic workflow changes | [Temporal: Python testing suite](https://docs.temporal.io/develop/python/testing-suite) | Solution Overview Test Strategy |

## 5. Test tooling

| ID | Claim | Source | Used in |
|---|---|---|---|
| R23 | dbt unit tests (dbt 1.8 or later) check model logic against fixed input rows and expected output before the model is built | [dbt: Unit tests](https://docs.getdbt.com/docs/build/unit-tests) | Solution Overview Test Strategy |
| R24 | `terraform test` (Terraform 1.6 or later) runs `.tftest.hcl` files, in plan-only mode for unit tests or against short-lived resources | [Terraform: Tests](https://developer.hashicorp.com/terraform/language/tests) | Solution Overview Test Strategy |
| R25 | pydantic-ai's `TestModel` and `FunctionModel`, swapped in with `Agent.override()`, test agent code without calling a real LLM | [Pydantic AI: Testing](https://pydantic.dev/docs/ai/guides/testing/) | Solution Overview Test Strategy |

## 6. Platform equivalents (portability table)

| ID | Claim | Source | Used in |
|---|---|---|---|
| R26 | Databricks metric views implement Unity Catalog semantics: metrics defined once and queried by any available dimension | [Databricks: Metric views](https://docs.databricks.com/aws/en/metric-views/) | Data Foundations ADR-003 |
| R27 | Databricks AI/BI Genie answers natural-language questions over governed data | [Databricks: AI/BI Genie](https://docs.databricks.com/aws/en/genie/) | Data Foundations ADR-003 |
| R28 | Microsoft Fabric data agents answer natural-language questions over Fabric data | [Microsoft: Fabric data agent](https://learn.microsoft.com/en-us/fabric/data-science/concept-data-agent) | Data Foundations ADR-003 |

---

## Checked but not confirmed

These were looked for and couldn't be confirmed from public documentation. The design treats each as open.

1. **Programmatic access to GCP's detected cost anomalies.** The documentation pages tried returned HTTP 404. Data Foundations §4.1 marks this as unconfirmed, and GCP anomalies aren't ingested until it is.
2. **Cloning Snowflake-managed Iceberg tables on a customer-managed volume** (R14). Listed under Open Items to Validate in the Solution Overview.
3. **CMP's capabilities** (Kubernetes distribution, KEDA, NetworkPolicy, Pod Security admission, Entra Workload ID). CMP is internal to the organization, so there is no public source; Build Specification §8 states them as assumptions.
