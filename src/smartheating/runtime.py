"""Application orchestration; dependencies can be replaced by a controlled clock and fake HA."""

import json
from datetime import datetime, timezone

from . import CONFIG_SCHEMA, __version__
from .config import Config
from .control import Arbiter, Safety, voting
from .devices import Desired, Devices, Entity
from .energy import ENERGY_MODES, Energy
from .forecast import Forecasts
from .measurements import Reports
from .metrics import COUNTERS, METRIC_MODES, Metrics, Sample
from .migration import validate_bridge
from .model import Clock, HomePort, Mode, Publisher, Reading, Target
from .mqtt import Mqtt
from .persistence import StateStore
from .schedules import DailySchedule
from .targets import Override, Targets
from .ux import MODE_NAMES, control_reason, room_attributes
from .validation import boolean, bounded, instant, mapping, sequence, string


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class Runtime:
    def __init__(self, config: Config, clock: Clock, home: HomePort, publisher: Publisher) -> None:
        self.config, self.clock, self.home = config, clock, home
        self.targets = Targets(config)
        self.safety = Safety(config)
        self.safety_candidate = Safety(config)
        self.reports = Reports(config.measurement_sources)
        self.arbiter = Arbiter(config)
        self.devices = Devices(config, home)
        self.metrics = Metrics(max_gap_s=config.cycle_s * 3)
        self.energy = Energy()
        self.forecasts = Forecasts()
        self._return_now = False
        self.arrivals: list[dict[str, object]] = []
        self.mqtt = Mqtt(config, publisher)
        self.store = StateStore(config.state_path)
        self.flags = {
            "warm_flag": config.initial_warm or False,
            "force_flow_safety_rooms": config.initial_safety or False,
        }
        self.schedules: dict[str, DailySchedule] = {}
        self.latest: dict[str, Target] = {}
        self._last_publish: datetime | None = None
        self._last_heartbeat: datetime | None = None
        self._last_targets: dict[str, float] = {}
        self._recovering: set[str] = set()
        self._connected = True
        self.issues: list[str] = []
        self.evaluation: dict[str, object] = {}
        data = self.store.load()
        if data is not None:
            self.restore(data)
        elif not config.shadow and (config.initial_safety is None or config.initial_warm is None):
            raise ValueError("Migration must explicitly preserve both existing switches")
        if self.store.recovered:
            raise RuntimeError("Recovered backup: reconcile Recorder counters before resuming")
        if (
            self.evaluation.get("version") != __version__
            or self.evaluation.get("config_id") != config.config_id
        ):
            self.evaluation = {
                "started": clock.now().isoformat(),
                "version": __version__,
                "config_id": config.config_id,
                "kind": "shadow" if config.shadow else "active",
            }

    def restore(self, data: dict[str, object]) -> None:
        self.evaluation = mapping(data.get("evaluation", {}))
        self.reports.restore(data.get("measurement_reports", {}))
        self.targets.mode = Mode(string(data.get("mode", "home")))
        if self.targets.mode is Mode.PREHEAT:
            raise ValueError("Persisted mode must be an explicit house profile")
        arrival = data.get("arrival")
        self.targets.arrival = instant(arrival) if arrival else None
        keys = {r.key for r in self.config.rooms}
        for key, value in mapping(data.get("overrides", {})).items():
            record = mapping(value)
            if key not in keys:
                raise ValueError(f"Unknown persisted room {key}")
            self.targets.overrides[key] = Override(
                bounded(record["value"], 5, 30), instant(record["until"])
            )
        for disabled_key in sequence(data.get("disabled", [])):
            name = string(disabled_key)
            if name not in keys:
                raise ValueError("Unknown disabled room")
            self.targets.disabled.add(name)
        flags = mapping(data["flags"])
        self.flags = {key: boolean(flags[key]) for key in self.flags}
        self.metrics.restore(data.get("counters", {}))
        self.energy.restore(data.get("energy", {}))
        self.forecasts.restore(data.get("forecasts", {}))
        self.arrivals = [mapping(item) for item in sequence(data.get("arrivals", []))][-100:]
        self._last_targets = {
            k: bounded(v, 5, 30) for k, v in mapping(data.get("last_targets", {})).items()
        }
        self._recovering = {string(k) for k in sequence(data.get("recovering", []))}

    def snapshot(self) -> dict[str, object]:
        return {
            "evaluation": self.evaluation,
            "measurement_reports": self.reports.dump(),
            "config_schema": CONFIG_SCHEMA,
            "config_id": self.config.config_id,
            "version": __version__,
            "mode": self.targets.mode.value,
            "arrival": self.targets.arrival.isoformat() if self.targets.arrival else None,
            "overrides": {
                k: {"value": v.value, "until": v.until.isoformat()}
                for k, v in self.targets.overrides.items()
            },
            "disabled": sorted(self.targets.disabled),
            "flags": self.flags,
            "counters": self.metrics.dump(),
            "energy": self.energy.dump(),
            "forecasts": self.forecasts.dump(),
            "arrivals": self.arrivals,
            "last_targets": self._last_targets,
            "recovering": sorted(self._recovering),
        }

    def start(self) -> None:
        self.mqtt.available(False)
        self.mqtt.setup()
        self.tick()
        self.mqtt.diagnostic("command_feedback", "Gotowe na polecenia")

    def connection(self, connected: bool) -> None:
        self._connected = connected
        self.devices.blocked = not connected or self.store.recovered
        self.mqtt.cache.clear()
        if connected:
            self.mqtt.rotate_session()
            self.mqtt.setup()
            self.targets.invalidate()
            self._last_publish = None
        else:
            self.safety = Safety(self.config)
            self.safety_candidate = Safety(self.config)
            self.reports.clear()
            self.arbiter = Arbiter(self.config)
            self.energy.update(None, "unobserved")
            self.mqtt.available(False)

    def command(self, topic: str, payload: str) -> None:
        now = self.clock.now()
        prefix = self.config.base_topic + "/"
        if not topic.startswith(prefix) or topic not in self.mqtt.command_topics():
            raise ValueError("Unknown command topic")
        relative = topic[len(prefix) :]
        session_prefix = f"session/{self.mqtt.session}/"
        if relative.startswith(session_prefix):
            relative = relative[len(session_prefix) :]
        parts = relative.split("/")
        if parts[0] == "system":
            key = parts[2]
            if key in self.flags:
                if payload not in ("ON", "OFF"):
                    raise ValueError("Switch expects ON or OFF")
                self.flags[key] = payload == "ON"
            elif key == "profile":
                self.targets.select(Mode(payload))
                self.forecasts = Forecasts()
            elif key == "arrival":
                arrival = instant(payload) if payload.strip() else None
                if arrival is not None and arrival <= now:
                    raise ValueError("Wybierz przyszłą datę i godzinę powrotu")
                self.targets.set_arrival(arrival)
                self.forecasts = Forecasts()
            elif key == "cancel_arrival":
                self.targets.set_arrival(None)
                self.forecasts = Forecasts()
            elif key == "return_now":
                self.targets.select(Mode.HOME)
                self.forecasts = Forecasts()
                self._return_now = True
        else:
            room, kind, _ = parts
            if kind == "temperature":
                schedule = self.schedules.get(room)
                if schedule is None:
                    raise ValueError("Cannot bound manual override without a working schedule")
                self.targets.manual(room, bounded(payload, 5, 30), schedule.at(now).until)
            elif kind == "resume":
                if not any(r.key == room for r in self.config.rooms):
                    raise ValueError("Unknown room")
                self.targets.overrides.pop(room, None)
                self.targets.invalidate()
            elif kind == "mode":
                if payload not in ("off", "heat"):
                    raise ValueError("Unsupported virtual climate mode")
                if payload == "off":
                    self.targets.disabled.add(room)
                else:
                    self.targets.disabled.discard(room)
                self.targets.invalidate()
            elif kind == "schedule":
                record = mapping(json.loads(payload))
                configured = next(r for r in self.config.rooms if r.key == room)
                if record.get("source") != configured.schedule:
                    raise ValueError("Schedule source does not match room")
                bounded(record["temperature"], 5, 30)
                # The schedule boundary, not the arriving MQTT packet, expires manual overrides.
                # A delayed/replayed schedule event must never remove a newer override.
                self.targets.invalidate()
        self.store.save(self.snapshot())
        self.mqtt.diagnostic("command_feedback", "Ustawienie zapisane w aplikacji")
        self.targets.invalidate()
        self.tick()

    def _entity(self, entity_id: str) -> Entity | None:
        try:
            return Entity.parse(self.home.read(entity_id))
        except (ValueError, KeyError, TypeError, OSError, RuntimeError):
            return None

    def tick(self) -> None:
        now = self.clock.now()
        if not self._connected:
            self.metrics.advance(
                now,
                {r.key: Sample(self.targets.mode.value, None, False) for r in self.config.rooms},
            )
            self.store.save(self.snapshot())
            return
        readings: dict[str, Reading] = {}
        self.schedules = {}
        for room in self.config.rooms:
            source = self.config.measurement_sources.get(room.key)
            observed = self._entity(source.entity if source else room.sensor)
            if observed is not None:
                try:
                    parsed_reading = (
                        self.reports.reading(room.key, observed, now)
                        if source
                        else observed.reading()
                    )
                    if parsed_reading is not None and parsed_reading.fresh(now, self.config.ttl_s):
                        readings[room.key] = parsed_reading
                except ValueError:
                    pass
            elif source:
                self.reports.reading(room.key, None, now)
            try:
                schedule_state = self.home.read(room.schedule)
                if not self.config.shadow:
                    validate_bridge(schedule_state, room.schedule, room.key, self.config.base_topic)
                self.schedules[room.key] = DailySchedule.from_ha(
                    schedule_state, self.config.timezone
                )
            except (ValueError, KeyError, TypeError, OSError, RuntimeError):
                pass
        arrival_due = self.targets.arrival is not None and now >= self.targets.arrival
        scheduled_arrival = self.targets.arrival
        latest = self.targets.plan(now, self.schedules, readings)
        for key, target in latest.items():
            if target.mode is Mode.PREHEAT or key in self.forecasts.episodes or self._return_now:
                self.forecasts.track(key, target, readings.get(key), now, self.config.ttl_s)
        if arrival_due or self._return_now:
            previous_predictions = {key: target.ready_at for key, target in self.latest.items()}
            self.arrivals.append(
                {
                    "scheduled": scheduled_arrival.isoformat() if scheduled_arrival else None,
                    "observed": now.isoformat(),
                    "kind": "return_now" if self._return_now else "scheduled",
                    "rooms": {
                        r.key: {
                            "target": latest[r.key].value,
                            "temperature": readings[r.key].value if r.key in readings else None,
                            "previous_prediction": str(previous_predictions.get(r.key))
                            if previous_predictions.get(r.key) is not None
                            else None,
                            "forecast": self.forecasts.episodes[r.key].dump()
                            if r.key in self.forecasts.episodes
                            else None,
                        }
                        for r in self.config.rooms
                    },
                }
            )
            self.arrivals = self.arrivals[-100:]
            self._last_publish = None
            self._return_now = False
        # Complete the small event record when a room first reaches its comfort band.
        for event in self.arrivals[-1:]:
            for room_key, raw_room in mapping(event["rooms"]).items():
                if room_key in self.forecasts.episodes:
                    room_record = mapping(raw_room)
                    forecast = self.forecasts.episodes[room_key]
                    existing_forecast = room_record.get("forecast")
                    if (
                        existing_forecast is not None
                        and mapping(existing_forecast).get("started")
                        == forecast.started.isoformat()
                        and room_record.get("forecast") != forecast.dump()
                    ):
                        room_record["forecast"] = forecast.dump()
                        self._last_publish = None
        self.latest = latest
        house_mode = (
            "preheat"
            if any(t.mode is Mode.PREHEAT for t in latest.values())
            else self.targets.mode.value
        )
        energy_source = self.config.measurement_sources.get("energy")
        energy_observation = self._entity(
            energy_source.entity if energy_source else self.config.heating_energy
        )
        try:
            if energy_source:
                energy_reading = self.reports.reading("energy", energy_observation, now)
                energy_value = energy_reading.value if energy_reading else None
            else:
                # Availability qualifies a cumulative HA counter, never time since its increment.
                energy_value = (
                    bounded(energy_observation.state, 0, 1e12) if energy_observation else None
                )
        except ValueError:
            energy_value = None
        self.energy.update(energy_value, house_mode)
        errors = {
            r.key: latest[r.key].value - readings[r.key].value
            for r in self.config.rooms
            if r.key in readings and r.key in self.schedules and r.key not in self.targets.disabled
        }
        confirmed: dict[str, bool] = {}
        candidate_eligible: dict[str, bool] = {}
        for room in self.config.rooms:
            results: list[bool] = []
            eligible: list[bool] = []
            for entity_id in room.trvs:
                observation = self._entity(entity_id)
                off = room.key in self.targets.disabled
                ready = off or (room.key in readings and room.key in self.schedules)
                if not ready or observation is None:
                    self.devices.status[entity_id] = "input_unavailable"
                    results.append(False)
                    eligible.append(False)
                    continue
                try:
                    desired = Desired.for_device(
                        latest[room.key].value,
                        observation,
                        "off" if off else "auto",
                    )
                except ValueError:
                    self.devices.status[entity_id] = "device_limits_or_mode_conflict"
                    results.append(False)
                    eligible.append(False)
                    continue
                eligible.append(True)
                results.append(self.devices.reconcile(entity_id, desired, observation, now))
            confirmed[room.key] = all(results) if room.trvs else True
            candidate_eligible[room.key] = all(eligible) if room.trvs else True
        # Shadow evaluates thermal demand independently of v1's actuator settings.
        # Physical acknowledgments remain separate and are never manufactured.
        vote_errors = (
            errors if self.config.shadow else {k: v for k, v in errors.items() if confirmed[k]}
        )
        freeze = self._entity(self.config.freeze_entity) if self.config.freeze_entity else None
        vote = voting(
            self.config,
            vote_errors,
            self.flags["warm_flag"],
            freeze is not None and freeze.state == "on" and freeze.fresh(now, self.config.ttl_s),
        )
        safety = self.safety.evaluate(now, errors, confirmed, self.flags["force_flow_safety_rooms"])
        candidate = self.safety_candidate.evaluate(
            now, errors, candidate_eligible, self.config.shadow
        )
        output = self._entity(self.config.output)
        output_value: float | None = None
        if output is not None:
            try:
                output_value = output.reading().value
            except ValueError:
                pass
        command: float | None = None
        output_confirmed = False
        reasons = list(self.issues)
        if (
            vote.ordinary is not None
            and "corridor" in readings
            and output_value is not None
            and output is not None
        ):
            if self.arbiter.previous is None:
                self.arbiter.previous, self.arbiter.at = output_value, now
            command = self.arbiter.command(now, readings["corridor"].value, vote.ordinary, safety)
            try:
                command = Desired.for_device(command, output).temperature
            except ValueError:
                command = output_value
                reasons.append("boiler_device_limits_conflict")
            # Deadband applies only to new commands; readback still confirms outstanding requests.
            desired_value = (
                command
                if abs(command - output_value) >= self.config.update_threshold
                else output_value
            )
            output_confirmed = self.devices.reconcile(
                self.config.output, Desired(desired_value), output, now
            )
            reasons.append("wam")
            if vote.radiator:
                reasons.append("radiator_demand")
            if safety:
                reasons.append("safety")
            if safety and any(e < -0.5 for e in errors.values()):
                reasons.append("shared_circuit_overheating_conflict")
        else:
            reasons.append("output_blocked_missing_input")
            self.devices.status[self.config.output] = (
                "unavailable" if output is None else "input_blocked"
            )
        samples: dict[str, Sample] = {}
        for room in self.config.rooms:
            target = latest[room.key]
            if self._last_targets.get(room.key, target.value) != target.value:
                self._recovering.add(room.key)
            if room.key in errors and abs(errors[room.key]) <= 0.5:
                self._recovering.discard(room.key)
            self._last_targets[room.key] = target.value
            state = self.safety.rooms.get(room.key)
            samples[room.key] = Sample(
                target.mode.value,
                errors.get(room.key),
                state.active if state else False,
                room.key in self._recovering,
                confirmed[room.key] and output_confirmed,
            )
        self.metrics.advance(now, samples)
        periodic = self._last_publish is None or (now - self._last_publish).total_seconds() >= 300
        # Checkpoint before publishing monotonic counters, never publish a value we cannot restore.
        if periodic:
            self.store.save(self.snapshot())
            for energy_mode in ENERGY_MODES:
                self.mqtt.diagnostic(
                    f"energy_{energy_mode}_kwh", self.energy.totals[energy_mode], force=True
                )
            self.mqtt.diagnostic("energy_issue", self.energy.issue or "none", force=True)
            self._last_publish = now
        for room in self.config.rooms:
            key, target = room.key, latest[room.key]
            reading = readings.get(key)
            self.mqtt.state(
                f"{key}/availability", "online" if reading else "offline", force=periodic
            )
            self.mqtt.state(f"{key}/temperature/state", round(target.value, 2), force=periodic)
            self.mqtt.state(
                f"{key}/mode/state",
                "off" if key in self.targets.disabled else "heat",
                force=periodic,
            )
            if reading:
                self.mqtt.state(f"{key}/current_temperature/state", reading.value, force=periodic)
            attributes = room_attributes(
                self.config,
                room,
                target,
                self.schedules.get(key),
                reading,
                self.targets.overrides.get(key),
                key in self.targets.disabled,
                confirmed[key],
                now,
                self.targets.arrival,
            )
            self.mqtt.state(f"{key}/attributes", attributes, force=periodic)
            for suffix, value in {
                "target_source": attributes["target_source"],
                "override_until": attributes["override_until"],
                "temperature": reading.value if reading else None,
                "target": round(target.value, 3),
                "comfort_target": target.comfort,
                "mode": target.mode.value,
                "readiness": target.ready_at.isoformat() if target.ready_at else None,
                "issues": ",".join(target.issues) or "none",
                "safety": "no_effect"
                if key in self.safety.rooms and self.safety.rooms[key].ineffective
                else "active"
                if samples[key].safety
                else "inactive",
                "trv_status": ";".join(
                    f"{t}:{self.devices.status.get(t, 'unknown')}" for t in room.trvs
                )
                or "rtl_unobserved",
                "measurement_status": self.reports.status.get(key, "ha_entity_timestamp"),
            }.items():
                self.mqtt.diagnostic(f"{key}_{suffix}", value, force=periodic)
            if room.safety:
                candidate_state = self.safety_candidate.rooms[key]
                candidate_status = (
                    "not_shadow"
                    if not self.config.shadow
                    else "blocked_inputs"
                    if key not in errors or not candidate_eligible[key]
                    else "no_effect"
                    if candidate_state.ineffective
                    else "active_assuming_commands"
                    if candidate_state.active
                    else "qualifying"
                    if candidate_state.since
                    else "inactive"
                )
                self.mqtt.diagnostic(f"{key}_safety_candidate", candidate_status, force=periodic)
        problems: list[str] = []
        for room in self.config.rooms:
            if room.key not in readings:
                problems.append(f"{room.name}: brak aktualnego pomiaru")
            if room.key not in self.schedules:
                problems.append(f"{room.name}: brak poprawnego harmonogramu")
            if room.trvs and not confirmed[room.key] and not self.config.shadow:
                problems.append(f"{room.name}: głowice nie potwierdziły nastaw")
        if not output_confirmed and not self.config.shadow:
            problems.append("CW400: nastawa niepotwierdzona")
        if self.energy.issue:
            problems.append("Brak wiarygodnego bilansu energii EMS")
        self.mqtt.diagnostic(
            "system_status",
            "Obserwacja" if self.config.shadow else "Wymaga uwagi" if problems else "Gotowe",
            force=periodic,
        )
        self.mqtt.state(
            "system/summary",
            {
                "problems": problems,
                "measurements_valid": len(readings),
                "measurements_total": len(self.config.rooms),
                "trvs_confirmed": sum(
                    self.devices.status.get(t) == "confirmed"
                    for r in self.config.rooms
                    for t in r.trvs
                ),
                "trvs_total": sum(len(r.trvs) for r in self.config.rooms),
                "manual_overrides": len(self.targets.overrides),
                "arrival": self.targets.arrival.isoformat() if self.targets.arrival else None,
                "requesting_rooms": [
                    r.name for r in self.config.rooms if errors.get(r.key, 0) > 0.5
                ],
            },
            force=periodic,
        )
        self.mqtt.diagnostic("control_reason", control_reason(reasons), force=periodic)
        self.mqtt.diagnostic(
            "actual_mode_label",
            MODE_NAMES[Mode.PREHEAT] if house_mode == "preheat" else MODE_NAMES[self.targets.mode],
            force=periodic,
        )
        for key, value in self.flags.items():
            self.mqtt.state(f"system/control/{key}/state", "ON" if value else "OFF", force=periodic)
        self.mqtt.state("system/control/profile/state", self.targets.mode.value, force=periodic)
        self.mqtt.state(
            "system/control/arrival/state",
            self.targets.arrival.isoformat() if self.targets.arrival else "",
            force=periodic,
        )
        diagnostics: dict[str, object] = {
            "version": __version__,
            "commit": self.config.commit,
            "config_id": self.config.config_id,
            "actual_mode": Mode.PREHEAT.value
            if any(t.mode is Mode.PREHEAT for t in latest.values())
            else self.targets.mode.value,
            "total_wam": vote.wam,
            "output_setpoint": command,
            "confirmed_setpoint": output_value,
            "output_offset": command - readings["corridor"].value if command is not None else None,
            "forced_burn_offset": vote.radiator,
            "safety_room_error": max(
                (errors[r.key] for r in self.config.rooms if r.safety and r.key in errors),
                default=None,
            ),
            "max_radiator_error": max(
                (errors[r.key] for r in self.config.rooms if r.trvs and r.key in errors),
                default=None,
            ),
            "forced_burn": "ON" if vote.radiator else "OFF",
            "force_flow_safety_rooms": "ON" if safety else "OFF",
            "output_reasons": ",".join(reasons),
            "command_status": "shadow_matches_observed"
            if self.config.shadow and output_confirmed
            else self.devices.status.get(self.config.output, "unknown"),
            "evaluation_started": self.evaluation["started"],
            "evaluation_kind": self.evaluation["kind"],
            "shadow_assumptions": "demand_independent_of_v1;safety_candidate_assumes_commands"
            if self.config.shadow
            else "none",
            "safety_candidate_offset": candidate,
        }
        for key, diagnostic_value in diagnostics.items():
            self.mqtt.diagnostic(key, diagnostic_value, force=periodic)
        if periodic:
            for room in self.config.rooms:
                for mode in METRIC_MODES:
                    bucket = self.metrics.counters.get(f"{room.key}/{mode}", {})
                    for metric in COUNTERS:
                        self.mqtt.diagnostic(
                            f"{room.key}_{mode}_{metric}", bucket.get(metric, 0), force=True
                        )
        if self._last_heartbeat is None or (now - self._last_heartbeat).total_seconds() >= 30:
            self.mqtt.publisher.publish(self.mqtt.topic("system/heartbeat"), "ON", False)
            self.mqtt.available(True)
            self._last_heartbeat = now

    def stop(self) -> None:
        self.store.save(self.snapshot())
        self.mqtt.available(False)
