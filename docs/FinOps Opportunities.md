# FinOps Platform & Practice Opportunities

|                  |                                                                                                                 |
| ---------------- | --------------------------------------------------------------------------------------------------------------- |
| **Status**       | Draft — unvalidated                                                                                             |
| **Creator**      | Matt Nestman                                                                                                    |
| **Last updated** | 2026-09-12                                                                                                      |
| **Audience**     | Engineering, Product, Architecture stakeholders; hiring/leadership stakeholders evaluating a proposed direction |

## Purpose

This document lists opportunities to extend the FinOps practice described in [FinOps Current State.md](FinOps%20Current%20State.md), responsive to a stakeholder's own stated direction in conversation: a desire to modernize, further automate and enrich the analyses performed, and provide better **"self-serve."**

It is written from the same outside-in vantage point as the current-state document — an educated set of opportunities, not a confirmed backlog — and carries the same caveat: it is likely incomplete or wrong in places, and should be corrected once validated from the inside.

**A note on framing:** the practice described in the current-state document — strong tagging coverage, true chargeback (not showback), an APM ID shared across cost/security/GRC, year-round commitment laddering — did not happen by accident. It reflects years of sustained discipline, and Microsoft's independent top-quartile maturity assessment backs that up. Nothing below is a fix for something broken. Every opportunity here is written as an *addition to* that foundation, aimed at the next tier most enterprises — even mature ones — haven't reached yet.

This document is split into two parts, deliberately kept separate: **technology stack/architecture** (the platform underneath the practice) and **FinOps process/practice** (what the practice does and enables). The work ahead spans both, and conflating them tends to produce solutions that are either all-infrastructure-no-outcome or all-process-no-platform.

---

## Part 1: Technology Stack & Architecture Opportunities

These modernize the platform underneath the existing practice. In each case, the goal is to carry forward the reconciliation, tagging, and rollup logic that already works — not to discard and rebuild it.

| Opportunity | Builds On | Why It Matters |
|---|---|---|
| Native cloud billing export ingestion, evaluating the **FOCUS** standard (FinOps Open Cost and Usage Specification — now supported by AWS, Azure, and GCP) where available, in place of file pulls | Existing multi-cloud reconciliation logic — the transformation rules carry forward; FOCUS would reduce how much cross-provider field mapping needs to be hand-built at all | Removes dependency on manual/scripted file pulls and shortens the path to more frequent refresh; FOCUS specifically could cut a meaningful share of the "reconcile AWS's fields against Azure's against GCP's" work down to organization-specific tag/attribution logic instead of full schema normalization |
| Managed orchestration (Airflow, ADF, or equivalent) | Existing PowerShell/stored-procedure pipeline steps — these can be ported into managed tasks rather than rewritten | Observability, retries, and dependency management for a pipeline that today runs on scheduled scripts |
| Governed data platform layer (e.g., a cloud data warehouse or lakehouse with native versioning) alongside or beneath SQL Server | The reconciled, APM-linked dataset already produced today | Adds versioning/ACID guarantees and a foundation that serves both existing BI reporting and future ML/AI consumption, without changing what's already trusted |
| Canonical data model exposed as a governed API | The resource-group/account rollups already computed today | Lets the data be consumed programmatically (self-serve tools, future services) instead of only through Power BI |
| Governed semantic layer defining core metrics once (e.g. "EC2 spend," "monthly burn rate," "RI coverage") | The canonical data model and rollups already computed today | Stops every consumer — including a future self-serve or AI interface — from re-deriving the same metric slightly differently; one definition, reused everywhere, matches how the reports are already trusted today |
| Entity/relationship model (knowledge graph) over accounts, resources, tags, and the APM ID | The APM ID's existing role as a cross-cloud resource identity key | Makes relational questions ("which resources in this vertical had both a cost anomaly and a recent deployment") directly answerable, and gives a future self-serve interface something structured to reason over instead of only flat rollup tables |
| MLOps foundation (MLflow or equivalent), favoring explainable model families (statistical/tree-based) for anomaly and rightsizing models | The anomaly-flagging logic already embedded in stored procedures today | Turns existing rule-based flagging into monitored, versioned models — evolution, not replacement — and explainability keeps every flagged item traceable to *why*, which matters as much for user trust and adoption as it does for governance |
| GenAI/RAG interface over the canonical data layer | The reconciled dataset and existing report definitions as source content | Directly addresses the stated "better self-serve" goal — natural-language querying instead of waiting on a report cycle |
| Evaluation/quality gate for AI-facing changes (a curated, domain-specific set of representative questions, checked before any prompt/retrieval/model change ships) | The GenAI/RAG interface above | Prevents a self-serve AI interface from quietly regressing in accuracy or trust over time — the same discipline already applied to code changes, extended to prompts and retrieval config |
| Formal data quality framework (freshness checks, schema evolution, automated validation) | The manual data-verification step already performed each cycle today | Automates a check that's already recognized as necessary and already being done by hand |
| Governance/catalog tooling (lineage, RBAC) | The APM ID's existing cross-functional reuse by Security & GRC | Extends an identity key that already spans domains into a fuller governance layer, rather than introducing a new one |

