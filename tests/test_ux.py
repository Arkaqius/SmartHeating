import json
from datetime import timedelta

import pytest
from conftest import FakeClock, FakeHome

from smartheating.model import Mode
from smartheating.runtime import Runtime


def last(home, topic):
    return next(payload for key, payload, _ in reversed(home.messages) if key == topic)


def test_room_resume_clears_only_selected_override_and_survives_restart(cfg):
    clock = FakeClock()
    home = FakeHome(cfg, clock)
    app = Runtime(cfg, clock, home, home)
    app.start()
    app.command(app.mqtt.command_topic("system/control/profile/set"), "away_long")
    app.command(
        app.mqtt.command_topic("system/control/arrival/set"),
        (clock.now() + timedelta(days=2)).isoformat(),
    )
    app.command(app.mqtt.command_topic("bedroom/temperature/set"), "24")
    app.command(app.mqtt.command_topic("kidsroom/temperature/set"), "23")
    attrs = json.loads(last(home, app.mqtt.topic("bedroom/attributes")))
    assert attrs["manual_override"] and attrs["target_source"] == "manual"
    assert attrs["override_until"] == app.targets.overrides["bedroom"].until.isoformat()
    flags = app.flags.copy()
    app.command(app.mqtt.command_topic("bedroom/resume/set"), "PRESS")
    assert "bedroom" not in app.targets.overrides
    assert "kidsroom" in app.targets.overrides
    assert app.targets.mode is Mode.LONG and app.targets.arrival is not None
    assert app.flags == flags
    restored = Runtime(cfg, clock, home, home)
    assert "bedroom" not in restored.targets.overrides
    assert "kidsroom" in restored.targets.overrides
    assert not home.calls


def test_cancel_arrival_keeps_profile_and_manual_override(cfg):
    clock = FakeClock()
    home = FakeHome(cfg, clock)
    app = Runtime(cfg, clock, home, home)
    app.start()
    app.command(app.mqtt.command_topic("system/control/profile/set"), "away_short")
    app.command(
        app.mqtt.command_topic("system/control/arrival/set"),
        (clock.now() + timedelta(days=1)).isoformat(),
    )
    app.command(app.mqtt.command_topic("office/temperature/set"), "21")
    app.command(app.mqtt.command_topic("system/control/cancel_arrival/set"), "PRESS")
    assert app.targets.mode is Mode.SHORT and app.targets.arrival is None
    assert "office" in app.targets.overrides
    assert last(home, app.mqtt.topic("system/control/arrival/state")) == ""
    assert not home.calls


def test_bad_arrival_does_not_mutate_profile_or_older_return(cfg):
    clock = FakeClock()
    home = FakeHome(cfg, clock)
    app = Runtime(cfg, clock, home, home)
    app.start()
    future = clock.now() + timedelta(days=1)
    app.command(app.mqtt.command_topic("system/control/arrival/set"), future.isoformat())
    for invalid in (clock.now().isoformat(), "2026-10-20T11:00:00", "not-a-date"):
        with pytest.raises(ValueError):
            app.command(app.mqtt.command_topic("system/control/arrival/set"), invalid)
        assert app.targets.arrival == future and app.targets.mode is Mode.HOME
    assert not home.calls


def test_native_datetime_discovery_and_original_climate_ids(cfg):
    clock = FakeClock()
    home = FakeHome(cfg, clock)
    app = Runtime(cfg, clock, home, home)
    app.start()
    discovery = {
        topic: json.loads(payload)
        for topic, payload, _ in home.messages
        if topic.startswith("homeassistant/")
    }
    config = discovery["homeassistant/datetime/sh2_arrival_at/config"]
    assert config["command_topic"] == app.mqtt.command_topic("system/control/arrival/set")
    assert config["value_template"] == "{{ value if value else 'None' }}"
    assert config["retain"] is False and "timezone" not in config
    climate = discovery["homeassistant/climate/sh2_bedroom/config"]
    assert climate["unique_id"] == "smart_heating_sh2_bedroom"
    assert climate["json_attributes_topic"] == app.mqtt.topic("bedroom/attributes")
    assert "action_topic" not in climate
    readiness = discovery["homeassistant/sensor/sh2_bedroom_readiness/config"]
    assert readiness["device_class"] == "timestamp"


def test_room_status_does_not_call_demand_confirmed_heat(cfg):
    clock = FakeClock()
    home = FakeHome(cfg, clock)
    app = Runtime(cfg, clock, home, home)
    app.start()
    attrs = json.loads(last(home, app.mqtt.topic("bedroom/attributes")))
    assert attrs["needs_heat"]
    assert attrs["commands_confirmed"]
    assert "heating" not in attrs and "flame" not in attrs
    assert attrs["target_source"] == "schedule"
    assert attrs["scheduled_temperature"] == app.latest["bedroom"].value
    assert not home.calls


def test_summary_does_not_hide_missing_measurement(cfg):
    clock = FakeClock()
    home = FakeHome(cfg, clock)
    app = Runtime(cfg, clock, home, home)
    app.start()
    room = next(r for r in cfg.rooms if r.key == "bedroom")
    del home.states[room.sensor]
    app.tick()
    summary = json.loads(last(home, app.mqtt.topic("system/summary")))
    assert any("Sypialnia: brak aktualnego pomiaru" == p for p in summary["problems"])
    assert summary["measurements_valid"] == len(cfg.rooms) - 1
    attrs = json.loads(last(home, app.mqtt.topic("bedroom/attributes")))
    assert not attrs["measurement_available"] and not attrs["in_comfort"]
    assert not home.calls
