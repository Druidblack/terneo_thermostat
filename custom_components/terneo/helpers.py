"""Shared helpers for Terneo entities."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError


async def async_execute_command(
    hass: HomeAssistant,
    command: Callable[..., bool],
    *args: Any,
    action: str = "update the thermostat",
    **kwargs: Any,
) -> None:
    """Run a synchronous thermostat command and surface failures to Home Assistant."""
    try:
        if kwargs:
            success = await hass.async_add_executor_job(lambda: command(*args, **kwargs))
        else:
            success = await hass.async_add_executor_job(command, *args)
    except ValueError as err:
        raise HomeAssistantError(str(err)) from err

    if not success:
        raise HomeAssistantError(
            f"Failed to {action}: the Terneo thermostat did not confirm the command"
        )


def build_device_info(thermostat: Any, entry: Any) -> dict[str, Any]:
    """Build consistent device registry information for all Terneo entities."""
    from .const import DOMAIN, MANUFACTURER

    return {
        "identifiers": {(DOMAIN, thermostat.sn)},
        "name": entry.title,
        "manufacturer": MANUFACTURER,
        "model": thermostat.model_name,
        "serial_number": thermostat.sn,
        "configuration_url": f"http://{thermostat.host}",
    }
