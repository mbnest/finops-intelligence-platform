# FinOps Current State

|                  |                                                                                    |
| ---------------- | ---------------------------------------------------------------------------------- |
| **Status**       | Draft — unvalidated                                                                |
| **Creator**      | Matt Nestman                                                                       |
| **Last updated** | 2026-09-12                                                                         |
| **Audience**     | Engineering, Product, Architecture stakeholders scoping FinOps platform investment |

## Purpose

This document reconstructs the current-state FinOps practice from an outside-in vantage point — built from a job posting and an informal, external conversation about the organization, not from insider access, system review, or interviews with process owners. That is a deliberate feature of how this document was produced, not an oversight: the objective is to demonstrate the ability to synthesize a credible current-state picture, and from it a grounded proposed solution, from limited external signal. Making sound, explicit assumptions under incomplete information is a skill in its own right, and this document is meant to exercise it.

Given that vantage point, this should be read as a **starting point and working hypothesis** for describing current state, not a finished or authoritative record — the kind of document a candidate or outside advisor produces before getting inside, meant to be corrected and sharpened once it is. It is likely to contain inaccuracies and is likely missing details that only an insider would know. Every assumption below is stated as an assumption, and every low-confidence item is flagged as such, so it is clear which parts to validate first rather than accept at face value.

## Methodology & Confidence

This document was reconstructed from informal conversation, not from direct system access, architecture diagrams, source code review, or interviews with every process owner. Treat every statement below as **directionally correct, not verified**, with the following specific limitations:

