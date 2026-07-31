"""Parsing of the WaterGuru dashboard payload into flat structures."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

# measurement type -> (key, unit fallback)
MEASUREMENT_TYPES = {
    "FREE_CL": "free_chlorine",
    "PH": "ph",
    "SKIMMER_FLOW": "skimmer_flow",
    "TA": "total_alkalinity",
    "CH": "calcium_hardness",
    "CYA": "cyanuric_acid",
    "SALT": "salt",
}

REFILLABLE_TYPES = {"LAB": "cassette", "BATT": "battery"}

STATUS_ORDER = {"GREEN": 0, "BLUE": 0, "YELLOW": 1, "ORANGE": 2, "RED": 3}


def _parse_time(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


@dataclass
class Measurement:
    key: str
    type: str
    title: str
    value: float | None
    unit: str | None
    status: str | None
    target: float | None
    ranges: dict[str, Any] = field(default_factory=dict)
    alert: str | None = None
    advice: str | None = None


@dataclass
class Refillable:
    key: str
    label: str
    status: str | None
    pct_left: float | None
    amount_left: float | None
    max_amount: float | None
    unit: str | None
    time_left_text: str | None
    urgent: bool = False


@dataclass
class Pod:
    pod_id: str
    name: str
    water_body_id: str
    product: str | None = None
    firmware: str | None = None
    last_connection: dt.datetime | None = None
    rssi: int | None = None
    rssi_desc: str | None = None
    refillables: dict[str, Refillable] = field(default_factory=dict)


@dataclass
class WaterBody:
    water_body_id: str
    name: str
    status: str | None = None
    water_temp: float | None = None
    size_gallons: float | None = None
    body_type: str | None = None
    last_measure_time: dt.datetime | None = None
    last_measure_human: str | None = None
    measurements: dict[str, Measurement] = field(default_factory=dict)
    alerts: list[str] = field(default_factory=list)
    advice: list[str] = field(default_factory=list)
    pods: dict[str, Pod] = field(default_factory=dict)

    @property
    def has_problem(self) -> bool:
        return STATUS_ORDER.get((self.status or "").upper(), 0) > 0


@dataclass
class WaterGuruData:
    water_bodies: dict[str, WaterBody] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def _parse_measurement(item: dict[str, Any]) -> Measurement | None:
    m_type = item.get("type")
    if not m_type:
        return None
    cfg = item.get("cfg") or {}
    value = item.get("floatValue")
    if value is None:
        value = item.get("intValue")
    if value is None:
        value = _number(item.get("value"))
    alerts = item.get("alerts") or []
    alert_text = alerts[0].get("text") if alerts else None
    advice = None
    if alerts:
        action = (alerts[0].get("advice") or {}).get("action") or {}
        advice = action.get("summary")
    return Measurement(
        key=MEASUREMENT_TYPES.get(m_type, m_type.lower()),
        type=m_type,
        title=item.get("title") or cfg.get("longLabel") or m_type,
        value=_number(value),
        unit=cfg.get("unit"),
        status=item.get("status"),
        target=_number(cfg.get("target") or cfg.get("defaultTarget")),
        ranges=cfg.get("floatRanges") or cfg.get("intRanges") or {},
        alert=alert_text,
        advice=advice,
    )


def _parse_refillable(item: dict[str, Any]) -> Refillable | None:
    r_type = item.get("type")
    if not r_type:
        return None
    return Refillable(
        key=REFILLABLE_TYPES.get(r_type, r_type.lower()),
        label=item.get("label") or r_type.title(),
        status=item.get("status"),
        pct_left=_number(item.get("pctLeft")),
        amount_left=_number(item.get("amountLeft")),
        max_amount=_number(item.get("maxAmount")),
        unit=item.get("unit"),
        time_left_text=item.get("timeLeftText"),
        urgent=bool(item.get("urgent")),
    )


def _parse_pod(entry: dict[str, Any], water_body_id: str, body_name: str) -> Pod | None:
    pod_info = entry.get("pod") or {}
    pod_id = entry.get("podId") or pod_info.get("podId")
    if pod_id is None:
        return None
    rssi_info = entry.get("rssiInfo") or {}
    product = pod_info.get("product")
    pod = Pod(
        pod_id=str(pod_id),
        name=f"{body_name} {product.title()}" if product else f"Pod {pod_id}",
        water_body_id=water_body_id,
        product=product,
        firmware=pod_info.get("fwUpdateVersion"),
        last_connection=_parse_time(pod_info.get("lastCxnTime")),
        rssi=rssi_info.get("rssi"),
        rssi_desc=rssi_info.get("desc"),
    )
    for item in entry.get("refillables") or []:
        refillable = _parse_refillable(item)
        if refillable:
            pod.refillables[refillable.key] = refillable
    return pod


def parse_dashboard(payload: dict[str, Any]) -> WaterGuruData:
    """Turn the raw dashboard response into WaterBody/Pod objects."""
    data = WaterGuruData(raw=payload)
    bodies = payload.get("waterBodies")
    if bodies is None and payload.get("viewType") == "WaterBodyView":
        bodies = [payload]  # single-body response
    for view in bodies or []:
        body_id = view.get("waterBodyId")
        if not body_id:
            continue
        info = view.get("waterBody") or {}
        body = WaterBody(
            water_body_id=body_id,
            name=view.get("name") or info.get("label") or "Pool",
            status=view.get("status"),
            water_temp=_number(view.get("waterTemp")),
            size_gallons=_number(info.get("sizeGallons")),
            body_type=info.get("type"),
            last_measure_time=_parse_time(view.get("latestMeasureTime")),
            last_measure_human=view.get("latestMeasureTimeHuman"),
        )
        for item in view.get("measurements") or []:
            measurement = _parse_measurement(item)
            if measurement:
                body.measurements[measurement.key] = measurement
        for alert in view.get("alerts") or []:
            if text := alert.get("text"):
                body.alerts.append(text)
            summary = ((alert.get("advice") or {}).get("action") or {}).get("summary")
            if summary:
                body.advice.append(summary)
        for entry in view.get("pods") or []:
            pod = _parse_pod(entry, body_id, body.name)
            if pod:
                body.pods[pod.pod_id] = pod
        data.water_bodies[body_id] = body
    return data
