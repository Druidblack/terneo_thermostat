"""Binary sensor platform for Terneo/Welrok thermostat diagnostics."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .helpers import build_device_info
from .thermostat import TerneoThermostat


@dataclass(frozen=True, kw_only=True)
class TerneoBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describe a Terneo diagnostic binary sensor."""

    value_fn: Callable[[TerneoThermostat], bool | None]
    required_status_key: str


DIAGNOSTIC_BINARY_SENSORS: tuple[TerneoBinarySensorEntityDescription, ...] = (
    TerneoBinarySensorEntityDescription(
        key="floor_sensor_open",
        translation_key="floor_sensor_open",
        name="Floor Sensor Open Circuit",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda t: t.floor_sensor_open,
        required_status_key="f.3",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoBinarySensorEntityDescription(
        key="floor_sensor_short",
        translation_key="floor_sensor_short",
        name="Floor Sensor Short Circuit",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda t: t.floor_sensor_short,
        required_status_key="f.4",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoBinarySensorEntityDescription(
        key="air_sensor_lost",
        translation_key="air_sensor_lost",
        name="Air Sensor Lost",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda t: t.air_sensor_lost,
        required_status_key="f.5",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoBinarySensorEntityDescription(
        key="preheat_active",
        translation_key="preheat_active",
        name="Pre-heating Active",
        icon="mdi:radiator",
        value_fn=lambda t: t.preheat_active,
        required_status_key="f.7",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoBinarySensorEntityDescription(
        key="window_open_active",
        translation_key="window_open_active",
        name="Window Open Action Active",
        icon="mdi:window-open-variant",
        value_fn=lambda t: t.window_open_active,
        required_status_key="f.8",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoBinarySensorEntityDescription(
        key="internal_overheat",
        translation_key="internal_overheat",
        name="Internal Overheat",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda t: t.internal_overheat,
        required_status_key="f.9",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoBinarySensorEntityDescription(
        key="time_sync_problem",
        translation_key="time_sync_problem",
        name="Time Sync Problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda t: t.time_sync_problem,
        required_status_key="f.10",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoBinarySensorEntityDescription(
        key="timekeeping_problem",
        translation_key="timekeeping_problem",
        name="Timekeeping Problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda t: t.timekeeping_problem,
        required_status_key="f.11",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoBinarySensorEntityDescription(
        key="overheat_control_problem",
        translation_key="overheat_control_problem",
        name="Overheat Control Problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda t: t.overheat_control_problem,
        required_status_key="f.12",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoBinarySensorEntityDescription(
        key="proportional_emergency_mode",
        translation_key="proportional_emergency_mode",
        name="Proportional Emergency Mode",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda t: t.proportional_emergency_mode,
        required_status_key="f.13",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoBinarySensorEntityDescription(
        key="long_load_warning",
        translation_key="long_load_warning",
        name="Long Load Warning",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda t: t.long_load_warning,
        required_status_key="f.17",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoBinarySensorEntityDescription(
        key="zero_cross_error",
        translation_key="zero_cross_error",
        name="Zero-cross Detection Error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda t: t.zero_cross_error,
        required_status_key="f.20",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoBinarySensorEntityDescription(
        key="ignore_cloud_time",
        translation_key="ignore_cloud_time",
        name="Cloud Time Ignored",
        icon="mdi:clock-remove-outline",
        value_fn=lambda t: t.ignore_cloud_time,
        required_status_key="f.21",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoBinarySensorEntityDescription(
        key="air_sensor_connected",
        translation_key="air_sensor_connected",
        name="Air Sensor Connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda t: t.air_sensor_connected_status,
        required_status_key="f.22",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoBinarySensorEntityDescription(
        key="air_sensor_low_battery",
        translation_key="air_sensor_low_battery",
        name="Air Sensor Low Battery",
        device_class=BinarySensorDeviceClass.BATTERY,
        value_fn=lambda t: t.air_sensor_low_battery,
        required_status_key="f.23",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Terneo diagnostic binary sensors."""
    coordinator = entry.runtime_data
    thermostat = coordinator.thermostat
    async_add_entities(
        TerneoDiagnosticBinarySensor(coordinator, thermostat, entry, description)
        for description in DIAGNOSTIC_BINARY_SENSORS
        if thermostat.supports_status_key(description.required_status_key)
    )


class TerneoDiagnosticBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Represent a Terneo telemetry flag."""

    _attr_has_entity_name = True
    entity_description: TerneoBinarySensorEntityDescription

    def __init__(self, coordinator, thermostat, entry, description) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._thermostat = thermostat
        self.entity_description = description
        self._attr_unique_id = f"{thermostat.sn}_{description.key}"
        self._attr_device_info = build_device_info(thermostat, entry)

    @property
    def is_on(self) -> bool | None:
        """Return the telemetry flag."""
        return self.entity_description.value_fn(self._thermostat)

    @property
    def available(self) -> bool:
        """Return whether the thermostat is available."""
        return self._thermostat.available

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data."""
        self.async_write_ha_state()
