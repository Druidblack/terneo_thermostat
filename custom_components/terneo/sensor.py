"""Sensor platform for Terneo/Welrok thermostat."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    RestoreSensor,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ParamNum, SENSOR_TYPES
from .helpers import build_device_info
from .thermostat import TerneoThermostat


@dataclass(frozen=True, kw_only=True)
class TerneoSensorEntityDescription(SensorEntityDescription):
    """Describe a Terneo sensor entity."""

    value_fn: Callable[[TerneoThermostat], Any]
    available_fn: Callable[[TerneoThermostat], bool] = lambda t: True
    required_param: int | None = None
    required_status_key: str | None = None
    require_device_available: bool = True


def _timestamp(value: float | None) -> datetime | None:
    """Convert an epoch timestamp to a timezone-aware datetime."""
    return None if value is None else datetime.fromtimestamp(value, UTC)


def get_sensor_type_name(thermostat: TerneoThermostat) -> str | None:
    """Get sensor type name."""
    sensor_type = thermostat.sensor_type
    if sensor_type is not None:
        return SENSOR_TYPES.get(sensor_type, f"Unknown ({sensor_type})")
    return None


SENSOR_DESCRIPTIONS: tuple[TerneoSensorEntityDescription, ...] = (
    TerneoSensorEntityDescription(
        key="floor_temperature",
        translation_key="floor_temperature",
        name="Floor Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda t: t.floor_temperature,
        required_status_key="t.1",
    ),
    TerneoSensorEntityDescription(
        key="air_temperature",
        translation_key="air_temperature",
        name="Air Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda t: t.air_temperature,
        required_status_key="t.2",
    ),
    TerneoSensorEntityDescription(
        key="setpoint",
        translation_key="setpoint",
        name="Target Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda t: t.setpoint,
        required_status_key="t.5",
    ),
    TerneoSensorEntityDescription(
        key="relay_on_time_limit",
        translation_key="relay_on_time_limit",
        name="Continuous Heating Limit",
        icon="mdi:timer-alert",
        native_unit_of_measurement=UnitOfTime.HOURS,
        value_fn=lambda t: t.relay_on_time_limit,
        required_param=ParamNum.RELAY_ON_TIME_LIMIT,
        entity_registry_enabled_default=False,
    ),
    TerneoSensorEntityDescription(
        key="sensor_type",
        translation_key="sensor_type_display",
        name="Sensor Type",
        icon="mdi:thermometer",
        value_fn=get_sensor_type_name,
        required_param=ParamNum.SENSOR_TYPE,
        entity_registry_enabled_default=False,
    ),
    TerneoSensorEntityDescription(
        key="ble_sensor_connected",
        translation_key="ble_sensor_connected",
        name="Wireless Sensor",
        icon="mdi:bluetooth-connect",
        value_fn=lambda t: "Connected" if t.air_sensor_connected_status else "Not connected",
        required_status_key="f.22",
        entity_registry_enabled_default=False,
    ),
    TerneoSensorEntityDescription(
        key="manual_floor_temp",
        translation_key="manual_floor_temp",
        name="Manual Floor Setpoint",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda t: t.manual_floor_temperature,
        required_param=ParamNum.MANUAL_FLOOR,
        entity_registry_enabled_default=False,
    ),
    TerneoSensorEntityDescription(
        key="manual_air_temp",
        translation_key="manual_air_temp",
        name="Manual Air Setpoint",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda t: t.manual_air_temperature,
        required_param=ParamNum.MANUAL_AIR,
        entity_registry_enabled_default=False,
    ),
    TerneoSensorEntityDescription(
        key="heating_energy",
        translation_key="heating_energy",
        name="Estimated Heating Energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:lightning-bolt",
        value_fn=lambda t: t.heating_energy_kwh,
        available_fn=lambda t: t.power_watts is not None and t.power_watts > 0,
        required_param=ParamNum.POWER,
    ),
    TerneoSensorEntityDescription(
        key="heating_time",
        translation_key="heating_time",
        name="Heating Time",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.HOURS,
        icon="mdi:timer",
        value_fn=lambda t: t.heating_time_hours,
        available_fn=lambda t: t.power_watts is not None and t.power_watts > 0,
        required_param=ParamNum.POWER,
    ),
    TerneoSensorEntityDescription(
        key="current_power",
        translation_key="current_power",
        name="Estimated Current Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        icon="mdi:flash",
        value_fn=lambda t: t.power_watts if t.relay_state else 0,
        available_fn=lambda t: t.power_watts is not None and t.power_watts > 0,
        required_param=ParamNum.POWER,
    ),
    TerneoSensorEntityDescription(
        key="heating_active",
        translation_key="heating_active",
        name="Heating Active",
        icon="mdi:radiator",
        value_fn=lambda t: "On" if t.relay_state else "Off",
        required_status_key="f.0",
    ),
    # Device telemetry diagnostics (all come from the existing cmd:4 poll).
    TerneoSensorEntityDescription(
        key="wifi_rssi",
        translation_key="wifi_rssi",
        name="Wi-Fi Signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dBm",
        value_fn=lambda t: t.wifi_rssi,
        required_status_key="o.0",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoSensorEntityDescription(
        key="internal_temperature",
        translation_key="internal_temperature",
        name="Internal Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda t: t.internal_temperature,
        required_status_key="t.0",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoSensorEntityDescription(
        key="mcu_temperature",
        translation_key="mcu_temperature",
        name="MCU Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda t: t.mcu_temperature,
        required_status_key="t.7",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoSensorEntityDescription(
        key="humidity",
        translation_key="humidity",
        name="Air Sensor Humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda t: t.humidity,
        required_status_key="o.4",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoSensorEntityDescription(
        key="timer_remaining",
        translation_key="timer_remaining",
        name="Timer Remaining",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=lambda t: t.timer_remaining_seconds,
        required_status_key="o.2",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoSensorEntityDescription(
        key="restart_reason",
        translation_key="restart_reason",
        name="Last Restart Reason",
        icon="mdi:restart-alert",
        value_fn=lambda t: t.restart_reason,
        required_status_key="o.1",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoSensorEntityDescription(
        key="wch_restart_reason",
        translation_key="wch_restart_reason",
        name="WCH Restart Reason",
        icon="mdi:restart-alert",
        value_fn=lambda t: t.wch_restart_reason,
        required_status_key="o.5",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoSensorEntityDescription(
        key="setpoint_step",
        translation_key="setpoint_step",
        name="Setpoint Step",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda t: t.setpoint_step,
        required_status_key="setPointStep",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    # Integration/API diagnostics. Keep these available even while the device is offline.
    TerneoSensorEntityDescription(
        key="api_failures",
        translation_key="api_failures",
        name="Consecutive API Failures",
        icon="mdi:lan-disconnect",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: t.consecutive_status_failures,
        require_device_available=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoSensorEntityDescription(
        key="last_status_update",
        translation_key="last_status_update",
        name="Last Successful Status Update",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda t: _timestamp(t.last_status_success),
        require_device_available=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoSensorEntityDescription(
        key="last_parameters_update",
        translation_key="last_parameters_update",
        name="Last Successful Parameters Update",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda t: _timestamp(t.last_parameters_success),
        require_device_available=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoSensorEntityDescription(
        key="last_api_error",
        translation_key="last_api_error",
        name="Last API Error",
        icon="mdi:alert-circle-outline",
        value_fn=lambda t: t.last_api_error or "None",
        require_device_available=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TerneoSensorEntityDescription(
        key="last_api_error_time",
        translation_key="last_api_error_time",
        name="Last API Error Time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda t: _timestamp(t.last_api_error_at),
        require_device_available=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Terneo sensor entities from a config entry."""
    coordinator = entry.runtime_data
    thermostat = coordinator.thermostat

    entities: list[TerneoSensorEntity] = []
    for description in SENSOR_DESCRIPTIONS:
        if (
            description.required_param is not None
            and not thermostat.supports_parameter(description.required_param)
        ):
            continue
        if (
            description.required_status_key is not None
            and not thermostat.supports_status_key(description.required_status_key)
        ):
            continue
        entities.append(TerneoSensorEntity(coordinator, thermostat, entry, description))

    async_add_entities(entities)


