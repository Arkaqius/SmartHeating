from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .config import Config
from .model import Emitter, Mode, Reading, Target
from .schedules import DailySchedule
from .validation import utc


@dataclass(frozen=True)
class Override:
    value: float
    until: datetime


@dataclass
class Targets:
    config: Config
    mode: Mode = Mode.HOME
    arrival: datetime | None = None
    overrides: dict[str, Override] = field(default_factory=dict)
    disabled: set[str] = field(default_factory=set)
    _cache: dict[str, Target] = field(default_factory=dict)
    _planned_at: datetime | None = None
    _schedule_snapshot: dict[str, DailySchedule] = field(default_factory=dict)
    _fresh_rooms: set[str] = field(default_factory=set)

    def select(self, mode: Mode) -> None:
        if mode is Mode.PREHEAT:
            raise ValueError("Preheat is a derived room mode")
        self.mode = mode
        self.overrides.clear()
        if mode is Mode.HOME:
            self.arrival = None
        self.invalidate()

    def set_arrival(self, arrival: datetime | None) -> None:
        if arrival is not None and arrival.tzinfo is None:
            raise ValueError("Arrival requires timezone")
        self.arrival = arrival
        self.invalidate()

    def invalidate(self) -> None:
        self._planned_at = None

    def manual(self, room: str, value: float, until: datetime) -> None:
        self.overrides[room] = Override(value, until)
        self.invalidate()

    def plan(
        self, now: datetime, schedules: dict[str, DailySchedule], readings: dict[str, Reading]
    ) -> dict[str, Target]:
        now = utc(now)
        if self.arrival is not None and now >= self.arrival:
            self.select(Mode.HOME)
        for key in list(self.overrides):
            if now >= self.overrides[key].until:
                del self.overrides[key]
                self.invalidate()
        # Schedule changes invalidate independently from the five-minute forecast interval.
        tokens = {k: s.at(now).token for k, s in schedules.items()}
        fresh_rooms = {
            key for key, reading in readings.items() if reading.fresh(now, self.config.ttl_s)
        }
        if (
            self._planned_at is not None
            and schedules == self._schedule_snapshot
            and fresh_rooms == self._fresh_rooms
            and 0 <= (now - self._planned_at).total_seconds() < self.config.plan_s
            and all(
                k in self._cache and self._cache[k].slot == token for k, token in tokens.items()
            )
            and all((k in schedules) == (t.slot != "missing") for k, t in self._cache.items())
        ):
            return self._cache
        result: dict[str, Target] = {}
        for room in self.config.rooms:
            issues: list[str] = []
            schedule = schedules.get(room.key)
            if schedule is None:
                scheduled, slot, until = room.default, "missing", now
                issues.append("schedule_unavailable")
            else:
                point = schedule.at(now)
                scheduled, slot, until = point.temperature, point.token, point.until
            comfort = scheduled
            effective = scheduled
            room_mode = self.mode
            if not room.away_exempt:
                if self.mode is Mode.SHORT:
                    effective = max(5, scheduled - room.short_drop)
                elif self.mode is Mode.LONG:
                    effective = min(scheduled, room.long_cap)
            reading = readings.get(room.key)
            fresh = reading is not None and reading.fresh(now, self.config.ttl_s)
            ready_at = None
            if self.arrival is not None and self.mode is not Mode.HOME and not room.away_exempt:
                comfort = schedule.at(self.arrival).temperature if schedule else scheduled
            if fresh and reading is not None:
                needed_s = max(0, comfort - reading.value) / room.warmup_rate * 3600
                ready_at = now + timedelta(
                    seconds=needed_s + (self.config.margin_s if needed_s else 0)
                )
                if self.arrival is not None and self.mode is not Mode.HOME and not room.away_exempt:
                    remaining_s = (self.arrival - now).total_seconds()
                    lead = min(needed_s + self.config.margin_s, self.config.max_lead_s)
                    if needed_s + self.config.margin_s > self.config.max_lead_s:
                        issues.append("lead_capped")
                    if remaining_s < needed_s:
                        issues.append("arrival_may_be_missed")
                    if remaining_s <= lead:
                        room_mode = Mode.PREHEAT
                        if room.emitter is Emitter.FLOOR:
                            # A moving target envelope reaches comfort before arrival.
                            ramp = (
                                comfort
                                - room.warmup_rate
                                * max(0, remaining_s - self.config.margin_s)
                                / 3600
                            )
                            effective = min(comfort, max(effective, ramp))
                        else:
                            effective = comfort
            else:
                issues.append("measurement_unavailable")
                # No forecast is invented. Start conservative preparation inside the lead cap.
                if (
                    self.arrival is not None
                    and self.mode is not Mode.HOME
                    and not room.away_exempt
                    and (self.arrival - now).total_seconds() <= self.config.max_lead_s
                ):
                    room_mode, effective = Mode.PREHEAT, comfort
            override = self.overrides.get(room.key)
            if override:
                effective = override.value
                if fresh and reading is not None:
                    needed_s = max(0, effective - reading.value) / room.warmup_rate * 3600
                    ready_at = now + timedelta(
                        seconds=needed_s + (self.config.margin_s if needed_s else 0)
                    )
            if room.away_exempt:
                room_mode = Mode.HOME
            result[room.key] = Target(
                effective, room_mode, comfort, slot, until, ready_at, tuple(issues)
            )
        self._cache, self._planned_at = result, now
        self._schedule_snapshot = schedules.copy()
        self._fresh_rooms = fresh_rooms
        return result
