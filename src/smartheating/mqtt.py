"""MQTT discovery contract. Active IDs stay compatible; shadow owns a separate device."""

import json
from uuid import uuid4

from . import __version__
from .config import Config
from .energy import ENERGY_MODES
from .metrics import COUNTERS, METRIC_MODES
from .model import Mode, Publisher


class Mqtt:
    def __init__(self, config: Config, publisher: Publisher) -> None:
        self.config = config
        self.publisher = publisher
        self.cache: dict[str, str] = {}
        self.session = uuid4().hex

    def command_topic(self, suffix: str) -> str:
        return self.topic(f"session/{self.session}/{suffix}")

    def rotate_session(self) -> None:
        self.session = uuid4().hex
        self.cache.clear()

    def topic(self, suffix: str) -> str:
        return f"{self.config.base_topic}/{suffix}"

    def state(self, suffix: str, value: object, *, force: bool = False) -> None:
        payload = value if isinstance(value, str) else json.dumps(value, allow_nan=False)
        topic = self.topic(suffix)
        if force or self.cache.get(topic) != payload:
            self.publisher.publish(topic, payload, True)
            self.cache[topic] = payload

    def available(self, online: bool) -> None:
        self.state("system/availability", "online" if online else "offline", force=True)

    def discover(self, domain: str, key: str, name: str, fields: dict[str, object]) -> None:
        object_id = f"{self.config.entity_prefix}_{key}"
        device_id = "smart_heating_v2_shadow" if self.config.shadow else "smart_heating"
        payload = {
            "name": name,
            "unique_id": f"smart_heating_{object_id}",
            "default_entity_id": f"{domain}.{object_id}",
            "availability_topic": self.topic("system/availability"),
            "device": {
                "identifiers": [device_id],
                "name": "Ogrzewanie 2.0 — obserwacja" if self.config.shadow else "Ogrzewanie",
                "manufacturer": "SmartHeating",
                "model": "AppDaemon",
                "sw_version": __version__,
            },
            **fields,
        }
        if "availability" in fields:
            payload.pop("availability_topic", None)
        self.publisher.publish(
            f"{self.config.discovery}/{domain}/{object_id}/config",
            json.dumps(payload, ensure_ascii=False),
            True,
        )

    def sensor(self, key: str, unit: str | None = None, counter: bool = False) -> None:
        fields: dict[str, object] = {
            "state_topic": self.topic(f"system/diagnostic/{key}/state"),
            "expire_after": 900,
            "availability": [
                {"topic": self.topic("system/availability")},
                {"topic": self.topic(f"system/diagnostic/{key}/availability")},
            ],
            "availability_mode": "all",
        }
        if unit:
            fields.update(
                unit_of_measurement=unit,
                state_class="total_increasing" if counter else "measurement",
            )
            if unit == "°C" and key not in (
                "total_wam",
                "output_offset",
                "forced_burn_offset",
                "safety_room_error",
                "max_radiator_error",
                "safety_candidate_offset",
            ):
                fields["device_class"] = "temperature"
            if unit == "kWh":
                fields["device_class"] = "energy"
        if key.endswith(("_readiness", "_override_until")):
            fields["device_class"] = "timestamp"
        self.discover("sensor", key, key.replace("_", " "), fields)

    def diagnostic(self, key: str, value: object, *, force: bool = False) -> None:
        self.state(
            f"system/diagnostic/{key}/availability",
            "offline" if value is None else "online",
            force=force,
        )
        if value is not None:
            self.state(f"system/diagnostic/{key}/state", value, force=force)

    def setup(self) -> None:
        for energy_mode in ENERGY_MODES:
            self.sensor(f"energy_{energy_mode}_kwh", "kWh", counter=True)
        self.sensor("energy_issue")
        for room in self.config.rooms:
            prefix = room.key
            self.discover(
                "climate",
                prefix,
                room.name,
                {
                    "temperature_state_topic": self.topic(f"{prefix}/temperature/state"),
                    "temperature_command_topic": self.command_topic(f"{prefix}/temperature/set"),
                    "current_temperature_topic": self.topic(f"{prefix}/current_temperature/state"),
                    "mode_state_topic": self.topic(f"{prefix}/mode/state"),
                    "mode_command_topic": self.command_topic(f"{prefix}/mode/set"),
                    "json_attributes_topic": self.topic(f"{prefix}/attributes"),
                    "modes": ["off", "heat"],
                    "min_temp": 5,
                    "max_temp": 30,
                    "temp_step": 0.5,
                    "precision": 0.1,
                    "temperature_unit": "C",
                    # No action_topic: virtual demand must not pretend to confirm heating.
                    "availability": [
                        {"topic": self.topic("system/availability")},
                        {"topic": self.topic(f"{prefix}/availability")},
                    ],
                    "availability_mode": "all",
                },
            )
            self.discover(
                "button",
                f"{prefix}_resume",
                f"{room.name}: wróć do harmonogramu",
                {"command_topic": self.command_topic(f"{prefix}/resume/set")},
            )
            for suffix in ("temperature", "target", "comfort_target"):
                self.sensor(f"{prefix}_{suffix}", "°C")
            for suffix in (
                "mode",
                "readiness",
                "issues",
                "safety",
                "trv_status",
                "measurement_status",
                "target_source",
                "override_until",
            ):
                self.sensor(f"{prefix}_{suffix}")
            if room.safety:
                self.sensor(f"{prefix}_safety_candidate")
            for mode in METRIC_MODES:
                for metric in COUNTERS:
                    self.sensor(
                        f"{prefix}_{mode}_{metric}",
                        "°C·h" if "degree" in metric else "h",
                        counter=True,
                    )
        for key in ("warm_flag", "force_flow_safety_rooms"):
            self.discover(
                "switch",
                key,
                key.replace("_", " "),
                {
                    "state_topic": self.topic(f"system/control/{key}/state"),
                    "command_topic": self.command_topic(f"system/control/{key}/set"),
                },
            )
        self.discover(
            "select",
            "profile",
            "Profil domu",
            {
                "options": [Mode.HOME.value, Mode.SHORT.value, Mode.LONG.value],
                "state_topic": self.topic("system/control/profile/state"),
                "command_topic": self.command_topic("system/control/profile/set"),
            },
        )
        self.discover(
            "text",
            "arrival",
            "Powrót (ISO 8601 ze strefą; puste = anuluj)",
            {
                "state_topic": self.topic("system/control/arrival/state"),
                "command_topic": self.command_topic("system/control/arrival/set"),
                "max": 40,
            },
        )
        self.discover(
            "button",
            "return_now",
            "Wracam teraz",
            {
                "command_topic": self.command_topic("system/control/return_now/set"),
            },
        )
        self.discover(
            "datetime",
            "arrival_at",
            "Termin powrotu",
            {
                "state_topic": self.topic("system/control/arrival/state"),
                "command_topic": self.command_topic("system/control/arrival/set"),
                "value_template": "{{ value if value else 'None' }}",
                "retain": False,
            },
        )
        self.discover(
            "button",
            "cancel_arrival",
            "Anuluj termin powrotu",
            {"command_topic": self.command_topic("system/control/cancel_arrival/set")},
        )
        self.sensor("system_status")
        self.discover(
            "sensor",
            "system_summary",
            "Stan sterowania",
            {
                "state_topic": self.topic("system/diagnostic/system_status/state"),
                "json_attributes_topic": self.topic("system/summary"),
                "expire_after": 900,
            },
        )
        self.sensor("command_feedback")
        self.sensor("control_reason")
        self.sensor("actual_mode_label")
        for key in (
            "total_wam",
            "output_offset",
            "output_setpoint",
            "confirmed_setpoint",
            "forced_burn_offset",
            "safety_room_error",
            "max_radiator_error",
            "safety_candidate_offset",
        ):
            self.sensor(key, "°C")
        for key in (
            "version",
            "config_id",
            "commit",
            "actual_mode",
            "output_reasons",
            "command_status",
            "evaluation_started",
            "evaluation_kind",
            "shadow_assumptions",
        ):
            self.sensor(key)
        for key in ("forced_burn", "force_flow_safety_rooms"):
            self.discover(
                "binary_sensor",
                key,
                key,
                {
                    "state_topic": self.topic(f"system/diagnostic/{key}/state"),
                    "expire_after": 900,
                },
            )
        self.discover(
            "binary_sensor",
            "runtime",
            "Sterownik odpowiada",
            {
                "state_topic": self.topic("system/heartbeat"),
                "expire_after": 90,
            },
        )

    def command_topics(self) -> list[str]:
        topics = [
            self.command_topic(f"{r.key}/{kind}/set")
            for r in self.config.rooms
            for kind in ("temperature", "mode", "resume")
        ]
        topics += [
            self.command_topic(f"system/control/{key}/set")
            for key in (
                "warm_flag",
                "force_flow_safety_rooms",
                "profile",
                "arrival",
                "return_now",
                "cancel_arrival",
            )
        ]
        return topics + [self.topic(f"{r.key}/schedule/set") for r in self.config.rooms]
