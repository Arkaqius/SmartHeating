import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import FakeClock, FakeHome, ha_entity

from smartheating.config import Config
from smartheating.devices import Desired, Devices, Entity
from smartheating.energy import ENERGY_MODES, Energy
from smartheating.metrics import COUNTERS, METRIC_MODES
from smartheating.migration import initial_state, scheduler_patch, validate_bridge
from smartheating.reporting import (
    ENERGY_CH,
    ENERGY_DHW,
    OUTSIDE,
    Experiment,
    build_report,
    gas_comparison,
    markdown,
)
from smartheating.runtime import Runtime


def statistics(end, coverage=1):
    result = {}
    start = end - timedelta(days=14, hours=1)
    rates = {
        "expected_h": 1,
        "measured_h": coverage,
        "comfort_h": 0.9 * coverage,
        "under_h": 0.05 * coverage,
        "over_h": 0.05 * coverage,
        "under_degree_h": 0.1,
        "over_degree_h": 0.1,
        "command_expected_h": 1,
        "command_confirmed_h": 1,
    }
    for mode in METRIC_MODES:
        for counter in COUNTERS:
            rate = rates.get(counter, 0) if mode == "home" else 0
            result[f"sensor.sh_bedroom_{mode}_{counter}"] = [
                {"start": (start + timedelta(hours=i)).timestamp() * 1000, "sum": i * rate}
                for i in range(337)
            ]
    for entity, rate in [(ENERGY_CH, 2), (ENERGY_DHW, 0.5)] + [
        (f"sensor.sh_energy_{mode}_kwh", 2 if mode == "home" else 0) for mode in ENERGY_MODES
    ]:
        result[entity] = [
            {"start": (start + timedelta(hours=i)).isoformat(), "sum": rate * i} for i in range(337)
        ]
    result[OUTSIDE] = [
        {"start": (start + timedelta(hours=i)).isoformat(), "mean": 8} for i in range(337)
    ]
    return result


def test_long_term_statistics_report_after_raw_history_purge():
    # Only hourly statistics are passed: no raw temperature history exists in this fixture.
    end = FakeClock().now()
    data = statistics(end)
    experiment = Experiment(
        "rooms.bedroom.weight",
        8,
        7,
        "Mniejszy błąd ETA",
        72,
        "Cofnij gdy błąd ETA wzrośnie o30min",
    )
    report = build_report(data, end, rooms=("bedroom",), experiment=experiment)
    assert report["tuning_eligible"]
    assert not report["issues"]
    assert report["rooms"]["bedroom"]["coverage"] == 1
    assert report["rooms"]["bedroom"]["totals"]["under_h"] == pytest.approx(8.4)
    assert report["energy"]["ch_kwh"] == 336
    assert report["energy"]["dhw_kwh"] == 84
    assert report["energy"]["ch_kwh_per_degree_day"] == pytest.approx(4.8)
    assert report["recommendation"]["parameter"] == "rooms.bedroom.weight"
    assert "Sypialnia" in markdown(report)


@pytest.mark.parametrize("coverage", [0.94, 0.5, 0])
def test_insufficient_coverage_never_recommends_tuning(coverage):
    end = FakeClock().now()
    report = build_report(statistics(end, coverage), end, rooms=("bedroom",))
    assert not report["tuning_eligible"]
    assert report["recommendation"] == "continue_observation"


def test_only_seven_days_must_wait_for_fourteen():
    end = FakeClock().now()
    data = statistics(end)
    for series in data.values():
        del series[:168]
    report = build_report(data, end, rooms=("bedroom",))
    assert report["rooms"]["bedroom"]["coverage"] == 1
    assert "need_14_days_of_reliable_data" in report["issues"]
    assert not report["tuning_eligible"]


def test_zero_allocation_with_real_heating_is_not_eligible():
    end = FakeClock().now()
    data = statistics(end)
    for point in data["sensor.sh_energy_home_kwh"]:
        point["sum"] = 0
    assert (
        "energy_allocation_does_not_reconcile"
        in build_report(data, end, rooms=("bedroom",))["issues"]
    )


@pytest.mark.parametrize("remove", [OUTSIDE, ENERGY_DHW, "sensor.sh_bedroom_home_under_h"])
def test_missing_required_statistics_is_explicit(remove):
    end = FakeClock().now()
    data = statistics(end)
    del data[remove]
    assert not build_report(data, end, rooms=("bedroom",))["tuning_eligible"]


def test_experiment_does_not_allow_comfort_or_burner_settings():
    with pytest.raises(ValueError):
        Experiment("boiler.gas_valve", 1, 2, "test", 72, "rollback").validate()
    with pytest.raises(ValueError):
        Experiment("bedroom.target", 21, 22, "test", 72, "rollback").validate()


def test_invoice_factor_recalculation_and_period_flag():
    result = gas_comparison(1308, 13968.84)
    assert result["invoice_equivalent_kwh"] == pytest.approx(15164.952)
    assert result["ems_difference_percent"] == pytest.approx(-7.8873476, abs=1e-5)
    assert result["estimated"]
    assert not gas_comparison(100, 1100, "2026-01-01", "2026-12-31", "2026-02-01", "2026-03-01")[
        "estimated"
    ]


