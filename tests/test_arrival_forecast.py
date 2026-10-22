from datetime import timedelta

from conftest import FakeClock, FakeHome
from test_reporting_migration import statistics

from smartheating.forecast import Forecasts
from smartheating.model import Mode, Reading
from smartheating.reporting import Experiment, assess_arrivals, build_report
from smartheating.runtime import Runtime


def test_forecast_episode_persists_first_prediction_and_observed_band(cfg):
    clock = FakeClock()
    home = FakeHome(cfg, clock)
    app = Runtime(cfg, clock, home, home)
    app.start()
    app.command(app.mqtt.command_topic("system/control/profile/set"), "away_long")
    arrival = clock.now() + timedelta(hours=2)
    app.command(app.mqtt.command_topic("system/control/arrival/set"), arrival.isoformat())
    assert app.latest["bedroom"].mode is Mode.PREHEAT
    forecast = app.forecasts.episodes["bedroom"]
    first_prediction = forecast.predicted
    assert first_prediction is not None
    clock.advance(300)
    target = app.latest["bedroom"]
    app.forecasts.track("bedroom", target, Reading(21.8, clock.now()), clock.now(), cfg.ttl_s)
    assert forecast.predicted == first_prediction
    assert forecast.observed_ready == clock.now()
    restored = Forecasts()
    restored.restore(app.forecasts.dump())
    assert restored.episodes["bedroom"].observed_ready == clock.now()


def arrivals(end):
    at = end - timedelta(days=1)
    return [
        {
            "scheduled": at.isoformat(),
            "observed": at.isoformat(),
            "rooms": {
                "bedroom": {
                    "target": 22,
                    "temperature": 21.8,
                    "forecast": {
                        "predicted": (at - timedelta(minutes=20)).isoformat(),
                        "observed_ready": (at - timedelta(minutes=10)).isoformat(),
                    },
                }
            },
        }
    ]


def test_report_scores_arrival_comfort_and_forecast_time():
    end = FakeClock().now()
    report = assess_arrivals(arrivals(end), end - timedelta(days=7), end)
    assert report["bedroom"]["within_band"] == 1
    assert report["bedroom"]["mean_forecast_abs_error_minutes"] == 10


def test_warmup_tuning_requires_completed_recovery():
    end = FakeClock().now()
    experiment = Experiment(
        "rooms.bedroom.warmup_rate", 0.5, 0.55, "Trafniejsze ETA", 72, "Cofnij gdy błąd rośnie"
    )
    report = build_report(statistics(end), end, rooms=("bedroom",), experiment=experiment)
    assert not report["tuning_eligible"]
    report = build_report(
        statistics(end), end, rooms=("bedroom",), experiment=experiment, arrivals=arrivals(end)
    )
    assert report["tuning_eligible"]


def test_restart_after_arrival_does_not_grade_late_measurement_as_arrival():
    end = FakeClock().now()
    events = arrivals(end)
    events[0]["observed"] = (end - timedelta(hours=12)).isoformat()
    report = assess_arrivals(events, end - timedelta(days=7), end)
    assert report["bedroom"]["events"] == 1
    assert report["bedroom"]["timely_observations"] == 0
