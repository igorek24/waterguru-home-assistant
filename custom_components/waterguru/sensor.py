"""WaterGuru sensors: water chemistry, cassette, battery, signal."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfElectricPotential,
    UnitOfTemperature,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import WaterGuruConfigEntry
from .const import CONF_TEMPERATURE_UNIT, TEMP_AUTO, TEMP_C, TEMP_F
from .entity import WaterGuruPodEntity, WaterGuruWaterBodyEntity

# Pool water is never 45 °C, so a reading that high has to be Fahrenheit.
FAHRENHEIT_THRESHOLD = 45

MEASUREMENT_ICONS = {
    "free_chlorine": "mdi:test-tube",
    "ph": "mdi:ph",
    "skimmer_flow": "mdi:waves-arrow-right",
    "total_alkalinity": "mdi:beaker-outline",
    "calcium_hardness": "mdi:water-opacity",
    "cyanuric_acid": "mdi:shield-sun-outline",
    "salt": "mdi:shaker-outline",
}

FLOW_UNITS = {"gpm": UnitOfVolumeFlowRate.GALLONS_PER_MINUTE}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WaterGuruConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = []

    for body_id, body in coordinator.data.water_bodies.items():
        entities.append(WaterGuruTemperatureSensor(coordinator, body_id, entry))
        entities.append(WaterGuruLastMeasureSensor(coordinator, body_id))
        entities.append(WaterGuruStatusSensor(coordinator, body_id))
        for key in body.measurements:
            entities.append(WaterGuruMeasurementSensor(coordinator, body_id, key))
        for pod_id, pod in body.pods.items():
            for key in pod.refillables:
                entities.append(
                    WaterGuruRefillableSensor(coordinator, body_id, pod_id, key)
                )
            entities.append(WaterGuruRssiSensor(coordinator, body_id, pod_id))
            entities.append(WaterGuruLastConnectionSensor(coordinator, body_id, pod_id))

    async_add_entities(entities)


class WaterGuruMeasurementSensor(WaterGuruWaterBodyEntity, SensorEntity):
    """A water chemistry reading (free chlorine, pH, flow, ...)."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, body_id: str, key: str) -> None:
        super().__init__(coordinator, body_id)
        self._key = key
        self._attr_unique_id = f"{body_id}_{key}"
        measurement = self._measurement
        self._attr_name = measurement.title if measurement else key.replace("_", " ")
        self._attr_icon = MEASUREMENT_ICONS.get(key)
        if key == "ph":
            self._attr_device_class = SensorDeviceClass.PH
        unit = measurement.unit if measurement else None
        if unit:
            self._attr_native_unit_of_measurement = FLOW_UNITS.get(unit, unit)
        self._attr_suggested_display_precision = 0 if key == "skimmer_flow" else 1

    @property
    def _measurement(self):
        body = self.body
        return body.measurements.get(self._key) if body else None

    @property
    def available(self) -> bool:
        return super().available and self._measurement is not None

    @property
    def native_value(self) -> float | None:
        measurement = self._measurement
        return measurement.value if measurement else None

    @property
    def extra_state_attributes(self) -> dict:
        measurement = self._measurement
        if not measurement:
            return {}
        attrs = {
            "status": measurement.status,
            "target": measurement.target,
        }
        if measurement.alert:
            attrs["alert"] = measurement.alert
        if measurement.advice:
            attrs["advice"] = measurement.advice
        if measurement.ranges:
            attrs["good_min"] = measurement.ranges.get("GREEN_MIN")
            attrs["good_max"] = measurement.ranges.get("GREEN_MAX")
        return attrs


class WaterGuruTemperatureSensor(WaterGuruWaterBodyEntity, SensorEntity):
    _attr_name = "Water temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, body_id: str, entry) -> None:
        super().__init__(coordinator, body_id)
        self._attr_unique_id = f"{body_id}_water_temp"
        self._configured_unit = entry.options.get(CONF_TEMPERATURE_UNIT, TEMP_AUTO)

    @property
    def native_value(self) -> float | None:
        body = self.body
        return body.water_temp if body else None

    @property
    def native_unit_of_measurement(self) -> str:
        if self._configured_unit == TEMP_C:
            return UnitOfTemperature.CELSIUS
        if self._configured_unit == TEMP_F:
            return UnitOfTemperature.FAHRENHEIT
        value = self.native_value
        if value is not None and value >= FAHRENHEIT_THRESHOLD:
            return UnitOfTemperature.FAHRENHEIT
        return UnitOfTemperature.CELSIUS


