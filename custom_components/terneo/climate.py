"""Climate platform for Terneo/Welrok thermostat."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, ControlType, OperationMode, ParamNum
from .thermostat import TerneoThermostat
from .helpers import async_execute_command, build_device_info

_LOGGER = logging.getLogger(__name__)

SUPPORT_FLAGS = (
    ClimateEntityFeature.TARGET_TEMPERATURE
    | ClimateEntityFeature.TURN_ON
    | ClimateEntityFeature.TURN_OFF
    | ClimateEntityFeature.PRESET_MODE
)

HVAC_MODES = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.AUTO]

PRESET_SCHEDULE = "schedule"
PRESET_MANUAL = "manual"
PRESET_MODES = [PRESET_SCHEDULE, PRESET_MANUAL]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Terneo climate entity from a config entry."""
    coordinator = entry.runtime_data
    thermostat = coordinator.thermostat

    async_add_entities([TerneoClimateEntity(coordinator, thermostat, entry)])


class TerneoClimateEntity(CoordinatorEntity, ClimateEntity):
    """Terneo climate entity."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = SUPPORT_FLAGS
    _attr_hvac_modes = HVAC_MODES
    _attr_preset_modes = PRESET_MODES

    def __init__(
        self,
        coordinator,
        thermostat: TerneoThermostat,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator)
        self._thermostat = thermostat
        self._entry = entry
        
        self._attr_unique_id = f"{thermostat.sn}_climate"
        self._attr_device_info = build_device_info(thermostat, entry)
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.AUTO]
        if thermostat.supports_parameter(ParamNum.COOLING_CONTROL_WAY):
            self._attr_hvac_modes.insert(2, HVACMode.COOL)

    @property
    def target_temperature_step(self) -> float:
        """Return the target temperature step reported by telemetry when available."""
        if self._thermostat.setpoint_step is not None:
            return self._thermostat.setpoint_step
        return 0.1 if self._thermostat.is_new_version else 1.0

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        # Return air temperature for new version if control type is air
        control_type = self._thermostat.control_type
        if (
            control_type in [ControlType.AIR, ControlType.AIR_WITH_FLOOR_LIMIT]
            and self._thermostat.air_temperature is not None
        ):
            return self._thermostat.air_temperature
        return self._thermostat.floor_temperature

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        return self._thermostat.setpoint

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature."""
        control_type = self._thermostat.control_type or ControlType.FLOOR
        
        if self._thermostat.is_new_version and control_type != ControlType.FLOOR:
            limit = self._thermostat.lower_air_limit
            return float(limit) if limit is not None else 5.0
        
        limit = self._thermostat.lower_limit
        return float(limit) if limit is not None else 5.0

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature."""
        control_type = self._thermostat.control_type or ControlType.FLOOR
        
        if self._thermostat.is_new_version and control_type != ControlType.FLOOR:
            limit = self._thermostat.upper_air_limit
            return float(limit) if limit is not None else 35.0
        
        limit = self._thermostat.upper_limit
        return float(limit) if limit is not None else 45.0

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        mode = self._thermostat.mode
        
        if mode == -1 or not self._thermostat.power_on:
            return HVACMode.OFF
        
        # Schedule mode takes precedence over the heating/cooling direction flag.
        if mode == OperationMode.SCHEDULE:
            return HVACMode.AUTO

        if self._thermostat.cooling_mode:
            return HVACMode.COOL

        return HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction:
        """Return current HVAC action."""
        if not self._thermostat.power_on or self._thermostat.mode == -1:
            return HVACAction.OFF
        
        if self._thermostat.relay_state:
            if self._thermostat.cooling_mode:
                return HVACAction.COOLING
            return HVACAction.HEATING
        
        return HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        """Return current preset mode."""
        mode = self._thermostat.mode
        
        if mode == OperationMode.SCHEDULE:
            return PRESET_SCHEDULE
        return PRESET_MANUAL

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs = {
            "serial_number": self._thermostat.sn,
            "device_type": "new" if self._thermostat.is_new_version else "old",
            "control_type": self._get_control_type_name(),
            "relay_state": self._thermostat.relay_state,
            "floor_temperature": self._thermostat.floor_temperature,
        }
        
        if self._thermostat.is_new_version:
            attrs["air_temperature"] = self._thermostat.air_temperature
        
        if self._thermostat.hysteresis is not None:
            attrs["hysteresis"] = self._thermostat.hysteresis
        
        if self._thermostat.power_watts is not None:
            attrs["power_watts"] = self._thermostat.power_watts
        
        return attrs

    def _get_control_type_name(self) -> str:
        """Get human-readable control type name."""
        control_type = self._thermostat.control_type
        if control_type == ControlType.FLOOR:
            return "floor"
        elif control_type == ControlType.AIR:
            return "air"
        elif control_type == ControlType.AIR_WITH_FLOOR_LIMIT:
            return "air_with_floor_limit"
        return "unknown"

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return

        await async_execute_command(
            self.hass,
            self._thermostat.set_setpoint,
            temperature,
            action="set the target temperature",
        )
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new HVAC mode using a single API write whenever possible."""
        if hvac_mode == HVACMode.OFF:
            await async_execute_command(
                self.hass, self._thermostat.turn_off, action="turn off the thermostat"
            )
        elif hvac_mode == HVACMode.HEAT:
            await async_execute_command(
                self.hass,
                self._thermostat.set_hvac_configuration,
                mode=OperationMode.MANUAL,
                cooling=False,
                action="set heating mode",
            )
        elif hvac_mode == HVACMode.COOL:
            await async_execute_command(
                self.hass,
                self._thermostat.set_hvac_configuration,
                mode=OperationMode.MANUAL,
                cooling=True,
                action="set cooling mode",
            )
        elif hvac_mode == HVACMode.AUTO:
            await async_execute_command(
                self.hass,
                self._thermostat.set_hvac_configuration,
                mode=OperationMode.SCHEDULE,
                action="set schedule mode",
            )

        await self.coordinator.async_request_refresh()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        mode = (
            OperationMode.SCHEDULE
            if preset_mode == PRESET_SCHEDULE
            else OperationMode.MANUAL
        )
        await async_execute_command(
            self.hass,
            self._thermostat.set_mode,
            mode,
            action=f"set {preset_mode} mode",
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        """Turn on the thermostat."""
        await async_execute_command(
            self.hass, self._thermostat.turn_on, action="turn on the thermostat"
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        """Turn off the thermostat."""
        await async_execute_command(
            self.hass, self._thermostat.turn_off, action="turn off the thermostat"
        )
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
