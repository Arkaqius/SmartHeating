"""Allocate estimated EMS CO increments by house mode, keeping uncertain intervals explicit."""

from dataclasses import dataclass, field

from .validation import bounded, mapping

ENERGY_MODES = ("home", "away_short", "away_long", "preheat", "mixed", "unobserved")


@dataclass
class Energy:
    totals: dict[str, float] = field(default_factory=lambda: dict.fromkeys(ENERGY_MODES, 0.0))
    last: float | None = None
    mode: str = "unobserved"
    issue: str | None = None

    def update(self, value: float | None, mode: str) -> None:
        if value is None:
            self.mode = "unobserved"
            self.issue = "ems_unavailable"
            return
        if self.issue == "ems_unavailable":
            self.issue = None
        if self.last is not None:
            delta = value - self.last
            if delta < 0:
                self.issue = "ems_counter_reset"
            elif delta:
                destination = self.mode if mode == self.mode else "mixed"
                if self.mode == "unobserved":
                    destination = "unobserved"
                self.totals[destination] += delta
                self.issue = None
                self.mode = mode
        self.last = value
        # A mode transition before the next EMS increment makes the interval ambiguous.
        if self.mode not in (mode, "unobserved"):
            self.mode = "mixed"
        else:
            self.mode = mode

    def dump(self) -> dict[str, object]:
        return {"totals": self.totals, "last": self.last}

    def restore(self, raw: object) -> None:
        record = mapping(raw)
        totals = mapping(record.get("totals", {}))
        self.totals = {mode: bounded(totals.get(mode, 0), 0, 1e12) for mode in ENERGY_MODES}
        value = record.get("last")
        self.last = bounded(value, 0, 1e12) if value is not None else None
        self.mode = "unobserved"
