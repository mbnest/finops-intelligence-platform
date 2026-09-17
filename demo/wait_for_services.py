"""Wait until Temporal and OPA are ready, or exit non-zero.

Checks what the tests actually need: a Temporal client that connects, and OPA answering a real
policy query. A plain port check passes before either service can serve a request.
"""

import asyncio
import json
import sys
import urllib.error
import urllib.request

from governed_automation.proposals import load_config

PROBE_INPUT = {"input": {
    "action": {"type": "stop", "snapshot_available": True},
    "target": {"resource_id": "probe", "apm_id": "APM-0000", "environment": "nonprod",
               "vertical_id": "none", "blast_radius": 1},
    "contract": {"status": "none", "tier_scope": "LOW", "execution_mode": "dry_run"},
    "controls": {"automation_enabled": True},
    "exclusions": [], "runs_last_24h": {"application": 0, "platform": 0},
    "caps": {"per_application": 10, "platform": 50},
}}


def opa_ready(url):
    request = urllib.request.Request(url, data=json.dumps(PROBE_INPUT).encode(),
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return "risk_tier" in json.load(response).get("result", {})
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return False


async def temporal_ready(address):
    from temporalio.client import Client

    try:
        await Client.connect(address)
        return True
    except Exception:
        return False


async def main(attempts=60, delay=2.0):
    config = load_config()
    for attempt in range(1, attempts + 1):
        opa = opa_ready(config["opa_decision_url"])
        temporal = await temporal_ready(config["temporal_address"])
        if opa and temporal:
            print("Temporal and OPA are ready")
            return 0
        if attempt % 5 == 0:
            print(f"waiting: opa={'up' if opa else 'down'} temporal={'up' if temporal else 'down'}")
        await asyncio.sleep(delay)
    print("Temporal or OPA did not become ready. Is `docker compose up -d` running?", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
