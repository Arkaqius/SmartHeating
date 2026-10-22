from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol


class Mode(str, Enum):
    HOME = "home"
    SHORT = "away_short"
    LONG = "away_long"
    PREHEAT = "preheat"


class Emitter(str, Enum):
    FLOOR = "floor"
    RADIATOR = "radiator"


class Clock(Protocol):
    def now(self) -> datetime: ...


class HomePort(Protocol):
    def read(self, entity: str) -> object: ...

    def call(self, service: str, data: dict[str, object]) -> None: ...


class Publisher(Protocol):
    def publish(self, topic: str, payload: str, retain: bool = True) -> None: ...


@dataclass(frozen=True)
class Reading:
    value: float
    at: datetime
    max_age_s: float | None = None

    def fresh(self, now: datetime, ttl: float) -> bool:
        from math import isfinite

        limit = self.max_age_s if self.max_age_s is not None else ttl
        return isfinite(self.value) and 0 <= (now - self.at).total_seconds() <= limit


@dataclass(frozen=True)
class Room:
    key: str
    name: str
    emitter: Emitter
    sensor: str
    schedule: str
    weight: float
    default: float
    trvs: tuple[str, ...] = ()
    short_drop: float = 1.0
    long_cap: float = 17.0
    warmup_rate: float = 0.5
    away_exempt: bool = False
    safety: bool = False


@dataclass(frozen=True)
class Target:
    value: float
    mode: Mode
    comfort: float
    slot: str
    next_boundary: datetime
    ready_at: datetime | None
    issues: tuple[str, ...] = ()
