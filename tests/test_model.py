"""Parser tests against a real WaterGuru dashboard payload.

The fixture is the sample payload published by the homebridge-waterguru
project (JSON5-ish: unquoted keys), normalised on load.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "wg_model", ROOT / "custom_components" / "waterguru" / "model.py"
)
model = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = model
_spec.loader.exec_module(model)


def _load_fixture() -> dict:
    raw = (ROOT / "tests" / "sample_waterbody.json5").read_text()
    raw = re.sub(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*):", r'\1"\2":', raw, flags=re.M)
    raw = re.sub(r",(\s*[}\]])", r"\1", raw)
    return json.loads(raw)


FIXTURE = _load_fixture()


def test_parses_single_water_body():
    data = model.parse_dashboard(FIXTURE)
    assert len(data.water_bodies) == 1
    body = next(iter(data.water_bodies.values()))
    assert body.name == "Koehl Pool"
    assert body.water_temp == 84
    assert body.status == "YELLOW"
    assert body.size_gallons == 22400
    assert body.last_measure_time is not None
    assert body.last_measure_human == "1 hour ago"


def test_parses_wrapped_dashboard():
    data = model.parse_dashboard({"waterBodies": [FIXTURE]})
    assert len(data.water_bodies) == 1


def test_measurements():
    body = next(iter(model.parse_dashboard(FIXTURE).water_bodies.values()))
    assert set(body.measurements) >= {"free_chlorine", "ph", "skimmer_flow"}

    fc = body.measurements["free_chlorine"]
    assert fc.value == 4.5 and fc.unit == "ppm" and fc.status == "GREEN"
    assert fc.target == 3.0
    assert fc.ranges["GREEN_MIN"] == 1.6

    ph = body.measurements["ph"]
    assert ph.value == 7.7 and ph.status == "YELLOW"
    assert ph.alert == "pH high"
    assert "dry acid" in ph.advice

    flow = body.measurements["skimmer_flow"]
    assert flow.value == 6 and flow.unit == "gpm"


def test_alerts_and_problem_flag():
    body = next(iter(model.parse_dashboard(FIXTURE).water_bodies.values()))
    assert body.alerts == ["pH high"]
    assert body.advice and "dry acid" in body.advice[0]
    assert body.has_problem is True


def test_pod_and_refillables():
    body = next(iter(model.parse_dashboard(FIXTURE).water_bodies.values()))
    assert len(body.pods) == 1
    pod = next(iter(body.pods.values()))
    assert pod.pod_id == "114682"
    assert pod.product == "SENSE"
    assert pod.firmware == "v11.1.3-0-g52795ae"
    assert pod.rssi == -71 and pod.rssi_desc == "Fair"
    assert pod.last_connection is not None

    cassette = pod.refillables["cassette"]
    assert cassette.pct_left == 81
    assert cassette.amount_left == 138 and cassette.max_amount == 171
    assert cassette.unit == "pad" and cassette.urgent is False
    assert cassette.time_left_text == "7 weeks left"

    battery = pod.refillables["battery"]
    assert battery.pct_left == 92 and battery.unit == "volt"
    assert battery.amount_left == 5.97


def test_multiple_water_bodies():
    second = json.loads(json.dumps(FIXTURE))
    second["waterBodyId"] = "second-body"
    second["name"] = "Spa"
    second["status"] = "GREEN"
    second["alerts"] = []
    data = model.parse_dashboard({"waterBodies": [FIXTURE, second]})
    assert len(data.water_bodies) == 2
    spa = data.water_bodies["second-body"]
    assert spa.name == "Spa" and spa.has_problem is False


def test_handles_empty_and_partial_payloads():
    assert model.parse_dashboard({}).water_bodies == {}
    assert model.parse_dashboard({"waterBodies": []}).water_bodies == {}
    partial = {"waterBodies": [{"waterBodyId": "x", "name": "Bare"}]}
    body = model.parse_dashboard(partial).water_bodies["x"]
    assert body.measurements == {} and body.pods == {} and body.water_temp is None


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as err:
                failures += 1
                print(f"FAIL {name}: {err}")
    raise SystemExit(1 if failures else 0)
