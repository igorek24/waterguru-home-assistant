"""Polling coordinator for WaterGuru."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import WaterGuruAuthError, WaterGuruClient, WaterGuruConnectionError
from .const import (
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
)
from .model import WaterGuruData, parse_dashboard

_LOGGER = logging.getLogger(__name__)


class WaterGuruCoordinator(DataUpdateCoordinator[WaterGuruData]):
    """Fetches the dashboard on a slow schedule."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: WaterGuruClient
    ) -> None:
        hours = entry.options.get(
            CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=hours),
            config_entry=entry,
        )
        self.client = client

    async def _async_update_data(self) -> WaterGuruData:
        try:
            payload = await self.client.async_get_dashboard()
        except WaterGuruAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except WaterGuruConnectionError as err:
            raise UpdateFailed(str(err)) from err

        data = parse_dashboard(payload)
        if not data.water_bodies:
            raise UpdateFailed("WaterGuru returned no water bodies")
        _LOGGER.debug(
            "Updated %d water body/bodies, %d pod(s)",
            len(data.water_bodies),
            sum(len(b.pods) for b in data.water_bodies.values()),
        )
        return data
