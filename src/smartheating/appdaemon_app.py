"""Thin AppDaemon entry point. Domain logic imports neither HA nor AppDaemon."""

import sys
from datetime import timedelta
from threading import RLock
from typing import Protocol, cast

from appdaemon_common import HealthAppBase, init_step

from . import __version__
from .config import Config
from .runtime import Runtime, SystemClock
from .validation import mapping, string


class MqttPlugin(Protocol):
    def mqtt_publish(self, topic: str, payload: str, retain: bool = True) -> object: ...

    def mqtt_subscribe(self, topic: str) -> object: ...

    def mqtt_unsubscribe(self, topic: str) -> object: ...

    def listen_event(self, callback: object, event: str, **kwargs: object) -> object: ...

    def cancel_listen_event(self, handle: object) -> object: ...


class SmartHeating(HealthAppBase):
    def initialize(self) -> None:
        self._sh_lock = RLock()
        self.heating_config = Config.parse(self.args)
        self.runtime: Runtime | None = None
        self.mqtt_handles: list[object] = []
        self.command_handles: list[object] = []
        self.command_topics: list[str] = []
        self.measurement_handles: list[object] = []
        self.ha_handles: list[object] = []
        self.connections: dict[str, bool] = {
            string(self.args.get("hass_plugin", "HASS")): True,
            string(self.args.get("mqtt_plugin", "MQTT")): True,
        }
        if self.heating_config.shadow:
            self.args.update(
                health_entity_id="sensor.sh2_health",
                health_unique_id="smart_heating_sh2_health",
                health_name="Ogrzewanie 2.0 — obserwacja",
                mqtt_base_topic="smart_heating_v2/app",
            )
        super().initialize()

    @init_step("runtime", order=10)
    def init_runtime(self) -> None:
        api = self.get_plugin_api(string(self.args.get("mqtt_plugin", "MQTT")))
        for method in (
            "mqtt_publish",
            "mqtt_subscribe",
            "mqtt_unsubscribe",
            "listen_event",
            "cancel_listen_event",
        ):
            if not callable(getattr(api, method, None)):
                raise RuntimeError(f"MQTT plugin missing {method}")
        self.mqtt_api = cast(MqttPlugin, api)
        self.runtime = Runtime(self.heating_config, SystemClock(), self, self)
        self.runtime.start()
        self.update_health_attrs(
            version=__version__,
            commit=self.heating_config.commit,
            config_id=self.heating_config.config_id,
            shadow=self.heating_config.shadow,
            python_version=sys.version.split()[0],
        )

    @init_step("listeners", order=20)
    def init_listeners(self) -> None:
        if self.runtime is None:
            raise RuntimeError("Runtime not initialized")
        self._subscribe_commands()
        self._subscribe_measurements()
        for event in ("plugin_started", "plugin_stopped"):
            self.ha_handles.append(self.listen_event(self.plugin_event, event))
            self.mqtt_handles.append(self.mqtt_api.listen_event(self.plugin_event, event))

    def _subscribe_commands(self) -> None:
        if self.runtime is None:
            return
        for handle in self.command_handles:
            self.mqtt_api.cancel_listen_event(handle)
        self.command_handles.clear()
        for topic in self.command_topics:
            if "/session/" in topic:
                self.mqtt_api.mqtt_unsubscribe(topic)
        self.command_topics = self.runtime.mqtt.command_topics()
        for topic in self.command_topics:
            self.mqtt_api.mqtt_subscribe(topic)
            self.command_handles.append(
                self.mqtt_api.listen_event(self.mqtt_message, "MQTT_MESSAGE", topic=topic)
            )

    def _subscribe_measurements(self) -> None:
        for handle in self.measurement_handles:
            self.mqtt_api.cancel_listen_event(handle)
        self.measurement_handles.clear()
        for topic in sorted({s.topic for s in self.heating_config.measurement_sources.values()}):
            # Listen before subscribe, so timestamped retained snapshots are not missed.
            self.measurement_handles.append(
                self.mqtt_api.listen_event(self.measurement_message, "MQTT_MESSAGE", topic=topic)
            )
            self.mqtt_api.mqtt_subscribe(topic)

    def measurement_message(self, event: str, data: object, kwargs: object) -> None:
        with self._sh_lock:
            try:
                message = mapping(data)
                retained = message.get("retain")
                if self.runtime is not None and all(self.connections.values()):
                    self.runtime.reports.ingest(
                        string(message["topic"]),
                        string(message["payload"]),
                        self.runtime.clock.now(),
                        retained if isinstance(retained, bool) else None,
                    )
            except (ValueError, KeyError) as exc:
                self.log(f"Invalid measurement report: {exc}", level="WARNING")

    @init_step("main_loop", order=30)
    def init_loop(self) -> None:
        self.schedule_every(
            "main_loop",
            self.datetime() + timedelta(seconds=self.heating_config.cycle_s),
            self.heating_config.cycle_s,
            self.loop,
        )
        self.start_heartbeat(1800)

    def read(self, entity: str) -> object:
        return self.get_state(entity, attribute="all")

    def call(self, service: str, data: dict[str, object]) -> None:
        if self.heating_config.shadow or not self.heating_config.active_authorized:
            raise RuntimeError("Physical writes disabled")
        self.call_service(service, **data)

    def publish(self, topic: str, payload: str, retain: bool = True) -> None:
        self.mqtt_api.mqtt_publish(topic, payload, retain=retain)

    def loop(self, kwargs: object) -> None:
        with self._sh_lock:
            try:
                if self.runtime is not None:
                    self.runtime.tick()
            except Exception as exc:
                self.enter_safe_state(f"SmartHeating: {exc}", stop_timers=True, stop_listeners=True)

    def mqtt_message(self, event: str, data: object, kwargs: object) -> None:
        with self._sh_lock:
            try:
                message = mapping(data)
                if message.get("retain") is True:
                    self.log("Ignoring retained command", level="WARNING")
                    return
                if self.runtime is not None:
                    self.runtime.command(string(message["topic"]), string(message["payload"]))
            except (ValueError, KeyError) as exc:
                self.log(f"Rejected command: {exc}", level="WARNING")
            except Exception as exc:
                self.enter_safe_state(
                    f"Command failed: {exc}", stop_timers=True, stop_listeners=True
                )

    def plugin_event(self, event: str, data: object, kwargs: object) -> None:
        with self._sh_lock:
            record = mapping(data)
            name = str(record.get("name", ""))
            if name in self.connections and self.runtime is not None:
                self.connections[name] = event == "plugin_started"
                self.runtime.connection(all(self.connections.values()))
                if all(self.connections.values()):
                    self._subscribe_commands()
                    self._subscribe_measurements()

    def on_enter_safe_state(self) -> None:
        try:
            if self.runtime is not None:
                self.runtime.devices.blocked = True
                self.runtime.mqtt.available(False)
        except (RuntimeError, OSError) as exc:
            self.log(f"Cannot publish fault availability: {exc}", level="ERROR")
        finally:
            self._cancel_events()

    def _cancel_events(self) -> None:
        for handle in self.measurement_handles:
            self.mqtt_api.cancel_listen_event(handle)
        self.measurement_handles.clear()
        for handle in self.command_handles:
            self.mqtt_api.cancel_listen_event(handle)
        self.command_handles.clear()
        for handle in self.mqtt_handles:
            self.mqtt_api.cancel_listen_event(handle)
        self.mqtt_handles.clear()
        for handle in self.ha_handles:
            self.cancel_listen_event(handle)
        self.ha_handles.clear()

    def terminate(self) -> None:
        with self._sh_lock:
            try:
                self._cancel_events()
                if self.runtime is not None:
                    self.runtime.stop()
            finally:
                super().terminate()
