"""Daily HA Scheduler schedules, evaluated in local civil time and compared in UTC."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .validation import bounded, mapping, sequence, string


@dataclass(frozen=True)
class Slot:
    start: time
    temperature: float


@dataclass(frozen=True)
class SchedulePoint:
    temperature: float
    token: str
    until: datetime


@dataclass(frozen=True)
class DailySchedule:
    slots: tuple[Slot, ...]
    zone: str

    @classmethod
    def from_ha(cls, raw: object, zone: str) -> "DailySchedule":
        state = mapping(raw)
        # Scheduler uses triggered while executing the enabled plan for about a minute.
        if state.get("state") not in ("on", "triggered"):
            raise ValueError("Schedule disabled or unavailable")
        attrs = mapping(state["attributes"])
        if sequence(attrs.get("weekdays", [])) != ["daily"]:
            raise ValueError("Only daily schedules supported; do not guess other calendars")
        times = sequence(attrs["timeslots"])
        actions = sequence(attrs["actions"])
        if len(times) != len(actions) or not times:
            raise ValueError("Schedule slots and actions differ")
        slots: list[Slot] = []
        ends: list[time] = []
        for timing, action in zip(times, actions, strict=True):
            start, end = string(timing).split(" - ")
            data = mapping(action)
            if data.get("service") not in ("climate.set_temperature", "mqtt.publish"):
                raise ValueError("Unsupported scheduler action")
            values = mapping(data["data"])
            # The migrated bridge keeps the source temperature in its JSON payload.
            if data["service"] == "mqtt.publish":
                import json

                values = mapping(json.loads(string(values["payload"])))
            slots.append(Slot(time.fromisoformat(start), bounded(values["temperature"], 5, 30)))
            ends.append(time.fromisoformat(end))
        if slots[0].start != time(0) or any(s.start.tzinfo for s in slots):
            raise ValueError("Schedule must cover the whole local day")
        if any(a.start >= b.start for a, b in zip(slots, slots[1:], strict=False)):
            raise ValueError("Schedule boundaries must be strictly ordered")
        if ends != [s.start for s in slots[1:]] + [time(0)]:
            raise ValueError("Schedule must have no gaps or overlapping slots")
        return cls(tuple(slots), zone)

    def at(self, now: datetime) -> SchedulePoint:
        if now.tzinfo is None:
            raise ValueError("Clock must be timezone-aware")
        zone = ZoneInfo(self.zone)
        local_day = now.astimezone(zone).date()
        boundaries: dict[datetime, tuple[int, Slot]] = {}
        for delta in (-1, 0, 1, 2):
            for index, slot in enumerate(self.slots):
                civil = datetime.combine(local_day + timedelta(days=delta), slot.start, zone)
                # Clamp nonexistent times to the end of the gap, preserving slot order.
                while civil.astimezone(timezone.utc).astimezone(zone).replace(
                    tzinfo=None
                ) != civil.replace(tzinfo=None):
                    civil += timedelta(minutes=1)
                # Autumn folds run once (fold=0).
                boundaries[civil.astimezone(timezone.utc)] = (index, slot)
        ordered = sorted(boundaries)
        current = max(t for t in ordered if t <= now)
        following = min(t for t in ordered if t > now)
        index, selected = boundaries[current]
        return SchedulePoint(selected.temperature, f"{current.isoformat()}:{index}", following)
