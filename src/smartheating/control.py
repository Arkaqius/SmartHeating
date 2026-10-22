"""Pure control decisions. A request does not establish flame, flow or delivered heat."""

from dataclasses import dataclass, field
from datetime import datetime

from .config import Config
from .model import Emitter
from .validation import utc


@dataclass(frozen=True)
class Vote:
    wam: float | None
    ordinary: float | None
    radiator: float


def voting(config: Config, errors: dict[str, float], warm: bool, freeze: bool) -> Vote:
    floor = [r for r in config.rooms if r.emitter is Emitter.FLOOR and r.key in errors]
    total = sum(r.weight for r in floor)
    if not total or "corridor" not in errors:
        return Vote(None, None, 0)
    wam = round(sum(errors[r.key] * r.weight for r in floor) / total, 2)
    base = wam + (config.warm_offset if warm else 0) + (config.freeze_offset if freeze else 0)
    rad = [r for r in config.rooms if r.emitter is Emitter.RADIATOR and r.key in errors]
    rad_total = sum(r.weight for r in rad)
    boost = 0.0
    if (
        errors["corridor"] + base < 0
        and rad_total
        and any(errors[r.key] > config.rad_threshold for r in rad)
    ):
        boost = sum(max(errors[r.key] * r.weight / rad_total, 0) for r in rad) * config.rad_factor
    return Vote(wam, base + boost, boost)


@dataclass
class SafetyRoom:
    since: datetime | None = None
    active: bool = False
    ineffective: bool = False

    def update(self, now: datetime, error: float | None, confirmed: bool, cfg: Config) -> float:
        now = utc(now)
        if error is None or not confirmed:
            # Restart qualification; never turn missing evidence into continued escalation.
            self.since, self.active, self.ineffective = None, False, False
            return 0
        if error < cfg.safety_off:
            self.since, self.active, self.ineffective = None, False, False
        elif error > cfg.safety_on:
            if self.since is None:
                self.since = now
            duration = (now - self.since).total_seconds()
            self.active = self.active or duration >= cfg.safety_delay_s
            self.ineffective = duration >= cfg.safety_diagnostic_s
        elif not self.active:
            self.since = None
        if self.active and self.since is not None:
            self.ineffective = (now - self.since).total_seconds() >= cfg.safety_diagnostic_s
        return cfg.safety_offset if self.active else 0


@dataclass
class Safety:
    config: Config
    rooms: dict[str, SafetyRoom] = field(default_factory=dict)

    def evaluate(
        self, now: datetime, errors: dict[str, float], confirmed: dict[str, bool], enabled: bool
    ) -> float:
        requests = [0.0]
        for room in self.config.rooms:
            if room.safety:
                state = self.rooms.setdefault(room.key, SafetyRoom())
                requests.append(
                    state.update(
                        now,
                        errors.get(room.key) if enabled else None,
                        confirmed.get(room.key, False),
                        self.config,
                    )
                )
        return max(requests)


@dataclass
class Arbiter:
    config: Config
    previous: float | None = None
    at: datetime | None = None

    def command(self, now: datetime, baseline: float, ordinary: float, safety: float) -> float:
        now = utc(now)
        desired = baseline + (max(ordinary, safety) if safety > 0 else ordinary)
        desired = min(self.config.max_setpoint, max(self.config.min_setpoint, desired))
        if self.previous is not None and self.at is not None:
            # Long outages do not allow a large first jump after recovery.
            elapsed = min(60, max(0, (now - self.at).total_seconds()))
            step = self.config.slew_per_minute * elapsed / 60
            desired = min(self.previous + step, max(self.previous - step, desired))
        self.previous, self.at = desired, now
        return desired
