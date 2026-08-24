"""Button platform for Terneo/Welrok thermostat."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .thermostat import TerneoThermostat
from .helpers import async_execute_command, build_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Terneo button entities from a config entry."""
    coordinator = entry.runtime_data
    thermostat = coordinator.thermostat

    async_add_entities([TerneoRestartButton(coordinator, thermostat, entry)])


class TerneoRestartButton(CoordinatorEntity, ButtonEntity):
    """Terneo restart button entity."""

    _attr_has_entity_name = True
    _attr_name = "Restart"
    _attr_icon = "mdi:restart"
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator,
        thermostat: TerneoThermostat,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator)
        self._thermostat = thermostat
        self._entry = entry
        
        self._attr_unique_id = f"{thermostat.sn}_restart"
        self._attr_device_info = build_device_info(thermostat, entry)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._thermostat.available

    async def async_press(self) -> None:
        """Handle the button press."""
        await async_execute_command(
            self.hass, self._thermostat.restart, action="restart the thermostat"
        )