---

## Part 2: FinOps Process & Practice Opportunities

### 2a. Analysis Enrichment

Opportunities to deepen the analyses the practice already performs.

- **Near-real-time cost visibility** as a complement to the existing monthly cycle — not a replacement for the disciplined monthly close, but a way to surface signal between cycles.
- **Unit economics** (cost per transaction/service/customer) layered onto the resource-group/account rollups that already exist.
- **ML-assisted analysis** — models to support cost anomaly detection, rightsizing recommendations, and RI/savings-plan modeling — as an augmentation to the FinOps team's existing forecast/budget-vs-actual, anomaly-review, and rightsizing process, not a replacement for their judgment.
- **Automated commitment coverage/utilization tracking** to augment the already-active 1yr/3yr laddering effort with continuous visibility rather than periodic review.
- **APM ID resolution rate as a trended governance KPI** — track the percentage of resources successfully linked to an APM ID over time (already strong per the current-state document), and separately track staleness of the volatile owner/contact fields under it, distinct from whether the underlying resource-to-application mapping is intact. Turns an assumption in the current-state document into something actually measured, and gives early warning if coverage quietly erodes.
- **The platform practicing what it preaches** — if a GenAI or ML layer is added, track its own operating cost (compute, token spend) with the same rigor applied to the cloud spend it analyzes. A FinOps platform with an unmeasured cost of its own undercuts its own credibility.

### 2b. Self-Serve Channels & Personas

Opportunity: design self-serve around two distinct personas, each with different access and needs:

- **Platform** — the FinOps/platform team itself, who need full cross-vertical visibility to do their own job.
- **Vertical** — business verticals, as customers of the horizontal team. Both personas are internal to the org — "Platform" and "Vertical" describe the relationship (who operates the platform vs. who consumes it), not any distinction between the organization and an outside party. Scoped to their own vertical/account data by default, plus **anonymized, aggregated cross-vertical benchmarks** so a vertical can see how it compares without seeing another vertical's raw numbers. Default benchmark set (assumed, to be confirmed with real stakeholders): rate/percentage-based metrics only — RI/SP coverage %, APM resolution %, anomaly rate — not raw-dollar percentiles, which are easier to reverse-engineer into a peer's actual spend.

| Channel | Primary Persona(s) | Description |
|---|---|---|
| Standard reports/dashboards | Platform + Vertical | On-demand view of current spend and chargeback position, replacing "wait for the monthly report" with something always available |
| Conversational interface (chatbot) | Platform + Vertical | The GenAI/RAG interface from Part 1 — natural-language querying in place of a report request |
| Published REST APIs | Platform + Vertical (technical/integration consumers) | The governed API from Part 1 — lets other tools and teams consume platform data programmatically, not just through a UI |
| FinOps signals embedded in existing platforms (push) | Vertical | Cost/anomaly/recommendation signals surfaced directly inside IDP, CMP, Internal Assistant, or wherever verticals already work, rather than requiring a trip to a separate FinOps destination |
| Vertical self-serve workbench with what-if analysis (pull) | Vertical (built and operated by the horizontal team) | A separate, vertical-facing product that pivots/aggregates existing tools (IDP, CMP, Internal Assistant), current and historical cost data, APM data, and other reference data into one surface for scenario planning — verticals come to the horizontal team's workbench rather than the horizontal team coming to them |

**Opportunity: push and pull as two front ends on one shared platform, not two separate ones.** Build push (FinOps-initiated reporting, suggestions, and automation delivered out to verticals) and pull (a vertical-initiated workbench for their own planning) as distinct product surfaces, matched to their different interaction patterns — notify versus explore. Back both with the *same* governed API(s), semantic layer, and knowledge graph from Part 1, rather than standing up two independently modeled platforms; a separately modeled workbench risks re-fragmenting the shared APM ID that the current practice's cross-functional reuse with Security/GRC already depends on. Scope the IDP/CMP/Internal Assistant integration itself as its own phase — aggregating live views from three existing platforms, each with its own auth and data model, is a meaningfully bigger lift than a dashboard or chatbot and shouldn't be sized as if it were comparable effort.

**What-if scenario analysis** is the workbench's core capability: model a proposed change (e.g., "what if we bought this savings plan," "what if we rightsized this fleet") against current and historical cost data, then let the result be submitted directly as a proposed action through the same risk-tiering/contract/guardrail gates defined in [2c](#2c-automated-optimization-actions-risk--blast-radius-aware) — turning a simulation into a governed action without a separate manual re-entry step. Beyond cost and APM data, plausible additional reference data sources (placeholders, not confirmed) include:

- ITSM/ticketing history (past incidents/changes tied to a resource or application)
- CMDB records (if distinct from the APM tool)
- CI/CD deployment history (correlating cost shifts with releases)
- Security/GRC risk registry entries (if not already folded into APM classification)

### 2c. Automated Optimization Actions (Risk & Blast-Radius Aware)

> **Assumption flag:** the current-state document describes rightsizing/cleanup as advisory-only — the FinOps team surfaces recommendations to owning departments but does not appear empowered to act unilaterally. This section assumes **no automated remediation exists today**. That assumption may well be wrong and should be validated before acting on it.

The opportunity is not to replace the team's judgment with automation — it's to let a bounded, low-risk subset of the recommendations they already generate today execute automatically, freeing the team's advisory effort for the cases that actually need it.

| Opportunity | Description |
|---|---|
| Risk/blast-radius tiering (LOW/MEDIUM/HIGH) | Classify optimization actions by risk and blast radius so low-risk cases can execute automatically, medium-risk cases automate with a delay and opt-out, and high-risk cases stay advisory-only, same as today; everything defaults to advisory-only until explicitly classified into one of the three tiers |
| Horizontal/vertical automation "contract" | An explicit, opt-in, SLA-like agreement between the FinOps/platform team and each owning application team, keyed on the APM ID, covering what's pre-approved, notification, change windows, rollback, and escalation |
| Policy schema & engine | Extend the existing tag/APM schema to carry risk tier, blast-radius classification, and consent status, and evaluate a policy engine to encode and enforce it |
| Scoped automation identity | A dedicated, auditable IAM identity for automated remediation, kept separate from human/break-glass access |
| Guardrails | Dry-run/simulation mode, staged/canary rollout, hard caps with a circuit breaker, full audit trail, a kill switch, a documented exception/opt-out process, and alignment with existing change management |

Detail on each below.

**Risk/blast-radius tiering:**

Before any tier below is enabled, every resource defaults to advisory-only — the current state for everything today, where the FinOps team recommends and a human decides. That default isn't itself a tier; it's the starting condition a resource stays in until explicitly classified into one of the three tiers below.

| Risk Tier | Example | Handling |
|---|---|---|
| LOW (low blast radius) | Unattached disks, deallocated resources with no active workload, idle dev/sandbox resources | Automate with notification; no pre-approval required per action |
| MEDIUM | Rightsizing non-prod, or prod with redundancy/auto-scaling in place | Automate with a delay window and an explicit opt-out |
| HIGH (high blast radius) | Production, stateful, customer-facing, or compliance-classified workloads | Remains advisory only, human-approved — same as today, a hard rule rather than a tunable threshold |

Notably, the risk/compliance classification this tiering needs may **already partially exist** — the current-state document notes the APM tool is assumed (not confirmed) to hold data/risk/compliance classification metadata already reused by Security & GRC. If that's accurate, the data model this depends on may already be most of the way there.

**The "contract" between the horizontal FinOps/platform team and business verticals**

Beyond the advisory-only default, an explicit, opt-in agreement between the owning application team and the FinOps/platform team is needed before automation acts on their resources — an SLA-like contract, keyed on the same APM ID already used for tagging, security, and GRC. It would need to define:

- Which automated actions are pre-approved for that application/environment
- The risk tier assigned, and who has authority to set or change it
- Notification requirements before and/or after an automated action
- Change-window constraints (e.g., no automated action during business-critical periods)
- Rollback guarantee and timeframe
- Escalation path if an automated action causes an incident
- A review/renewal cadence for the agreement itself, so it doesn't go stale

Because it's keyed on the APM ID, the identity and ownership plumbing this needs may already largely exist — what's likely missing is the contract schema and a mechanism to capture consent, not the underlying identity model.

**Policy review & enrichment likely needed**

- Extend the existing 8-tag schema (or an APM-linked policy record) to capture risk tier, blast-radius classification, automation consent status, and the designated approver — a natural extension of a tagging practice already at strong coverage, not a new discipline.
- Evaluate a policy engine (cloud-native tooling per provider, or a unified layer) to encode and enforce tiering/contract rules — check against whatever IaC/governance tooling already exists before introducing something new.
- Clarify who owns policy authorship and review — likely a joint responsibility across FinOps, application owners, and Security/GRC given the shared use of the APM ID today.
- Review IAM/permission boundaries — automated remediation needs its own scoped, auditable identity, separate from human access.

**Guardrails**

This is what the solution design (`Solution_Architecture_Governed_Automation.md`) later names the **Guardrail Engine** — the system built to enforce everything below, not a separate future concept.

