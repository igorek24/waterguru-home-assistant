"""Base entities for WaterGuru."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import WaterGuruCoordinator
from .model import Pod, WaterBody


class WaterGuruWaterBodyEntity(CoordinatorEntity[WaterGuruCoordinator]):
    """Entity attached to a body of water (the pool itself)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WaterGuruCoordinator, body_id: str) -> None:
        super().__init__(coordinator)
        self._body_id = body_id

    @property
    def body(self) -> WaterBody | None:
        return self.coordinator.data.water_bodies.get(self._body_id)

    @property
    def available(self) -> bool:
        return super().available and self.body is not None

    @property
    def device_info(self) -> DeviceInfo:
        body = self.body
        return DeviceInfo(
            identifiers={(DOMAIN, self._body_id)},
            name=body.name if body else "Pool",
            manufacturer=MANUFACTURER,
            model=(body.body_type or "Water body").replace("_", " ").title()
            if body
            else "Water body",
        )


class WaterGuruPodEntity(CoordinatorEntity[WaterGuruCoordinator]):
    """Entity attached to a physical WaterGuru pod."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: WaterGuruCoordinator, body_id: str, pod_id: str
    ) -> None:
        super().__init__(coordinator)
        self._body_id = body_id
        self._pod_id = pod_id

    @property
    def pod(self) -> Pod | None:
        body = self.coordinator.data.water_bodies.get(self._body_id)
        return body.pods.get(self._pod_id) if body else None

    @property
    def available(self) -> bool:
        return super().available and self.pod is not None

    @property
    def device_info(self) -> DeviceInfo:
        pod = self.pod
        return DeviceInfo(
            identifiers={(DOMAIN, f"pod_{self._pod_id}")},
            via_device=(DOMAIN, self._body_id),
            name=pod.name if pod else f"Pod {self._pod_id}",
            manufacturer=MANUFACTURER,
            model=(pod.product or "Pod").title() if pod else "Pod",
            sw_version=pod.firmware if pod else None,
            serial_number=self._pod_id,
        )
