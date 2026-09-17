# FinOps Platform Demo Slice

A small, runnable slice of the architecture in [`docs/`](../docs). It is not a small version of the whole platform. Each piece exists to prove one design claim in working code:

1. **The cost data model is right**: FOCUS data with four cost columns that really differ, and restated billing periods replaced, not duplicated.
2. **The anomaly detector is judged against ground truth**, not just claimed to work.
3. **Governed automation separates workflow from policy**: Temporal runs the workflow, OPA decides the risk tier.
4. **MCP tools enforce who can do what in code**, not in a prompt.

Build progress, decisions, and data rules are in [PLAN.md](PLAN.md).

## What stands in for what

| In the design | In this demo |
|---|---|
| Snowflake, Iceberg tables, Snowflake Tasks | DuckDB, with dbt run by hand or in CI |
| Snowflake Semantic Views | dbt metric models plus a YAML metric catalog |
| Snowpark ML batch scoring | Python scoring against DuckDB |
| Provider billing exports | FOCUS files generated from a declarative spec (`data_generator/spec.yaml`) |
| IDP, CMP, Terraform execution | A fake executor that writes an audit row |
| Cloud Workbench agent | Any MCP client |

The dbt models and Python are the parts the design treats as portable (Data Foundations ADR-003). Everything Snowflake-specific is a stand-in.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/).

```bash
cd demo
uv sync
uv run python -m data_generator.generate
uv run dbt build --project-dir dbt --profiles-dir dbt
```

Later steps add commands here as they land.
