"""The Terneo/Welrok thermostat integration."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_extract_config_entry_ids
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_DEVICE_TYPE,
    CONF_SERIAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DEVICE_TYPE_OLD,
    DOMAIN,
)
from .coordinator import TerneoDataUpdateCoordinator
from .thermostat import TerneoThermostat

_LOGGER = logging.getLogger(__name__)

SERVICE_SET_FLOOR_LIMITS = "set_floor_limits"
SERVICE_SET_AIR_LIMITS = "set_air_limits"
SERVICE_RESTART = "restart"

SERVICE_FLOOR_LIMITS_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required("lower"): vol.All(vol.Coerce(int), vol.Range(min=5, max=40)),
        vol.Required("upper"): vol.All(vol.Coerce(int), vol.Range(min=10, max=45)),
    }
)
SERVICE_AIR_LIMITS_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required("lower"): vol.All(vol.Coerce(int), vol.Range(min=5, max=30)),
        vol.Required("upper"): vol.All(vol.Coerce(int), vol.Range(min=10, max=35)),
    }
)
SERVICE_TARGET_SCHEMA = cv.make_entity_service_schema({})

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.BUTTON,
]

# Typed alias for runtime data on modern Home Assistant.
type TerneoConfigEntry = ConfigEntry[TerneoDataUpdateCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration and register actions once."""
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TerneoConfigEntry) -> bool:
    """Set up Terneo thermostat from a config entry."""
    scan_interval = entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL)
    timeout = max(entry.options.get("timeout", DEFAULT_TIMEOUT), DEFAULT_TIMEOUT)

    try:
        thermostat = await hass.async_add_executor_job(
            lambda: TerneoThermostat(
                serial_number=entry.data[CONF_SERIAL],
                host=entry.data[CONF_HOST],
                device_type=entry.data.get(CONF_DEVICE_TYPE, DEVICE_TYPE_OLD),
                timeout=timeout,
            )
        )
    except Exception as err:
        raise ConfigEntryNotReady(
            f"Failed to connect to Terneo thermostat: {err}"
        ) from err

    coordinator = TerneoDataUpdateCoordinator(
        hass,
        thermostat,
        entry_id=entry.entry_id,
        scan_interval=scan_interval,
    )
    await coordinator.async_restore_persistent_state()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    return True


async def _async_get_target_coordinators(
    hass: HomeAssistant, call: ServiceCall
) -> list[TerneoDataUpdateCoordinator]:
    """Resolve an action target to loaded Terneo coordinators."""
    entry_ids = await async_extract_config_entry_ids(call)
    if not entry_ids:
        raise ServiceValidationError("Select at least one Terneo thermostat target")

    result: list[TerneoDataUpdateCoordinator] = []
    for entry_id in entry_ids:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            continue
        coordinator = getattr(entry, "runtime_data", None)
        if isinstance(coordinator, TerneoDataUpdateCoordinator):
            result.append(coordinator)

    if not result:
        raise ServiceValidationError(
            "The selected target does not contain a loaded Terneo thermostat"
        )
    return result


async def _async_run_action_command(
    hass: HomeAssistant,
    coordinator: TerneoDataUpdateCoordinator,
    command,
    *args,
    action: str,
    refresh: bool = True,
) -> None:
    """Run an action command and report failed writes to Home Assistant."""
    try:
        success = await hass.async_add_executor_job(command, *args)
    except ValueError as err:
        raise ServiceValidationError(str(err)) from err

    if not success:
        raise HomeAssistantError(
            f"Failed to {action}: the Terneo thermostat did not confirm the command"
        )

    if refresh:
        await coordinator.async_request_refresh()


def async_register_services(hass: HomeAssistant) -> None:
    """Register Terneo integration actions once."""

    async def handle_set_floor_limits(call: ServiceCall) -> None:
        lower = call.data["lower"]
        upper = call.data["upper"]
        if lower >= upper:
            raise ServiceValidationError("Lower floor limit must be below upper limit")

        for coordinator in await _async_get_target_coordinators(hass, call):
            await _async_run_action_command(
                hass,
                coordinator,
                coordinator.thermostat.set_floor_limits,
                lower,
                upper,
                action="set floor temperature limits",
            )

    async def handle_set_air_limits(call: ServiceCall) -> None:
        lower = call.data["lower"]
        upper = call.data["upper"]
        if lower >= upper:
            raise ServiceValidationError("Lower air limit must be below upper limit")

        coordinators = await _async_get_target_coordinators(hass, call)
        if any(
            not coordinator.thermostat.supports_parameter(33)
            or not coordinator.thermostat.supports_parameter(34)
            for coordinator in coordinators
        ):
            raise ServiceValidationError(
                "Air temperature limits are not supported by one or more selected thermostats"
            )

        for coordinator in coordinators:
            await _async_run_action_command(
                hass,
                coordinator,
                coordinator.thermostat.set_air_limits,
                lower,
                upper,
                action="set air temperature limits",
            )

    async def handle_restart(call: ServiceCall) -> None:
        for coordinator in await _async_get_target_coordinators(hass, call):
            await _async_run_action_command(
                hass,
                coordinator,
                coordinator.thermostat.restart,
                action="restart the thermostat",
                refresh=False,
            )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_FLOOR_LIMITS,
        handle_set_floor_limits,
        schema=SERVICE_FLOOR_LIMITS_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_AIR_LIMITS,
        handle_set_air_limits,
        schema=SERVICE_AIR_LIMITS_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESTART,
        handle_restart,
        schema=SERVICE_TARGET_SCHEMA,
    )


async def async_update_options(hass: HomeAssistant, entry: TerneoConfigEntry) -> None:
    """Reload after polling/timeout options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TerneoConfigEntry) -> bool:
    """Unload a config entry and persist estimated counters."""
    coordinator = getattr(entry, "runtime_data", None)
    if isinstance(coordinator, TerneoDataUpdateCoordinator):
        await coordinator.async_save_persistent_state(force=True)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
