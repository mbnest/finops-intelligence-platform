# FinOps Platform & Practice Opportunities

|                  |                                                                                                                 |
| ---------------- | --------------------------------------------------------------------------------------------------------------- |
| **Status**       | Draft, unvalidated                                                                                              |
| **Creator**      | Matt Nestman                                                                                                    |
| **Last updated** | 2026-09-17                                                                                                      |
| **Audience**     | Engineering, Product, Architecture stakeholders; hiring/leadership stakeholders evaluating a proposed direction |

## Purpose

This document lists opportunities to extend the FinOps practice described in [FinOps Current State.md](FinOps%20Current%20State.md). It responds to the direction a stakeholder described in conversation: modernize, automate more, enrich the analyses, and provide better **"self-serve."**

It comes from the same outside-in view as the current-state document: an informed set of opportunities, not a confirmed backlog. It is likely incomplete or wrong in places and should be corrected once validated from the inside.

**On framing:** the practice in the current-state document (strong tagging coverage, true chargeback, an APM ID shared across cost, security, and GRC, year-round commitment laddering) reflects years of discipline, and Microsoft's top-quartile maturity rating supports that. Nothing below fixes something broken. Every opportunity is an *addition to* that foundation, aimed at the tier most enterprises, including mature ones, haven't reached.

The document has two parts: **technology stack and architecture** (the platform under the practice) and **FinOps process and practice** (what the practice does). The work spans both. Mixing them tends to produce either infrastructure with no outcome or process with no platform.

---

## Part 1: Technology Stack & Architecture Opportunities

These modernize the platform under the existing practice. In each case the goal is to carry forward the reconciliation, tagging, and rollup logic that already works, not to throw it away.