class TerneoSensorEntity(CoordinatorEntity, RestoreSensor):
    """Terneo sensor entity."""

    _attr_has_entity_name = True
    entity_description: TerneoSensorEntityDescription

    def __init__(
        self,
        coordinator,
        thermostat: TerneoThermostat,
        entry: ConfigEntry,
        description: TerneoSensorEntityDescription,
    ) -> None:
        """Initialize the sensor entity."""
        super().__init__(coordinator)
        self._thermostat = thermostat
        self.entity_description = description
        self._attr_unique_id = f"{thermostat.sn}_{description.key}"
        self._attr_device_info = build_device_info(thermostat, entry)

    async def async_added_to_hass(self) -> None:
        """Restore 1.0.x counter values once, then use integration storage."""
        await super().async_added_to_hass()
        if self.entity_description.key not in {"heating_energy", "heating_time"}:
            return

        last_data = await self.async_get_last_sensor_data()
        if last_data is None or last_data.native_value is None:
            return
        try:
            previous_value = float(last_data.native_value)
        except (TypeError, ValueError):
            return
        if previous_value <= 0:
            return

        if (
            self.entity_description.key == "heating_energy"
            and self._thermostat.heating_energy_kwh <= 0
        ):
            self._thermostat.restore_energy_counters(
                energy_kwh=previous_value,
                heating_time_seconds=self._thermostat.heating_time_hours * 3600.0,
            )
            await self.coordinator.async_save_persistent_state(force=True)
        elif (
            self.entity_description.key == "heating_time"
            and self._thermostat.heating_time_hours <= 0
        ):
            self._thermostat.restore_energy_counters(
                energy_kwh=self._thermostat.heating_energy_kwh,
                heating_time_seconds=previous_value * 3600.0,
            )
            await self.coordinator.async_save_persistent_state(force=True)

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        return self.entity_description.value_fn(self._thermostat)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if self.entity_description.require_device_available and not self._thermostat.available:
            return False
        return self.entity_description.available_fn(self._thermostat)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