def test_energy_modes_mixed_intervals_restart_and_reset():
    energy = Energy()
    energy.update(100, "home")
    energy.update(101, "home")
    energy.update(101, "away_long")
    energy.update(102, "away_long")
    energy.update(103, "away_long")
    assert energy.totals["home"] == energy.totals["mixed"] == energy.totals["away_long"] == 1
    restored = Energy()
    restored.restore(energy.dump())
    restored.update(105, "home")
    assert restored.totals["unobserved"] == 2
    restored.update(1, "home")
    assert restored.issue == "ems_counter_reset"
    assert all(v >= 0 for v in restored.totals.values())


def test_migration_preserves_switches_disabled_and_manual_target(cfg):
    clock = FakeClock()
    home = FakeHome(cfg, clock)
    for room in cfg.rooms:
        home.states[f"climate.sh_{room.key}"] = ha_entity("heat", clock, temperature=room.default)
    home.states["climate.sh_garage"]["state"] = "off"
    home.states["climate.sh_bedroom"]["attributes"]["temperature"] = 23
    for flag in ("warm_flag", "force_flow_safety_rooms"):
        home.states[f"switch.sh_{flag}"] = ha_entity("off", clock)
    state = initial_state(cfg, home.states, clock.now())
    assert state["disabled"] == ["garage"]
    assert state["overrides"]["bedroom"]["value"] == 23
    assert not state["flags"]["force_flow_safety_rooms"]
    changes = scheduler_patch(cfg, home.states)
    for room in cfg.rooms:
        migrated = {"state": "on", "attributes": changes[room.schedule]["after"]}
        validate_bridge(migrated, room.schedule, room.key, "smart_heating")


def test_active_controller_requires_bridge_and_can_then_control(cfg):
    cfg = replace(
        cfg, shadow=False, active_authorized=True, base_topic="smart_heating", entity_prefix="sh"
    )
    clock = FakeClock()
    home = FakeHome(cfg, clock)
    app = Runtime(cfg, clock, home, home)
    app.start()
    assert not home.calls
    changes = scheduler_patch(cfg, home.states)
    for room in cfg.rooms:
        home.states[room.schedule]["attributes"] = changes[room.schedule]["after"]
    clock.advance(60)
    home.states["climate.bedroom_left_trv"]["state"] = "heat"
    app.tick()
    assert any(call[1].get("entity_id") == "climate.bedroom_left_trv" for call in home.calls)
    assert all(call[1].get("preset_mode") != "boost" for call in home.calls)


def test_static_actuator_settings_do_not_expire_as_temperature_readings(cfg):
    clock = FakeClock()
    home = FakeHome(cfg, clock)
    app = Runtime(cfg, clock, home, home)
    app.start()
    clock.advance(cfg.ttl_s + 1)
    for room in cfg.rooms:
        home.states[room.sensor] = ha_entity(19, clock)
    app.tick()
    assert home.messages[-1]
    assert app.devices.status[cfg.output] != "input_blocked"


def test_old_session_commands_rejected_after_restart_or_reconnect(cfg):
    clock = FakeClock()
    home = FakeHome(cfg, clock)
    app = Runtime(cfg, clock, home, home)
    old_topic = app.mqtt.command_topic("system/control/profile/set")
    app.connection(False)
    app.connection(True)
    with pytest.raises(ValueError, match="Unknown"):
        app.command(old_topic, "away_long")
    assert app.targets.mode.value == "home"


def test_off_without_measurement_and_during_previous_heating_cooldown(cfg):
    cfg = replace(cfg, shadow=False, active_authorized=True)
    clock = FakeClock()
    home = FakeHome(cfg, clock)
    app = Runtime(cfg, clock, home, home)
    app.start()
    home.states["sensor.sypialnia_temperatura"] = None
    app.command(app.mqtt.command_topic("bedroom/mode/set"), "off")
    off_heads = {
        data["entity_id"]
        for service, data in home.calls
        if service == "climate/set_hvac_mode" and data["hvac_mode"] == "off"
    }
    assert off_heads == {"climate.bedroom_left_trv", "climate.bedroom_right_trv"}
    devices = Devices(cfg, home)
    current = Entity.parse(ha_entity("auto", clock, temperature=15, preset_mode="manual"))
    for _ in range(4):
        devices.reconcile("climate.test", Desired(22, "auto", "manual"), current, clock.now())
        clock.advance(30)
    previous = len(home.calls)
    devices.reconcile("climate.test", Desired(17, "off", "manual"), current, clock.now())
    assert len(home.calls) == previous + 3


def test_discovery_uses_one_availability_form(cfg):
    clock = FakeClock()
    home = FakeHome(cfg, clock)
    Runtime(cfg, clock, home, home).start()
    for topic, payload, _ in home.messages:
        if topic.endswith("/config"):
            record = json.loads(payload)
            assert not ("availability" in record and "availability_topic" in record)


@pytest.mark.parametrize(
    "values",
    [
        {"min_setpoint": 30, "max_setpoint": 15},
        {"safety_on": 0.2, "safety_off": 0.5},
        {"schema": 3},
    ],
)
def test_invalid_config_is_rejected(raw_config, values):
    raw_config["v2"].update(values)
    with pytest.raises(ValueError):
        Config.parse(raw_config)


def test_appdaemon_injected_path_is_not_part_of_configuration(raw_config):
    expected = Config.parse(raw_config).config_id
    raw_config["config_path"] = Path("/config/apps/SmartHeating2/apps.yaml")
    assert Config.parse(raw_config).config_id == expected
