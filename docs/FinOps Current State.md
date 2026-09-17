# FinOps Current State

|                  |                                                                                    |
| ---------------- | ---------------------------------------------------------------------------------- |
| **Status**       | Draft, unvalidated                                                                 |
| **Creator**      | Matt Nestman                                                                       |
| **Last updated** | 2026-09-17                                                                         |
| **Audience**     | Engineering, Product, Architecture stakeholders scoping FinOps platform investment |

## Purpose

This document reconstructs the organization's current FinOps practice from the outside, using a job posting and an informal conversation about the organization. There was no insider access, system review, or interview with process owners. That is intentional: the goal is to show how a credible current-state picture, and a grounded solution built on it, can come from limited information. Making sound, explicit assumptions with incomplete information is a skill in its own right.

Read it as a **starting point and working hypothesis**, not an authoritative record: the kind of document a candidate or outside advisor writes before getting inside, to be corrected once they are. It likely contains inaccuracies and is missing details only an insider would know. Every assumption is labeled as one, and low-confidence items are flagged, so it's clear what to validate first.

## Methodology & Confidence

This document comes from informal conversation, not system access, architecture diagrams, code review, or interviews with every process owner. Treat everything below as **directionally correct, not verified**, with these limitations:

- **No primary-source validation.** Nothing has been checked against the SQL Server schema, the PowerShell and stored procedure source, Power BI report definitions, or a process document. Statements reflect what was recalled in conversation, which may be incomplete or out of date.
- **Single-source recollection.** Statements marked "assumed" or "not confirmed" came from inference or secondhand description. They are the highest-priority items to validate before this document supports architecture or budget decisions.
- **Unclear ownership in places.** Some steps (reconciliation verification, rightsizing tooling) had no named owner in the conversation. Where ownership is unknown, it says so.
- **No end-to-end walkthrough.** This describes the process as told, not as observed. Edge cases, exception handling, and failure modes weren't discussed.
- **The external maturity rating is a single aggregate score**, with no breakdown by capability (see [External Maturity Benchmark](#external-maturity-benchmark)). It doesn't confirm that every capability area here is mature.

**Recommended next step:** validate the "not confirmed" and "assumed" items with the actual process owners (the FinOps team lead and whoever administers the SQL Server/PowerShell pipeline) before using this document as the basis for a target-state design.

## Executive Summary

The organization runs a self-built FinOps practice on SQL Server and Power BI, covering AWS, Azure, and GCP. Cost and usage files are pulled from each cloud, loaded into a local SQL Server database with PowerShell and stored procedures, reconciled against the enterprise Application Portfolio Management (APM) ID, and rolled up into Power BI reports. On a cadence believed to be monthly, the FinOps team reviews anomalies, reports forecast and budget against actuals, and makes advisory rightsizing recommendations, ending in chargeback to owning departments one month in arrears. Tagging coverage is strong (strong), and the practice does true chargeback, not showback. Both are signs of maturity. Microsoft has rated the organization in the top quartile of enterprises it has assessed for FinOps maturity, though the basis for that score isn't fully known.

The practice is process-mature but light on tooling. Most of what a modern FinOps platform automates (continuous ingestion, anomaly alerting, rightsizing enforcement, unit economics) is done manually or semi-manually on a monthly cycle, by a team that can recommend but not act on its own findings.

## External Maturity Benchmark

Microsoft has told the organization it ranks in the **top quartile** for FinOps maturity among the enterprises Microsoft has worked with.

Treat this as directional context, not a validated capability assessment, for three reasons:

1. It is a **single aggregate score**. The dimensions behind it (tagging coverage, chargeback maturity, commitment optimization, anomaly management, forecasting accuracy, and so on) and their weighting aren't known.
2. It may **lean on Azure-side practice** more than AWS or GCP, given Microsoft's vantage point and the Azure-native tooling (Synapse/Fabric, ADX) named in the job description.
3. It reframes the gaps below without removing them. Real-time anomaly detection, enforced rightsizing, and unit economics are areas most enterprise FinOps practices haven't reached, even mature ones. Read the gaps here as **the current frontier of a strong practice**, not as deficiencies.

## Current Technology Stack

| Component | Role |
|---|---|
| SQL Server (local instance) | System of record for ingested, reconciled cloud cost/usage data |
| PowerShell | Data acquisition (file pulls from cloud vendors) and pipeline orchestration |
| SQL Server Stored Procedures | Data loading, reconciliation, aggregation, anomaly-flagging logic |
| Power BI | Reporting and analysis layer, used for spend review and anomaly/optimization analysis |

**Enterprise data platform direction (known):** Snowflake is the organization's data platform standard, and the organization is actively consolidating onto it. The FinOps pipeline above hasn't moved yet. This is the main reason the target state is built on Snowflake (Data Foundations ADR-003).

No orchestration framework (such as Airflow or ADF), lakehouse layer, or native cloud billing export integration was described. Data acquisition is file-based, not a managed pipeline against the providers' billing exports or APIs.

## Cloud Metadata & Tagging

- **Tagging coverage:** strong of resources across all three clouds carry the 8 baseline tags.
- **APM ID coverage:** roughly nearly all of resources carry a resolvable APM ID, per the same conversation. That is higher than the strong figure for all 8 tags, since not every resource carries all 8.
- **Application Portfolio ID (APM ID):** one of the 8 tags. It links each resource to the enterprise Application Portfolio Management (APM) tool, which holds application metadata, ownership, and points of contact. Data, risk, and compliance classification is *assumed* to live there too; not confirmed.
- **Cross-functional reuse:** Security and GRC use the same APM IDs for their own reviews and audits. That is a real architectural asset: cost, security, and compliance already share one resource identity key.

## Data Flow

```
AWS / Azure / GCP billing & usage files
        │  (PowerShell pull; cadence not confirmed, believed monthly)
        ▼
   SQL Server (local)
        │  (Stored procedures: load, reconcile to APM ID, aggregate)
        ▼
   Resource Group / Account rollups
        │
        ├──► Power BI reports (spend review, anomaly flags, consumption analysis)
        └──► Monthly FinOps cycle (anomaly review, forecasting, rightsizing, chargeback)
```

**Cadence:** believed to be monthly, not daily or continuous. This is an assumption. It isn't confirmed whether files are pulled and loaded daily and only reported monthly, or whether the pull itself is monthly. The second half of the month is described as the busy period for report generation, which fits a process that concentrates effort around month-end.

## Process & Capability Inventory

### Team & Capacity

A 2-person team does everything in this section: improving the tooling, generating and distributing reports, answering ad hoc questions from business verticals, and the proactive analysis (anomaly review, rightsizing, forecasting) described below. This comes from conversation, not a confirmed org chart. The team lead spends roughly half their time on operational work (stakeholder follow-ups, RI/commitment planning and laddering, PO handling), leaving the other half for proactive analysis. Not confirmed: the second team member's time split, or whether anyone outside the team helps.

**Known staffing change:** the team lead, who also built the SQL Server/PowerShell pipeline, retires in the end of the year. Two things leave with them. The roughly 50% operational load above falls to whoever remains or replaces them. And much of the pipeline's business logic (reconciliation rules, APM matching, anomaly flags, chargeback allocation) likely exists only in that code and in the lead's knowledge. The organization is hiring a principal engineer to modernize the platform, which suggests the remaining staff aren't expected to take on modern data, ML, and agentic work alone.

### Reporting Process
1. **Data Verification**: manual review of cloud vendor data for accuracy.
2. **Reconciliation Verification**: cost data reconciled to APM ID during processing. *Who verifies this step, and how, isn't confirmed.*
3. **Report Generation**: Power BI reports for spend review, anomaly identification, and consumption-based pricing analysis.

### Anomaly Detection
Some anomaly flagging is automated in the PowerShell and stored-procedure logic, so this isn't purely manual. Given the assumed monthly refresh, that automation probably also runs monthly. Automation exists; continuous detection doesn't appear to.

### Forecasting & Budgeting
Done by the FinOps team as part of the monthly report cycle, per conversation. The method and ownership beyond "the FinOps team" aren't confirmed.

### Rightsizing & Waste Elimination
The FinOps team sends rightsizing and cleanup suggestions to owning departments, possibly using other tools or working with cloud engineers; the specifics aren't confirmed. This happens in the monthly cycle. The FinOps team does **not** appear to have authority to act on resources itself: recommendations are advisory to the owning department. That is an authority boundary, not a tooling gap.

### Consumption-Based Pricing / Commitment Management
1-year and 3-year commitment end dates are staggered through the year, not concentrated at one renewal, so commitment optimization is continuous work.

### Payment & Chargeback
After bill verification and contract association, POs are entered into the relevant system and cloud vendors are paid. Owning departments are charged back (true chargeback, not showback), typically one month in arrears.

## Known Gaps & Unconfirmed Items

What to validate before treating this document as authoritative, in priority order:

| Item | Why it matters |
|---|---|
| Business rules embedded in the legacy stored procedures and PowerShell scripts | Their author retires in the end of the year, so they need to be written down and turned into tests before then (Solution Overview, migration step 0a) |
| Actual data pull/refresh cadence (daily vs. monthly) | Determines how current the target platform needs to be; the biggest open assumption here |
| Who owns reconciliation verification | Unclear today, for a step that affects chargeback accuracy |
| What tooling supports rightsizing recommendations | "Other tools" or "working with cloud engineers" isn't specific enough to design an integration |
| APM tool's actual classification metadata | Assumed to include data, risk, and compliance classification; not confirmed |
| Dimensional breakdown of Microsoft's maturity score | Needed to know which capability areas are strong and which are adequate |
| Whether AWS/GCP practice maturity matches Azure | Relevant given Azure-native tooling and Microsoft's likely Azure-weighted view |

## Other Known Context

- **Datadog** came up in conversation as one of the SaaS platforms whose cost the organization wants to bring under FinOps in the future, which confirms the organization uses it. That it is the organization's observability platform of record is an inference from what Datadog does, not something stated. The target-state design reuses it for monitoring and alerting on that assumption.
- **SaaS cost management is a stated future direction** (Datadog is one example). It is outside this document set's current scope of AWS, Azure, and GCP.

## Out of Scope

This document doesn't cover: engineering or product teams' use of cost data, cost allocation disputes and escalation, licensing cost management, sustainability and carbon tracking, or tooling outside the SQL Server/PowerShell/Power BI stack. Absence here means "not discussed," not "doesn't exist."
