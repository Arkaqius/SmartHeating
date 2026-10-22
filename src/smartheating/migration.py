"""Prepare reviewable local snapshots and scheduler changes; never mutate Home Assistant."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .ha_api import reader_from_environment
from .schedules import DailySchedule
from .validation import bounded, mapping, sequence


def scheduler_patch(
    config: Config, states: dict[str, object], base_topic: str = "smart_heating"
) -> dict[str, object]:
    result: dict[str, object] = {}
    for room in config.rooms:
        original = mapping(states[room.schedule])
        parsed = DailySchedule.from_ha(original, config.timezone)
        attrs = mapping(original["attributes"])
        actions: list[dict[str, object]] = []
        for index, slot in enumerate(parsed.slots):
            actions.append(
                {
                    "service": "mqtt.publish",
                    "data": {
                        "topic": f"{base_topic}/{room.key}/schedule/set",
                        "retain": False,
                        "payload": json.dumps(
                            {
                                "source": room.schedule,
                                "slot": index,
                                "temperature": slot.temperature,
                            }
                        ),
                    },
                }
            )
        result[room.schedule] = {"before": attrs, "after": {**attrs, "actions": actions}}
    return result


def initial_state(config: Config, states: dict[str, object], now: datetime) -> dict[str, object]:
    flags = {
        key: mapping(states[f"switch.sh_{key}"])["state"]
        for key in ("force_flow_safety_rooms", "warm_flag")
    }
    if any(value not in ("on", "off") for value in flags.values()):
        raise ValueError("Cannot migrate unknown switch values")
    disabled: list[str] = []
    overrides: dict[str, object] = {}
    for room in config.rooms:
        climate = mapping(states[f"climate.sh_{room.key}"])
        if climate.get("state") not in ("off", "heat"):
            raise ValueError(f"Cannot migrate unavailable room {room.key}")
        if climate["state"] == "off":
            disabled.append(room.key)
        scheduled = DailySchedule.from_ha(states[room.schedule], config.timezone).at(now)
        target = bounded(mapping(climate["attributes"])["temperature"], 5, 30)
        if abs(target - scheduled.temperature) > 0.01:
            overrides[room.key] = {"value": target, "until": scheduled.until.isoformat()}
    return {
        "schema": 2,
        "config_schema": 2,
        "config_id": config.config_id,
        "mode": "home",
        "arrival": None,
        "overrides": overrides,
        "disabled": disabled,
        "flags": {key: value == "on" for key, value in flags.items()},
        "counters": {},
    }


def validate_bridge(raw: object, schedule: str, room: str, base_topic: str) -> None:
    actions = sequence(mapping(mapping(raw)["attributes"])["actions"])
    for action in actions:
        record = mapping(action)
        if record.get("service") != "mqtt.publish":
            raise ValueError("Active controller requires migrated scheduler commands")
        data = mapping(record["data"])
        if (
            data.get("topic") != f"{base_topic}/{room}/schedule/set"
            or data.get("retain") is not False
        ):
            raise ValueError("Wrong scheduler destination or retained command")
        if mapping(json.loads(str(data.get("payload")))).get("source") != schedule:
            raise ValueError("Wrong scheduler source")


def main() -> None:
    import yaml

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("cfg/app_cfg.yaml"))
    parser.add_argument("--output", type=Path, default=Path("runtime/migration"))
    parser.add_argument("--snapshot", type=Path, help="Use an existing read-only HA state export")
    args = parser.parse_args()
    apps = mapping(yaml.safe_load(Path(args.config).read_text(encoding="utf-8")))
    raw = next(iter(apps.values()))
    config = Config.parse(raw)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    if args.snapshot:
        states = mapping(json.loads(Path(args.snapshot).read_text(encoding="utf-8")))
    else:
        reader = reader_from_environment()
        ids = {r.sensor for r in config.rooms} | {r.schedule for r in config.rooms}
        ids |= {head for r in config.rooms for head in r.trvs}
        ids |= {f"climate.sh_{r.key}" for r in config.rooms}
        ids |= {config.output, "switch.sh_force_flow_safety_rooms", "switch.sh_warm_flag"}
        states = {entity: reader.state(entity) for entity in sorted(ids)}
    (output / "ha-before.json").write_text(
        json.dumps(states, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (output / "scheduler-changes.json").write_text(
        json.dumps(scheduler_patch(config, states), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    seed = initial_state(config, states, datetime.now(timezone.utc))
    (output / "initial-state.json").write_text(json.dumps(seed, indent=2), encoding="utf-8")
    manifest = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "config_id": config.config_id,
        "files": {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path("src").rglob("*.py"))
        },
        "deployment_hashes": "not_verified",
        "applied_to_ha": False,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
