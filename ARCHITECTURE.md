# AppDaemon Architecture Rules

This document describes the architecture rules used by SmartHeating and intended
for future AppDaemon applications in this Home Assistant setup.

## Core Model

AppDaemon owns application logic and runtime state.

Home Assistant owns physical devices, integrations, dashboards, automations, and
external signals.

MQTT discovery is the interface used by AppDaemon applications to expose their
own entities to Home Assistant.

```text
Home Assistant physical entities
        -> AppDaemon get_state / listen_state
        -> application logic and runtime state
        -> MQTT discovery + MQTT state topics
        -> Home Assistant app-owned entities
        -> MQTT command topics
        -> AppDaemon
```

## Rules

1. Physical and external inputs are read from Home Assistant.

   Examples:
   - room temperature sensors
   - physical TRV climate entities
   - boiler entities
   - weather/freezing indicators
   - contact sensors and other real device states

2. App-owned entities are created by AppDaemon through MQTT discovery.

   Examples:
   - virtual climate entities
   - diagnostic sensors
   - runtime binary sensors
   - manual control switches

3. App-owned entities are controlled through MQTT command topics.

   AppDaemon must not create an MQTT entity and then use Home Assistant
   `get_state` or `listen_state` as the command path for that same entity.

4. Home Assistant helpers are not application state storage.

   Do not use `input_number`, `input_boolean`, `input_select`, or similar helpers
   to persist runtime values such as internal offsets, WAM values, virtual
   setpoints, or manual flags.

5. Helpers are allowed for Home Assistant-native UI or automation workflows.

   A helper can be valid when it belongs to a separate HA workflow, dashboard
   control, schedule, timer, or automation that is not acting as AppDaemon's
   internal state store.

6. MQTT plugin is required for apps that expose MQTT entities.

   If an app creates entities via MQTT discovery, it should also receive
   commands via MQTT subscribe. Do not add an optimistic Home Assistant
   `listen_state` fallback for app-owned MQTT entities.

7. AppDaemon apps use `appdaemon_common` for lifecycle and health.

   Apps should inherit from `HealthAppBase`, split startup into ordered
   `@init_step` methods, use named timer/listener helpers, and expose one
   standardized MQTT health sensor.

8. Safe state belongs to the app base.

   Application code should call `enter_safe_state(...)` on unrecoverable
   runtime or hardware failures. The common base marks the health entity as
   `faulted`, cancels registered timers/listeners, and then calls the app's
   `on_enter_safe_state()` hook for app-specific publishing or cleanup.

## Entity Ownership

### Home Assistant-Owned Entities

These are configured by integrations, devices, or HA helpers. AppDaemon can read
or control them through Home Assistant services.

Examples:
```text
sensor.livingroom_temperature
climate.office_trv
number.thermostat_hc1_manual_temperature_2
binary_sensor.some_window_contact
```

### AppDaemon-Owned Entities

These are created and updated by AppDaemon with MQTT discovery. Home Assistant is
only the UI/API consumer for these entities.

Examples:
```text
climate.sh_livingroom
switch.sh_warm_flag
switch.sh_force_flow_safety_rooms
sensor.sh_total_wam
binary_sensor.sh_forced_burn
```

## MQTT Discovery Pattern

AppDaemon publishes retained discovery payloads:

```text
homeassistant/<domain>/<object_id>/config
```

Examples:
```text
homeassistant/climate/sh_livingroom/config
homeassistant/switch/sh_warm_flag/config
homeassistant/sensor/sh_total_wam/config
```

Each discovery payload should include:

- `name`
- `unique_id`
- `default_entity_id`
- state topic
- command topic, for controllable entities
- availability topic
- shared device metadata

Application state is then published to app topics:

```text
smart_heating/livingroom/temperature/state
smart_heating/livingroom/temperature/set
smart_heating/livingroom/current_temperature/state
smart_heating/system/control/warm_flag/state
smart_heating/system/control/warm_flag/set
smart_heating/system/diagnostic/total_wam/state
```

## Recommended App Structure

Each AppDaemon app should clearly define:

- `inputs`: Home Assistant entities read by the app
- `outputs`: physical Home Assistant entities controlled by the app
- `mqtt_entities`: app-owned entities exposed through MQTT discovery
- `runtime_state`: in-memory app state
- `diagnostics`: MQTT sensors and binary sensors used for debugging

Each AppDaemon app should also define:

- `health_entity_id`: the MQTT discovery sensor used by `HealthAppBase`
- `health_unique_id`: stable MQTT discovery unique ID for the health sensor
- `mqtt_plugin`: the AppDaemon MQTT plugin name, usually `MQTT`
- `heartbeat_s`: heartbeat interval in seconds

## AppDaemon Common Contract

`appdaemon_common` is a shared AppDaemon package kept outside individual app
repositories. It should not be copied into SmartHeating or any other app repo.
AppDaemon must have the parent directory of `appdaemon_common` on its Python
import path.

Example AppDaemon configuration:

```yaml
appdaemon:
  import_paths:
    - /addon_configs/a0d7b954_appdaemon/apps
```

Use the directory that contains the `appdaemon_common` folder, not the
`appdaemon_common` folder itself.

Use `HealthAppBase` when an app should expose lifecycle state to Home Assistant:

```python
from appdaemon_common import HealthAppBase, init_step


class MyApp(HealthAppBase):
    @init_step("config", order=10)
    def init_config_step(self):
        ...
```

Expected health states:

```text
init
running
degraded
faulted
```

The health sensor is an AppDaemon-owned MQTT entity. It is not a Home Assistant
helper and should not be used as runtime state storage.

For SmartHeating:

```text
sensor.sh_health
```

Use a stable explicit unique ID such as:

```yaml
health_entity_id: sensor.sh_health
health_unique_id: smart_heating_sh_health
```

This avoids collisions with older retained MQTT discovery payloads if the health
entity name is changed later.

SmartHeating also uses the common base for:

- ordered init steps
- common heartbeat logging
- health attributes such as config hash, last loop time, and last output
- named main loop timer
- named Home Assistant state listeners
- common safe-state transition

## Anti-Patterns

Avoid:

```text
AppDaemon creates MQTT entity -> AppDaemon reads that entity from HA get_state
```

Avoid:

```text
AppDaemon runtime value -> input_number/input_boolean helper -> AppDaemon reads it back
```

Prefer:

```text
HA UI -> MQTT command topic -> AppDaemon runtime state -> MQTT state topic -> HA UI
```

Prefer:

```text
Physical HA entity -> AppDaemon get_state/listen_state -> app logic
```

## SmartHeating Current Contract

SmartHeating reads:

- room temperature sensors from Home Assistant
- physical TRV entities from Home Assistant
- boiler/thermostat entities from Home Assistant
- optional external freezing flag from Home Assistant

SmartHeating owns and exposes:

- virtual room climates
- manual control switches
- WAM and offset diagnostics
- forced burn diagnostics
- safety flow diagnostics

SmartHeating does not use Home Assistant helpers as runtime state storage.
