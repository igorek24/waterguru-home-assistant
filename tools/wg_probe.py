#!/usr/bin/env python3
"""Probe a WaterGuru account from the command line.

    python3 tools/wg_probe.py you@example.com 'password' [--raw]

Prints what the integration would create, without Home Assistant.
Requires: aiohttp, pycognito (both ship with Home Assistant).
"""

import argparse
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "custom_components" / "waterguru"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"wg_{name}", COMP / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


api = _load("api")
model = _load("model")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("email")
    parser.add_argument("password")
    parser.add_argument("--raw", action="store_true", help="dump the raw payload")
    args = parser.parse_args()

    import aiohttp

    async with aiohttp.ClientSession() as session:
        client = api.WaterGuruClient(session, args.email, args.password)
        try:
            user_id = await client.async_validate()
        except api.WaterGuruAuthError as err:
            print(f"AUTH FAILED: {err}")
            return 1
        except api.WaterGuruConnectionError as err:
            print(f"CONNECTION FAILED: {err}")
            return 2
        print(f"authenticated, userId={user_id}")

        payload = await client.async_get_dashboard()
        if args.raw:
            print(json.dumps(payload, indent=2)[:20000])
            return 0

        data = model.parse_dashboard(payload)
        print(f"top-level keys: {sorted(payload)[:8]}")
        print(f"{len(data.water_bodies)} water body/bodies\n")
        for body in data.water_bodies.values():
            print(f"== {body.name} [{body.status}] temp={body.water_temp}")
            print(f"   last measurement: {body.last_measure_time} ({body.last_measure_human})")
            for m in body.measurements.values():
                print(f"   {m.title:18s} {m.value} {m.unit or ''} [{m.status}] target={m.target}")
            for alert in body.alerts:
                print(f"   ALERT: {alert}")
            for advice in body.advice:
                print(f"   ADVICE: {advice}")
            for pod in body.pods.values():
                print(f"   -- pod {pod.pod_id} {pod.product} fw={pod.firmware} rssi={pod.rssi}")
                for r in pod.refillables.values():
                    print(f"      {r.label:10s} {r.pct_left}% ({r.amount_left}/{r.max_amount} {r.unit}) {r.time_left_text}")
        # second call exercises the token/credential cache
        await client.async_get_dashboard()
        print("\nsecond fetch OK (credential caching works)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