| Opportunity | Builds On | Why It Matters |
|---|---|---|
| Native cloud billing export ingestion using the **FOCUS** standard (FinOps Open Cost and Usage Specification, offered by AWS, Azure, and GCP, with GCP's export in preview) where available, in place of file pulls | Existing multi-cloud reconciliation logic. The transformation rules carry forward, and FOCUS reduces how much cross-provider field mapping has to be hand-built | Removes the dependency on scripted file pulls and makes more frequent refresh possible. FOCUS could shrink much of the "map AWS fields to Azure fields to GCP fields" work down to organization-specific tag and attribution logic |
| Managed orchestration (Airflow, ADF, or equivalent) | Existing PowerShell and stored-procedure steps, which can be ported into managed tasks | Monitoring, retries, and dependency management for a pipeline that runs on scheduled scripts today |
| Governed data platform (a cloud data warehouse or lakehouse with native versioning) alongside or under SQL Server | The reconciled, APM-linked dataset produced today | Adds versioning and ACID guarantees, and serves both existing BI reporting and future ML and AI use without changing what's already trusted |
| Canonical data model exposed as a governed API | The resource-group and account rollups computed today | Lets tools and services use the data programmatically, not only through Power BI |
| Governed semantic layer defining core metrics once ("EC2 spend," "monthly burn rate," "RI coverage") | The canonical data model and existing rollups | Stops each consumer, including a future AI interface, from computing the same metric slightly differently |
| Entity/relationship model (knowledge graph) over accounts, resources, tags, and the APM ID | The APM ID's role as a cross-cloud resource identity key | Makes relational questions answerable ("which resources in this vertical had a cost anomaly and a recent deployment") and gives an AI interface structure to reason over |
| MLOps foundation (MLflow or equivalent), favoring explainable models (statistical or tree-based) for anomaly and rightsizing work | The anomaly-flagging logic in today's stored procedures | Turns rule-based flagging into monitored, versioned models. Explainability keeps every flag traceable to a reason, which matters for adoption as much as for governance |
| GenAI interface over the governed data | The reconciled dataset and existing report definitions | Addresses the "better self-serve" goal directly: ask a question instead of waiting for a report cycle |
| Evaluation gate for AI changes (a curated set of real questions, checked before any prompt, retrieval, or model change ships) | The GenAI interface above | Keeps an AI interface from slowly losing accuracy, applying the testing discipline used for code to prompts and retrieval |
| Formal data quality framework (freshness checks, schema evolution, automated validation) | The manual data-verification step done each cycle today | Automates a check the team already knows is necessary and does by hand |
| Governance and catalog tooling (lineage, access control) | Security and GRC's existing use of the APM ID | Builds a fuller governance layer on an identity key that already spans domains |

---

## Part 2: FinOps Process & Practice Opportunities

### 2a. Analysis Enrichment

Ways to deepen the analyses the practice already does.

- **Daily cost visibility** alongside the monthly cycle, to surface signal between month-end closes. Daily is the practical floor, because provider billing data arrives in batches hours behind usage. The disciplined monthly close stays.
- **Unit economics** (cost per transaction, service, or customer) on top of the existing resource-group and account rollups.
- **ML-assisted analysis** for anomaly detection, rightsizing, and RI/savings-plan planning, supporting the team's forecasting, anomaly review, and rightsizing work. It informs their judgment; it doesn't replace it.
- **Continuous commitment coverage and utilization tracking** to support the existing 1-year/3-year laddering between periodic reviews.
- **APM ID resolution rate as a trended governance KPI.** Track the share of resources linked to an APM ID over time (about nearly all today, per the current-state document), and separately track how stale the owner and contact fields under it are. That turns an assumption into a measurement and gives early warning if coverage slips.
- **Tracking the platform's own cost.** If a GenAI or ML layer is added, track its compute and token spend as rigorously as the cloud spend it analyzes. A FinOps platform that doesn't measure its own cost loses credibility.

### 2b. Self-Serve Channels & Personas

Design self-serve around two personas with different access and needs:

- **Platform**: the FinOps/platform team, who need full cross-vertical visibility to do their jobs.
- **Vertical**: business verticals, the customers of the horizontal team. Both personas are internal; "Platform" and "Vertical" describe who runs the platform and who uses it. Verticals see their own vertical and account data by default, plus **anonymized, aggregated cross-vertical benchmarks** so they can compare themselves without seeing another vertical's numbers. Default benchmark set (assumed, to confirm with stakeholders): rates and percentages only, such as RI/SP coverage %, APM resolution %, and anomaly rate. Raw-dollar percentiles are excluded because they are easier to reverse-engineer into a peer's actual spend.

| Channel | Primary Persona(s) | Description |
|---|---|---|
| Standard reports/dashboards | Platform + Vertical | An always-available view of current spend and chargeback position, instead of waiting for the monthly report |
| Conversational interface (chatbot) | Platform + Vertical | The GenAI interface from Part 1: ask in natural language instead of requesting a report |
| Published REST APIs | Internal teams and tools | The governed API from Part 1, for programmatic use outside a UI |
| FinOps signals embedded in existing platforms (push) | Vertical | Cost, anomaly, and recommendation signals shown inside IDP, CMP, Internal Assistant, or wherever verticals already work |
| Vertical self-serve workbench with what-if analysis (pull) | Vertical (built and run by the horizontal team) | A vertical-facing product that brings existing tools (IDP, CMP, Internal Assistant), current and historical cost data, APM data, and other reference data into one place for scenario planning |

**Push and pull as two front ends on one platform.** Build push (FinOps-initiated reports, suggestions, and automation delivered to verticals) and pull (a workbench verticals use for their own planning) as separate product surfaces, since one notifies and the other supports exploration. Back both with the *same* governed APIs, semantic layer, and knowledge graph from Part 1. A separately modeled workbench would risk fragmenting the shared APM ID that Security and GRC also depend on. Treat the IDP, CMP, and Internal Assistant integration as its own phase: combining live views from three platforms, each with its own authentication and data model, is much bigger work than a dashboard or chatbot.

**What-if scenario analysis** is the workbench's core capability. A vertical models a change ("what if we bought this savings plan," "what if we rightsized this fleet") against current and historical cost data, and can submit the result as a proposed action through the same risk-tier, contract, and guardrail checks defined in [2c](#2c-automated-optimization-actions-risk--blast-radius-aware), with no manual re-entry. Possible additional reference data (placeholders, not confirmed):

- ITSM/ticketing history (past incidents and changes tied to a resource or application)
- CMDB records (if separate from the APM tool)
- CI/CD deployment history (to correlate cost changes with releases)
- Security/GRC risk register entries (if not already part of APM classification)

### 2c. Automated Optimization Actions (Risk & Blast-Radius Aware)

> **Assumption flag:** the current-state document describes rightsizing and cleanup as advisory only. The FinOps team recommends to owning departments but doesn't appear to have authority to act. This section assumes **no automated remediation exists today**. That may be wrong and should be validated.

The goal isn't to replace the team's judgment with automation. It is to let a bounded, low-risk subset of the recommendations the team already makes execute automatically, so the team's advisory effort goes to the cases that need it.

| Opportunity | Description |
|---|---|
| Risk/blast-radius tiering (LOW/MEDIUM/HIGH) | Classify actions by risk and blast radius: LOW executes automatically, MEDIUM executes after a delay with an opt-out, HIGH stays advisory as today. Everything is advisory until classified |
| Horizontal/vertical automation "contract" | An explicit, opt-in, SLA-like agreement between the FinOps/platform team and each owning application team, keyed on the APM ID, covering what's pre-approved, notification, change windows, rollback, and escalation |
| Policy schema & engine | Extend the tag/APM schema to carry risk tier, blast-radius classification, and consent status, and evaluate a policy engine to enforce it |
| Scoped automation identity | A dedicated, auditable identity for automated remediation, separate from human and break-glass access |
| Guardrails | Dry-run mode, staged rollout, hard caps with a circuit breaker, a full audit trail, a kill switch, an exception/opt-out process, and alignment with existing change management |

Details on each follow.

**Risk/blast-radius tiering:**

Until a tier is enabled, every resource is advisory only, which is how everything works today: the FinOps team recommends and a person decides. Advisory isn't a tier; it is the starting condition until a resource is classified into one of the three tiers.

| Risk Tier | Example | Handling |
|---|---|---|
| LOW (low blast radius) | Unattached disks, deallocated resources with no workload, idle dev/sandbox resources | Automate with notification; no per-action pre-approval |
| MEDIUM | Rightsizing non-prod, or prod with redundancy or autoscaling in place | Automate after a delay window with an explicit opt-out |
| HIGH (high blast radius) | Production, stateful, customer-facing, or compliance-classified workloads | Advisory only, human-approved as today. A fixed rule, not a tunable threshold |

The risk and compliance classification this tiering needs may **partly exist already**. The current-state document notes the APM tool is assumed (not confirmed) to hold data, risk, and compliance classification that Security and GRC use. If so, much of the data model is already in place.

**The "contract" between the horizontal FinOps/platform team and business verticals**

Beyond the advisory default, the owning application team and the FinOps/platform team need an explicit, opt-in agreement before automation acts on that team's resources. It is SLA-like, keyed on the same APM ID used for tagging, security, and GRC, and defines:

- Which automated actions are pre-approved for that application and environment
- The risk tier assigned, and who can set or change it
- Notification requirements before or after an automated action
- Change-window constraints (for example, no automated action during business-critical periods)
- Rollback guarantee and timeframe
- Escalation path if an automated action causes an incident
- A review and renewal cadence, so the agreement doesn't go stale

Because it is keyed on the APM ID, the identity and ownership data likely exists. What's missing is the contract schema and a way to capture consent.

**Policy review & enrichment likely needed**

- Extend the 8-tag schema, or an APM-linked policy record, to capture risk tier, blast-radius classification, automation consent status, and the designated approver. This builds on a tagging practice already at strong coverage.
- Evaluate a policy engine (per-provider tooling or a unified layer) to encode and enforce tier and contract rules. Check existing IaC and governance tooling first.
- Clarify who writes and reviews policy. It is probably shared across FinOps, application owners, and Security/GRC, given the shared APM ID.
- Review IAM boundaries. Automated remediation needs its own scoped, auditable identity, separate from human access.

**Guardrails**

The solution design (`Solution_Architecture_Governed_Automation.md`) calls the system that enforces these the **Guardrail Engine**.

- Dry-run mode before any tier moves from recommending to applying.
- Staged rollout: enable automation for a small group of LOW-tier applications first, then expand based on results.
- Hard caps per run (resources touched, spend change) with a circuit breaker on unusual volume.
- A full audit trail: every automated action logged with before and after state, linked to the APM ID and the contract that authorized it.
- An org-wide and per-vertical kill switch.
- A documented exception process so a team can exclude specific resources without leaving the program.
- Alignment with existing change management (CAB or equivalent), if one exists. Not assumed here; needs confirmation.

### 2d. Bill Verification as Exception-Based Review

The current-state document describes bill verification as manual: a reviewer checks that cloud vendor billing looks right before it moves on to PO creation and chargeback.

Opportunity: make it exception-based. Clear lines automatically where the system is confident, and send the rest to a person, instead of either automating it fully or leaving it fully manual.

| Opportunity | Description |
|---|---|
| Confidence + evidence-scored reconciliation | Reconcile invoice lines against the billing data behind them, contracted terms, and expected usage, with a confidence score and evidence (contract terms applied or missing, historical comparison, the size of the difference) for each line |
| Confidence + impact-based routing (hard rule) | High-confidence, low-dollar lines clear automatically. Low-confidence or high-dollar lines always go to a person, whatever the confidence. A fixed rule, the same pattern as the HIGH tier in [2c](#2c-automated-optimization-actions-risk--blast-radius-aware) |

A person stays in bill verification, but their time moves from confirming every line to the ambiguous or high-value exceptions, which is a better use of a scarce reviewer. This is also a prerequisite for PO auto-drafting, though a separate capability: drafting a PO is defensible only on top of a scored, evidenced verification, not on a number nobody verified. PO auto-draft is designed in `Solution_Architecture_PO_Auto_Draft.md`, listed in the Sub-Document Index of `FinOps Solution Overview.md`.

---

## Open Items: Assumptions Adopted

To let the solution documents (`FinOps Solution Overview.md` and its sub-documents) proceed, most open questions here have a stated, adopted assumption. Each is also flagged in the sub-document it affects. One item stays open because it is a business decision; the rest can be corrected once validated from the inside.

- **No automated remediation exists today.** Adopted as stated; it is the baseline Governed Automation is designed against.
- **APM classification coverage.** Adopted: partial. The APM tool likely carries *some* classification data (GRC's compliance work almost certainly needs it), but not a blast-radius field, which is an infrastructure concept GRC wouldn't need. Governed Automation's schema extension assumes one new field, not a new classification effort.
- **Change management / CAB.** Adopted: one almost certainly exists at this scale. Governed Automation's MEDIUM-tier change windows are designed to respect an existing CAB calendar and freeze schedule.
- **Organizational risk appetite and timeline for automated action: left open.** This is a business decision, not a technical one, so no assumption is adopted. The Solution Overview's phasing reflects technical dependencies and operational priorities, not an assumed go-ahead.
- **"Better self-serve" scope.** Adopted: both reporting and optimization actions. The what-if-to-Governed-Automation path only makes sense under that reading.
- **FOCUS adoption today.** Adopted: not in use. Nothing in the description of the PowerShell/SQL pipeline suggests it, so Data Foundations treats enabling FOCUS exports as a setup task per provider.
- **Bill-verification scoring today.** Adopted: today's check is manual or pass/fail, with no scoring. Phase 4's scoring is new, not an enhancement of existing logic.
- **IDP / CMP / Internal Assistant API readiness.** Split assumption: IDP and CMP are assumed to have usable APIs (Governed Automation calls them directly). Internal Assistant is the uncertain one, since chat tools don't always offer a clean integration surface, and Cloud Workbench Expansion treats it as the higher-risk integration.
- **What-if-to-automated-action trust.** Resolved by design: a what-if proposal gets no special trust. It goes through the same LOW/MEDIUM/HIGH tiering as any other proposal, so there is no bypass to trust.
- **Cross-vertical benchmark selection.** Adopted default: rates and percentages only (RI coverage %, APM resolution %, anomaly rate), not raw-dollar percentiles, which are easier to reverse-engineer into a peer's spend. To be confirmed with stakeholders before anything ships.
