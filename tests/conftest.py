from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from smartheating.config import Config


@pytest.fixture
def raw_config(tmp_path):
    data = yaml.safe_load(Path("legacy/app_cfg.yaml").read_text())["HeaterController"]
    data["v2"] = {
        "state_path": str(tmp_path / "state.json"),
        "initial_safety": True,
        "initial_warm": False,
    }
    return data


@pytest.fixture
def cfg(raw_config):
    return Config.parse(raw_config)


@dataclass
class FakeClock:
    value: datetime = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)

    def now(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


def ha_entity(state, clock, **attrs):
    return {"state": str(state), "attributes": attrs, "last_updated": clock.now().isoformat()}


def schedule_entity(temps=(20, 20), starts=("00:00:00", "18:00:00")):
    return {
        "state": "on",
        "attributes": {
            "weekdays": ["daily"],
            "timeslots": [
                f"{start} - {end}"
                for start, end in zip(starts, (*starts[1:], "00:00:00"), strict=True)
            ],
            "actions": [
                {"service": "climate.set_temperature", "data": {"temperature": t}} for t in temps
            ],
        },
    }


class FakeHome:
    def __init__(self, cfg, clock):
        self.states = {}
        self.calls = []
        self.messages = []
        for room in cfg.rooms:
            self.states[room.sensor] = ha_entity(19, clock)
            self.states[room.schedule] = schedule_entity((room.default, room.default))
            for trv in room.trvs:
                self.states[trv] = ha_entity(
                    "auto",
                    clock,
                    temperature=room.default,
                    preset_mode="manual",
                    hvac_modes=["auto", "heat", "off"],
                    preset_modes=["manual", "schedule", "boost"],
                    min_temp=5,
                    max_temp=30,
                    target_temp_step=0.5,
                )
        self.states[cfg.output] = ha_entity(20, clock, min=5, max=30, step=0.5)

    def read(self, entity):
        return self.states.get(entity)

    def call(self, service, data):
        self.calls.append((service, data))

    def publish(self, topic, payload, retain=True):
        self.messages.append((topic, payload, retain))
