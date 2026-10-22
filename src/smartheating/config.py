"""Read the existing deployment shape plus explicit v2 settings."""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from .measurements import Source
from .model import Emitter, Room
from .validation import boolean, bounded, mapping, number, string

NAMES = dict(
    zip(
        (
            "livingroom",
            "corridor",
            "bathroom",
            "entrance",
            "upper_corridor",
            "wardrobe",
            "upper_bathroom",
            "office",
            "kidsroom",
            "bedroom",
            "garage",
        ),
        (
            "Salon",
            "Korytarz",
            "Łazienka",
            "Wiatrołap",
            "Korytarz górny",
            "Garderoba",
            "Łazienka górna",
            "Biuro",
            "Pokój dzieci",
            "Sypialnia",
            "Garaż",
        ),
        strict=True,
    )
)


@dataclass(frozen=True)
class Config:
    rooms: tuple[Room, ...]
    output: str
    state_path: Path
    config_id: str
    shadow: bool = True
    active_authorized: bool = False
    base_topic: str = "smart_heating_v2"
    entity_prefix: str = "sh2"
    discovery: str = "homeassistant"
    timezone: str = "Europe/Warsaw"
    cycle_s: int = 5
    ttl_s: float = 1800
    rad_factor: float = 4
    rad_threshold: float = 0
    warm_offset: float = 0.5
    freeze_offset: float = 0.5
    freeze_entity: str = ""
    safety_on: float = 0.5
    safety_off: float = 0.2
    safety_delay_s: float = 900
    safety_diagnostic_s: float = 3600
    safety_offset: float = 4
    slew_per_minute: float = 0.5
    min_setpoint: float = 15
    max_setpoint: float = 30
    update_threshold: float = 0.5
    retry_s: float = 30
    max_attempts: int = 3
    retry_cooldown_s: float = 900
    plan_s: float = 300
    margin_s: float = 1800
    max_lead_s: float = 86400
    initial_safety: bool | None = None
    initial_warm: bool | None = None
    commit: str = "unpackaged"
    heating_energy: str = "sensor.boiler_energy_heating"
    measurement_sources: dict[str, Source] = field(default_factory=dict)

    @classmethod
    def parse(cls, raw: object) -> "Config":
        args = mapping(raw)
        v2 = mapping(args.get("v2", {}))
        if number(v2.get("schema", 2)) != 2:
            raise ValueError("Unsupported configuration schema")
        cfg = mapping(args.get("config", {}))
        floor = mapping(args["wam_factors"])
        rad = mapping(args["rads_factors"])
        sensors = mapping(args["HAL_room_temperatures"])
        heads = mapping(args["HAL_climate_TRVs"])
        defaults = mapping(args["default_setpoints"])
        overrides = mapping(v2.get("rooms", {}))
        sources = {
            key: Source.parse(value, counter=key == "energy")
            for key, value in mapping(v2.get("measurement_sources", {})).items()
        }
        if set(sources) - (set(floor) | set(rad) | {"energy"}):
            raise ValueError("Unknown room in measurement_sources")
        rooms: list[Room] = []
        for key, weight in {**floor, **rad}.items():
            if key not in NAMES or key not in sensors:
                raise ValueError(f"Unknown room or missing sensor: {key}")
            is_floor = key in floor
            room_cfg = mapping(overrides.get(key, {}))
            head_keys = ("bedroom_left", "bedroom_right") if key == "bedroom" else (key,)
            trvs = () if is_floor else tuple(string(heads[h]) for h in head_keys)
            rooms.append(
                Room(
                    key,
                    NAMES[key],
                    Emitter.FLOOR if is_floor else Emitter.RADIATOR,
                    string(sensors[key]),
                    string(
                        room_cfg.get("schedule", f"switch.schedule_{key.replace('_', '')}heating")
                    ),
                    bounded(weight, 0, 1000),
                    bounded(defaults[key], 5, 30),
                    trvs,
                    bounded(room_cfg.get("short_drop", 0.5 if is_floor else 1), 0, 10),
                    bounded(room_cfg.get("long_cap", 18 if is_floor else 17), 5, 30),
                    bounded(room_cfg.get("warmup_rate", 0.25 if is_floor else 0.5), 0.01, 10),
                    boolean(room_cfg.get("away_exempt", key == "garage")),
                    boolean(room_cfg.get("safety", key in ("bedroom", "kidsroom"))),
                )
            )
        if "corridor" not in floor or not any(r.weight > 0 for r in rooms if r.key in floor):
            raise ValueError("Floor voting requires corridor and nonzero weights")
        if not any(r.weight > 0 for r in rooms if r.key in rad):
            raise ValueError("Radiator voting requires nonzero weights")
        if set(floor) & set(rad):
            raise ValueError("Room cannot belong to both voting groups")
        shadow = boolean(v2.get("shadow", True))
        authorized = boolean(v2.get("active_authorized", False))
        if not shadow and not authorized:
            raise ValueError("Active control requires completed takeover and active_authorized")
        mqtt = mapping(args.get("mqtt_climates", {}))
        zone = string(v2.get("timezone", "Europe/Warsaw"))
        ZoneInfo(zone)
        safety = v2.get("initial_safety")
        warm = v2.get("initial_warm")
        if number(v2.get("min_setpoint", 15)) > number(v2.get("max_setpoint", 30)):
            raise ValueError("min_setpoint must not exceed max_setpoint")
        if number(v2.get("safety_off", 0.2)) >= number(v2.get("safety_on", 0.5)):
            raise ValueError("Safety release threshold must be below activation")
        # AppDaemon injects runtime metadata (including pathlib.Path) into args.
        # Hash only the configuration actually consumed by this application.
        config_keys = (
            "module",
            "class",
            "mqtt_plugin",
            "hass_plugin",
            "mqtt_climates",
            "config",
            "v2",
            "wam_factors",
            "rads_factors",
            "default_setpoints",
            "HAL_room_temperatures",
            "HAL_climate_TRVs",
            "HAL_output",
            "HAL_inputs",
        )
        canonical = {key: args[key] for key in config_keys if key in args}
        return cls(
            rooms=tuple(rooms),
            output=string(mapping(args["HAL_output"])["thermostat_setpoint"]),
            state_path=Path(string(v2.get("state_path", "runtime/smartheating-v2.json"))),
            config_id=hashlib.sha256(
                json.dumps(canonical, sort_keys=True, allow_nan=False).encode()
            ).hexdigest()[:16],
            shadow=shadow,
            active_authorized=authorized,
            base_topic="smart_heating_v2"
            if shadow
            else string(mqtt.get("base_topic", "smart_heating")),
            entity_prefix="sh2" if shadow else string(mqtt.get("entity_prefix", "sh")),
            discovery=string(mqtt.get("discovery_prefix", "homeassistant")),
            timezone=zone,
            cycle_s=int(bounded(cfg.get("cycle_time", 5), 1, 60)),
            ttl_s=bounded(v2.get("measurement_ttl_s", 1800), 30, 86400),
            rad_factor=bounded(cfg.get("rads_error_factor", 4), 0, 20),
            rad_threshold=number(cfg.get("force_burn_thres", 0)),
            warm_offset=bounded(cfg.get("warm_flag_offset", 0.5), -5, 5),
            freeze_offset=bounded(cfg.get("frezzing_flag_offset", 0.5), -5, 5),
            freeze_entity=string(mapping(args.get("HAL_inputs", {})).get("frezzing_flag", "")),
            safety_offset=bounded(
                cfg.get("force_flow_offset", cfg.get("force_flow_off", 4)), 0, 10
            ),
            slew_per_minute=bounded(v2.get("slew_per_minute", 0.5), 0.01, 10),
            min_setpoint=bounded(v2.get("min_setpoint", 15), 5, 30),
            max_setpoint=bounded(v2.get("max_setpoint", 30), 15, 35),
            update_threshold=bounded(cfg.get("error_offset_update_threshold", 0.5), 0.1, 2),
            initial_safety=None if safety is None else boolean(safety),
            initial_warm=None if warm is None else boolean(warm),
            commit=string(v2.get("commit", "unpackaged")),
            heating_energy=string(v2.get("heating_energy", "sensor.boiler_energy_heating")),
            measurement_sources=sources,
            safety_on=bounded(v2.get("safety_on", 0.5), 0.1, 5),
            safety_off=bounded(v2.get("safety_off", 0.2), 0, 2),
            safety_delay_s=bounded(v2.get("safety_delay_s", 900), 60, 3600),
            safety_diagnostic_s=bounded(v2.get("safety_diagnostic_s", 3600), 900, 86400),
            retry_s=bounded(v2.get("retry_s", 30), 5, 600),
            max_attempts=int(bounded(v2.get("max_attempts", 3), 1, 5)),
            retry_cooldown_s=bounded(v2.get("retry_cooldown_s", 900), 60, 3600),
            margin_s=bounded(v2.get("margin_s", 1800), 0, 14400),
            max_lead_s=bounded(v2.get("max_lead_s", 86400), 300, 86400),
        )
