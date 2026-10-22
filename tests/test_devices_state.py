import json
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from conftest import FakeClock, FakeHome, ha_entity

from smartheating.control import SafetyRoom
from smartheating.devices import Desired, Devices, Entity
from smartheating.metrics import Metrics, Sample
from smartheating.persistence import StateStore
from smartheating.runtime import Runtime
from smartheating.validation import number


def test_trv_auto_manual_readback_bounded_retries(cfg):
    cfg = replace(cfg, shadow=False, active_authorized=True)
    clock = FakeClock()
    home = FakeHome(cfg, clock)
    devices = Devices(cfg, home)
    entity = "climate.bedroom_left_trv"
    wrong = Entity.parse(ha_entity("heat", clock, temperature=15, preset_mode="schedule"))
    desired = Desired(22, "auto", "manual")
    for _ in range(8):
        assert not devices.reconcile(entity, desired, wrong, clock.now())
        clock.advance(31)
    assert len(home.calls) == 9  # 3 attempts, 3 required services per attempt
    assert home.calls[0][1]["hvac_mode"] == "auto"
    assert devices.status[entity] == "unconfirmed"
    correct = Entity.parse(ha_entity("auto", clock, temperature=22, preset_mode="manual"))
    assert devices.reconcile(entity, desired, correct, clock.now())
    assert entity not in devices.pending


def test_off_supersedes_old_heating_request(cfg):
    cfg = replace(cfg, shadow=False, active_authorized=True)
    clock = FakeClock()
    home = FakeHome(cfg, clock)
    device = Devices(cfg, home)
    actual = Entity.parse(ha_entity("auto", clock, temperature=15, preset_mode="manual"))
    device.reconcile("climate.test", Desired(22, "auto", "manual"), actual, clock.now())
    clock.advance(2)
    device.reconcile("climate.test", Desired(17, "off", "manual"), actual, clock.now())
    assert home.calls[-3][1]["hvac_mode"] == "off"
    assert home.calls[-1][1]["temperature"] == 17


def test_changing_target_does_not_reset_retry_budget(cfg):
    cfg = replace(cfg, shadow=False, active_authorized=True)
    clock = FakeClock()
    home = FakeHome(cfg, clock)
    device = Devices(cfg, home)
    actual = Entity.parse(ha_entity(18, clock))
    for i in range(12):
        device.reconcile(cfg.output, Desired(20 + i / 10), actual, clock.now())
        clock.advance(31)
    assert len(home.calls) == 3


def test_device_step_and_limits_and_unsupported_mode():
    entity = Entity.parse(ha_entity(20, FakeClock(), min=10, max=25, step=0.5))
    assert Desired.for_device(21.34, entity).temperature == 21.5
    with pytest.raises(ValueError):
        Desired.for_device(30, entity)
    with pytest.raises(ValueError):
        Desired.for_device(22, entity, "auto")


def test_metrics_no_cancellation_restore_no_double_count():
    clock = FakeClock()
    metrics = Metrics(max_gap_s=3600)
    metrics.advance(clock.now(), {"room": Sample("home", 1, True)})
    clock.advance(3600)
    metrics.advance(clock.now(), {"room": Sample("home", -1, False)})
    clock.advance(3600)
    metrics.advance(clock.now(), {"room": Sample("home", 0, False)})
    bucket = metrics.counters["room/home"]
    assert bucket["under_degree_h"] == bucket["over_degree_h"] == 1
    assert bucket["comfort_h"] == 0
    restored = Metrics()
    restored.restore(metrics.dump())
    restored.advance(clock.now(), {"room": Sample("home", 0, False)})
    assert restored.counters["room/home"] == bucket
    clock.advance(3600)
    restored.advance(clock.now(), {"room": Sample("home", 0, False)})
    assert restored.counters["room/home"]["measured_h"] == 2


def test_restart_gap_is_unobserved_not_reassigned_to_home():
    clock = FakeClock()
    metrics = Metrics()
    metrics.advance(clock.now(), {"room": Sample("away_long", 0, False)})
    restored = Metrics()
    restored.restore(metrics.dump())
    clock.advance(8 * 3600)
    restored.advance(clock.now(), {"room": Sample("home", 0, False)})
    assert restored.counters["room/unobserved"]["expected_h"] == 8
    assert "room/home" not in restored.counters


