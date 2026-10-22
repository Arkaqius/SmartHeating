"""Qualify published measurement snapshots independently of HA value changes.

Z2M snapshots retain their publisher timestamp, including after resubscription.
For untimestamped EMS reports the first message is quarantined whenever the
plugin omits the retain flag. A later report qualifies receipt, never a constant
HA value. Receipt is evidence of a published snapshot, not a firmware sample.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .model import Reading
from .validation import bounded, instant, mapping, string, utc

if TYPE_CHECKING:
    from .devices import Entity


@dataclass(frozen=True)
class Source:
    entity: str
    topic: str
    value_path: tuple[str, ...]
    max_age_s: float
    timestamp_key: str = ""
    counter: bool = False

    @classmethod
    def parse(cls, raw: object, *, counter: bool = False) -> Source:
        data = mapping(raw)
        entity, topic = string(data["entity"]), string(data["topic"])
        path = string(data["value_path"])
        if not entity.startswith("sensor.") or not topic or "+" in topic or "#" in topic:
            raise ValueError("Measurement source requires a sensor and an exact MQTT topic")
        if not path or any(not key for key in path.split(".")):
            raise ValueError("Measurement value_path must contain nonempty keys")
        return cls(
            entity,
            topic,
            tuple(path.split(".")),
            bounded(data["max_age_s"], 30, 86400),
            string(data.get("timestamp_key", "")),
            counter,
        )


@dataclass
class Reports:
    sources: dict[str, Source]
    latest: dict[str, Reading] = field(default_factory=dict)
    quarantine: dict[str, datetime] = field(default_factory=dict)
    status: dict[str, str] = field(default_factory=dict)
    invalid: set[str] = field(default_factory=set)

    def clear(self) -> None:
        self.latest.clear()
        self.quarantine.clear()
        self.status.clear()
        self.invalid.clear()

    def dump(self) -> dict[str, object]:
        return {
            key: {
                "entity": self.sources[key].entity,
                "topic": self.sources[key].topic,
                "value_path": list(self.sources[key].value_path),
                "timestamp_key": self.sources[key].timestamp_key,
                "value": reading.value,
                "at": reading.at.isoformat(),
            }
            for key, reading in self.latest.items()
            # EMS requires new live evidence after restart, not a cached receipt time.
            if self.sources[key].timestamp_key
        }

    def restore(self, raw: object) -> None:
        for key, value in mapping(raw).items():
            source = self.sources.get(key)
            if source is None or not source.timestamp_key:
                continue
            record = mapping(value)
            if (
                record.get("entity") != source.entity
                or record.get("topic") != source.topic
                or record.get("value_path") != list(source.value_path)
                or record.get("timestamp_key") != source.timestamp_key
            ):
                continue
            self.latest[key] = Reading(
                bounded(record["value"], -50, 80), instant(record["at"]), source.max_age_s
            )

    def ingest(self, topic: str, payload: str, now: datetime, retained: bool | None) -> None:
        now = utc(now)
        for key, source in self.sources.items():
            if topic != source.topic:
                continue
            try:
                data = mapping(json.loads(payload))
                value: object = data
                for part in source.value_path:
                    value = mapping(value)[part]
                parsed = bounded(
                    value, 0 if source.counter else -50, 1e12 if source.counter else 80
                )
                if source.timestamp_key:
                    epoch = bounded(data[source.timestamp_key], 0, 1e15)
                    at = datetime.fromtimestamp(
                        epoch / 1000 if epoch > 1e11 else epoch, timezone.utc
                    )
                elif retained is True:
                    self.status[key] = "retained_without_timestamp"
                    continue
                elif retained is None:
                    first = self.quarantine.setdefault(key, now)
                    if (now - first).total_seconds() < 5:
                        self.status[key] = "waiting_live_report"
                        continue
                    at = now
                else:
                    at = now
                reading = Reading(parsed, at, source.max_age_s)
                if not reading.fresh(now, source.max_age_s):
                    self.status[key] = "stale_or_future_report"
                    continue
                previous = self.latest.get(key)
                if previous is not None and reading.at < previous.at:
                    self.status[key] = "out_of_order_report"
                    continue
                self.latest[key] = reading
                self.invalid.discard(key)
                self.status[key] = "published_snapshot"
            except KeyError:
                # A humidity-only packet must not refresh or erase a temperature.
                continue
            except (ValueError, TypeError, OverflowError, OSError):
                self.latest.pop(key, None)
                self.invalid.add(key)
                self.status[key] = "invalid_report"

    def reading(self, key: str, entity: Entity | None, now: datetime) -> Reading | None:
        source = self.sources[key]
        if entity is None or key in self.invalid:
            self.status[key] = "source_unavailable" if entity is None else "invalid_report"
            return None
        # Validate the HA source as well: cached MQTT must not mask NaN/unavailable.
        try:
            bounded(entity.state, 0 if source.counter else -50, 1e12 if source.counter else 80)
        except ValueError:
            self.status[key] = "source_invalid"
            return None
        snapshot = self.latest.get(key)
        if snapshot is not None:
            if snapshot.fresh(now, source.max_age_s):
                self.status[key] = "published_snapshot"
                return snapshot
            self.status[key] = "report_expired"
            return None
        # A retained value re-created by HA can have a new HA timestamp. Only a
        # timestamped publisher snapshot or a qualified live receipt proves age.
        self.status[key] = "waiting_live_report"
        return None
