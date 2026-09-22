# FinOps Intelligence Platform: Solution Architecture

A from-scratch solution architecture for a governed, AI-assisted FinOps platform: a reconstructed current state, the opportunities, a five-phase target design, build-ready specifications, and a migration plan, in one cross-referenced document set.

| | |
|---|---|
| **Status** | Draft, unvalidated (by design; see [Methodology](#methodology--limitations)) |
| **Author** | Matt Nestman |
| **Last updated** | 2026-09-17 |

---

## What this is

This repository works through an ambiguous, high-stakes architecture problem from limited outside information: a job posting and an informal conversation about the organization, with no insider access, system review, or interviews. From that starting point it:

1. Reconstructs the **current-state** FinOps practice ([`FinOps Current State.md`](docs/FinOps%20Current%20State.md)).
2. Identifies the **opportunities** a modern platform opens up ([`FinOps Opportunities.md`](docs/FinOps%20Opportunities.md)).
3. Designs the **target platform** end to end: architecture, data model, ML and AI governance, ADRs, build-ready specifications, an operating model, and a migration plan, across fifteen cross-referenced documents.
4. Makes the agentic design explicit. A durable-workflow **Orchestrator** (Temporal) is kept separate from a policy-as-code **Guardrail Engine** (OPA), so no single component decides both what to do and whether it is safe. Cloud Workbench, the platform's one agentic surface, is a **bounded agent with an explicit graph** (pydantic-graph: typed nodes and edges, tools over MCP, and the ability to propose a governed action but never execute one), chosen over more autonomous frameworks such as LangGraph or CrewAI for the auditability a financial domain needs.
5. **Builds a runnable slice of it** ([`demo/`](demo)), so the load-bearing claims are demonstrated in code instead of asserted in prose.


## Why

The FinOps practice this platform modernizes is **process-mature but light on tooling**. It has real discipline (strong tagging coverage, true chargeback, an APM ID shared across cost, security, and GRC, and a top-quartile maturity assessment from a cloud provider) running on a monthly SQL Server and PowerShell pipeline that can recommend but not act. A small central team runs it, and the lead spends roughly half their time on operational work (stakeholder follow-ups, commitment planning, PO handling) that a governed platform could take on.

"Governed" is doing real work in that sentence. Every delegated action, whether a model or a person proposes it, is classified by the same Guardrail Engine and executed by the same Orchestrator. The team gets time back because the harness makes delegation safe, not because the agent is trusted more.

Nothing here fixes something broken. Every phase adds to a foundation that already works.

## The solution at a glance

Five phases, each built on the data and governance foundation of the phases before it:

| Phase | What it is | Why it comes there |
|---|---|---|
| **1: Data Platform Foundation** | A governed Snowflake platform on open Iceberg tables: mediation, cost basis, semantic layer, ontology, catalog, data quality | Every later phase reads from it, so it is built first |
| **2: Core Intelligence & Self-Serve Foundations** | Anomaly detection, rightsizing rules, an RI/SP planner, a REST API, and dashboards | First user-facing value, and the source of what Phase 3 automates; simple, deterministic surfaces before anything agentic |
| **3: Governed Automation** | A risk-tiered action layer with two separate components: an **Orchestrator** (Temporal) for the durable workflow and a **Guardrail Engine** (OPA) for risk classification and guardrails (dry-run, kill switch, caps, circuit breaker). Plus a signed horizontal/vertical contract and disposition-SLA escalation | Proven against one proposal source (Core Intelligence) before a second is added |
| **4: Financial Process Automation** | Exception-based bill verification of provider invoice lines, starting on rules and moving to a model once labels exist | A different domain (financial) using the same routing pattern |
| **5: Cloud Workbench** | A bounded conversational **agent** over the same governed data that retrieves, answers, cites sources, and can propose a governed action, plus push/pull/what-if expansion and GenAI-assisted PO drafting | Last, because it is the most complex and least predictable layer; a read-only pilot for the FinOps team runs earlier |

Phases 2, 3, and 5 form one **agentic and automation harness**, not three systems side by side. Every proposed action, from Core Intelligence's models, Cloud Workbench's agent, or a what-if scenario, enters through the same `propose_action` call and passes through the same Orchestrator and Guardrail Engine. Workflow execution and risk policy are separated on purpose, so neither the proposing agent nor the workflow engine decides whether an action is safe.

For the short version, read [`FinOps Architecture Brief.md`](docs/FinOps%20Architecture%20Brief.md). For full detail, diagrams, and the master decision log, read [`FinOps Solution Overview.md`](docs/FinOps%20Solution%20Overview.md).

## The value

No dollar ROI is claimed. That number belongs to whoever has the organization's cost data, and inventing one would be worse than having none. What can be defended from the outside:

**Time, not dollars.** The team lead loses about half their time to three kinds of operational work. The rollout is ordered to relieve them early, not in architecture order:

- **Stakeholder follow-ups**: a per-vertical "why did my bill change" report in the first reporting wave (no AI needed), then a read-only Cloud Workbench pilot for the FinOps team, then Cloud Workbench for verticals.
- **Commitment planning**: a commitment coverage and expiry view in the first reporting wave, then a forecast-then-optimize RI/SP planner once historical data is loaded.
- **PO handling**: Bill Verification's rules-based review queue before any ML, then PO Auto-Draft, which removes re-keying.

That toil is measured before anything changes, so each wave's effect can be shown. The platform also measures its own value afterward: the inputs to a future ROI calculation (anomaly dollar impact, recommendation realization rate, commitment coverage) are metrics the semantic layer already computes.

None of that time comes back unless the automation is trustworthy, which is what the Orchestrator and Guardrail Engine are for. A recommendation that sits in a queue saves nobody time, and an action that runs without an auditable risk classification isn't something a FinOps lead should trust with production. Separating workflow from policy is what lets LOW-tier actions run unattended while HIGH-tier actions always wait for a person: the same harness, with the outcome set by policy.

**Built to be run by one engineer, and to outlast them.** The team lead, who also built today's pipeline, retires at the end of the year, and the role this repository responds to is a single principal engineer. So the design covers the full modern stack (data platform, ML, self-serve APIs, ontology and graph, agents) while keeping what that engineer operates small: managed services instead of self-hosted ones, three containers on the organization's existing container platform, no clusters or self-hosted databases, and each technology introduced only when first needed. Capturing the lead's business rules as tests before that departure is the first step of the migration plan. The operational work doesn't retire with the lead; it lands on whoever remains, which makes moving it into the platform more urgent. See the Operating Model in [`FinOps Solution Overview.md`](docs/FinOps%20Solution%20Overview.md).

## How to read this

1. [`FinOps Architecture Brief.md`](docs/FinOps%20Architecture%20Brief.md): the whole design in a few pages.
2. [`FinOps Current State.md`](docs/FinOps%20Current%20State.md): where the practice is today per current understanding, and how confident to be in that picture.
3. [`FinOps Opportunities.md`](docs/FinOps%20Opportunities.md): what a modern platform adds.
4. [`FinOps Solution Overview.md`](docs/FinOps%20Solution%20Overview.md): phases, architecture, operating model, test strategy, rollout waves, master ADRs, and the index of sub-documents.
5. The **Solution Architecture** sub-documents, one per phase or extension (linked from the Overview's Sub-Document Index).
6. [`Platform_Build_Specification.md`](docs/Platform_Build_Specification.md): table names, job names, function signatures, and policy names for every phase.
7. [`References.md`](docs/References.md): vendor documentation behind decision-driving claims, and what couldn't be confirmed.
8. [`demo/`](demo): the runnable slice, with a quickstart and a short tour of what to look at.

## The demo slice

The design's four load-bearing claims are the ones a reviewer should be most skeptical of, so [`demo/`](demo) proves each in working code. It runs locally in minutes on DuckDB and Docker, with no cloud account:

| Claim | How the demo shows it |
|---|---|
| The cost data model is right | FOCUS data with four cost columns that genuinely differ, and restated billing periods replaced rather than merged |
| Models are judged, not trusted | Anomalies of known kind and size are injected; the detector never sees the answer key, and an eval gate scores it against a naive baseline and fails the build when it slips |
| Workflow and policy stay separate | A Temporal workflow sequences and waits; OPA classifies risk. Four idle resources produce four different governed outcomes |
| Personas are enforced in code | An MCP server binds the action tool only for a persona allowed to act, and scopes every read to the caller's verticals |

Every one of those is checked by breaking it: removing the latest-delivery logic, raising the detector's dollar floor, deleting the kill-switch re-check, and binding the action tool for everyone each fail the tests that claim to cover them. `demo/README.md` has the quickstart and the tour; `demo/PLAN.md` has the decisions and build log.

**What the demo is not.** It stands in for the platform, it does not implement it: DuckDB for Snowflake, generated data for provider exports, and a fake executor in place of IDP or CMP. The stand-ins are listed in `demo/README.md`.

## Repository structure

```
docs/
├── FinOps Architecture Brief.md                                 Short version for reviewers
├── FinOps Current State.md                                      Where the practice is today
├── FinOps Opportunities.md                                      What a modern platform adds
├── FinOps Solution Overview.md                                  Master doc: phases, operating model, tests, rollout, ADRs, index
├── Solution_Architecture_Data_Foundations.md               Phase 1: data platform
├── Solution_Architecture_MLOps_Pipeline.md                 Phase 2: Core Intelligence (ML)
├── Solution_Architecture_Self_Serve_Foundations.md         Phase 2: REST API and dashboards
├── Solution_Architecture_Governed_Automation.md            Phase 3: Orchestrator (Temporal) and Guardrail Engine (OPA)
├── Solution_Architecture_Governed_Automation_Contract.md   Phase 3 extension: the horizontal/vertical contract
├── Solution_Architecture_Bill_Verification.md              Phase 4: exception-based bill verification
├── Solution_Architecture_Cloud_Workbench.md                Phase 5: conversational agent (pydantic-graph)
├── Solution_Architecture_Cloud_Workbench_Expansion.md      Phase 5 extension: push/pull and what-if channels
├── Solution_Architecture_PO_Auto_Draft.md                  Phase 5 extension: PO drafting on the same agent stack
├── Platform_Build_Specification.md                         Build-ready detail for every phase
├── References.md                                                Vendor documentation behind key claims
└── Systems Engineer Prin.md                                     The job posting this responds to (kept local, not committed)

demo/                                                            Runnable slice of the design
├── README.md                                                    Quickstart, what to look for, stand-ins
├── PLAN.md                                                      Decisions, build order, progress log
├── data_generator/                                              spec.yaml holds every generation rule
├── dbt/                                                         bronze, silver, gold, metric models, tests
├── core_intelligence/                                           Anomaly detector and eval gate
├── governed_automation/                                         Temporal workflow and OPA policies
├── mcp_server/                                                  Persona-bound tools
└── tests/                                                       pytest suite
```

## Methodology & limitations

Every document states its confidence and labels assumptions as assumptions. The Methodology & Confidence section of `FinOps Current State.md` covers this in full, and it applies to everything built on it. In short: nothing here is verified against the organization's systems, ownership, or data. Each "Open Items to Validate" list is what a real engagement would confirm first.

**Accuracy and completeness are separate risks.** The assumption labelling above covers the first: facts that may be wrong. The second is capabilities a design built from the outside didn't notice it was missing. One is documented — recommendation delivery and lifecycle tracking (Solution Overview, Capability Map) — and more should be expected. The useful distinction is whether closing a gap changes a decision or only adds a piece. The ones found so far are additive: a table, an endpoint, a job, a metric definition, changing no ADR, phase dependency, or part of the data model. That is a backlog, not a rewrite. A gap that moved one of those would be worth treating differently.

## Status

All five phases have a solution architecture, and the Build Specification covers every phase. The Solution Overview includes an operating model, a wave-based migration plan, and a communications plan. Not included on purpose: stakeholder validation of any inferred fact; numbers for sizing, platform cost, on-call, and staffing (these need the organization's data, and the Overview's Implementation Prerequisites section lists each one, its inputs, and how it would be produced); and a detailed test plan (the Overview's Test Strategy sets direction only). The Overview's Open Items to Validate has the current list.

The demo covers a slice of Phases 1 to 3 and 5: the data foundation, anomaly detection with its eval gate, the governed action harness, and the MCP tool surface. Bill verification, RI/SP planning, the ontology and graph, and the agent itself are designed but not built.