- **No primary-source validation.** Nothing here has been confirmed against the SQL Server schema, PowerShell/stored procedure source, PowerBI report definitions, or a system-of-record process document. Statements reflect what was recalled in conversation, which may be incomplete, outdated, or filtered through the recollection of whoever was speaking.
- **Single-source recollection.** Where a statement is qualified below as "assumed" or "not confirmed," it means the information came from inference or secondhand description rather than a direct, confident answer — these are the highest-priority items to validate before this document is used to justify architecture or budget decisions.
- **Ownership is unclear in places.** Several steps in the process (data reconciliation verification, rightsizing tooling) do not have a named owner in the source conversation. Where RACI is unknown, it is called out explicitly rather than guessed.
- **No end-to-end walkthrough.** This reflects a description of the process, not an observed execution of it. Edge cases, exception handling, and failure modes are not covered because they were not discussed.
- **External maturity context is a single aggregate score**, not a dimensional breakdown — see [External Maturity Benchmark](#external-maturity-benchmark) below. It should not be read as confirmation that every capability area described here is independently mature.

**Recommended next step:** validate the items flagged "not confirmed" or "assumed" below with the actual process owners (FinOps team lead, whoever administers the SQL Server/PowerShell pipeline) before this document is used as the basis for a target-state design.

## Executive Summary

The organization runs a self-built, SQL-Server-and-PowerBI-based FinOps practice covering AWS, Azure, and GCP. Cost and usage files are pulled from each cloud, loaded into a local SQL Server database via PowerShell and stored procedures, reconciled against an enterprise Application Portfolio Management (APM) ID, and rolled up into PowerBI reports. On a cadence believed to be monthly, the FinOps team performs anomaly review, forecasting/budget-vs-actual reporting, and advisory rightsizing recommendations, culminating in chargeback to owning departments one month in arrears. Tagging coverage is strong (strong), and the practice already performs true chargeback rather than showback — both signals of relative maturity. Microsoft has independently rated this organization in the top quartile of enterprises it has assessed for FinOps maturity, though the basis for that score is not fully known (see below).

The practice is process-mature but tooling-light: most of what a modern FinOps platform would automate (continuous ingestion, anomaly alerting, rightsizing enforcement, unit economics) is instead done manually or semi-manually on a monthly batch cycle, by a team that can recommend but not act unilaterally on findings.

## External Maturity Benchmark

Microsoft has advised that this organization ranks in the **top quartile** for FinOps maturity among the enterprises Microsoft has worked with.

This should be treated as directional context, not a validated capability assessment, for three reasons:

1. It is a **single aggregate score** — the underlying dimensions (tagging coverage, chargeback maturity, commitment optimization, anomaly management, forecasting accuracy, etc.) and their relative weighting are not known.
2. The assessment may be **more heavily informed by Azure-side practice** than by the AWS/GCP portions of the estate, given Microsoft's vantage point and the org's use of Azure-native tooling (Synapse/Fabric, ADX) elsewhere.
3. It reframes — but does not eliminate — the gaps identified below. Capabilities like real-time anomaly detection, enforced (not advisory) rightsizing, and unit economics are areas most enterprise FinOps practices have not reached, even at high maturity. The gaps in this document should be read as **the current frontier of a strong practice**, not as remedial deficiencies.

## Current Technology Stack

| Component | Role |
|---|---|
| SQL Server (local instance) | System of record for ingested, reconciled cloud cost/usage data |
| PowerShell | Data acquisition (file pulls from cloud vendors) and pipeline orchestration |
| SQL Server Stored Procedures | Data loading, reconciliation, aggregation, anomaly-flagging logic |
| Power BI | Reporting and analysis layer, consumed for spend review and anomaly/optimization analysis |

No orchestration framework (e.g., Airflow, ADF), lakehouse layer, or cloud-native billing export integration was described — data acquisition is file-based rather than a managed pipeline against native cloud billing APIs/exports.

## Cloud Metadata & Tagging

- **Tagging coverage:** strong of resources across all three clouds carry 8 baseline tags.
- **Application Portfolio ID (APM ID):** one of the 8 tags, linking each resource to the enterprise Application Portfolio Management (APM) tool, which holds application metadata, ownership, and points of contact. Classification metadata for data/risk/compliance is *assumed* to also live there — not confirmed.
- **Cross-functional reuse:** Security & GRC use the same APM IDs for their own review, management, and audit processes — this is a real architectural asset, since it means cost, security, and compliance domains already share a common resource identity key rather than maintaining separate mappings.

## Data Flow

```
AWS / Azure / GCP billing & usage files
        │  (PowerShell — pull, cadence not confirmed; believed monthly)
        ▼
   SQL Server (local)
        │  (Stored procedures — load, reconcile to APM ID, aggregate)
        ▼
   Resource Group / Account rollups
        │
        ├──► Power BI reports (spend review, anomaly flags, consumption analysis)
        └──► Monthly FinOps cycle (anomaly review, forecasting, rightsizing, chargeback)
```

**Cadence:** believed to be monthly rather than daily/continuous, though this is an assumption — it has not been confirmed whether cloud files are pulled and loaded daily with reporting simply *consumed* monthly, or whether the pull itself is monthly. Anecdotally, the latter part of the calendar month is described as the busy period for report generation, consistent with a process that concentrates effort — automated and manual — around month-end rather than running continuously.

## Process & Capability Inventory

### Team & Capacity

A 2-person team performs everything in this section: enhancing the existing tooling, generating and distributing reports, fielding ad hoc questions from business verticals, and the proactive analysis (anomaly review, rightsizing, forecasting) described below — per conversational recollection, not a confirmed org chart. The team lead spends roughly 50% of their time on operational matters — stakeholder follow-ups, RI/commitment planning and laddering, PO handling — leaving roughly half their time for the proactive/analytical work described in this section. Not confirmed: the second team member's own time split, or whether any partial/shared support exists outside this immediate team.

### Reporting Process
1. **Data Verification** — manual review of cloud vendor data for accuracy.
2. **Reconciliation Verification** — reconciliation of cost data back to APM ID during processing; *it is not confirmed who verifies this step or how*.
3. **Report Generation** — Power BI reports produced for spend review, anomaly identification, and consumption-based pricing analysis.

### Anomaly Detection
Some anomaly detection/flagging is automated within the existing PowerShell/stored-procedure logic — this is not a purely manual review step. However, given the assumed monthly (rather than daily) refresh cadence, this automated detection likely also only *runs* monthly rather than near-real-time. Automation exists; continuous/real-time operation does not appear to.

### Forecasting & Budgeting
Performed by the FinOps team as part of the monthly report cycle, per conversational recollection. Specific methodology and ownership beyond "the FinOps team" are not confirmed.

### Rightsizing & Waste Elimination
The FinOps team surfaces rightsizing/cleanup suggestions back to owning departments, possibly using additional tooling and/or in partnership with cloud engineers — the specifics of this tooling/partnership are not confirmed. This happens as part of the monthly cycle. Notably, the FinOps team does **not** appear to be empowered to take unilateral action on resources: recommendations are advisory to the owning department, not directly enforced. This is a process/authority boundary, not a tooling gap.

### Consumption-Based Pricing / Commitment Management
Contract end dates (1-year and 3-year commitments) are staggered throughout the year rather than concentrated at a single renewal point, so commitment optimization is a continuous rather than periodic effort.

### Payment & Chargeback
Following bill verification and contract association, POs are entered into the relevant system and cloud vendors are paid. Owning departments are charged back — true chargeback, not showback — typically one month in arrears.

## Known Gaps & Unconfirmed Items

Prioritized list of what to validate before treating this document as authoritative:

| Item | Why it matters |
|---|---|
| Actual data pull/refresh cadence (daily vs. monthly) | Determines how "real-time" a target-state platform actually needs to be — the biggest open assumption in this document |
| Who owns reconciliation verification | Currently unowned/unclear; a RACI gap for a step that affects chargeback accuracy |
| What tooling supports rightsizing recommendations | "Other tools" and/or "partnership with cloud engineers" is not specific enough to design an integration point |
| APM tool's actual classification metadata contents | Assumed to include data/risk/compliance classification; not confirmed |
| Dimensional breakdown of Microsoft's maturity score | Needed to know which capability areas are genuinely strong vs. merely adequate |
| Whether AWS/GCP practice maturity matches Azure | Relevant given the org's Azure-native tooling elsewhere and Microsoft's likely Azure-weighted vantage point |

## Out of Scope

This document does not cover: engineering/product team consumption of cost data (self-service access, if any), cost allocation disputes/escalation process, licensing cost management, sustainability/carbon tracking, or any tooling used outside the SQL Server/PowerShell/Power BI stack. Absence here means "not discussed," not "does not exist."
