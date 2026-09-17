"""Tests for the MCP server: what each persona can call, and what it can see.

The point of these is that persona rules are enforced in code. A Vertical caller has no action tool
bound at all, and every read is filtered by vertical before it leaves the query layer.
"""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from temporalio.client import Client
from temporalio.service import RPCError
from temporalio.worker import Worker

from governed_automation.proposals import load_config
from governed_automation.run_demo import ACTIVITIES
from governed_automation.workflow import ProposeAction
from mcp_server import personas
from mcp_server.server import build_server

WORKPLACE = personas.vertical_persona("logistics")


async def tool_names(persona):
    return sorted(tool.name for tool in await build_server(persona).list_tools())


def payload(result):
    return json.loads(result.content[0].text)


async def test_the_platform_persona_gets_the_action_tool():
    assert "propose_action" in await tool_names(personas.PLATFORM)


async def test_a_vertical_persona_has_no_action_tool_bound():
    """Not 'the model was told not to': the tool does not exist for this caller."""
    names = await tool_names(WORKPLACE)
    assert "propose_action" not in names
    assert "get_cost_by_account" in names


async def test_a_vertical_cannot_read_another_verticals_account():
    server = build_server(WORKPLACE)
    with pytest.raises(ToolError, match="outside your verticals"):
        await server.call_tool("get_cost_by_account", {"account_id": "aws-111111111111"})


async def test_a_vertical_can_read_its_own_account():
    result = await build_server(WORKPLACE).call_tool("get_cost_by_account", {"account_id": "aws-222222222222"})
    body = payload(result)
    assert body["vertical_id"] == "logistics"
    assert body["cost_basis"].startswith("effective_cost")
    assert len(body["periods"]) == 3


def verticals_in(result):
    return {json.loads(item.text)["vertical_id"] for item in result.content}


async def test_anomalies_are_filtered_to_the_callers_verticals():
    platform = await build_server(personas.PLATFORM).call_tool("get_anomalies", {"limit": 50})
    vertical = await build_server(WORKPLACE).call_tool("get_anomalies", {"limit": 50})
    assert len(verticals_in(platform)) > 1
    assert verticals_in(vertical) == {"logistics"}


async def test_variance_is_filtered_to_the_callers_verticals():
    result = await build_server(WORKPLACE).call_tool("get_spend_variance", {"billing_period": "2026-06"})
    body = payload(result)
    assert {row["vertical_id"] for row in body["verticals"]} == {"logistics"}


async def test_a_metric_answer_carries_its_governed_definition():
    """Grounding: the number and the definition of the number come from the same catalog."""
    result = await build_server(WORKPLACE).call_tool("get_metric_definition", {"metric_name": "metric_ri_coverage"})
    body = payload(result)
    assert body["cost_basis"] == "effective_cost"
    assert "Committed" in body["definition"]


async def test_an_unknown_metric_names_the_ones_that_exist():
    with pytest.raises(ToolError, match="metric_total_spend"):
        await build_server(WORKPLACE).call_tool("get_metric_definition", {"metric_name": "metric_made_up"})


async def test_proposing_an_action_goes_through_the_governed_harness():
    """The tool can start a proposal; it cannot decide or execute anything itself."""
    config = load_config()
    try:
        client = await Client.connect(config["temporal_address"])
    except (RPCError, RuntimeError, OSError) as error:
        pytest.skip(f"Temporal dev server not reachable, run `docker compose up -d` ({error})")

    with ThreadPoolExecutor(max_workers=4) as pool:
        async with Worker(client, task_queue=config["task_queue"], workflows=[ProposeAction],
                          activities=ACTIVITIES, activity_executor=pool):
            result = await build_server(personas.PLATFORM).call_tool(
                "propose_action", {"resource_id": "aws-ec2-support-dev"})
    body = payload(result)
    assert body["risk_tier"] == "LOW"
    assert body["outcome"] == "executed"


async def test_proposing_an_action_outside_your_scope_is_refused():
    """Scope is checked even for a persona that does have the tool: binding is not a blank cheque."""
    scoped_operator = personas.Persona(name="platform-logistics", verticals=("logistics",), can_propose_actions=True)
    server = build_server(scoped_operator)
    with pytest.raises(ToolError, match="outside your verticals"):
        await server.call_tool("propose_action", {"resource_id": "gcp-gce-usage-sandbox"})


async def test_an_unknown_resource_is_reported_clearly():
    with pytest.raises(ToolError, match="not currently proposed"):
        await build_server(personas.PLATFORM).call_tool("propose_action", {"resource_id": f"made-up-{uuid.uuid4()}"})


async def test_the_server_starts_over_stdio_for_each_persona():
    """The entry point the README gives to MCP clients, exercised the way a client uses it."""
    import os

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def tools_over_stdio(env_extra):
        params = StdioServerParameters(command="uv", args=["run", "python", "-m", "mcp_server.server"],
                                       env={**os.environ, **env_extra})
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            return sorted(tool.name for tool in (await session.list_tools()).tools)

    assert "propose_action" in await tools_over_stdio({"FINOPS_PERSONA": "platform"})
    assert "propose_action" not in await tools_over_stdio(
        {"FINOPS_PERSONA": "vertical", "FINOPS_VERTICALS": "logistics"})
