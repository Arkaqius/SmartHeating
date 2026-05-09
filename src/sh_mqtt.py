"""
MQTT discovery and state publishing for SmartHeating managed climates.
"""

import json
import re
from typing import Any, Optional

from sh_types import (
    DEFAULT_ROOM_FRIENDLY_NAMES,
    DEFAULT_ROOM_SETPOINT,
    MqttClimateRoom,
)


INVALID_STATES = (None, "unknown", "unavailable")


MQTT_CONTROL_SWITCHES: dict[str, dict[str, str]] = {
    "warm_flag": {
        "name": "Dogrzanie",
        "icon": "mdi:heat-wave",
    },
    "force_flow_safety_rooms": {
        "name": "Wymuszenie przepływu - pokoje bezpieczeństwa",
        "icon": "mdi:radiator",
    },
}

MQTT_NUMERIC_DIAGNOSTICS: dict[str, dict[str, str]] = {
    "total_wam": {
        "name": "WAM całkowity",
        "icon": "mdi:scale-balance",
        "unit": "°C",
    },
    "output_offset": {
        "name": "Offset wyjściowy",
        "icon": "mdi:thermometer-lines",
        "unit": "°C",
    },
    "output_setpoint": {
        "name": "Zadanie wyjściowe kotła",
        "icon": "mdi:thermostat",
        "unit": "°C",
    },
    "forced_burn_offset": {
        "name": "Offset wymuszonego grzania",
        "icon": "mdi:fire-alert",
        "unit": "°C",
    },
    "safety_room_error": {
        "name": "Błąd pokoju bezpieczeństwa",
        "icon": "mdi:home-thermometer-outline",
        "unit": "°C",
    },
    "max_radiator_error": {
        "name": "Maksymalny błąd grzejników",
        "icon": "mdi:radiator",
        "unit": "°C",
    },
    "loop_duration": {
        "name": "Czas pętli SmartHeating",
        "icon": "mdi:timer-outline",
        "unit": "s",
    },
}

MQTT_BINARY_DIAGNOSTICS: dict[str, dict[str, str]] = {
    "forced_burn": {
        "name": "Wymuszone grzanie aktywne",
        "icon": "mdi:fire-alert",
    },
    "force_flow_safety_rooms": {
        "name": "Wymuszenie przepływu aktywne",
        "icon": "mdi:radiator",
    },
}

MQTT_TEXT_DIAGNOSTICS: dict[str, dict[str, str]] = {
    "output_reasons": {
        "name": "Powody decyzji SmartHeating",
        "icon": "mdi:format-list-bulleted",
    },
}


