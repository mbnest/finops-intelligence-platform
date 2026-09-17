"""MCP server exposing the platform's tools (Build Specification §5).

Which tools exist depends on who is asking. A Vertical caller gets read tools over its own data and
never sees `propose_action`: the tool is not bound for that persona, so there is no instruction for a
model to talk its way past (Cloud Workbench ADR-007).

Run it as the agent's tool server:

    FINOPS_PERSONA=platform uv run python -m mcp_server.server
    FINOPS_PERSONA=vertical FINOPS_VERTICALS=workplace uv run python -m mcp_server.server
"""

import functools
import inspect
import uuid

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from mcp_server import personas, queries

INSTRUCTIONS = """Cost and usage tools for the FinOps platform.

Answer from these tools only, and cite the metric definition when a number comes from a metric.
All spend is amortized (effective cost) unless a tool says otherwise."""


def guarded(fn):
    """Turn a refusal or a missing object into a ToolError, so the caller is told why.

    Anything else is a real failure and keeps its traceback on the server side.
    """
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except (PermissionError, KeyError) as error:
                raise ToolError(str(error).strip("'")) from error
        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (PermissionError, KeyError) as error:
            raise ToolError(str(error).strip("'")) from error
    return wrapper


def build_server(persona=None):
    """Build a server whose tools match the persona. The binding is the enforcement."""
    persona = persona or personas.from_environment()
    server = MCPServer(name=f"finops-{persona.name}", version="0.1.0", instructions=INSTRUCTIONS)

    @server.tool(description="The governed definition of a metric: how it is computed, its grain, and cost basis.")
    @guarded
    def get_metric_definition(metric_name: str) -> dict:
        return queries.metric_definition(metric_name)

    @server.tool(description="Spend for one account by billing period, on the amortized cost basis.")
    @guarded
    def get_cost_by_account(account_id: str, billing_period: str | None = None) -> dict:
        return queries.cost_by_account(persona, account_id, billing_period)

    @server.tool(description="Cost anomalies detected by Core Intelligence, with the evidence behind each one.")
    @guarded
    def get_anomalies(limit: int = 20) -> list:
        return queries.anomalies(persona, limit)

    @server.tool(description="Why spend changed in a billing period, split into new resources, removed "
                             "resources, usage change, price change, and charges with no resource.")
    @guarded
    def get_spend_variance(billing_period: str) -> dict:
        return queries.spend_variance(persona, billing_period)

    if persona.can_propose_actions:
        @server.tool(description="Propose an action on an idle resource. The action is classified and "
                                 "governed before anything runs; it may execute, wait for approval, or "
                                 "stay advisory.")
        @guarded
        async def propose_action(resource_id: str) -> dict:
            return await _propose(persona, resource_id)

    return server


async def _propose(persona, resource_id):
    """Hand the proposal to Governed Automation and report what the harness decided.

    The tool cannot execute anything itself: it starts the workflow and reports the outcome.
    """
    from temporalio.client import Client

    from governed_automation.proposals import load_config
    from governed_automation.workflow import ProposeAction

    config = load_config()
    proposal = queries.idle_resource(persona, resource_id)
    proposal["origin"] = "cloud_workbench"
    proposal["timers"] = {"opt_out_window_seconds": config["opt_out_window_seconds"],
                          "approval_timeout_seconds": config["approval_timeout_seconds"]}
    client = await Client.connect(config["temporal_address"])
    handle = await client.start_workflow(
        ProposeAction.run, proposal, id=f"{proposal['proposal_id']}-{uuid.uuid4().hex[:8]}",
        task_queue=config["task_queue"])
    return await handle.result()


def main():
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
