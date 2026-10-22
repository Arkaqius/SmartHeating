"""Small recovery episodes for later calibration, rather than a second history database."""

from dataclasses import dataclass, field
from datetime import datetime

from .model import Reading, Target
from .validation import bounded, instant, mapping, number


@dataclass
class Episode:
    started: datetime
    goal: float
    start_temperature: float | None
    predicted: datetime | None
    observed_ready: datetime | None = None

    def dump(self) -> dict[str, object]:
        return {
            "started": self.started.isoformat(),
            "goal": self.goal,
            "start_temperature": self.start_temperature,
            "predicted": self.predicted.isoformat() if self.predicted else None,
            "observed_ready": self.observed_ready.isoformat() if self.observed_ready else None,
        }


@dataclass
class Forecasts:
    episodes: dict[str, Episode] = field(default_factory=dict)

    def track(
        self, key: str, target: Target, reading: Reading | None, now: datetime, ttl: float
    ) -> None:
        current = self.episodes.get(key)
        if current is None or abs(current.goal - target.comfort) > 0.01:
            current = Episode(
                now, target.comfort, reading.value if reading else None, target.ready_at
            )
            self.episodes[key] = current
        if reading and reading.fresh(now, ttl) and current.observed_ready is None:
            if abs(current.goal - reading.value) <= 0.5:
                current.observed_ready = max(current.started, reading.at)

    def restore(self, raw: object) -> None:
        for key, value in mapping(raw).items():
            record = mapping(value)
            predicted, observed = record.get("predicted"), record.get("observed_ready")
            temperature = record.get("start_temperature")
            self.episodes[key] = Episode(
                instant(record["started"]),
                bounded(record["goal"], 5, 30),
                number(temperature) if temperature is not None else None,
                instant(predicted) if predicted else None,
                instant(observed) if observed else None,
            )

    def dump(self) -> dict[str, object]:
        return {key: episode.dump() for key, episode in self.episodes.items()}
