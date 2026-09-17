# Follow-Up: Review of Completeness, Validity, and Technical Signal

| | |
|---|---|
| **Status** | Review notes |
| **Scope** | Entire document set in `docs/` and `README.md`, reviewed against `Systems Engineer Prin.md` |
| **Last updated** | 2026-09-17 |

## Summary

Short answer: partly. The document set shows strong systems and governance thinking, and a few ideas in it are genuinely senior. But it reads more like an architect who writes specs than the "practitioner who goes deep" the role asks for. Someone who has worked with cloud billing data would also spot domain mistakes that undercut the technical credibility.

The posting says three times that this is a **principal individual contributor** role. "Not just a leader" is the right concern, and right now the repository doesn't settle it.

---

## 1. What Works

1. **Keeping the workflow separate from the safety decision.** Temporal runs the workflow, OPA decides the risk tier, and everything enters through a single `propose_action` call. The AI agent can propose an action but has no path to execute one or change its tier.
2. **Checking whether a resource is managed by Terraform before acting on it** (Governed Automation FR6). Routing those changes through a Terraform PR, so the next `apply` doesn't undo them, is the kind of detail only someone who has run infrastructure thinks of.
3. **Metric discipline that reaches Power BI.** The point that local DAX measures can quietly redefine a metric, even when the report reads from Semantic Views, comes from real experience.
4. **No vector store for structured data.** Answering definition questions with a direct lookup instead of embeddings shows good judgment.
5. **Where the agent's rules are enforced.** Persona and tool access are enforced in the orchestration graph, not in the prompt.
6. **A realistic migration plan:** parallel runs, current-period data before historical backfill, and a pass/fail gate at every step.
7. **Honest about assumptions** throughout.

---

## 2. Problems a Technical Reviewer Would Catch

### 2.1 Cloud billing data details (the biggest credibility risk)

> **Status: addressed.** Items 1-4 below are corrected in Data Foundations (§4.1 sources, §4.3 cost basis and ER model, §4.4 ontology), Build Specification (§1-4, §10), Bill Verification (§2.1, FR1, §3.2, ADR-4, glossary), and the Solution Overview's migration gates. The findings are kept below for reference.

1. **Which cost?** `gold.fact_cost_daily.cost_usd` doesn't say whether it is billed, amortized, or list cost. FOCUS separates `BilledCost`, `EffectiveCost`, `ListCost`, and `ContractedCost` for a reason. RI/SP coverage, chargeback, and bill verification each need a different one.
2. **Rerunning the pipeline safely.** Build Specification §2 says to `MERGE` on `line_item_id`. AWS says CUR line item IDs aren't stable across report refreshes, and Azure has no equivalent ID. Providers rewrite a whole billing period many times, so the usual pattern is to replace data per billing period, not to upsert rows.
3. **A check that would fail constantly.** `dq_check_null_resource_id` fails any non-tax row with no resource ID. Support fees, marketplace charges, commitment purchases, and some data-transfer charges legitimately have none.
4. **Bill verification uses the wrong data.**
   1. It scores rows from `fact_cost_daily` (one row per resource per day, with no unit rate), not invoice lines.
   2. It never ingests invoices, EDP/MACC discounts, or credits.
   3. FOCUS already carries `ContractedUnitPrice`, which covers part of what the separate rate-card feed is for.

### 2.2 How the ML problems are framed

> **Status: items 1-5 addressed.** Item 4: provider recommendations and anomalies ingested daily (Data Foundations §4.1; Build Specification §1, §3), build-vs-use decision per capability (MLOps Pipeline ADR-007), provider baselines in the eval gates (§2.4), and migration step 0 plus provider comparisons in steps 13, 16, and 19 (Solution Overview). Items 1-3: Labels and eval gates per model (MLOps Pipeline §2.4; Bill Verification §3.3 rules-first staging; Build Specification anomaly dispositions and review reason codes; Solution Overview ADR-M4), rightsizing as deterministic sizing rules (MLOps Pipeline §2.3, ADR-003), and RI/SP as forecast-then-optimize with a commitment inventory (MLOps Pipeline §2.3, ADR-006; `gold.dim_commitment`). Item 5: batch inference inside Snowflake, with AKS kept for long-running services (MLOps Pipeline §2.1, §2.5, §2.6, ADR-008; Bill Verification §3.1, §3.4; Build Specification §8, §10).

1. **Labels that don't exist.**
   1. The bill verification model trains on "historical human verification outcomes." The document set's own adopted assumption says today's check is manual and unscored, so those labels probably don't exist.
   2. The anomaly eval gate ("meet or exceed on a held-out set") has the same problem: no labels are defined.
