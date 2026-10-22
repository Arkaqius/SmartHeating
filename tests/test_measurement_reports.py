import json
from dataclasses import replace
from datetime import timedelta

import pytest
from conftest import FakeClock, FakeHome, ha_entity
from test_reporting_migration import statistics

from smartheating.config import Config
from smartheating.devices import Entity
from smartheating.energy import Energy
from smartheating.measurements import Reports, Source
from smartheating.reporting import build_report
from smartheating.runtime import Runtime


def source(counter=False):
    return Source(
        "sensor.raw",
        "test/source",
        ("temperature",),
        3900,
        "last_seen" if not counter else "",
        counter,
    )


def report(clock, value=20):
    return json.dumps({"temperature": value, "last_seen": clock.now().timestamp() * 1000})


def test_unchanged_temperature_uses_published_time_without_retimestamping():
    clock = FakeClock()
    entity = Entity.parse(ha_entity(20, clock))
    reports = Reports({"bedroom": source()})
    clock.advance(4 * 3600)
    reports.ingest("test/source", report(clock), clock.now(), True)
    sample = reports.reading("bedroom", entity, clock.now())
    assert sample.value == 20
    assert sample.at == clock.now()
    clock.advance(2000)
    assert reports.reading("bedroom", entity, clock.now()).fresh(clock.now(), 1800)
    clock.advance(1901)
    assert reports.reading("bedroom", entity, clock.now()) is None


def test_humidity_only_packet_does_not_refresh_temperature():
    clock = FakeClock()
    entity = Entity.parse(ha_entity(20, clock))
    reports = Reports({"bedroom": source()})
    reports.ingest("test/source", report(clock), clock.now(), False)
    at = reports.latest["bedroom"].at
    clock.advance(3901)
    reports.ingest(
        "test/source",
        json.dumps({"humidity": 50, "last_seen": clock.now().timestamp() * 1000}),
        clock.now(),
        False,
    )
    assert reports.latest["bedroom"].at == at
    assert reports.reading("bedroom", entity, clock.now()) is None


@pytest.mark.parametrize("value", ["NaN", None, True, 500])
def test_invalid_temperature_does_not_reuse_cached_report(value):
    clock = FakeClock()
    reports = Reports({"bedroom": source()})
    reports.ingest("test/source", report(clock), clock.now(), False)
    reports.ingest("test/source", report(clock, value), clock.now(), False)
    assert reports.reading("bedroom", Entity.parse(ha_entity(20, clock)), clock.now()) is None


def test_retained_replay_future_out_of_order_and_unavailable_source():
    clock = FakeClock()
    reports = Reports({"bedroom": source()})
    old = report(clock)
    clock.advance(4000)
    reports.ingest("test/source", old, clock.now(), True)
    assert not reports.latest
    reports.ingest("test/source", report(clock), clock.now(), True)
    current = reports.latest["bedroom"]
    reports.ingest("test/source", old, clock.now(), True)
    assert reports.latest["bedroom"] == current
    assert reports.reading("bedroom", None, clock.now()) is None
    assert reports.reading("bedroom", Entity.parse(ha_entity("NaN", clock)), clock.now()) is None
    reports.clear()
    assert not reports.latest and not reports.quarantine
    future = json.dumps({"temperature": 20, "last_seen": (clock.now().timestamp() + 60) * 1000})
    reports.ingest("test/source", future, clock.now(), False)
    assert not reports.latest


def test_ems_requires_live_report_and_constant_value_proves_transport():
    clock = FakeClock()
    reports = Reports({"energy": source(counter=True)})
    entity = Entity.parse(ha_entity(123, clock))
    message = '{"temperature":123}'
    reports.ingest("test/source", message, clock.now(), True)
    assert reports.reading("energy", entity, clock.now()) is None
    reports.ingest("test/source", message, clock.now(), None)
    assert reports.reading("energy", entity, clock.now()) is None
    clock.advance(6)
    reports.ingest("test/source", message, clock.now(), None)
    assert reports.reading("energy", entity, clock.now()).value == 123
    clock.advance(3901)
    assert reports.reading("energy", entity, clock.now()) is None
    reports.ingest("test/source", message, clock.now(), False)
    assert reports.reading("energy", entity, clock.now()).value == 123


def test_publisher_timestamp_survives_restart_without_promoting_ha_retained_value():
    clock = FakeClock()
    sources = {"bedroom": source(), "energy": replace(source(counter=True), topic="test/energy")}
    reports = Reports(sources)
    reports.ingest("test/source", report(clock), clock.now(), True)
    reports.ingest("test/energy", '{"temperature":123}', clock.now(), False)
    restored = Reports(sources)
    restored.restore(reports.dump())
    assert "energy" not in restored.latest
    assert restored.latest["bedroom"].at == reports.latest["bedroom"].at
    clock.advance(3901)
    fresh_ha_retained = Entity.parse(ha_entity(20, clock))
    assert restored.reading("bedroom", fresh_ha_retained, clock.now()) is None
    empty = Reports(sources)
    assert empty.reading("bedroom", fresh_ha_retained, clock.now()) is None