def test_dst_duration_is_absolute(cfg):
    zone = ZoneInfo("Europe/Warsaw")
    a = datetime(2026, 10, 25, 2, 50, tzinfo=zone, fold=0)
    b = datetime(2026, 10, 25, 2, 10, tzinfo=zone, fold=1)
    state = SafetyRoom()
    state.update(a, 1, True, cfg)
    assert state.update(b, 1, True, cfg) == 4
    metrics = Metrics(max_gap_s=3600)
    metrics.advance(a, {"room": Sample("home", 0, False)})
    metrics.advance(b, {"room": Sample("home", 0, False)})
    assert metrics.counters["room/home"]["comfort_h"] == pytest.approx(1 / 3)


def test_atomic_backup_and_schema(tmp_path):
    store = StateStore(tmp_path / "state.json")
    store.save({"mode": "home"})
    store.save({"mode": "away_long"})
    assert json.loads(store.backup.read_text())["mode"] == "home"
    store.path.write_text("broken")
    assert store.load()["mode"] == "home"
    assert store.recovered
    store.path.write_text('{"schema": 3}')
    with pytest.raises(RuntimeError, match="Unsupported"):
        store.load()
    store.path.write_text('{"schema": 1.5}')
    with pytest.raises(RuntimeError):
        store.load()
    store.path.write_text('{"schema": 1, "mode": "home"}')
    assert store.load()["schema"] == 2


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), "NaN", True, None])
def test_invalid_numbers(invalid):
    with pytest.raises(ValueError):
        number(invalid)


def test_shadow_start_commands_restart_connection_and_stop_never_write(cfg):
    clock = FakeClock()
    home = FakeHome(cfg, clock)
    app = Runtime(cfg, clock, home, home)
    app.start()
    for topic, value in [
        ("system/control/profile/set", "away_long"),
        ("system/control/arrival/set", (clock.now() + timedelta(hours=2)).isoformat()),
        ("bedroom/temperature/set", "23"),
        ("bedroom/mode/set", "off"),
        ("system/control/return_now/set", "PRESS"),
    ]:
        app.command(app.mqtt.command_topic(topic), value)
    app.connection(False)
    clock.advance(300)
    app.tick()
    app.connection(True)
    app.tick()
    app.stop()
    Runtime(cfg, clock, home, home).start()
    assert home.calls == []
    assert all("smart_heating/" not in topic for topic, _, _ in home.messages)
    assert all("/sh_" not in topic for topic, _, _ in home.messages)


def test_restart_preserves_switches_mode_arrival_overrides_and_counters(cfg):
    clock = FakeClock()
    home = FakeHome(cfg, clock)
    app = Runtime(cfg, clock, home, home)
    app.start()
    app.command(app.mqtt.command_topic("system/control/force_flow_safety_rooms/set"), "OFF")
    app.command(app.mqtt.command_topic("system/control/profile/set"), "away_short")
    app.command(
        app.mqtt.command_topic("system/control/arrival/set"),
        (clock.now() + timedelta(hours=1)).isoformat(),
    )
    app.command(app.mqtt.command_topic("bedroom/temperature/set"), "23")
    app.stop()
    restored = Runtime(cfg, clock, home, home)
    assert not restored.flags["force_flow_safety_rooms"]
    assert restored.targets.mode.value == "away_short"
    assert restored.targets.overrides["bedroom"].value == 23
    clock.advance(3601)
    restored.start()
    assert restored.targets.mode.value == "home"
    assert not restored.targets.overrides


def test_both_bedroom_heads_required_and_stale_nan_excluded(cfg):
    clock = FakeClock()
    home = FakeHome(cfg, clock)
    home.states["climate.bedroom_left_trv"] = ha_entity(
        "auto", clock, temperature=15, preset_mode="schedule"
    )
    app = Runtime(cfg, clock, home, home)
    app.start()
    clock.advance(901)
    app.tick()
    assert not app.safety.rooms["bedroom"].active
    home.states["sensor.salon_temperatura"] = ha_entity("NaN", clock)
    clock.advance(cfg.ttl_s + 1)
    app.tick()
    assert not any(s.active for s in app.safety.rooms.values())
    assert not home.calls
