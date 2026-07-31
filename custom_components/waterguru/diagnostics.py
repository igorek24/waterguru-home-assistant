"""Diagnostics for WaterGuru."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import WaterGuruConfigEntry

TO_REDACT = {
    CONF_EMAIL,
    CONF_PASSWORD,
    "userId",
    "user_id",
    "ipAddr",
    "wifiId",
    "bleId",
    "shortBleId",
    "url",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: WaterGuruConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "summary": {
            "water_bodies": [
                {
                    "name": body.name,
                    "status": body.status,
                    "water_temp": body.water_temp,
                    "measurements": {
                        key: {"value": m.value, "unit": m.unit, "status": m.status}
                        for key, m in body.measurements.items()
                    },
                    "pods": [
                        {
                            "product": pod.product,
                            "firmware": pod.firmware,
                            "rssi": pod.rssi,
                            "refillables": {
                                key: r.pct_left for key, r in pod.refillables.items()
                            },
                        }
                        for pod in body.pods.values()
                    ],
                }
                for body in data.water_bodies.values()
            ]
        },
        "raw": async_redact_data(data.raw, TO_REDACT),
    }