2. **Rightsizing** is framed as supervised regression/classification, but nothing defines what the correct answer would be. In practice it is utilization percentiles against instance size plus headroom.
3. **RI/SP planning** is an optimization under uncertainty (forecast usage, then choose a commitment mix). It is described only as "forecasting models."
4. **No comparison with free provider tools.** AWS Compute Optimizer, AWS Cost Anomaly Detection, Azure Advisor, and GCP Recommender are never mentioned. A principal would use them as baselines or as model inputs.
5. **Model serving adds an extra hop.** Serving on AKS contradicts the "keep compute next to the data" reasoning used for Snowpark ML. With a ~24h billing lag, batch scoring inside Snowflake is simpler.

### 2.3 Too much complexity for the team

1. The design runs roughly sixteen technologies: Snowflake, Neo4j, Postgres, Redis, self-hosted Temporal, OPA, Airflow, AKS, Datadog, Evidently, Streamlit, a Teams bot, pydantic-graph, MCP, Cortex Analyst, and Azure OpenAI.
2. The team is two people whose core problem is lack of time.
3. There is no sizing, cost estimate, on-call model, or staffing plan anywhere.
4. The Neo4j decision record (Data Foundations ADR-004) admits recursive SQL queries handle today's graph depth. At principal level, what you choose to leave out is a big part of the signal.

### 2.4 The platform choice isn't really argued

1. Data Foundations ADR-003 only compares Snowflake with Databricks.
2. Everything else points to Microsoft: Power BI, Teams, Azure OpenAI, a top-quartile Microsoft maturity rating, and a job posting that names Fabric, Synapse, and ADX. Microsoft Fabric needs an explicit comparison.
3. The posting asks for Iceberg or Delta Lake. Snowflake-managed Iceberg tables would meet that at almost no cost. Right now the requirement is met by substitution.

### 2.5 Sequencing against the stated pain

1. The lead's biggest time sink (stakeholder follow-ups) is addressed in Phase 5.
2. RI planning comes at migration steps 18-20.
3. Phase 1 replaces the whole platform before anyone gets value.
4. A couple of early quick wins would strengthen the pitch, for example commitment coverage reporting or native anomaly alerts.

### 2.6 Places the documents contradict each other

1. **Guardrail Engine definition.** The Solution Overview glossary still defines it as doing "risk-tiering, orchestration, and execution," which contradicts the Temporal/OPA split.
2. **Can verticals take action?** Cloud Workbench calls "no action-taking for verticals" a standing product boundary, but Build Specification §12 gives verticals `propose_action` in the pull workbench.
3. **Are dashboards vertical-facing?** Self-Serve Foundations says the API/dashboards are not, but ADR-M1 says verticals get dashboard self-serve in Phase 2.
4. **Missing proposal sources.** The `propose_action` `origin` type only allows `core_intelligence` and `cloud_workbench`. The approval table also has `self_serve_api`, and the what-if and push sources aren't allowed either.
5. **Leftover function.** `check_confidence_threshold(retrieval_scores)` remains, but no scored retrieval is left to produce those scores.
6. **Guardrails not designed.** Kill switch, circuit breaker, and dry-run are marked "Partial." For an automation layer, those are the most important guardrails.
7. **Unsourced facts.**
   1. APM coverage of nearly all appears with no source (Current State says strong tagging).
   2. Datadog is stated as the organization fact while everything else is hedged.

---

## 3. Things That Work Against the Intended Impression

1. **No code at all.** This is the biggest gap for an individual-contributor role. The Build Specification says "No implementation code is included by design." One small working slice would outweigh 10,000 words of spec, for example:
   1. FOCUS sample data
   2. A dbt model
   3. One anomaly model
   4. A `propose_action` Temporal workflow with an OPA policy
   5. A tiny MCP tool
2. **Edit history left in the text.** Phrases like "An earlier version of this document..." (14 times), "per explicit direction," "previously had no deployable," and "not merely reverted on request" read like a revision log. Move that history into superseded decision records.
3. **Length and style.** The set is about 51,000 words, with 933 em-dashes and 175 uses of "rather than." It is hard to skim, and many reviewers will read it as AI-generated prose. A 2-3 page architecture brief with diagrams in front, and the details behind it, would land much better.
4. **Missing items from the job description.**
   1. Event-driven design (even a sentence explaining why batch is right).
   2. A testing strategy.
   3. Kubernetes specifics such as autoscaling and container security hardening.

---

## 4. If Only Three Things Get Fixed

1. Build one small working slice with code.
2. Fix the billing-data details (which cost, per-period reloads, bill verification from invoices) and the ML problem framing.
3. Cut the stack down and add a Fabric vs. Snowflake decision with rough sizing and cost.
