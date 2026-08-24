"""Config flow for Terneo/Welrok thermostat integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_SERIAL,
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_OLD,
    DEVICE_TYPE_NEW,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
)
from .thermostat import TerneoThermostat

_LOGGER = logging.getLogger(__name__)


def _validate_connection_sync(host: str, serial: str) -> dict[str, Any]:
    """Validate connection with the same timeout/retry logic used at runtime."""
    thermostat = TerneoThermostat(
        serial_number=serial,
        host=host,
        device_type=DEVICE_TYPE_OLD,
        timeout=DEFAULT_TIMEOUT,
    )

    result = thermostat.get_parameters()
    if not result or "sn" not in result:
        raise CannotConnect("Invalid device response - check serial number")
    if result["sn"] != serial:
        raise CannotConnect("Serial number mismatch")

    params = {p[0]: p for p in result.get("par", [])}
    has_air_sensor = 4 in params or 6 in params or 33 in params
    device_type = DEVICE_TYPE_NEW if has_air_sensor else DEVICE_TYPE_OLD

    return {
        "serial": serial,
        "device_type": device_type,
        "title": f"terneo_{serial}",
    }


async def validate_connection(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    try:
        return await hass.async_add_executor_job(
            _validate_connection_sync,
            data[CONF_HOST].strip(),
            data[CONF_SERIAL].strip(),
        )
    except CannotConnect:
        raise
    except Exception as err:
        _LOGGER.error("Connection error: %s", err)
        raise CannotConnect("Cannot connect to device") from err


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class TerneoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Terneo thermostat."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_info: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_connection(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                # Check if already configured
                await self.async_set_unique_id(info["serial"])
                self._abort_if_unique_id_configured()

                # Store data for next step
                self._discovered_info = {
                    **user_input,
                    CONF_HOST: user_input[CONF_HOST].strip(),
                    CONF_SERIAL: info["serial"],
                    CONF_DEVICE_TYPE: info["device_type"],
                    "title": info["title"],
                }
                
                return await self.async_step_options()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_SERIAL): str,
                }
            ),
            errors=errors,
        )

    async def async_step_options(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the options step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Combine with discovered info
            data = {
                **self._discovered_info,
                CONF_NAME: user_input.get(CONF_NAME, DEFAULT_NAME),
            }
            
            return self.async_create_entry(
                title=user_input.get(CONF_NAME, self._discovered_info.get("title", DEFAULT_NAME)),
                data=data,
            )

        device_type_label = (
            "Новая версия (с датчиком воздуха)" 
            if self._discovered_info.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_NEW 
            else "Старая версия (без датчика воздуха)"
        )

        return self.async_show_form(
            step_id="options",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_NAME, 
                        default=self._discovered_info.get("title", DEFAULT_NAME)
                    ): str,
                }
            ),
            description_placeholders={
                "serial": self._discovered_info.get(CONF_SERIAL, "Unknown"),
                "device_type": device_type_label,
            },
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Allow changing the thermostat IP/hostname without removing it."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            serial = entry.data[CONF_SERIAL]
            try:
                info = await validate_connection(
                    self.hass, {CONF_HOST: host, CONF_SERIAL: serial}
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(info["serial"])
                self._abort_if_unique_id_mismatch()
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={
                        **entry.data,
                        CONF_HOST: host,
                        CONF_DEVICE_TYPE: info["device_type"],
                    },
                )
                return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str}
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return TerneoOptionsFlowHandler()


class TerneoOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Terneo thermostat."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "scan_interval",
                        default=self.config_entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL),
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
                    vol.Optional(
                        "timeout",
                        default=max(self.config_entry.options.get("timeout", DEFAULT_TIMEOUT), DEFAULT_TIMEOUT),
                    ): vol.All(vol.Coerce(int), vol.Range(min=7, max=120)),
                }
            ),
        )
