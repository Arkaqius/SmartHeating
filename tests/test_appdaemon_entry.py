import importlib
import sys
import types

import pytest
from conftest import FakeClock, FakeHome

from smartheating.config import Config


class FakeMqtt:
    def __init__(self, home):
        self.home = home
        self.handles = {}
        self.subscribed = set()
        self.sequence = 0

    def mqtt_publish(self, topic, payload, retain=True):
        self.home.publish(topic, payload, retain)

    def mqtt_subscribe(self, topic):
        self.subscribed.add(topic)

    def mqtt_unsubscribe(self, topic):
        self.subscribed.discard(topic)

    def listen_event(self, callback, event, **kwargs):
        self.sequence += 1
        self.handles[self.sequence] = (callback, event, kwargs)
        return self.sequence

    def cancel_listen_event(self, handle):
        del self.handles[handle]


@pytest.fixture
def app(monkeypatch, raw_config):
    def init_step(name, order):
        def decorate(function):
            function.init_order = order
            return function

        return decorate

    class Base:
        def initialize(self):
            for _, method in sorted(
                (getattr(self, key).init_order, getattr(self, key))
                for key in dir(self)
                if callable(getattr(self, key)) and hasattr(getattr(self, key), "init_order")
            ):
                method()

        def get_state(self, entity, attribute="all"):
            return self.home.read(entity)

        def get_plugin_api(self, name):
            return self.mqtt

        def call_service(self, service, **data):
            self.home.call(service, data)

        def log(self, message, level="INFO"):
            self.logs.append((message, level))

        def datetime(self):
            return self.clock.now()

        def schedule_every(self, name, start, interval, callback):
            self.timers[name] = callback

        def start_heartbeat(self, interval):
            self.timers["heartbeat"] = interval

        def listen_event(self, callback, event, **kwargs):
            handle = len(self.events) + 1
            self.events[handle] = (callback, event, kwargs)
            return handle

        def cancel_listen_event(self, handle):
            del self.events[handle]

        def update_health_attrs(self, **kwargs):
            self.health.update(kwargs)

        def enter_safe_state(self, reason, **kwargs):
            self.timers.clear()
            self.fault = reason
            self.on_enter_safe_state()

        def terminate(self):
            self.stopped = True

    fake_module = types.ModuleType("appdaemon_common")
    fake_module.HealthAppBase = Base
    fake_module.init_step = init_step
    monkeypatch.setitem(sys.modules, "appdaemon_common", fake_module)
    module = importlib.import_module("smartheating.appdaemon_app")
    importlib.reload(module)
    instance = module.SmartHeating()
    instance.args = raw_config
    instance.config = {"appdaemon": "reserved by AppDaemon"}
    instance.clock = FakeClock()
    instance.home = FakeHome(Config.parse(raw_config), instance.clock)
    instance.mqtt = FakeMqtt(instance.home)
    instance.logs, instance.events, instance.timers, instance.health = [], {}, {}, {}
    return instance


def test_entry_shadow_lifecycle_and_reserved_configuration(app):
    for name in ("SmartHeating", "smart_heating_v2"):
        module = importlib.import_module(name)
        assert module.SmartHeating.__module__ == name
        assert issubclass(module.SmartHeating, type(app))
    app.initialize()
    assert app.config == {"appdaemon": "reserved by AppDaemon"}
    assert app.args["health_entity_id"] == "sensor.sh2_health"
    assert app.health["shadow"]
    assert set(app.timers) == {"main_loop", "heartbeat"}
    app.loop({})
    app.terminate()
    assert not app.home.calls
    assert not app.mqtt.handles
    assert not app.events
    assert app.stopped


def test_reconnect_rotates_commands_and_cleans_old_subscriptions(app):
    app.initialize()
    previous = app.runtime.mqtt.command_topic("system/control/profile/set")
    expected = len(app.mqtt.handles)
    for _ in range(3):
        app.plugin_event("plugin_stopped", {"name": "MQTT"}, {})
        assert app.runtime.devices.blocked
        app.plugin_event("plugin_started", {"name": "MQTT"}, {})
    assert len(app.mqtt.handles) == expected
    assert previous not in app.mqtt.subscribed
    app.mqtt_message("MQTT_MESSAGE", {"topic": previous, "payload": "away_long"}, {})
    assert app.runtime.targets.mode.value == "home"


def test_custom_plugin_name_is_monitored(app):
    app.args["mqtt_plugin"] = "ZigbeeMqtt"
    app.initialize()
    app.plugin_event("plugin_stopped", {"name": "ZigbeeMqtt"}, {})
    assert app.runtime.devices.blocked


def test_fault_cancels_listeners_even_when_mqtt_publish_fails(app):
    app.initialize()

    def fail(*args, **kwargs):
        raise OSError("Disconnected")

    app.mqtt.mqtt_publish = fail
    app.runtime.tick = fail
    app.loop({})
    assert app.runtime.devices.blocked
    assert not app.timers
    assert not app.mqtt.handles
    assert not app.events


def test_measurement_subscription_reconnect_and_cleanup(app):
    app.args["v2"]["measurement_sources"] = {
        "corridor": {
            "entity": "sensor.raw",
            "topic": "ems/thermostat_data",
            "value_path": "hc1.currtemp",
            "max_age_s": 300,
        }
    }
    app.initialize()
    count = len(app.mqtt.handles)
    app.measurement_message(
        "MQTT_MESSAGE",
        {"topic": "ems/thermostat_data", "payload": '{"hc1":{"currtemp":21}}', "retain": False},
        {},
    )
    assert app.runtime.reports.latest["corridor"].value == 21
    app.plugin_event("plugin_stopped", {"name": "MQTT"}, {})
    assert not app.runtime.reports.latest
    app.plugin_event("plugin_started", {"name": "MQTT"}, {})
    assert len(app.mqtt.handles) == count
    app.terminate()
    assert not app.mqtt.handles and not app.home.calls
