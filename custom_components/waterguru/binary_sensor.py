"""WaterGuru binary sensors: water problem, cassette/battery low."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import WaterGuruConfigEntry
from .entity import WaterGuruPodEntity, WaterGuruWaterBodyEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WaterGuruConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = []
    for body_id, body in coordinator.data.water_bodies.items():
        entities.append(WaterGuruProblemSensor(coordinator, body_id))
        for pod_id, pod in body.pods.items():
            for key in pod.refillables:
                entities.append(
                    WaterGuruRefillNeededSensor(coordinator, body_id, pod_id, key)
                )
    async_add_entities(entities)


class WaterGuruProblemSensor(WaterGuruWaterBodyEntity, BinarySensorEntity):
    """On when WaterGuru reports anything other than a green status."""

    _attr_name = "Water problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator, body_id: str) -> None:
        super().__init__(coordinator, body_id)
        self._attr_unique_id = f"{body_id}_problem"

    @property
    def is_on(self) -> bool | None:
        body = self.body
        return body.has_problem if body else None

    @property
    def extra_state_attributes(self) -> dict:
        body = self.body
        if not body:
            return {}
        return {
            "status": body.status,
            "alerts": body.alerts,
            "advice": body.advice,
        }


class WaterGuruRefillNeededSensor(WaterGuruPodEntity, BinarySensorEntity):
    """On when the cassette or battery needs attention."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator, body_id: str, pod_id: str, key: str) -> None:
        super().__init__(coordinator, body_id, pod_id)
        self._key = key
        self._attr_unique_id = f"pod_{pod_id}_{key}_low"
        self._attr_name = "Cassette low" if key == "cassette" else "Battery low"

    @property
    def _refillable(self):
        pod = self.pod
        return pod.refillables.get(self._key) if pod else None

    @property
    def available(self) -> bool:
        return super().available and self._refillable is not None

    @property
    def is_on(self) -> bool | None:
        refillable = self._refillable
        if not refillable:
            return None
        if refillable.urgent:
            return True
        return (refillable.status or "").upper() in ("YELLOW", "ORANGE", "RED")

    @property
    def extra_state_attributes(self) -> dict:
        refillable = self._refillable
        if not refillable:
            return {}
        return {
            "percent_left": refillable.pct_left,
            "time_left": refillable.time_left_text,
            "status": refillable.status,
        }
