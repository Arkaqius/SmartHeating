import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from conftest import FakeClock, FakeHome, ha_entity, schedule_entity

from smartheating.migration import scheduler_patch, validate_bridge
from smartheating.runtime import Runtime
from smartheating.schedules import DailySchedule


@pytest.mark.parametrize("state", ["on", "triggered"])
def test_running_schedule_keeps_valid_plan(state):
    raw = schedule_entity((22, 23))
    raw["state"] = state
    schedule = DailySchedule.from_ha(raw, "Europe/Warsaw")
    before = datetime(2026, 10, 27, 16, 59, 55, tzinfo=timezone.utc)
    after = datetime(2026, 10, 27, 17, tzinfo=timezone.utc)
    assert schedule.at(before).temperature == 22
    assert schedule.at(after).temperature == 23
    assert schedule.at(before).token != schedule.at(after).token


@pytest.mark.parametrize("state", ["off", "unknown", "unavailable", None])
def test_inactive_or_unknown_schedule_still_rejected(state):
    raw = schedule_entity()
    raw["state"] = state
    with pytest.raises(ValueError, match="disabled or unavailable"):
        DailySchedule.from_ha(raw, "Europe/Warsaw")


def test_triggered_schedule_still_validates_definition_and_command_bridge():
    raw = schedule_entity((22, 23))
    raw["state"] = "triggered"
    raw["attributes"]["timeslots"][0] = "00:00:00 - 17:00:00"
    with pytest.raises(ValueError, match="gaps or overlapping"):
        DailySchedule.from_ha(raw, "Europe/Warsaw")
    with pytest.raises(ValueError, match="migrated scheduler commands"):
        validate_bridge(raw, "switch.plan", "corridor", "smart_heating")


@pytest.mark.parametrize("room_key", ["corridor", "upper_bathroom", "bedroom"])
@pytest.mark.parametrize("next_temperature", [22, 23])
def test_active_runtime_keeps_targets_and_control_through_trigger_minute(
    cfg, room_key, next_temperature
):
    cfg = replace(cfg, shadow=False, active_authorized=True, initial_safety=False)
    clock = FakeClock(datetime(2026, 10, 27, 16, 59, 55, tzinfo=timezone.utc))
    home = FakeHome(cfg, clock)
    room = next(r for r in cfg.rooms if r.key == room_key)
    home.states[room.schedule] = schedule_entity((22, next_temperature))
    changes = scheduler_patch(cfg, home.states, cfg.base_topic)
    for entity_id, change in changes.items():
        home.states[entity_id]["attributes"] = change["after"]
    app = Runtime(cfg, clock, home, home)
    app.start()
    app.command(app.mqtt.command_topic(f"{room_key}/temperature/set"), "24")
    assert app.latest[room_key].value == 24
    previous_slot = app.latest[room_key].slot

    clock.advance(5)
    home.states[room.schedule]["state"] = "triggered"
    # Scheduler remains triggered for a minute, including equal-temperature boundaries.
    for _ in range(12):
        for configured in cfg.rooms:
            home.states[configured.sensor] = ha_entity(19, clock)
        app.tick()
        assert room_key in app.schedules
        assert app.latest[room_key].value == next_temperature
        assert app.latest[room_key].slot != previous_slot
        assert "schedule_unavailable" not in app.latest[room_key].issues
        assert room_key not in app.targets.overrides
        assert app.devices.status[cfg.output] != "input_blocked"
        attrs = next(
            payload
            for topic, payload, _ in reversed(home.messages)
            if topic == app.mqtt.topic(f"{room_key}/attributes")
        )
        assert json.loads(attrs)["schedule_available"]
        clock.advance(5)

    home.states[room.schedule]["state"] = "on"
    app.tick()
    assert app.latest[room_key].value == next_temperature
    assert app.latest[room_key].slot != previous_slot
