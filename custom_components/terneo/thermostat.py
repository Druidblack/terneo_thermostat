"""Terneo/Welrok Thermostat API client."""
import logging
import time
from typing import Any

import requests

from .const import (
    ParamNum,
    ControlType,
    OperationMode,
    DataType,
    DEVICE_TYPE_OLD,
    DEVICE_TYPE_NEW,
    CMD_GET_PARAMS,
    CMD_GET_STATUS,
    DEFAULT_TIMEOUT,
    DEFAULT_PARAMETERS_SCAN_INTERVAL,
    PARAMETERS_RETRY_INTERVAL,
    REQUEST_RETRIES,
    REQUEST_RETRY_DELAY,
    MAX_CONSECUTIVE_STATUS_FAILURES,
)

_LOGGER = logging.getLogger(__name__)


class TerneoThermostat:
    """
    A class for interacting with the Terneo/Welrok Thermostat's HTTP API.
    
    Supports both old (before June 2025) and new (from June 2025) versions.
    
    Parameters
    ----------
    serial_number : str
        Serial Number of device
    host : str
        Hostname or IP address.
    device_type : str, optional
        Device type: 'old' or 'new'
    timeout : int, optional
        Connection timeout in seconds (default: 7)
    """

    def __init__(
        self,
        serial_number: str,
        host: str,
        device_type: str = DEVICE_TYPE_OLD,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        """Initialize the thermostat."""
        self.sn = serial_number
        self.host = host
        self.device_type = device_type
        self._is_new_version = device_type == DEVICE_TYPE_NEW
        self._timeout = timeout
        
        self._base_url = f"http://{host}/{{endpoint}}.cgi"
        self._last_request = 0.0
        self._last_parameters_update = 0.0
        self._last_parameters_attempt = 0.0
        self._consecutive_status_failures = 0
        self._last_status_success: float | None = None
        self._last_parameters_success: float | None = None
        self._last_api_error: str | None = None
        self._last_api_error_at: float | None = None
        self._last_api_success: float | None = None
        
        # Cached state
        self._available = False
        self._parameters: dict[int, Any] = {}
        self._status: dict[str, Any] = {}
        
        # Derived state
        self._setpoint: float | None = None
        self._floor_temperature: float | None = None
        self._air_temperature: float | None = None
        self._mode: int | None = None
        self._relay_state: bool | None = None
        self._power_on: bool | None = None
        
        # Energy tracking
        self._last_relay_update: float | None = None
        self._heating_energy_kwh: float = 0.0  # Accumulated energy in kWh
        self._heating_time_seconds: float = 0.0  # Accumulated heating time in seconds
        
        # Verify connection. A transient startup timeout should get one retry;
        # Home Assistant will also retry config-entry setup if both attempts fail.
        verify_url = self._base_url.format(endpoint="api.html")[:-4]
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = requests.get(verify_url, timeout=self._timeout)
                response.raise_for_status()
                self._available = True
                last_error = None
                break
            except requests.RequestException as err:
                last_error = err
                if attempt == 0:
                    time.sleep(REQUEST_RETRY_DELAY)

        if last_error is not None:
            _LOGGER.warning("Connection to thermostat failed during setup: %s", last_error)
            raise last_error

    def _get_url(self, endpoint: str) -> str:
        """Get the full URL for an endpoint."""
        return self._base_url.format(endpoint=endpoint)

    def _post(
        self,
        endpoint: str = "api",
        *,
        retries: int = 0,
        warn_on_failure: bool = True,
        **kwargs,
    ) -> dict | bool:
        """Perform a POST request with rate limiting and optional retry.

        Read-only polling requests can suppress final warnings because availability
        is handled by ``get_status``. Idempotent write requests are retried once;
        non-idempotent commands such as restart explicitly use no retry.
        """
        request_data = kwargs.get("json", {})
        attempts = max(1, retries + 1)

        for attempt in range(1, attempts + 1):
            # Terneo local API is sensitive to requests sent back-to-back.
            elapsed = time.time() - self._last_request
            if elapsed < 1.0:
                time.sleep(1.0 - elapsed)

            try:
                response = requests.post(
                    self._get_url(endpoint),
                    timeout=self._timeout,
                    **kwargs,
                )
                response.raise_for_status()
                self._last_request = time.time()
                self._last_api_success = self._last_request
            except requests.RequestException as err:
                self._last_request = time.time()
                if attempt < attempts:
                    _LOGGER.debug(
                        "Terneo request failed (attempt %s/%s), retrying: %s",
                        attempt,
                        attempts,
                        err,
                    )
                    time.sleep(REQUEST_RETRY_DELAY)
                    continue
                log = _LOGGER.warning if warn_on_failure else _LOGGER.debug
                self._record_api_error(f"HTTP request failed: {err}")
                log(
                    "Terneo POST request failed after %s attempt(s): %s",
                    attempts,
                    err,
                )
                return False

            try:
                content = response.json()
            except ValueError as err:
                if attempt < attempts:
                    _LOGGER.debug(
                        "Terneo returned invalid JSON (attempt %s/%s), retrying: %s",
                        attempt,
                        attempts,
                        err,
                    )
                    time.sleep(REQUEST_RETRY_DELAY)
                    continue
                log = _LOGGER.warning if warn_on_failure else _LOGGER.debug
                self._record_api_error(f"Invalid JSON response: {err}")
                log(
                    "Terneo returned invalid JSON after %s attempt(s): %s",
                    attempts,
                    err,
                )
                return False

            if content.get("status") == "timeout":
                if attempt < attempts:
                    _LOGGER.debug(
                        "Terneo API timeout (attempt %s/%s), retrying request: %s",
                        attempt,
                        attempts,
                        request_data,
                    )
                    time.sleep(REQUEST_RETRY_DELAY)
                    continue
                log = _LOGGER.warning if warn_on_failure else _LOGGER.debug
                self._record_api_error(f"Device API timeout for request {request_data}")
                log(
                    "Terneo API timeout after %s attempt(s) for request: %s",
                    attempts,
                    request_data,
                )
                return False

            return content

        return False

    def _record_api_error(self, message: str) -> None:
        """Remember the most recent API error for diagnostics."""
        self._last_api_error = message[:250]
        self._last_api_error_at = time.time()

    def get_parameters(self) -> dict | bool:
        """Get all parameters from the device.

        Parameter polling is deliberately less frequent than status polling.
        """
        self._last_parameters_attempt = time.monotonic()
        result = self._post(
            json={"cmd": CMD_GET_PARAMS, "sn": self.sn},
            retries=REQUEST_RETRIES,
            warn_on_failure=False,
        )
        if result and "par" in result:
            self._parameters = {p[0]: (p[1], p[2]) for p in result["par"]}
            self._last_parameters_update = time.monotonic()
            self._last_parameters_success = time.time()

            # Derive capabilities from the parameter set actually reported by the
            # thermostat instead of relying only on a coarse old/new model flag.
            has_air_features = any(
                int(param) in self._parameters
                for param in (
                    ParamNum.MANUAL_AIR,
                    ParamNum.AWAY_AIR,
                    ParamNum.UPPER_AIR_LIMIT,
                    ParamNum.LOWER_AIR_LIMIT,
                    ParamNum.AIR_CORRECTION,
                    ParamNum.BLE_SENSOR_BIND,
                )
            )
            self._is_new_version = has_air_features
            self.device_type = DEVICE_TYPE_NEW if has_air_features else DEVICE_TYPE_OLD
            return result
        return False

    def set_parameters(self, params: list[list]) -> dict | bool:
        """Set parameters on the device and update the local cache on success."""
        result = self._post(
            json={"sn": self.sn, "par": params},
            retries=REQUEST_RETRIES,
        )
        if not result:
            return False

        # Keep parameter entities responsive without forcing a full cmd:1 after
        # every write. The next slow parameter refresh remains authoritative.
        for param in params:
            if len(param) < 3:
                continue
            param_num, data_type, value = param[0], param[1], param[2]
            self._parameters[int(param_num)] = (int(data_type), str(value))

            if int(param_num) == int(ParamNum.POWER_OFF):
                self._power_on = str(value) != "1"
            elif int(param_num) == int(ParamNum.MODE) and self._power_on is not False:
                self._mode = int(value)

        return result

    def get_status(self) -> dict | bool:
        """Get the status dictionary from the thermostat with one retry."""
        result = self._post(
            json={"cmd": CMD_GET_STATUS, "sn": self.sn},
            retries=REQUEST_RETRIES,
            warn_on_failure=False,
        )
        if result:
            previous_failures = self._consecutive_status_failures
            self._status = result
            self._last_status_success = time.time()
            self._consecutive_status_failures = 0
            self._available = True
            if previous_failures:
                _LOGGER.info(
                    "Terneo connection restored after %s failed status update(s)",
                    previous_failures,
                )
            return result

        self._consecutive_status_failures += 1
        if not self._status:
            self._available = False
        elif self._consecutive_status_failures >= MAX_CONSECUTIVE_STATUS_FAILURES:
            if self._available:
                _LOGGER.warning(
                    "Terneo unavailable after %s consecutive failed status updates",
                    self._consecutive_status_failures,
                )
            self._available = False
        return False

    def restart(self) -> bool:
        """Restart the device."""
        result = self._post(endpoint="test", json={"cmd": "restart"})
        if result and result.get("success") == "true":
            _LOGGER.info("Device restart command sent successfully")
            return True
        _LOGGER.warning("Failed to send restart command")
        return False

    def _get_param_value(self, param_num: int) -> Any | None:
        """Get a parameter value from cache."""
        if param_num in self._parameters:
            data_type, value = self._parameters[param_num]
            return self._convert_value(value, data_type)
        return None

    @staticmethod
    def _convert_value(value: str, data_type: int) -> Any:
        """Convert string value to appropriate type."""
        if data_type == DataType.BOOL:
            return value == "1"
        elif data_type in (DataType.INT8, DataType.INT16, DataType.INT32):
            return int(value)
        elif data_type in (DataType.UINT8, DataType.UINT16, DataType.UINT32):
            return int(value)
        return value

    def _temperature_from_api(self, value: int, param_num: int) -> float:
        """Convert API temperature value to Celsius."""
        if self._is_new_version:
            # New version uses °C*10 for most temperature parameters
            return value / 10.0
        else:
            # Old version uses °C directly
            return float(value)

    def _temperature_to_api(self, value: float, param_num: int) -> str:
        """Convert Celsius to API temperature value."""
        if self._is_new_version:
            return str(int(value * 10))
        else:
            return str(int(value))

    # Properties

    @property
    def available(self) -> bool:
        """Return if device is available."""
        return self._available

    @property
    def is_new_version(self) -> bool:
        """Return if device is new version with air sensor."""
        return self._is_new_version

    def supports_parameter(self, param_num: int) -> bool:
        """Return whether cmd:1 reports support for a parameter.

        If the parameter cache is not available yet, return True so a transient
        cmd:1 failure during startup does not permanently suppress entities.
        """
        if not self._parameters:
            return True
        return int(param_num) in self._parameters

    def supports_status_key(self, key: str) -> bool:
        """Return whether the current telemetry contains a status key."""
        return key in self._status

    @property
    def model_name(self) -> str:
        """Return a capability-based model label without guessing exact hardware."""
        return "OZ/AZ (Air sensor)" if self._is_new_version else "OZ (Legacy)"

    @property
    def power_on(self) -> bool | None:
        """Return if device is powered on."""
        return self._power_on

    @property
    def floor_temperature(self) -> float | None:
        """Current floor temperature in Celsius."""
        return self._floor_temperature

    @property
    def air_temperature(self) -> float | None:
        """Current air temperature in Celsius (new version only)."""
        return self._air_temperature

    @property
    def setpoint(self) -> float | None:
        """Current temperature setpoint in Celsius."""
        return self._setpoint

    @property
    def mode(self) -> int | None:
        """Current operation mode."""
        return self._mode

    @property
    def relay_state(self) -> bool | None:
        """Current relay state (heating active)."""
        return self._relay_state

    @property
    def control_type(self) -> int | None:
        """Current control type (floor/air/air with floor limit)."""
        if "m.0" in self._status:
            return int(self._status["m.0"])
        return self._get_param_value(ParamNum.CONTROL_TYPE)

    @property
    def hysteresis(self) -> float | None:
        """Current hysteresis value in Celsius."""
        value = self._get_param_value(ParamNum.HYSTERESIS)
        if value is not None:
            return value / 10.0
        return None

    @property
    def children_lock(self) -> bool | None:
        """Return if children lock is enabled."""
        return self._get_param_value(ParamNum.CHILDREN_LOCK)

    @property
    def cooling_mode(self) -> bool | None:
        """Return if cooling mode is enabled (vs heating)."""
        if "m.5" in self._status:
            return int(self._status["m.5"]) == 1
        return self._get_param_value(ParamNum.COOLING_CONTROL_WAY)

    @property
    def upper_limit(self) -> int | None:
        """Maximum floor temperature setpoint."""
        return self._get_param_value(ParamNum.UPPER_LIMIT)

    @property
    def lower_limit(self) -> int | None:
        """Minimum floor temperature setpoint."""
        return self._get_param_value(ParamNum.LOWER_LIMIT)

    @property
    def upper_air_limit(self) -> int | None:
        """Maximum air temperature setpoint (new version only)."""
        if self._is_new_version:
            return self._get_param_value(ParamNum.UPPER_AIR_LIMIT)
        return None

    @property
    def lower_air_limit(self) -> int | None:
        """Minimum air temperature setpoint (new version only)."""
        if self._is_new_version:
            return self._get_param_value(ParamNum.LOWER_AIR_LIMIT)
        return None

    @property
    def brightness(self) -> int | None:
        """Display brightness (0-10)."""
        return self._get_param_value(ParamNum.BRIGHTNESS)

    @property
    def use_night_brightness(self) -> bool | None:
        """Return if night brightness mode is enabled."""
        return self._get_param_value(ParamNum.USE_NIGHT_BRIGHT)

    @property
    def pre_control(self) -> bool | None:
        """Return if pre-heating is enabled."""
        return self._get_param_value(ParamNum.PRE_CONTROL)

    @property
    def window_open_control(self) -> bool | None:
        """Return if window open detection is enabled (new version only)."""
        if self._is_new_version:
            return self._get_param_value(ParamNum.WINDOW_OPEN_CONTROL)
        return None

    @property
    def lan_block(self) -> bool | None:
        """Return if LAN API changes are blocked."""
        return self._get_param_value(ParamNum.LAN_BLOCK)

    @property
    def cloud_block(self) -> bool | None:
        """Return if cloud changes are blocked."""
        return self._get_param_value(ParamNum.CLOUD_BLOCK)

    @property
    def power_watts(self) -> int | None:
        """Connected power in Watts."""
        value = self._get_param_value(ParamNum.POWER)
        if value is not None:
            if value <= 150:
                return value * 10
            else:
                return value * 20 - 1500
        return None

    @property
    def floor_correction(self) -> float | None:
        """Floor sensor correction in Celsius."""
        value = self._get_param_value(ParamNum.FLOOR_CORRECTION)
        if value is not None:
            return value / 10.0
        return None

    @property
    def air_correction(self) -> float | None:
        """Air sensor correction in Celsius (new version only)."""
        if self._is_new_version:
            value = self._get_param_value(ParamNum.AIR_CORRECTION)
            if value is not None:
                return value / 10.0
        return None

    @property
    def sensor_type(self) -> int | None:
        """Temperature sensor type (resistance)."""
        return self._get_param_value(ParamNum.SENSOR_TYPE)

    @property
    def prop_koef(self) -> int | None:
        """Proportional mode coefficient (minutes of load in 30-min cycle)."""
        return self._get_param_value(ParamNum.PROP_KOEF)

    @property
    def nc_contact_control(self) -> bool | None:
        """Return if relay is inverted (NC mode)."""
        return self._get_param_value(ParamNum.NC_CONTACT_CONTROL)

    @property
    def night_bright_start(self) -> int | None:
        """Night brightness start time (minutes from 00:00)."""
        return self._get_param_value(ParamNum.NIGHT_BRIGHT_START)

    @property
    def night_bright_end(self) -> int | None:
        """Night brightness end time (minutes from 00:00)."""
        return self._get_param_value(ParamNum.NIGHT_BRIGHT_END)

    @property
    def relay_on_time_limit(self) -> int | None:
        """Continuous heating time limit for alarm (hours, read-only)."""
        return self._get_param_value(ParamNum.RELAY_ON_TIME_LIMIT)

    @property
    def button_minus_cor(self) -> int | None:
        """Minus button sensitivity correction (-30 to 30)."""
        return self._get_param_value(ParamNum.BUTTON_MINUS_COR)

    @property
    def button_menu_cor(self) -> int | None:
        """Menu button sensitivity correction (-30 to 30)."""
        return self._get_param_value(ParamNum.BUTTON_MENU_COR)

    @property
    def button_plus_cor(self) -> int | None:
        """Plus button sensitivity correction (-30 to 30)."""
        return self._get_param_value(ParamNum.BUTTON_PLUS_COR)

    @property
    def off_button_lock(self) -> bool | None:
        """Return if automatic button lock is disabled (read-only)."""
        return self._get_param_value(ParamNum.OFF_BUTTON_LOCK)

    @property
    def min_temp_advanced(self) -> int | None:
        """Min floor temp limit in air control mode (new version only)."""
        if self._is_new_version:
            return self._get_param_value(ParamNum.MIN_TEMP_ADVANCED)
        return None

    @property
    def max_temp_advanced(self) -> int | None:
        """Max floor temp limit in air control mode (new version only)."""
        if self._is_new_version:
            return self._get_param_value(ParamNum.MAX_TEMP_ADVANCED)
        return None

    @property
    def ble_sensor_interval(self) -> int | None:
        """Wireless air sensor poll interval in minutes (new version only)."""
        if self._is_new_version:
            return self._get_param_value(ParamNum.BLE_SENSOR_INTERVAL)
        return None

    @property
    def ble_sensor_bind(self) -> bool | None:
        """Return if wireless air sensor is connected (new version, read-only)."""
        if self._is_new_version:
            return self._get_param_value(ParamNum.BLE_SENSOR_BIND)
        return None

    @property
    def upper_warning_temp(self) -> int | None:
        """Upper temperature threshold for alarm (new version only)."""
        if self._is_new_version:
            return self._get_param_value(ParamNum.UPPER_WARNING_TEMP)
        return None

    @property
    def lower_warning_temp(self) -> int | None:
        """Lower temperature threshold for alarm (new version only)."""
        if self._is_new_version:
            return self._get_param_value(ParamNum.LOWER_WARNING_TEMP)
        return None

    @property
    def away_floor_temperature(self) -> float | None:
        """Away mode floor temperature setpoint."""
        value = self._get_param_value(ParamNum.AWAY_FLOOR)
        if value is not None:
            return self._temperature_from_api(value, ParamNum.AWAY_FLOOR)
        return None

    @property
    def away_air_temperature(self) -> float | None:
        """Away mode air temperature setpoint (new version only)."""
        if self._is_new_version:
            value = self._get_param_value(ParamNum.AWAY_AIR)
            if value is not None:
                return self._temperature_from_api(value, ParamNum.AWAY_AIR)
        return None

    @property
    def manual_floor_temperature(self) -> float | None:
        """Manual mode floor temperature setpoint."""
        value = self._get_param_value(ParamNum.MANUAL_FLOOR)
        if value is not None:
            return self._temperature_from_api(value, ParamNum.MANUAL_FLOOR)
        return None

    @property
    def manual_air_temperature(self) -> float | None:
        """Manual mode air temperature setpoint (new version only)."""
        if self._is_new_version:
            value = self._get_param_value(ParamNum.MANUAL_AIR)
            if value is not None:
                return self._temperature_from_api(value, ParamNum.MANUAL_AIR)
        return None

    # Telemetry diagnostics

    def _status_int(self, key: str) -> int | None:
        """Return an integer telemetry value if present."""
        value = self._status.get(key)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _status_flag(self, key: str) -> bool | None:
        """Return a boolean telemetry flag if present."""
        value = self._status_int(key)
        return None if value is None else value == 1

    @property
    def internal_temperature(self) -> float | None:
        value = self._status_int("t.0")
        return None if value is None else value / 16.0

    @property
    def mcu_temperature(self) -> float | None:
        value = self._status_int("t.7")
        return None if value is None else value / 16.0

    @property
    def wifi_rssi(self) -> int | None:
        return self._status_int("o.0")

    @property
    def humidity(self) -> int | None:
        return self._status_int("o.4")

    @property
    def timer_remaining_seconds(self) -> int | None:
        value = self._status_int("o.2")
        return None if value is None else value * 5

    @property
    def setpoint_step(self) -> float | None:
        value = self._status.get("setPointStep")
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @property
    def restart_reason(self) -> str | None:
        value = self._status_int("o.1")
        if value is None:
            return None
        return {
            1: "Power reset",
            3: "Software restart",
            9: "Low-voltage software restart",
        }.get(value, f"Unknown ({value})")

    @property
    def wch_restart_reason(self) -> str | None:
        value = self._status_int("o.5")
        if value is None:
            return None
        return {
            0: "Other / unknown",
            3: "Restart",
            4: "Software fault",
        }.get(value, f"Unknown ({value})")

    @property
    def floor_sensor_open(self) -> bool | None:
        return self._status_flag("f.3")

    @property
    def floor_sensor_short(self) -> bool | None:
        return self._status_flag("f.4")

    @property
    def air_sensor_lost(self) -> bool | None:
        return self._status_flag("f.5")

    @property
    def preheat_active(self) -> bool | None:
        return self._status_flag("f.7")

    @property
    def window_open_active(self) -> bool | None:
        return self._status_flag("f.8")

    @property
    def internal_overheat(self) -> bool | None:
        return self._status_flag("f.9")

    @property
    def time_sync_problem(self) -> bool | None:
        return self._status_flag("f.10")

    @property
    def timekeeping_problem(self) -> bool | None:
        return self._status_flag("f.11")

    @property
    def overheat_control_problem(self) -> bool | None:
        return self._status_flag("f.12")

    @property
    def proportional_emergency_mode(self) -> bool | None:
        return self._status_flag("f.13")

    @property
    def long_load_warning(self) -> bool | None:
        return self._status_flag("f.17")

    @property
    def zero_cross_error(self) -> bool | None:
        return self._status_flag("f.20")

    @property
    def ignore_cloud_time(self) -> bool | None:
        return self._status_flag("f.21")

    @property
    def air_sensor_connected_status(self) -> bool | None:
        return self._status_flag("f.22")

    @property
    def air_sensor_low_battery(self) -> bool | None:
        return self._status_flag("f.23")

    @property
    def consecutive_status_failures(self) -> int:
        return self._consecutive_status_failures

    @property
    def last_status_success(self) -> float | None:
        return self._last_status_success

    @property
    def last_parameters_success(self) -> float | None:
        return self._last_parameters_success

    @property
    def last_api_error(self) -> str | None:
        return self._last_api_error

    @property
    def last_api_error_at(self) -> float | None:
        return self._last_api_error_at

    # Setters

    def set_setpoint(self, temperature: float) -> bool:
        """Set target temperature."""
        control_type = self.control_type or ControlType.FLOOR
        
        if control_type == ControlType.FLOOR:
            param = ParamNum.MANUAL_FLOOR
        else:
            param = ParamNum.MANUAL_AIR if self._is_new_version else ParamNum.MANUAL_FLOOR
        
        temp_value = self._temperature_to_api(temperature, param)
        
        # Turn on, set manual mode, and set temperature
        result = self.set_parameters([
            [ParamNum.POWER_OFF, DataType.BOOL, "0"],
            [ParamNum.MODE, DataType.UINT8, str(OperationMode.MANUAL)],
            [param, DataType.INT8 if not self._is_new_version else DataType.INT16, temp_value],
        ])
        
        if result:
            self._setpoint = temperature
        return bool(result)

    def set_mode(self, mode: int) -> bool:
        """Set operation mode (0=schedule, 3=manual) and power on."""
        return self.set_hvac_configuration(mode=mode)

    def set_hvac_configuration(
        self,
        *,
        mode: int,
        cooling: bool | None = None,
    ) -> bool:
        """Apply power, schedule/manual mode and heating/cooling in one request."""
        if mode not in [OperationMode.SCHEDULE, OperationMode.MANUAL]:
            raise ValueError("Mode must be 0 (schedule) or 3 (manual)")

        params = [
            [ParamNum.POWER_OFF, DataType.BOOL, "0"],
            [ParamNum.MODE, DataType.UINT8, str(int(mode))],
        ]
        if cooling is not None:
            params.append([
                ParamNum.COOLING_CONTROL_WAY,
                DataType.BOOL,
                "1" if cooling else "0",
            ])

        return bool(self.set_parameters(params))

    def turn_on(self) -> bool:
        """Turn on the thermostat."""
        result = self.set_parameters([[ParamNum.POWER_OFF, DataType.BOOL, "0"]])
        if result:
            self._power_on = True
        return bool(result)

    def turn_off(self) -> bool:
        """Turn off the thermostat."""
        result = self.set_parameters([[ParamNum.POWER_OFF, DataType.BOOL, "1"]])
        if result:
            self._power_on = False
        return bool(result)

    def set_children_lock(self, enabled: bool) -> bool:
        """Set children lock."""
        result = self.set_parameters([
            [ParamNum.CHILDREN_LOCK, DataType.BOOL, "1" if enabled else "0"]
        ])
        return bool(result)

    def set_cooling_mode(self, enabled: bool) -> bool:
        """Set cooling mode (vs heating)."""
        result = self.set_parameters([
            [ParamNum.COOLING_CONTROL_WAY, DataType.BOOL, "1" if enabled else "0"]
        ])
        return bool(result)

    def set_control_type(self, control_type: int) -> bool:
        """Set control type (0=floor, 1=air, 2=air with floor limit)."""
        if control_type not in [0, 1, 2]:
            raise ValueError("Control type must be 0, 1, or 2")
        
        result = self.set_parameters([
            [ParamNum.CONTROL_TYPE, DataType.UINT8, str(control_type)]
        ])
        return bool(result)

    def set_hysteresis(self, value: float) -> bool:
        """Set hysteresis in Celsius."""
        api_value = int(value * 10)
        result = self.set_parameters([
            [ParamNum.HYSTERESIS, DataType.UINT8, str(api_value)]
        ])
        return bool(result)

    def set_brightness(self, value: int) -> bool:
        """Set display brightness (0-10)."""
        if not 0 <= value <= 10:
            raise ValueError("Brightness must be between 0 and 10")
        
        result = self.set_parameters([
            [ParamNum.BRIGHTNESS, DataType.UINT8, str(value)]
        ])
        return bool(result)

    def set_pre_control(self, enabled: bool) -> bool:
        """Set pre-heating mode."""
        result = self.set_parameters([
            [ParamNum.PRE_CONTROL, DataType.BOOL, "1" if enabled else "0"]
        ])
        return bool(result)

    def set_window_open_control(self, enabled: bool) -> bool:
        """Set window open detection (new version only)."""
        if not self._is_new_version:
            _LOGGER.warning("Window open control is only available on new version")
            return False
        
        result = self.set_parameters([
            [ParamNum.WINDOW_OPEN_CONTROL, DataType.BOOL, "1" if enabled else "0"]
        ])
        return bool(result)

    def set_use_night_brightness(self, enabled: bool) -> bool:
        """Set night brightness mode."""
        result = self.set_parameters([
            [ParamNum.USE_NIGHT_BRIGHT, DataType.BOOL, "1" if enabled else "0"]
        ])
        return bool(result)

    def set_floor_limits(self, lower: int, upper: int) -> bool:
        """Set floor temperature limits."""
        if lower >= upper:
            raise ValueError("Lower floor limit must be below upper limit")
        result = self.set_parameters([
            [ParamNum.LOWER_LIMIT, DataType.INT8, str(lower)],
            [ParamNum.UPPER_LIMIT, DataType.INT8, str(upper)],
        ])
        return bool(result)

    def set_air_limits(self, lower: int, upper: int) -> bool:
        """Set air temperature limits (new version only)."""
        if lower >= upper:
            raise ValueError("Lower air limit must be below upper limit")
        if not self._is_new_version:
            _LOGGER.warning("Air limits are only available on new version")
            return False
        
        result = self.set_parameters([
            [ParamNum.LOWER_AIR_LIMIT, DataType.INT8, str(lower)],
            [ParamNum.UPPER_AIR_LIMIT, DataType.INT8, str(upper)],
        ])
        return bool(result)

    def set_sensor_type(self, sensor_type: int) -> bool:
        """Set temperature sensor type (0-6)."""
        if not 0 <= sensor_type <= 6:
            raise ValueError("Sensor type must be between 0 and 6")
        
        result = self.set_parameters([
            [ParamNum.SENSOR_TYPE, DataType.UINT8, str(sensor_type)]
        ])
        return bool(result)

    def set_prop_koef(self, value: int) -> bool:
        """Set proportional mode coefficient (minutes in 30-min cycle)."""
        if not 0 <= value <= 30:
            raise ValueError("Proportional coefficient must be between 0 and 30")
        
        result = self.set_parameters([
            [ParamNum.PROP_KOEF, DataType.UINT8, str(value)]
        ])
        return bool(result)

    def set_nc_contact_control(self, enabled: bool) -> bool:
        """Set relay inversion (NC mode)."""
        result = self.set_parameters([
            [ParamNum.NC_CONTACT_CONTROL, DataType.BOOL, "1" if enabled else "0"]
        ])
        return bool(result)

    def set_night_brightness_time(self, start_minutes: int, end_minutes: int) -> bool:
        """Set night brightness time range (minutes from 00:00)."""
        if not 0 <= start_minutes <= 1439 or not 0 <= end_minutes <= 1439:
            raise ValueError("Time must be between 0 and 1439 minutes")
        
        result = self.set_parameters([
            [ParamNum.NIGHT_BRIGHT_START, DataType.UINT16, str(start_minutes)],
            [ParamNum.NIGHT_BRIGHT_END, DataType.UINT16, str(end_minutes)],
        ])
        return bool(result)

    def set_button_corrections(self, minus: int, menu: int, plus: int) -> bool:
        """Set button sensitivity corrections (-30 to 30)."""
        for val in [minus, menu, plus]:
            if not -30 <= val <= 30:
                raise ValueError("Button correction must be between -30 and 30")
        
        result = self.set_parameters([
            [ParamNum.BUTTON_MINUS_COR, DataType.INT8, str(minus)],
            [ParamNum.BUTTON_MENU_COR, DataType.INT8, str(menu)],
            [ParamNum.BUTTON_PLUS_COR, DataType.INT8, str(plus)],
        ])
        return bool(result)

    def set_floor_correction(self, value: float) -> bool:
        """Set floor sensor correction in Celsius."""
        api_value = int(value * 10)
        if not -127 <= api_value <= 127:
            raise ValueError("Floor correction must be between -12.7 and 12.7")
        
        result = self.set_parameters([
            [ParamNum.FLOOR_CORRECTION, DataType.INT8, str(api_value)]
        ])
        return bool(result)

    def set_air_correction(self, value: float) -> bool:
        """Set air sensor correction in Celsius (new version only)."""
        if not self._is_new_version:
            _LOGGER.warning("Air correction is only available on new version")
            return False
        
        api_value = int(value * 10)
        if not -127 <= api_value <= 127:
            raise ValueError("Air correction must be between -12.7 and 12.7")
        
        result = self.set_parameters([
            [ParamNum.AIR_CORRECTION, DataType.INT8, str(api_value)]
        ])
        return bool(result)

    def set_lan_block(self, enabled: bool) -> bool:
        """Set LAN API block."""
        result = self.set_parameters([
            [ParamNum.LAN_BLOCK, DataType.BOOL, "1" if enabled else "0"]
        ])
        return bool(result)

    def set_cloud_block(self, enabled: bool) -> bool:
        """Set cloud block."""
        result = self.set_parameters([
            [ParamNum.CLOUD_BLOCK, DataType.BOOL, "1" if enabled else "0"]
        ])
        return bool(result)

    def set_advanced_floor_limits(self, min_temp: int, max_temp: int) -> bool:
        """Set floor temp limits for air control mode (new version only)."""
        if not self._is_new_version:
            _LOGGER.warning("Advanced floor limits are only available on new version")
            return False
        
        result = self.set_parameters([
            [ParamNum.MIN_TEMP_ADVANCED, DataType.INT8, str(min_temp)],
            [ParamNum.MAX_TEMP_ADVANCED, DataType.INT8, str(max_temp)],
        ])
        return bool(result)

    def set_ble_sensor_interval(self, minutes: int) -> bool:
        """Set wireless sensor poll interval in minutes (new version only)."""
        if not self._is_new_version:
            _LOGGER.warning("BLE sensor interval is only available on new version")
            return False
        
        if not 1 <= minutes <= 60:
            raise ValueError("BLE sensor interval must be between 1 and 60 minutes")
        
        result = self.set_parameters([
            [ParamNum.BLE_SENSOR_INTERVAL, DataType.UINT8, str(minutes)]
        ])
        return bool(result)

    def set_warning_temps(self, lower: int, upper: int) -> bool:
        """Set temperature warning thresholds (new version only)."""
        if not self._is_new_version:
            _LOGGER.warning("Warning temps are only available on new version")
            return False
        
        result = self.set_parameters([
            [ParamNum.LOWER_WARNING_TEMP, DataType.INT8, str(lower)],
            [ParamNum.UPPER_WARNING_TEMP, DataType.INT8, str(upper)],
        ])
        return bool(result)

    def set_away_temperature(self, floor_temp: float, air_temp: float | None = None) -> bool:
        """Set away mode temperatures."""
        params = [
            [ParamNum.AWAY_FLOOR, 
             DataType.INT8 if not self._is_new_version else DataType.INT16, 
             self._temperature_to_api(floor_temp, ParamNum.AWAY_FLOOR)]
        ]
        
        if self._is_new_version and air_temp is not None:
            params.append([
                ParamNum.AWAY_AIR, 
                DataType.INT16, 
                self._temperature_to_api(air_temp, ParamNum.AWAY_AIR)
            ])
        
        result = self.set_parameters(params)
        return bool(result)

    def set_power(self, watts: int) -> bool:
        """Set connected power in Watts."""
        # Convert watts to API value
        if watts <= 1500:
            api_value = watts // 10
        else:
            api_value = (watts + 1500) // 20
        
        result = self.set_parameters([
            [ParamNum.POWER, DataType.UINT16, str(api_value)]
        ])
        return bool(result)

    def _parameters_refresh_due(self) -> bool:
        """Return whether the full cmd:1 parameter refresh is due."""
        now = time.monotonic()

        if self._last_parameters_update <= 0:
            # After a failed initial/full refresh, avoid retrying cmd:1 on every
            # fast status poll. Try again after a short cooldown instead.
            return (
                self._last_parameters_attempt <= 0
                or now - self._last_parameters_attempt >= PARAMETERS_RETRY_INTERVAL
            )

        return now - self._last_parameters_update >= DEFAULT_PARAMETERS_SCAN_INTERVAL

    def update(self) -> bool:
        """Update device state using fast status and slow parameter polling.

        cmd:4 is the heartbeat and is requested every coordinator cycle. cmd:1 is
        only refreshed every two minutes. One or two failed status cycles keep the
        last known state available; the device is marked unavailable after three
        consecutive failed status cycles.
        """
        status_result = self.get_status()
        status_ok = bool(status_result)

        if status_ok:
            self._parse_status(status_result)

            # Full parameters are configuration data and change infrequently.
            # Do not let a cmd:1 failure invalidate an otherwise healthy cmd:4.
            if self._parameters_refresh_due():
                params_result = self.get_parameters()
                if not params_result:
                    _LOGGER.debug(
                        "Terneo parameter refresh failed; keeping cached parameters"
                    )

            # Firmware without f.16 needs POWER_OFF from cmd:1/cache.
            if "f.16" not in status_result:
                power_off = self._get_param_value(ParamNum.POWER_OFF)
                if power_off is not None:
                    self._power_on = not power_off

            return True

        # Do not flap entities on a single transient timeout or malformed JSON.
        if self._status and self._available:
            _LOGGER.debug(
                "Terneo status refresh failed (%s/%s); keeping cached state",
                self._consecutive_status_failures,
                MAX_CONSECUTIVE_STATUS_FAILURES,
            )
            return True

        return False

    def _parse_status(self, data: dict) -> None:
        """Parse status response."""
        # Floor temperature (t.1 = raw * 16)
        if "t.1" in data:
            self._floor_temperature = float(data["t.1"]) / 16.0
        
        # Air temperature: parse by telemetry capability, not cached model type.
        if "t.2" in data:
            self._air_temperature = float(data["t.2"]) / 16.0
        
        # Setpoint (t.5 = raw * 16)
        if "t.5" in data:
            self._setpoint = float(data["t.5"]) / 16.0
        
        # Mode
        if "m.1" in data:
            mode_value = int(data["m.1"])
            # Check power state
            if "f.16" in data:
                is_on = int(data["f.16"]) == 0
                self._power_on = is_on
            else:
                power_off = self._get_param_value(ParamNum.POWER_OFF)
                is_on = not power_off if power_off is not None else self._power_on is not False
            
            if not is_on:
                self._mode = -1  # Off
            else:
                self._mode = mode_value
        
        # Relay state and energy tracking
        if "f.0" in data:
            new_relay_state = int(data["f.0"]) == 1
            self._update_energy_tracking(new_relay_state)
            self._relay_state = new_relay_state

    def _update_energy_tracking(self, new_relay_state: bool) -> None:
        """Update energy consumption tracking based on relay state."""
        current_time = time.time()
        
        # If we have a previous measurement and relay was ON, calculate energy
        if self._last_relay_update is not None and self._relay_state is True:
            elapsed_seconds = current_time - self._last_relay_update
            
            # Sanity check: skip if elapsed time is too long (>5 min) or negative
            # This prevents accumulating large errors after restarts/gaps
            if 0 < elapsed_seconds <= 300:
                power_watts = self.power_watts
                if power_watts and power_watts > 0:
                    # Calculate energy in kWh: (W * seconds) / (1000 * 3600)
                    energy_kwh = (power_watts * elapsed_seconds) / 3600000.0
                    self._heating_energy_kwh += energy_kwh
                    self._heating_time_seconds += elapsed_seconds
        
        self._last_relay_update = current_time

    @property
    def heating_energy_kwh(self) -> float:
        """Total energy consumed by heating in kWh (since integration start)."""
        return round(self._heating_energy_kwh, 3)

    @property
    def heating_time_hours(self) -> float:
        """Total heating time in hours (since integration start)."""
        return round(self._heating_time_seconds / 3600.0, 2)

    def reset_energy_counter(self) -> None:
        """Reset energy and time counters."""
        self._heating_energy_kwh = 0.0
        self._heating_time_seconds = 0.0

    def restore_energy_counters(
        self, energy_kwh: float = 0.0, heating_time_seconds: float = 0.0
    ) -> None:
        """Restore estimated energy counters from Home Assistant storage."""
        self._heating_energy_kwh = max(0.0, float(energy_kwh))
        self._heating_time_seconds = max(0.0, float(heating_time_seconds))

    def energy_counter_state(self) -> dict[str, float]:
        """Return serializable estimated energy counter state."""
        return {
            "energy_kwh": self._heating_energy_kwh,
            "heating_time_seconds": self._heating_time_seconds,
        }


# Backward compatibility alias
Thermostat = TerneoThermostat
