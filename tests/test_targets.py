from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from conftest import FakeClock, schedule_entity

from smartheating.model import Mode, Reading
from smartheating.schedules import DailySchedule
from smartheating.targets import Targets


def schedules(cfg):
    return {
        r.key: DailySchedule.from_ha(schedule_entity((22, 22)), cfg.timezone) for r in cfg.rooms
    }


def readings(cfg, now, temperature=19):
    return {r.key: Reading(temperature, now) for r in cfg.rooms}


def test_manual_expires_at_equal_temperature_slot(cfg):
    now = datetime(2026, 10, 20, 15, 59, tzinfo=timezone.utc)
    targets = Targets(cfg)
    sch = schedules(cfg)
    targets.manual("bedroom", 24, sch["bedroom"].at(now).until)
    assert targets.plan(now, sch, readings(cfg, now))["bedroom"].value == 24
    later = now + timedelta(minutes=1)
    assert targets.plan(later, sch, readings(cfg, later))["bedroom"].value == 22


@pytest.mark.parametrize("mode,floor,rad", [(Mode.SHORT, 21.5, 21), (Mode.LONG, 18, 17)])
def test_away_profiles_and_garage(cfg, mode, floor, rad):
    now = FakeClock().now()
    targets = Targets(cfg)
    targets.select(mode)
    plan = targets.plan(now, schedules(cfg), readings(cfg, now))
    assert plan["livingroom"].value == floor
    assert plan["bedroom"].value == rad
    assert plan["garage"].value == 22
    assert targets.mode == mode and targets.arrival is None


def test_independent_preheat_eta_change_cancellation_return_now(cfg):
    now = FakeClock().now()
    targets = Targets(cfg)
    targets.select(Mode.LONG)
    targets.set_arrival(now + timedelta(hours=9))
    plan = targets.plan(now, schedules(cfg), readings(cfg, now))
    assert plan["livingroom"].mode == Mode.PREHEAT  # 12h + margin
    assert plan["bedroom"].mode == Mode.LONG  # 6h + margin
    targets.set_arrival(now + timedelta(hours=2))
    assert (
        "arrival_may_be_missed"
        in targets.plan(now, schedules(cfg), readings(cfg, now))["bedroom"].issues
    )
    targets.set_arrival(None)
    assert targets.plan(now, schedules(cfg), readings(cfg, now))["livingroom"].value == 18
    targets.select(Mode.HOME)
    assert targets.plan(now, schedules(cfg), readings(cfg, now))["bedroom"].value == 22


def test_mode_clears_override_and_expired_return_goes_home(cfg):
    now = FakeClock().now()
    targets = Targets(cfg)
    targets.manual("bedroom", 24, now + timedelta(hours=2))
    targets.select(Mode.LONG)
    assert not targets.overrides
    targets.set_arrival(now - timedelta(minutes=1))
    assert targets.plan(now, schedules(cfg), readings(cfg, now))["bedroom"].mode == Mode.HOME


def test_missing_data_and_max_lead_are_visible(cfg):
    now = FakeClock().now()
    targets = Targets(cfg, Mode.LONG, now + timedelta(hours=23))
    plan = targets.plan(now, schedules(cfg), {})
    assert plan["bedroom"].ready_at is None
    assert "measurement_unavailable" in plan["bedroom"].issues
    targets.invalidate()
    assert (
        "lead_capped"
        in targets.plan(now, schedules(cfg), readings(cfg, now, 5))["livingroom"].issues
    )


def test_arrival_target_uses_future_schedule(cfg):
    now = datetime(2026, 10, 20, 15, tzinfo=timezone.utc)
    sch = {r.key: DailySchedule.from_ha(schedule_entity((18, 22)), cfg.timezone) for r in cfg.rooms}
    targets = Targets(cfg, Mode.LONG, now + timedelta(hours=2))
    assert targets.plan(now, sch, readings(cfg, now))["bedroom"].comfort == 22


def test_dst_gap_does_not_reorder_slots():
    schedule = DailySchedule.from_ha(
        schedule_entity((18, 19, 22), ("00:00:00", "02:30:00", "03:00:00")), "Europe/Warsaw"
    )
    now = datetime(2027, 3, 28, 3, 40, tzinfo=ZoneInfo("Europe/Warsaw"))
    assert schedule.at(now).temperature == 22


def test_dst_fold_and_midnight_next_boundary():
    schedule = DailySchedule.from_ha(
        schedule_entity((18, 22), ("00:00:00", "02:30:00")), "Europe/Warsaw"
    )
    now = datetime(2026, 10, 25, 2, 15, tzinfo=ZoneInfo("Europe/Warsaw"), fold=1)
    assert schedule.at(now).temperature == 22
    midnight = schedule.at(now).until
    assert midnight.astimezone(ZoneInfo("Europe/Warsaw")).hour == 0
    assert midnight > now.astimezone(timezone.utc)