class MqttClimateMixin:
    """
    Mixin that exposes room setpoints/current temperatures as MQTT climate entities.
    """

    def init_mqtt_climates(self) -> None:
        """
        Publish discovery for app-owned room climates and initialize local setpoints.
        """
        self.mqtt_plugin_api = self.resolve_mqtt_plugin_api()
        self.mqtt_command_topics: dict[str, tuple[str, str]] = {}
        self.mqtt_control_command_topics: dict[str, str] = {}
        self.mqtt_climate_rooms = self.build_mqtt_climate_rooms()
        self.init_mqtt_control_flags()
        self.room_hvac_modes = {
            room_name: self.get_initial_room_hvac_mode(room_name)
            for room_name in self.mqtt_climate_rooms
        }
        self.room_setpoints = {
            room_name: self.get_initial_room_setpoint(room_name)
            for room_name in self.mqtt_climate_rooms
        }
        for room_name, mode in self.room_hvac_modes.items():
            self.apply_room_hvac_mode_to_trvs(room_name, mode)

        for room in self.mqtt_climate_rooms.values():
            self.publish_mqtt_climate_discovery(room)
            self.publish_room_climate_state(room.room)

        self.publish_mqtt_control_discovery()
        self.publish_mqtt_diagnostic_discovery()
        self.publish_mqtt_control_states()
        self.publish_mqtt_diagnostic_states()

        self.log(
            f"Initialized {len(self.mqtt_climate_rooms)} MQTT climate entities.",
            level="INFO",
        )

    def build_mqtt_climate_rooms(self) -> dict[str, MqttClimateRoom]:
        """
        Build room climate metadata from config loaded by ConfigMixin.
        """
        rooms: dict[str, MqttClimateRoom] = {}
        for room_name, temperature_entity in self.room_temperature_entities.items():
            rooms[room_name] = MqttClimateRoom(
                room=room_name,
                friendly_name=self.room_friendly_names.get(
                    room_name, self.format_room_name(room_name)
                ),
                climate_entity=self.get_room_climate_entity(room_name),
                temperature_entity=temperature_entity,
                trv_entities=tuple(
                    self.room_trv_climate_entities.get(room_name, ())
                ),
            )
        return rooms

    def resolve_mqtt_plugin_api(self) -> Any:
        """
        Return the required AppDaemon MQTT plugin API.
        """
        health_mqtt_api = getattr(self, "_health_mqtt_api", None)
        if health_mqtt_api is not None:
            return health_mqtt_api

        configured_plugin = str(self.args.get("mqtt_plugin", "MQTT"))
        try:
            return self.get_plugin_api(configured_plugin)
        except Exception as e:
            self.log_debug(f"MQTT plugin API '{configured_plugin}' unavailable: {e}")

        self.handle_config_error(
            RuntimeError(
                "AppDaemon MQTT plugin is required for SmartHeating MQTT entities."
            )
        )

    def setup_mqtt_climate_listeners(self) -> None:
        """
        Register temperature sensor and setpoint listeners for managed climates.
        """
        for room_name, room in self.mqtt_climate_rooms.items():
            self.listen_state_named(
                f"room_temperature_{room_name}",
                self.room_temperature_update,
                room.temperature_entity,
                room=room_name,
            )

            self.subscribe_mqtt_climate_commands(room_name)

        self.setup_mqtt_control_switch_listeners()

    def subscribe_mqtt_climate_commands(self, room_name: str) -> None:
        """
        Subscribe to MQTT command topics for a managed climate.
        """
        topics = {
            self.mqtt_room_topic(room_name, "temperature/set"): "temperature",
            self.mqtt_room_topic(room_name, "mode/set"): "mode",
        }
        for topic, command in topics.items():
            self.mqtt_command_topics[topic] = (room_name, command)
            self.mqtt_subscribe(topic)
            self.mqtt_plugin_api.listen_event(
                self.mqtt_climate_command_update,
                self.mqtt_event_name,
                topic=topic,
            )

    def publish_mqtt_climate_discovery(self, room: MqttClimateRoom) -> None:
        """
        Publish a retained MQTT discovery payload for a room climate.
        """
        room_name = room.room
        object_id = self.mqtt_object_id(room.climate_entity)
        payload: dict[str, Any] = {
            "name": room.friendly_name,
            "unique_id": f"smart_heating_{object_id}",
            "default_entity_id": room.climate_entity,
            "modes": ["off", "heat"],
            "mode_command_topic": self.mqtt_room_topic(room_name, "mode/set"),
            "current_temperature_topic": self.mqtt_room_topic(
                room_name, "current_temperature/state"
            ),
            "action_topic": self.mqtt_room_topic(room_name, "action/state"),
            "availability_topic": self.mqtt_room_topic(room_name, "availability"),
            "temperature_command_topic": self.mqtt_room_topic(
                room_name, "temperature/set"
            ),
            "min_temp": self.mqtt_min_temp,
            "max_temp": self.mqtt_max_temp,
            "temp_step": self.mqtt_temp_step,
            "precision": self.mqtt_precision,
            "temperature_unit": self.mqtt_temperature_unit,
            "device": self.mqtt_device_info(),
        }

        payload["temperature_state_topic"] = self.mqtt_room_topic(
            room_name, "temperature/state"
        )
        payload["mode_state_topic"] = self.mqtt_room_topic(
            room_name, "mode/state"
        )

        discovery_topic = (
            f"{self.mqtt_discovery_prefix}/climate/{object_id}/config"
        )
        self.mqtt_publish(
            discovery_topic,
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
            retain=True,
        )

    def publish_all_mqtt_climate_states(
        self, kwargs: Optional[dict[str, Any]] = None
    ) -> None:
        """
        Publish current state for every managed climate.
        """
        for room_name in self.mqtt_climate_rooms:
            self.publish_room_climate_state(room_name)

    def init_mqtt_control_flags(self) -> None:
        """
        Initialize app-owned control flags.
        """
        self.control_flags = {flag_key: False for flag_key in MQTT_CONTROL_SWITCHES}

    def publish_mqtt_control_discovery(self) -> None:
        """
        Publish retained MQTT discovery payloads for app-owned control switches.
        """
        for flag_key, meta in MQTT_CONTROL_SWITCHES.items():
            entity_id = self.mqtt_control_switch_entity(flag_key)
            object_id = self.mqtt_object_id(entity_id)
            payload: dict[str, Any] = {
                "name": meta["name"],
                "unique_id": f"smart_heating_{object_id}",
                "default_entity_id": entity_id,
                "icon": meta["icon"],
                "state_topic": self.mqtt_system_topic(f"control/{flag_key}/state"),
                "command_topic": self.mqtt_system_topic(f"control/{flag_key}/set"),
                "availability_topic": self.mqtt_system_topic("availability"),
                "payload_on": "ON",
                "payload_off": "OFF",
                "state_on": "ON",
                "state_off": "OFF",
                "device": self.mqtt_device_info(),
            }
            self.mqtt_publish(
                f"{self.mqtt_discovery_prefix}/switch/{object_id}/config",
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
                retain=True,
            )

    def publish_mqtt_diagnostic_discovery(self) -> None:
        """
        Publish retained MQTT discovery payloads for internal diagnostic entities.
        """
        for key, meta in MQTT_NUMERIC_DIAGNOSTICS.items():
            entity_id = self.mqtt_sensor_entity(key)
            object_id = self.mqtt_object_id(entity_id)
            payload: dict[str, Any] = {
                "name": meta["name"],
                "unique_id": f"smart_heating_{object_id}",
                "default_entity_id": entity_id,
                "icon": meta["icon"],
                "state_topic": self.mqtt_system_topic(f"diagnostic/{key}/state"),
                "availability_topic": self.mqtt_system_topic("availability"),
                "entity_category": "diagnostic",
                "state_class": "measurement",
                "device": self.mqtt_device_info(),
            }
            unit = meta.get("unit")
            if unit:
                payload["unit_of_measurement"] = unit

            self.mqtt_publish(
                f"{self.mqtt_discovery_prefix}/sensor/{object_id}/config",
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
                retain=True,
            )

        for key, meta in MQTT_BINARY_DIAGNOSTICS.items():
            entity_id = self.mqtt_binary_sensor_entity(key)
            object_id = self.mqtt_object_id(entity_id)
            payload = {
                "name": meta["name"],
                "unique_id": f"smart_heating_{object_id}",
                "default_entity_id": entity_id,
                "icon": meta["icon"],
                "state_topic": self.mqtt_system_topic(f"diagnostic/{key}/state"),
                "availability_topic": self.mqtt_system_topic("availability"),
                "payload_on": "ON",
                "payload_off": "OFF",
                "entity_category": "diagnostic",
                "device": self.mqtt_device_info(),
            }
            self.mqtt_publish(
                f"{self.mqtt_discovery_prefix}/binary_sensor/{object_id}/config",
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
                retain=True,
            )

        for key, meta in MQTT_TEXT_DIAGNOSTICS.items():
            entity_id = self.mqtt_sensor_entity(key)
            object_id = self.mqtt_object_id(entity_id)
            payload = {
                "name": meta["name"],
                "unique_id": f"smart_heating_{object_id}",
                "default_entity_id": entity_id,
                "icon": meta["icon"],
                "state_topic": self.mqtt_system_topic(f"diagnostic/{key}/state"),
                "availability_topic": self.mqtt_system_topic("availability"),
                "entity_category": "diagnostic",
                "device": self.mqtt_device_info(),
            }
            self.mqtt_publish(
                f"{self.mqtt_discovery_prefix}/sensor/{object_id}/config",
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
                retain=True,
            )

    def setup_mqtt_control_switch_listeners(self) -> None:
        """
        Register command listeners for app-owned MQTT control switches.
        """
        for flag_key in MQTT_CONTROL_SWITCHES:
            command_topic = self.mqtt_system_topic(f"control/{flag_key}/set")
            self.mqtt_control_command_topics[command_topic] = flag_key
            self.mqtt_subscribe(command_topic)
            self.mqtt_plugin_api.listen_event(
                self.mqtt_control_command_update,
                self.mqtt_event_name,
                topic=command_topic,
            )

    def publish_mqtt_control_states(self) -> None:
        """
        Publish state for every app-owned control switch.
        """
        self.publish_mqtt_system_availability()
        for flag_key in MQTT_CONTROL_SWITCHES:
            self.publish_mqtt_control_state(flag_key)

    def publish_mqtt_control_state(self, flag_key: str) -> None:
        """
        Publish one control switch state.
        """
        self.mqtt_publish(
            self.mqtt_system_topic(f"control/{flag_key}/state"),
            "ON" if self.control_flags.get(flag_key, False) else "OFF",
            retain=True,
        )

    def publish_mqtt_diagnostic_states(self) -> None:
        """
        Publish internal diagnostic states used by dashboards and troubleshooting.
        """
        self.publish_mqtt_system_availability()

        numeric_states = {
            "total_wam": self.last_wam,
            "output_offset": self.last_output_offset,
            "output_setpoint": self.last_output_setpoint,
            "forced_burn_offset": self.last_forced_burn_offset,
            "safety_room_error": self.last_safety_room_error,
            "max_radiator_error": self.get_max_radiator_error(),
            "loop_duration": self.last_loop_duration,
        }
        for key, value in numeric_states.items():
            self.mqtt_publish(
                self.mqtt_system_topic(f"diagnostic/{key}/state"),
                self.format_mqtt_optional_number(value),
                retain=True,
            )

        binary_states = {
            "forced_burn": self.last_forced_burn_active,
            "force_flow_safety_rooms": self.last_force_flow_safety_active,
        }
        for key, value in binary_states.items():
            self.mqtt_publish(
                self.mqtt_system_topic(f"diagnostic/{key}/state"),
                "ON" if value else "OFF",
                retain=True,
            )

        output_reasons = (
            ", ".join(self.last_output_reasons)
            if self.last_output_reasons
            else "none"
        )
        self.mqtt_publish(
            self.mqtt_system_topic("diagnostic/output_reasons/state"),
            output_reasons,
            retain=True,
        )

    def publish_mqtt_system_availability(self) -> None:
        """
        Publish shared availability for SmartHeating MQTT system entities.
        """
        self.mqtt_publish(
            self.mqtt_system_topic("availability"), "online", retain=True
        )

    def publish_room_climate_state(self, room_name: str) -> None:
        """
        Publish current temperature, setpoint, mode, action, and availability.
        """
        temperature = self.get_room_temperature_state(room_name)
        if temperature is None:
            self.mqtt_publish(
                self.mqtt_room_topic(room_name, "availability"),
                "offline",
                retain=True,
            )
            return

        self.mqtt_publish(
            self.mqtt_room_topic(room_name, "availability"), "online", retain=True
        )
        self.mqtt_publish(
            self.mqtt_room_topic(room_name, "current_temperature/state"),
            self.format_mqtt_number(temperature),
            retain=True,
        )
        self.mqtt_publish(
            self.mqtt_room_topic(room_name, "action/state"),
            self.get_room_hvac_action(room_name, temperature),
            retain=True,
        )

        self.mqtt_publish(
            self.mqtt_room_topic(room_name, "temperature/state"),
            self.format_mqtt_number(self.get_room_setpoint(room_name)),
            retain=True,
        )
        self.mqtt_publish(
            self.mqtt_room_topic(room_name, "mode/state"),
            self.room_hvac_modes.get(room_name, "heat"),
            retain=True,
        )

    def room_temperature_update(
        self,
        entity: str,
        attribute: str,
        old: Any,
        new: Any,
        kwargs: dict[str, Any],
    ) -> None:
        """
        Republish a climate state when the room temperature sensor changes.
        """
        room_name = kwargs["room"]
        if old != new:
            self.publish_room_climate_state(room_name)

    def mqtt_climate_command_update(
        self, event_name: str, data: dict[str, Any], kwargs: dict[str, Any]
    ) -> None:
        """
        Handle MQTT setpoint and mode commands.
        """
        if getattr(self, "_safe_state_entered", False):
            self.log_debug("Ignoring MQTT climate command while in safe state.")
            return

        topic = data.get("topic")
        payload = data.get("payload")
        if isinstance(payload, bytes):
            payload = payload.decode()

        command = self.mqtt_command_topics.get(topic)
        if command is None:
            self.log_debug(f"Ignoring MQTT command on unknown topic: {topic}")
            return

        room_name, command_type = command
        if command_type == "temperature":
            self.update_room_setpoint(room_name, payload, source=topic)
        elif command_type == "mode":
            self.update_room_hvac_mode(
                room_name, str(payload).strip().lower(), source=topic
            )

    def mqtt_control_command_update(
        self, event_name: str, data: dict[str, Any], kwargs: dict[str, Any]
    ) -> None:
        """
        Handle MQTT switch commands for app-owned control flags.
        """
        if getattr(self, "_safe_state_entered", False):
            self.log_debug("Ignoring MQTT control command while in safe state.")
            return

        topic = data.get("topic")
        payload = data.get("payload")
        if isinstance(payload, bytes):
            payload = payload.decode()

        flag_key = self.mqtt_control_command_topics.get(topic)
        if flag_key is None:
            self.log_debug(f"Ignoring MQTT control command on unknown topic: {topic}")
            return

        value = self.parse_mqtt_bool(payload)
        if value is None:
            self.log(
                f"Ignoring invalid control payload for {flag_key}: {payload}",
                level="ERROR",
            )
            return
        self.update_mqtt_control_flag(flag_key, value, source=topic)

    def update_mqtt_control_flag(
        self,
        flag_key: str,
        value: bool,
        source: str,
    ) -> None:
        """
        Store a control flag and publish state.
        """
        previous = self.control_flags.get(flag_key)
        self.control_flags[flag_key] = value
        if flag_key == "warm_flag":
            self.warm_flag = value
        elif flag_key == "force_flow_safety_rooms":
            self.force_flow_flag = value

        if previous != value:
            self.log(
                f"Control flag changed: {flag_key} {previous} -> {value} from {source}",
                level="INFO",
            )

        self.publish_mqtt_control_state(flag_key)

    def update_room_setpoint(
        self, room_name: str, raw_value: Any, source: str
    ) -> None:
        """
        Store a room setpoint and mirror it to any physical TRVs for that room.
        """
        try:
            setpoint = float(raw_value)
        except (TypeError, ValueError) as e:
            self.log(
                f"Ignoring invalid setpoint for {room_name} from {source}: "
                f"{raw_value} ({e})",
                level="ERROR",
            )
            return

        setpoint = min(max(setpoint, self.mqtt_min_temp), self.mqtt_max_temp)
        previous = self.room_setpoints.get(room_name)
        self.room_setpoints[room_name] = setpoint
        if previous != setpoint:
            self.log(
                f"Room setpoint changed: {room_name} {previous} -> {setpoint}",
                level="INFO",
            )
        if self.room_hvac_modes.get(room_name, "heat") != "off":
            self.apply_room_setpoint_to_trvs(room_name, setpoint)
        self.publish_room_climate_state(room_name)

    def update_room_hvac_mode(
        self, room_name: str, mode: str, source: str
    ) -> None:
        """
        Store heat/off mode for a managed climate.
        """
        if mode not in ("heat", "off"):
            self.log(
                f"Ignoring unsupported HVAC mode for {room_name} from {source}: {mode}",
                level="ERROR",
            )
            return

        previous = self.room_hvac_modes.get(room_name)
        self.room_hvac_modes[room_name] = mode
        if previous != mode:
            self.log(
                f"Room HVAC mode changed: {room_name} {previous} -> {mode}",
                level="INFO",
            )
        self.apply_room_hvac_mode_to_trvs(room_name, mode)
        self.publish_room_climate_state(room_name)

    def apply_room_hvac_mode_to_trvs(self, room_name: str, mode: str) -> None:
        """
        Mirror heat/off mode to physical TRV climate entities.
        """
        for trv_entity in self.room_trv_climate_entities.get(room_name, ()):
            self.call_service(
                "climate/set_hvac_mode",
                entity_id=trv_entity,
                hvac_mode=mode,
            )
            if mode == "heat":
                self.call_service(
                    "climate/set_temperature",
                    entity_id=trv_entity,
                    temperature=self.get_room_setpoint(room_name),
                )

    def apply_room_setpoint_to_trvs(self, room_name: str, setpoint: float) -> None:
        """
        Mirror the room setpoint to physical TRV climate entities.
        """
        for trv_entity in self.room_trv_climate_entities.get(room_name, ()):
            self.call_service(
                "climate/set_temperature",
                entity_id=trv_entity,
                temperature=setpoint,
            )

    def get_room_temperature_state(self, room_name: str) -> Optional[float]:
        """
        Return the current room temperature from its configured input sensor.
        """
        room = self.mqtt_climate_rooms.get(room_name)
        if room is None:
            return None

        state = self.get_state(room.temperature_entity)
        if state in INVALID_STATES:
            return None
        try:
            return float(state)
        except (TypeError, ValueError):
            return None

    def get_room_setpoint(self, room_name: str) -> float:
        """
        Return the current target temperature for a room.
        """
        return self.room_setpoints.get(room_name, self.default_room_setpoint)

    def get_initial_room_setpoint(self, room_name: str) -> float:
        """
        Prefer physical TRV state, then configured defaults.
        """
        for entity in self.room_trv_climate_entities.get(room_name, ()):
            value = self.get_state(entity, attribute="temperature")
            if value not in INVALID_STATES:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass

        if room_name in self.room_default_setpoints:
            return self.room_default_setpoints[room_name]

        return getattr(self, "default_room_setpoint", DEFAULT_ROOM_SETPOINT)

    def get_initial_room_hvac_mode(self, room_name: str) -> str:
        """
        Prefer physical TRV mode, then heat.
        """
        for entity in self.room_trv_climate_entities.get(room_name, ()):
            state = self.get_state(entity)
            if state in ("heat", "off"):
                return state

        return "heat"

    def get_room_hvac_action(self, room_name: str, temperature: float) -> str:
        """
        Derive climate action from mode and current room error.
        """
        if self.room_hvac_modes.get(room_name, "heat") == "off":
            return "off"
        if self.get_room_setpoint(room_name) - temperature > self.heat_action_threshold:
            return "heating"
        return "idle"

    def mqtt_publish(
        self, topic: str, payload: str, retain: bool = False, qos: int = 0
    ) -> None:
        """
        Publish MQTT via the required AppDaemon MQTT plugin.
        """
        try:
            if hasattr(self.mqtt_plugin_api, "mqtt_publish"):
                self.mqtt_plugin_api.mqtt_publish(
                    topic, payload, retain=retain, qos=qos
                )
            else:
                self.mqtt_plugin_api.call_service(
                    "publish",
                    topic=topic,
                    payload=payload,
                    retain=retain,
                    qos=qos,
                )
        except Exception as e:
            self.handle_hw_error(f"MQTT plugin publish failed for {topic}: {e}")

    def mqtt_subscribe(self, topic: str) -> None:
        """
        Subscribe through the AppDaemon MQTT plugin.
        """
        if hasattr(self.mqtt_plugin_api, "mqtt_subscribe"):
            self.mqtt_plugin_api.mqtt_subscribe(topic)
        else:
            self.mqtt_plugin_api.call_service("subscribe", topic=topic)

    def mqtt_room_topic(self, room_name: str, suffix: str) -> str:
        """
        Build a MQTT topic for a room.
        """
        return f"{self.mqtt_base_topic}/{room_name}/{suffix}"

    def mqtt_system_topic(self, suffix: str) -> str:
        """
        Build a MQTT topic for app-wide system entities.
        """
        return f"{self.mqtt_base_topic}/system/{suffix}"

    def mqtt_device_info(self) -> dict[str, Any]:
        """
        Return common MQTT discovery device metadata.
        """
        return {
            "identifiers": ["smart_heating"],
            "name": "Ogrzewanie",
            "manufacturer": "SmartHeating",
            "model": "AppDaemon",
        }

    def mqtt_object_id(self, entity_id: str) -> str:
        """
        Convert an entity_id into a MQTT discovery object id.
        """
        object_id = entity_id.split(".", 1)[1] if "." in entity_id else entity_id
        return re.sub(r"[^a-zA-Z0-9_-]", "_", object_id)

    def get_room_climate_entity(self, room_name: str) -> str:
        """
        Return the generated climate entity_id for a room.
        """
        return f"climate.{self.mqtt_entity_prefix}_{room_name}"

    def mqtt_control_switch_entity(self, flag_key: str) -> str:
        """
        Return the generated switch entity_id for a control flag.
        """
        return f"switch.{self.mqtt_entity_prefix}_{flag_key}"

    def mqtt_sensor_entity(self, sensor_key: str) -> str:
        """
        Return the generated sensor entity_id for a diagnostic value.
        """
        return f"sensor.{self.mqtt_entity_prefix}_{sensor_key}"

    def mqtt_binary_sensor_entity(self, sensor_key: str) -> str:
        """
        Return the generated binary_sensor entity_id for a diagnostic value.
        """
        return f"binary_sensor.{self.mqtt_entity_prefix}_{sensor_key}"

    def format_mqtt_number(self, value: float) -> str:
        """
        Format MQTT numeric payloads compactly while preserving decimal precision.
        """
        return f"{round(value, 2):.2f}".rstrip("0").rstrip(".")

    def format_mqtt_optional_number(self, value: Optional[float]) -> str:
        """
        Format optional numeric payloads for MQTT sensors.
        """
        if value is None:
            return "unknown"
        return self.format_mqtt_number(value)

    def parse_mqtt_bool(self, payload: Any) -> Optional[bool]:
        """
        Parse a MQTT switch command payload.
        """
        value = str(payload).strip().lower()
        if value in ("on", "true", "1", "yes"):
            return True
        if value in ("off", "false", "0", "no"):
            return False
        return None

    def get_max_radiator_error(self) -> Optional[float]:
        """
        Return the maximum radiator error when available.
        """
        if not isinstance(self.rads_error, list) or not self.rads_error:
            return None
        return max(self.rads_error)

    def format_room_name(self, room_name: str) -> str:
        """
        Convert a config room key into a friendly name.
        """
        return DEFAULT_ROOM_FRIENDLY_NAMES.get(
            room_name, room_name.replace("_", " ").title()
        )