def test_energy_unavailable_clears_on_same_value_and_reset_stays_visible():
    energy = Energy()
    energy.update(100, "home")
    energy.update(None, "home")
    energy.update(100, "home")
    assert energy.issue is None
    energy.update(1, "home")
    energy.update(1, "home")
    assert energy.issue == "ems_counter_reset"
    assert sum(energy.totals.values()) == 0


def test_shadow_radiator_demand_independent_of_v1_mode_and_candidate_is_separate(cfg):
    clock = FakeClock()
    home = FakeHome(cfg, clock)
    for room in cfg.rooms:
        home.states[room.sensor] = ha_entity(room.default + (1 if not room.trvs else -2), clock)
        for trv in room.trvs:
            home.states[trv]["state"] = "heat"
    app = Runtime(cfg, clock, home, home)
    app.flags["force_flow_safety_rooms"] = False
    app.start()
    assert app.mqtt.cache[app.mqtt.topic("system/diagnostic/forced_burn_offset/state")] != "0.0"
    clock.advance(900)
    app.tick()
    assert app.safety_candidate.rooms["bedroom"].active
    assert app.safety_candidate.rooms["kidsroom"].active
    assert not app.safety.rooms["bedroom"].active
    assert all(
        v == 0 for k, b in app.metrics.counters.items() for m, v in b.items() if m == "safety_h"
    )
    assert not home.calls


def test_missing_head_blocks_shadow_candidate_and_real_safety(cfg):
    clock = FakeClock()
    home = FakeHome(cfg, clock)
    home.states["climate.bedroom_left_trv"] = None
    app = Runtime(cfg, clock, home, home)
    app.start()
    clock.advance(901)
    app.tick()
    assert not app.safety_candidate.rooms["bedroom"].active
    assert not app.safety.rooms["bedroom"].active
    assert not home.calls


def test_runtime_uses_raw_source_and_live_report_instead_of_template_change(cfg):
    clock = FakeClock()
    policy = Source("sensor.raw", "ems/thermostat_data", ("hc1", "currtemp"), 300)
    cfg = replace(cfg, measurement_sources={"corridor": policy})
    home = FakeHome(cfg, clock)
    home.states["sensor.raw"] = ha_entity(21, clock)
    home.states["sensor.korytarz_temperatura"] = ha_entity("NaN", clock)
    clock.advance(7200)
    app = Runtime(cfg, clock, home, home)
    app.start()
    assert "measurement_unavailable" in app.latest["corridor"].issues
    app.reports.ingest("ems/thermostat_data", '{"hc1":{"currtemp":21}}', clock.now(), False)
    app.tick()
    assert "measurement_unavailable" not in app.latest["corridor"].issues
    assert app.reports.status["corridor"] == "published_snapshot"
    assert not home.calls


def test_evaluation_restart_preserves_epoch_and_counters_config_change_starts_new(cfg):
    clock = FakeClock()
    home = FakeHome(cfg, clock)
    app = Runtime(cfg, clock, home, home)
    app.start()
    clock.advance(5)
    app.tick()
    app.stop()
    same = Runtime(cfg, clock, home, home)
    assert same.evaluation == app.evaluation
    changed = Runtime(replace(cfg, config_id="new"), clock, home, home)
    assert changed.evaluation["started"] == clock.now().isoformat()
    assert changed.metrics.counters == app.metrics.counters


def test_new_evaluation_rejects_old_good_statistics():
    end = FakeClock().now()
    result = build_report(
        statistics(end), end, rooms=("bedroom",), evaluation_started=end - timedelta(days=2)
    )
    assert not result["tuning_eligible"]
    assert "need_14_days_in_current_evaluation" in result["issues"]


def test_source_config_rejects_unknown_room_and_wildcards(raw_config):
    raw_config["v2"]["measurement_sources"] = {
        "missing": {
            "entity": "sensor.x",
            "topic": "test",
            "value_path": "temperature",
            "max_age_s": 100,
        }
    }
    with pytest.raises(ValueError, match="Unknown room"):
        Config.parse(raw_config)
    raw_config["v2"]["measurement_sources"] = {
        "bedroom": {
            "entity": "sensor.x",
            "topic": "test/#",
            "value_path": "temperature",
            "max_age_s": 100,
        }
    }
    with pytest.raises(ValueError, match="exact MQTT"):
        Config.parse(raw_config)
