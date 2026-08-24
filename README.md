# Terneo/Welrok Thermostat Integration for Home Assistant

<img width="2000" height="334" alt="4c8grq59fdbxs708khd8hru46i0iqvxv" src="https://github.com/user-attachments/assets/fecdffe1-d71b-4e64-84e9-54028a8cd8b5" /> 

<img width="725" height="135" alt="logotipwelrokgoluboj" src="https://github.com/user-attachments/assets/18102fa7-717f-4e65-a940-4ebd2f64ba84" />



Custom component for Home Assistant to control Terneo/Welrok thermostats via local API.

## Supported Devices

This integration supports both old and new versions of Welrok/Terneo thermostats:

- **Old version (OZ without air sensor)** - devices manufactured before June 2025
- **New version (OZ with air sensor / AZ)** - devices manufactured from June 2025

The integration automatically detects the device version during setup and, from v1.1.0, uses the actual parameter set returned by `cmd:1` to expose only capabilities supported by that thermostat/firmware.

## Features

<img width="421" height="378" alt="image" src="https://github.com/user-attachments/assets/c4e45499-fb6e-4a13-a75d-17c640502aa0" />


### Climate Entity
- Turn on/off
- Set target temperature
- Switch between heating/cooling modes
- Schedule (AUTO) and manual (HEAT/COOL) modes
- Preset modes: Schedule, Manual

### Sensors
- Floor temperature
- Air temperature (new version only)
- Target temperature
- Connected power (W)
- Hysteresis
- Sensor corrections

### Energy Monitoring
- **Estimated Heating Energy** - calculated accumulated energy in kWh (compatible with long-term statistics)
- **Heating Time** - accumulated relay-on time in hours
- **Estimated Current Power** - configured heater power while the relay is active, otherwise 0 W
- **Heating Active** - relay state indicator (On/Off)

The estimated energy and heating-time counters are persisted by Home Assistant and survive integration/Home Assistant restarts. When upgrading from 1.0.x, the integration attempts to migrate the previous restored sensor values.

> **Note:** Energy/power values are estimates based on the configured connected power and relay state; they are not measurements from an energy meter.


### Diagnostics (v1.1.0)
Diagnostic entities are created only when the corresponding telemetry key is reported by the device and are disabled by default. They include:

- Wi-Fi RSSI
- Internal and MCU temperatures
- Air-sensor humidity
- Timer remaining time
- Last reboot reasons
- Reported setpoint step
- Floor sensor open/short circuit faults
- Air sensor loss / connection / low battery
- Internal overheat and overheat-control fault
- Time sync/timekeeping faults
- Zero-cross detection fault
- Long-load warning and proportional emergency mode
- API diagnostics: consecutive status failures, last successful status/parameter updates, last API error

All device telemetry diagnostics reuse the existing `cmd:4` poll and do not add extra periodic HTTP requests.

### Switches
- Power on/off
- Children lock
- Cooling mode (vs heating)
- Pre-heating
- Night brightness mode
- Window open detection (new version only)

### Number Controls
- Display brightness (0-10)
- Hysteresis setting

### Select Controls
- Control type:
  - Floor sensor
  - Air sensor (new version only)
  - Air with floor limit (new version only)

### Services
- `terneo.set_floor_limits` - Set min/max floor temperature limits
- `terneo.set_air_limits` - Set min/max air temperature limits (new version only)

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the three dots menu and select "Custom repositories"
4. Add this repository URL with category "Integration"
5. Install "Terneo Thermostat"
6. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/terneo` folder to your `config/custom_components` directory
2. Restart Home Assistant

## Configuration

### GUI Configuration (Recommended)

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for "Terneo"
4. Enter the IP address and serial number of your thermostat
5. The integration will automatically detect the device version and supported capabilities

To change the IP address/hostname later, use **Reconfigure** from the integration entry instead of removing and re-adding the thermostat.

### Configuration Options

After adding the integration, you can configure:

- **Update interval** - How often to poll current status with `cmd:4` (10-300 seconds, default: 10)
- **Connection timeout** - HTTP request timeout (7-120 seconds, default: 7)

Full parameter data (`cmd:1`) is refreshed separately every 120 seconds to reduce load on the thermostat API. Read requests are retried once after transient timeouts/malformed responses, and a thermostat is marked unavailable only after three consecutive failed status cycles.

## API Documentation

This integration uses the Welrok Local API:

- [New version (OZ with air sensor)](https://welrok-local-api.readthedocs.io/en/latest/OZ/en/parameters.html)
- [Old version (OZ without air sensor)](https://welrok-local-api.readthedocs.io/en/latest/Old/en/parameters.html)

### Security Note

By default, local API control without a security token is blocked on the device for security reasons. To enable local control, set the `bLc` parameter to `oFF` on your thermostat.

- [New version (OZ with air sensor)](https://welrok-local-api.readthedocs.io/en/latest/OZ/en/safety.html)
- [Old version (OZ without air sensor)](https://welrok-local-api.readthedocs.io/en/latest/Old/en/safety.html)

## Parameters Supported

### Common Parameters (both versions)
| Parameter | Description |
|-----------|-------------|
| mode | Operation mode: schedule=0, manual=3 |
| controlType | Control: floor=0, air=1, air with floor limit=2 |
| manualFloorTemperature | Manual mode floor setpoint |
| awayFloorTemperature | Away mode floor setpoint |
| hysteresis | Temperature hysteresis |
| brightness | Display brightness (0-10) |
| upperLimit / lowerLimit | Floor temperature limits |
| powerOff | Device power state |
| childrenLock | Children lock |
| coolingControlWay | Heating=0, Cooling=1 |
| preControl | Pre-heating mode |
| useNightBright | Night brightness mode |

### New Version Only
| Parameter | Description |
|-----------|-------------|
| manualAir | Manual mode air setpoint |
| awayAir | Away mode air setpoint |
| upperAirLimit / lowerAirLimit | Air temperature limits |
| minTempAdvancedMode / maxTempAdvancedMode | Floor limits in air control mode |
| airCorrection | Air sensor correction |
| bleSensorInterval | Wireless sensor poll interval |
| windowOpenControl | Window open detection |

## Troubleshooting

### Cannot connect to device
- Ensure the thermostat is connected to your network
- Check that the IP address is correct
- Verify that local API is enabled (`bLc` = `oFF`)

### Commands not working
- Check if `lanBlock` (parameter 114) is disabled
- Ensure the device is not in cloud-only mode

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License.

## Credits

- Original integration by [@Makave1i](https://github.com/Makave1i)
- Extended by [@DevRedOWL](https://github.com/DevRedOWL)
- Rewrited by [@titovskiy](https://github.com/titovskiy)
