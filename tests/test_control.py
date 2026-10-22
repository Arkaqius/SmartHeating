import random
from dataclasses import replace
from datetime import timedelta

import pytest
from conftest import FakeClock
from sh_logic import LogicMixin

from smartheating.control import Arbiter, Safety, voting


class Legacy(LogicMixin):
    def log_debug(self, message):
        pass


def test_characterization_voting_matches_existing_calculations(cfg):
    rng = random.Random(720)
    old = Legacy()
    old.force_burn_thres, old.rads_error_factor = cfg.rad_threshold, cfg.rad_factor
    floor, rad = cfg.rooms[:7], cfg.rooms[7:]
    old.wam_params = [r.weight / sum(x.weight for x in floor) for r in floor]
    old.rads_params = [r.weight / sum(x.weight for x in rad) for r in rad]
    for _ in range(500):
        errors = {r.key: rng.uniform(-3, 3) for r in cfg.rooms}
        old.wam_errors = [errors[r.key] for r in floor]
        old.rads_error = [errors[r.key] for r in rad]
        wam = old.sh_apply_wam_voting(0)
        original = old.sh_check_forced_burn(wam)
        actual = voting(cfg, errors, False, False)
        assert actual.wam == wam
        assert actual.ordinary == pytest.approx(original)


def test_missing_sensor_renormalizes_and_corridor_is_required(cfg):
    result = voting(cfg, {"corridor": 1, "livingroom": -1}, False, False)
    assert result.wam == 0
    assert voting(cfg, {"livingroom": 1}, False, False).wam is None


def test_warm_floor_cold_bedroom_keeps_radiator_demand(cfg):
    errors = {r.key: -1 for r in cfg.rooms}
    errors["bedroom"] = 2
    assert voting(cfg, errors, False, False).radiator == pytest.approx(2 * 8 / 19 * 4)


def test_safety_delay_hysteresis_max_and_no_effect(cfg):
    now = FakeClock().now()
    safety = Safety(cfg)
    errors, ack = {"bedroom": 1, "kidsroom": 1.2}, {"bedroom": True, "kidsroom": True}
    assert safety.evaluate(now, errors, ack, True) == 0
    assert safety.evaluate(now + timedelta(seconds=899), errors, ack, True) == 0
    assert safety.evaluate(now + timedelta(seconds=900), errors, ack, True) == 4
    assert safety.evaluate(now + timedelta(seconds=3600), errors, ack, True) == 4
    assert all(s.ineffective for s in safety.rooms.values())
    assert (
        safety.evaluate(
            now + timedelta(seconds=3605), {"bedroom": 0.2, "kidsroom": 0.19}, ack, True
        )
        == 4
    )
    assert safety.evaluate(now + timedelta(seconds=3610), {"bedroom": 0.19}, ack, True) == 0


def test_unconfirmed_safety_does_not_accumulate_time(cfg):
    now = FakeClock().now()
    safety = Safety(cfg)
    for i in range(15):
        assert (
            safety.evaluate(now + timedelta(minutes=i), {"kidsroom": 3}, {"kidsroom": False}, True)
            == 0
        )
    assert (
        safety.evaluate(now + timedelta(minutes=16), {"kidsroom": 3}, {"kidsroom": True}, True) == 0
    )


def test_safety_cannot_lower_ordinary_and_output_slew(cfg):
    now = FakeClock().now()
    arb = Arbiter(cfg)
    assert arb.command(now, 20, 5, 4) == 25
    assert arb.command(now + timedelta(seconds=30), 20, 9, 4) == 25.25
    arb = Arbiter(replace(cfg, max_setpoint=24))
    assert arb.command(now, 20, 9, 4) == 24
