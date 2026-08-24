"""Data update coordinator for the Terneo/Welrok integration."""
from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, ENERGY_SAVE_INTERVAL
from .thermostat import TerneoThermostat

_LOGGER = logging.getLogger(__name__)


class TerneoDataUpdateCoordinator(DataUpdateCoordinator[TerneoThermostat]):
    """Coordinate polling and persistent estimated-energy state."""

    def __init__(
        self,
        hass: HomeAssistant,
        thermostat: TerneoThermostat,
        *,
        entry_id: str,
        scan_interval: int,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"Terneo {thermostat.sn}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.thermostat = thermostat
        self._energy_store: Store[dict[str, Any]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.energy"
        )
        self._last_energy_save = 0.0

    async def async_restore_persistent_state(self) -> None:
        """Restore estimated energy/time counters from HA storage."""
        data = await self._energy_store.async_load()
        if not isinstance(data, dict):
            return
        try:
            self.thermostat.restore_energy_counters(
                energy_kwh=float(data.get("energy_kwh", 0.0)),
                heating_time_seconds=float(data.get("heating_time_seconds", 0.0)),
            )
        except (TypeError, ValueError):
            _LOGGER.warning("Ignoring invalid persisted Terneo energy state")

    async def async_save_persistent_state(self, *, force: bool = False) -> None:
        """Persist estimated energy/time counters at a bounded frequency."""
        now = time.monotonic()
        if not force and now - self._last_energy_save < ENERGY_SAVE_INTERVAL:
            return
        await self._energy_store.async_save(self.thermostat.energy_counter_state())
        self._last_energy_save = now

    async def _async_update_data(self) -> TerneoThermostat:
        """Fetch fresh thermostat data."""
        try:
            success = await self.hass.async_add_executor_job(self.thermostat.update)
        except Exception as err:
            raise UpdateFailed(f"Error communicating with Terneo API: {err}") from err

        if not success:
            raise UpdateFailed("Failed to update thermostat data")

        await self.async_save_persistent_state()
        return self.thermostat
