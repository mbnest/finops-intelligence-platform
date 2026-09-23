"""Standalone Temporal worker, run once alongside the MCP server (Build Specification §6).

`run_demo.py` bundles a worker with the proposals it drives through in one process. A real MCP
client instead calls `propose_action` whenever an operator asks, so something needs to already be
polling the task queue before that happens:

    uv run python -m governed_automation.worker
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from governed_automation import storage
from governed_automation.proposals import load_config
from governed_automation.run_demo import ACTIVITIES
from governed_automation.workflow import ProposeAction


async def main():
    config = load_config()
    storage.connection()  # create the control, exclusion, and audit tables before the worker starts
    client = await Client.connect(config["temporal_address"])
    print(f"worker ready on task queue {config['task_queue']}")
    with ThreadPoolExecutor(max_workers=8) as pool:
        async with Worker(client, task_queue=config["task_queue"], workflows=[ProposeAction],
                          activities=ACTIVITIES, activity_executor=pool):
            await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