- Dry-run/simulation mode before any tier moves from "recommend" to "apply."
- Staged/canary rollout — enable automation for a small cohort of LOW-tier applications first, expand based on results.
- Hard caps per run (resources touched, spend-delta) with a circuit breaker on anomalous volume.
- Full audit trail — every automated action logged with before/after state, linked to both the APM ID and the contract that authorized it.
- An org-wide and per-vertical kill switch.
- A documented exception/opt-out process for a team to exclude specific resources without leaving the program entirely.
- Alignment with existing change management (CAB or equivalent), if one exists — not assumed here, needs confirmation.

### 2d. Bill Verification as Exception-Based Review

The current-state document describes bill verification as a fully manual step — a reviewer checks that cloud vendor billing looks accurate before it flows into PO creation and chargeback, upstream of everything else in the payment/chargeback flow.

Opportunity: convert this into an exception-based review — automated where the system is confident, routed to a human where it isn't — rather than either fully automating it or leaving it fully manual.

| Opportunity | Description |
|---|---|
| Confidence + evidence-scored reconciliation | Automatically reconcile invoiced line items against contracted rates and expected usage, producing a confidence score plus supporting evidence (matching contract clause, historical rate comparison, delta explanation) per line item |
| Confidence + impact-based routing (hard rule) | High-confidence, low-dollar-impact items clear automatically; low-confidence or high-dollar-impact items always route to a human, regardless of confidence — a hard rule, not a tunable threshold, the same pattern used for high-risk actions in [2c](#2c-automated-optimization-actions-risk--blast-radius-aware) |

This doesn't remove the human from bill verification — it shifts their time from 100% line-by-line confirmation to the genuinely ambiguous or high-value exceptions, a more defensible use of a scarce reviewer's judgment. It's also a natural predecessor to the PO-creation-automation idea discussed separately: a confidence-scored, evidence-attached bill verification step is what would make auto-drafting a PO from that data defensible, rather than automating on top of a number nobody has formally verified.

---

## Open Items — Assumptions Adopted

Most of the items originally listed here have been converted into educated, stated assumptions so the solution documents (`FinOps Solution Overview.md` and its sub-documents) could proceed rather than stall — each is flagged in the relevant sub-document at the point it affects, not just here. Two remain genuinely open by design; everything else has an adopted position, correctable once validated from the inside.

- **No automated remediation exists today.** Adopted as-is — this is the baseline Governed Automation is designed against.
- **APM classification coverage.** Adopted: partial. Assume the APM tool already carries *some* classification data (GRC's own compliance work almost certainly requires it), but not a blast-radius-specific field — that's a FinOps/infra concept GRC wouldn't need. Governed Automation's schema extension assumes one net-new field, not a from-scratch classification effort.
- **Change management / CAB.** Adopted: yes, one almost certainly exists at this scale. Governed Automation's MEDIUM-tier change windows are designed to respect an existing CAB calendar/freeze schedule rather than invent one.
- **Organizational risk appetite and timeline for automated action — genuinely left open.** This is a business decision, not a technical one; no assumption is adopted either way. The Solution Overview's phasing reflects technical dependency order only, not an assumed go-ahead.
- **"Better self-serve" scope.** Adopted: both reporting and optimization actions. The what-if → Governed Automation bridge already designed in this document only makes sense under that reading, so no separate assumption was needed to reach it.
- **FOCUS adoption today.** Adopted: not currently in use. Nothing in the Current State document's description of a multi-year PowerShell/SQL pipeline suggests it, so Data Foundations treats enabling FOCUS exports as a discrete per-provider setup task, not something already available.
- **Bill-verification scoring today.** Adopted: today's check is a true pass/fail (or fully manual), not scored. Current State describes manual review, not existing confidence logic — so Phase 4's model is genuinely net-new, not an enhancement of something already there.
- **IDP / CMP / Internal Assistant API readiness.** Split assumption: IDP and CMP are already assumed API-reachable (Governed Automation calls them directly). Internal Assistant (the real, existing tool) is the genuinely uncertain one — chat tools don't always expose a clean integration surface — and is flagged as the higher-risk item in Cloud Workbench Expansion's planning, not assumed away.
- **What-if → automated-action trust.** Resolved architecturally rather than assumed: a what-if-originated proposal gets no special trust. It routes through the identical LOW/MEDIUM/HIGH tiering as any other proposal source, so there's no bypass that would need separate trust in the first place.
- **Cross-vertical benchmark selection.** Adopted default: rate/percentage-based metrics only (RI coverage %, APM resolution %, anomaly rate) — not raw-dollar percentiles, which are easier to reverse-engineer into a peer's actual spend. Confirmed with real stakeholders before anything ships.
