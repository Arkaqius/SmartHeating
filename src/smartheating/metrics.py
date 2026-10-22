"""Integrate errors before Recorder purges raw samples; counters never use mean error."""

from dataclasses import dataclass, field
from datetime import datetime

from .validation import bounded, instant, mapping, utc

COUNTERS = (
    "expected_h",
    "measured_h",
    "under_h",
    "over_h",
    "comfort_h",
    "safety_h",
    "under_degree_h",
    "over_degree_h",
    "recovery_h",
    "recovery_under_h",
    "recovery_over_h",
    "command_expected_h",
    "command_confirmed_h",
)

METRIC_MODES = ("home", "away_short", "away_long", "preheat", "unobserved")


@dataclass(frozen=True)
class Sample:
    mode: str
    error: float | None
    safety: bool
    recovery: bool = False
    command_confirmed: bool = True


@dataclass
class Metrics:
    max_gap_s: float = 15
    counters: dict[str, dict[str, float]] = field(default_factory=dict)
    at: datetime | None = None
    previous: dict[str, Sample] = field(default_factory=dict)

    def advance(self, now: datetime, samples: dict[str, Sample]) -> None:
        now = utc(now)
        if self.at is not None:
            elapsed = (now - self.at).total_seconds()
            if elapsed < 0:
                raise ValueError("Clock moved backwards; no counters credited")
            hours = elapsed / 3600
            for room, current in samples.items():
                old = self.previous.get(room)
                mode = old.mode if old else "unobserved"
                bucket = self.counters.setdefault(f"{room}/{mode}", dict.fromkeys(COUNTERS, 0.0))
                bucket["expected_h"] += hours
                if (
                    old is None
                    or old.error is None
                    or current.error is None
                    or elapsed > self.max_gap_s
                ):
                    continue
                # Left-constant integration, bounded by max_gap; never interpolate through outages.
                bucket["measured_h"] += hours
                bucket["command_expected_h"] += hours
                bucket["command_confirmed_h"] += hours if old.command_confirmed else 0
                under, over = old.error > 0.5, old.error < -0.5
                bucket["under_h" if under else "over_h" if over else "comfort_h"] += hours
                bucket["under_degree_h"] += max(0, old.error) * hours
                bucket["over_degree_h"] += max(0, -old.error) * hours
                bucket["safety_h"] += hours if old.safety else 0
                if old.recovery:
                    bucket["recovery_h"] += hours
                    bucket["recovery_under_h"] += hours if under else 0
                    bucket["recovery_over_h"] += hours if over else 0
        self.at, self.previous = now, samples

    def dump(self) -> dict[str, object]:
        return {"at": self.at.isoformat() if self.at else None, "values": self.counters}

    def restore(self, raw: object) -> None:
        data = mapping(raw)
        at = data.get("at")
        self.at = instant(at) if at is not None else None
        for key, values in mapping(data.get("values", {})).items():
            bucket = mapping(values)
            self.counters[key] = {name: bounded(bucket.get(name, 0), 0, 1e12) for name in COUNTERS}
        # Deliberately no prior sample: downtime is expected time, never measured comfort.
        self.previous.clear()
