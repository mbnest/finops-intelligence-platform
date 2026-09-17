# FinOps Intelligence Platform — Solution Architecture

A complete, from-scratch solution architecture for a governed, AI-assisted FinOps platform — reconstructed current state, identified opportunities, five-phase target-state design, build-ready specifications, and a migration plan, all in one continuous, cross-referenced document set.

| | |
|---|---|
| **Status** | Draft — unvalidated (by design; see [Methodology](#methodology--honest-limitations)) |
| **Author** | Matt Nestman |
| **Last updated** | 2026-09-17 |

---

## What this is

This repository reasons through an ambiguous, high-stakes architecture problem from limited external signal — a job posting and an informal conversation about the organization — with no insider access, system review, or interviews. From that starting point it:

1. Reconstructs a credible **current-state** FinOps practice ([`FinOps Current State.md`](docs/FinOps%20Current%20State.md)),
2. Identifies the **opportunities** a modern platform unlocks ([`FinOps Opportunities.md`](docs/FinOps%20Opportunities.md)),
3. Designs the **target-state platform** end to end — architecture, data model, AI governance, ADRs, build-ready specs, and a migration/cutover plan across thirteen cross-referenced documents,
4. Names the underlying agentic-systems patterns explicitly rather than leaving them implicit: a durable-workflow **Orchestrator** (Temporal) kept deliberately separate from a policy-as-code **Guardrail Engine** (OPA), and — for Cloud Workbench, the one genuinely agentic surface in this platform — a **bounded, explicitly-graphed agent** (pydantic-graph: typed nodes and edges, dynamic tool selection via MCP, and the ability to self-initiate a governed action) chosen deliberately over a more autonomous framework like LangGraph or CrewAI, for the auditability a regulated, financial-adjacent domain requires. Not one black-box agent loop deciding both what to do and whether it's safe to do it, and not an open-ended planner either.

**A note on the company name.** the organization is a real company, referenced because a real job posting named it. Nothing in this repository is confirmed the organization fact, and every document says so, repeatedly, on purpose — this is not an insider account of the organization's actual systems, and it isn't affiliated with or endorsed by the organization. The point of this exercise isn't "here's what the organization's FinOps platform is." It's "here's how I approach the problem, and how far I take it when nobody's stopping me."

## Why

The practice this platform replaces is **process-mature but tooling-light** — real discipline (strong tagging, true chargeback, a shared APM ID across cost/security/GRC, an independent top-quartile maturity rating), running on a monthly-batch, SQL-Server-and-PowerShell pipeline that can recommend but not act. A 2-person team runs the whole practice, and the lead loses roughly half their time to operational drag — stakeholder follow-ups, commitment planning, PO handling — that a governed platform can absorb instead of a person. "Governed" isn't a hedge word here: every delegated action, whether proposed by a model or a person, is executed by the same Orchestrator and classified by the same Guardrail Engine a human already trusts — the team gets time back *because* the harness makes delegation safe, not because the agent is simply trusted more.

Nothing here is framed as a fix for something broken. Every phase is an *addition* to a foundation that already works, aimed at the tier most enterprises — even mature ones — haven't reached yet.

## The solution, at a glance

Five phases, each building on the governance and data foundation the ones before it establish:

| Phase | What it is | Why it's sequenced there |
|---|---|---|
| **1 — Data Platform Foundation** | A governed Snowflake platform: mediation, semantic layer, knowledge graph, catalog, data quality | Every later phase reads from this layer — build it once, correctly, first |
| **2 — Core Intelligence & Self-Serve Foundations** | ML-driven anomaly/rightsizing/RI-SP models, a REST API, and dashboards | First user-facing value, and the source of what Phase 3 automates — simple, deterministic surfaces before anything agentic |
| **3 — Governed Automation** | A risk-tiered action layer split into two deliberately separate components: an **Orchestrator** (Temporal) running the durable workflow — sequencing, opt-out timers, approval waits, retries, rollback — and a **Guardrail Engine** (OPA policy-as-code) the Orchestrator calls out to for every LOW/MEDIUM/HIGH risk classification. Plus a signed horizontal/vertical contract and a disposition-SLA escalation path | Proven against one proposal source (Core Intelligence) before a second one is added |
| **4 — Financial Process Automation** | Exception-based bill verification — confidence-scored, evidence-attached reconciliation | A different domain (financial, not infrastructure) sharing the same routing pattern, sequenced once the core platform is stable |
| **5 — Cloud Workbench** | A bounded, explicitly-graphed conversational **agent** (pydantic-graph, not an open-ended autonomous loop) over the same governed data — retrieves, answers, cites sources, and can self-initiate a governed action, never executes one itself — plus push/pull/what-if expansion and GenAI-assisted PO drafting | Deliberately last — the most complex, least predictable layer, built once the foundation under it is proven |

Phases 2, 3, and 5 aren't three independent systems that happen to sit next to each other — every proposed action, whether it originates from Core Intelligence's models or Cloud Workbench's agent, enters through the identical `propose_action` tool call and passes through the same Orchestrator/Guardrail Engine pair. That shared entry point is what makes it one **agentic and automation harness**, not three: orchestration (workflow execution and state) and policy enforcement (risk classification) are separated on purpose, so neither the proposing agent nor the workflow engine is ever the thing deciding whether an action is safe to run.

Full detail, diagrams, and the master architecture decision log: [`FinOps Solution Overview.md`](docs/FinOps%20Solution%20Overview.md).

## So what — the value

No dollar-value ROI is claimed here — that number belongs to whoever has the organization's actual cost data, and inventing one would be worse than not having it. What *is* defensible from the outside:

**Time, not dollars.** The 2-person team's lead currently loses ~50% of their time to three operational-drag items, each of which maps directly onto a phase above:

- Reactive stakeholder follow-ups → **Cloud Workbench** (Phase 5), whose entire purpose is deflecting that Q&A load
- RI/commitment planning → **Core Intelligence**'s coverage/utilization metrics (Phase 2), already designed
- PO handling → **Bill Verification + PO Auto-Draft** (Phases 4–5), which remove the re-keying step entirely, not just speed it up

The honest pitch is "same 2-person team, less time lost to toil, more time for the analysis only they can do" — not a dollar figure. And the platform is built to measure its own value going forward: every input a future ROI calculation would need (anomaly dollar impact, recommendation realization rate, RI/SP coverage) is a metric Phase 1–2 already computes into the semantic layer. Pre-launch, that's a formula. Post-launch, it's real numbers.

None of that time-back is real unless the automation earning it is trustworthy — which is what the Orchestrator/Guardrail Engine harness is actually for. A recommendation that only ever sits in a queue doesn't save anyone's time; an action that executes itself without a human-auditable risk classification isn't something a FinOps lead should trust with production infrastructure. Splitting workflow execution (Orchestrator) from risk policy (Guardrail Engine) is what lets LOW-tier actions run unattended while HIGH-tier actions still always wait on a human — the same harness, two different outcomes, decided by policy, not by which component happened to run first.

## How to read this

Recommended order, each building on the last:

1. [`FinOps Current State.md`](docs/FinOps%20Current%20State.md) — where the practice is today, and how confident to be in that picture
2. [`FinOps Opportunities.md`](docs/FinOps%20Opportunities.md) — what a modern platform adds on top of it
3. [`FinOps Solution Overview.md`](docs/FinOps%20Solution%20Overview.md) — the five-phase target state, master architecture, and every sub-document indexed
4. The **Solution Architecture** sub-documents (linked from the Overview's Sub-Document Index) — one per phase or phase extension
5. [`Platform_Build_Specification.md`](docs/Platform_Build_Specification.md) — table names, job names, function signatures, policy names, at build-ready specificity for every phase

## Repository structure

```
docs/
├── FinOps Current State.md                                    Where the practice is today
├── FinOps Opportunities.md                                     What a modern platform adds
├── FinOps Solution Overview.md                                 Master doc — phasing, diagrams, ADRs, full index
├── Solution_Architecture_Data_Foundations.md               Phase 1 — data platform
├── Solution_Architecture_MLOps_Pipeline.md                 Phase 2 — Core Intelligence (ML)
├── Solution_Architecture_Self_Serve_Foundations.md         Phase 2 — REST API + dashboards
├── Solution_Architecture_Governed_Automation.md            Phase 3 — Orchestrator (Temporal) + Guardrail Engine (OPA)
├── Solution_Architecture_Governed_Automation_Contract.md   Phase 3 ext. — the horizontal/vertical contract
├── Solution_Architecture_Bill_Verification.md              Phase 4 — exception-based bill verification
├── Solution_Architecture_Cloud_Workbench.md                Phase 5 — conversational agent (pydantic-graph orchestration)
├── Solution_Architecture_Cloud_Workbench_Expansion.md      Phase 5 ext. — push/pull/what-if channels
├── Solution_Architecture_PO_Auto_Draft.md                  Phase 5 ext. — reuses the same agent stack for PO drafting
└── Platform_Build_Specification.md                        Build-ready detail for every phase above
```

## Methodology & honest limitations

Every document in this set states its own confidence level and flags assumptions as assumptions — see `FinOps Current State.md`'s own Methodology & Confidence section for the full treatment, which applies to everything built on top of it. In short: nothing here is verified against real the organization systems, ownership, or data; every "Open Items to Validate" section is a deliberate, honest list of what a real engagement would need to confirm first, not a gap to be embarrassed about.

## Status

All five phases have a complete solution architecture, all four originally-scoped sub-documents are written, and the Build Specification covers every phase at build-ready detail. A migration/cutover sequence and communications plan exist end to end. What's deliberately not here: real stakeholder validation of any inferred fact, a build timeline/staffing plan, and a test/QA strategy beyond what each phase's own eval gates and data-quality checks cover — see `FinOps Solution Overview.md`'s Open Items to Validate for the current, honest list.