class WaterGuruStatusSensor(WaterGuruWaterBodyEntity, SensorEntity):
    _attr_name = "Status"
    _attr_icon = "mdi:pool"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["GREEN", "YELLOW", "ORANGE", "RED", "BLUE"]

    def __init__(self, coordinator, body_id: str) -> None:
        super().__init__(coordinator, body_id)
        self._attr_unique_id = f"{body_id}_status"

    @property
    def native_value(self) -> str | None:
        body = self.body
        if not body or not body.status:
            return None
        status = body.status.upper()
        return status if status in self._attr_options else None

    @property
    def extra_state_attributes(self) -> dict:
        body = self.body
        if not body:
            return {}
        return {
            "alerts": body.alerts,
            "advice": body.advice,
            "size_gallons": body.size_gallons,
            "last_measurement": body.last_measure_human,
        }


class WaterGuruLastMeasureSensor(WaterGuruWaterBodyEntity, SensorEntity):
    _attr_name = "Last measurement"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, coordinator, body_id: str) -> None:
        super().__init__(coordinator, body_id)
        self._attr_unique_id = f"{body_id}_last_measurement"

    @property
    def native_value(self):
        body = self.body
        return body.last_measure_time if body else None


class WaterGuruRefillableSensor(WaterGuruPodEntity, SensorEntity):
    """Cassette or battery level."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator, body_id: str, pod_id: str, key: str) -> None:
        super().__init__(coordinator, body_id, pod_id)
        self._key = key
        self._attr_unique_id = f"pod_{pod_id}_{key}"
        self._attr_name = "Cassette" if key == "cassette" else "Battery"
        if key == "battery":
            self._attr_device_class = SensorDeviceClass.BATTERY
        else:
            self._attr_icon = "mdi:cassette"

    @property
    def _refillable(self):
        pod = self.pod
        return pod.refillables.get(self._key) if pod else None

    @property
    def available(self) -> bool:
        return super().available and self._refillable is not None

    @property
    def native_value(self) -> float | None:
        refillable = self._refillable
        return refillable.pct_left if refillable else None

    @property
    def extra_state_attributes(self) -> dict:
        refillable = self._refillable
        if not refillable:
            return {}
        attrs = {
            "status": refillable.status,
            "time_left": refillable.time_left_text,
            "urgent": refillable.urgent,
        }
        if refillable.unit == "pad":
            attrs["measurements_left"] = refillable.amount_left
            attrs["measurements_total"] = refillable.max_amount
        elif refillable.unit == "volt":
            attrs["voltage"] = refillable.amount_left
            attrs["voltage_full"] = refillable.max_amount
        return attrs


class WaterGuruRssiSensor(WaterGuruPodEntity, SensorEntity):
    _attr_name = "Wi-Fi signal"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, body_id: str, pod_id: str) -> None:
        super().__init__(coordinator, body_id, pod_id)
        self._attr_unique_id = f"pod_{pod_id}_rssi"

    @property
    def native_value(self) -> int | None:
        pod = self.pod
        return pod.rssi if pod else None

    @property
    def extra_state_attributes(self) -> dict:
        pod = self.pod
        return {"quality": pod.rssi_desc} if pod else {}


class WaterGuruLastConnectionSensor(WaterGuruPodEntity, SensorEntity):
    _attr_name = "Last connection"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:wifi-check"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, body_id: str, pod_id: str) -> None:
        super().__init__(coordinator, body_id, pod_id)
        self._attr_unique_id = f"pod_{pod_id}_last_connection"

    @property
    def native_value(self):
        pod = self.pod
        return pod.last_connection if pod else None
