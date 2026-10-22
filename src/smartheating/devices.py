"""Validated observations and bounded, read-back-confirmed command reconciliation."""

from dataclasses import dataclass, field
from datetime import datetime

from .config import Config
from .model import HomePort, Reading
from .validation import bounded, instant, mapping, number, utc


@dataclass(frozen=True)
class Entity:
    state: str
    attributes: dict[str, object]
    reported: datetime

    @classmethod
    def parse(cls, raw: object) -> "Entity":
        data = mapping(raw)
        state = data.get("state")
        if not isinstance(state, str) or state in ("unknown", "unavailable"):
            raise ValueError("Entity unavailable")
        return cls(
            state,
            mapping(data.get("attributes", {})),
            instant(data.get("last_reported", data.get("last_updated"))),
        )

    def fresh(self, now: datetime, ttl: float) -> bool:
        return 0 <= (now - self.reported).total_seconds() <= ttl

    def reading(self) -> Reading:
        value = number(self.state)
        if not -50 <= value <= 80:
            raise ValueError("Temperature out of plausible range")
        return Reading(value, self.reported)


@dataclass(frozen=True)
class Desired:
    temperature: float
    mode: str | None = None
    preset: str | None = None

    @classmethod
    def for_device(cls, temperature: float, entity: Entity, mode: str | None = None) -> "Desired":
        attrs = entity.attributes
        low = number(attrs.get("min_temp" if mode else "min", 5))
        high = number(attrs.get("max_temp" if mode else "max", 30))
        step = bounded(attrs.get("target_temp_step" if mode else "step", 0.5), 0.01, 5)
        if not low <= temperature <= high:
            raise ValueError("Requested temperature exceeds device limits")
        if mode is not None:
            modes = attrs.get("hvac_modes")
            presets = attrs.get("preset_modes")
            if not isinstance(modes, list) or mode not in modes:
                raise ValueError("Device does not support required mode")
            if not isinstance(presets, list) or "manual" not in presets:
                raise ValueError("Device does not support manual preset")
        value = min(high, max(low, low + round((temperature - low) / step) * step))
        return cls(round(value, 4), mode, "manual" if mode else None)

    def matches(self, entity: Entity) -> bool:
        try:
            value = number(entity.state if self.mode is None else entity.attributes["temperature"])
        except (ValueError, KeyError):
            return False
        return (
            abs(value - self.temperature) < 0.06
            and (self.mode is None or entity.state == self.mode)
            and (self.preset is None or entity.attributes.get("preset_mode") == self.preset)
        )


@dataclass
class Pending:
    desired: Desired
    attempts: int = 0
    sent_at: datetime | None = None
    failed_at: datetime | None = None


@dataclass
class Devices:
    config: Config
    port: HomePort
    pending: dict[str, Pending] = field(default_factory=dict)
    status: dict[str, str] = field(default_factory=dict)
    blocked: bool = False

    def reconcile(
        self, entity_id: str, desired: Desired, observation: Entity | None, now: datetime
    ) -> bool:
        now = utc(now)
        # Setpoints can remain unchanged for days. Availability and connection gates,
        # rather than temperature TTL, qualify this HA state snapshot.
        if observation is None:
            self.status[entity_id] = "unavailable"
            return False
        pending = self.pending.get(entity_id)
        if pending is not None and desired.mode == "off" and pending.desired.mode != "off":
            pending = Pending(desired)
            self.pending[entity_id] = pending
        if desired.matches(observation):
            self.pending.pop(entity_id, None)
            self.status[entity_id] = "confirmed"
            return True
        if self.config.shadow or self.blocked:
            self.status[entity_id] = (
                "shadow_difference" if self.config.shadow else "connection_blocked"
            )
            return False
        if pending and pending.failed_at is not None:
            if (now - pending.failed_at).total_seconds() < self.config.retry_cooldown_s:
                self.status[entity_id] = "unconfirmed"
                return False
            pending = None
        if pending is not None and pending.desired.matches(observation):
            pending = None
        if pending is None:
            pending = Pending(desired)
            self.pending[entity_id] = pending
        elif pending.desired != desired:
            pending.desired = desired
        # Supersede intent without resetting the retry budget for a changing temperature.
        if pending.sent_at and (now - pending.sent_at).total_seconds() < self.config.retry_s:
            self.status[entity_id] = "awaiting_confirmation"
            return False
        if pending.attempts >= self.config.max_attempts:
            pending.failed_at = now
            self.status[entity_id] = "unconfirmed"
            return False
        pending.attempts += 1
        pending.sent_at = now
        try:
            self._send(entity_id, pending.desired)
        except (RuntimeError, OSError, ValueError):
            self.status[entity_id] = "transport_error"
        else:
            self.status[entity_id] = "awaiting_confirmation"
        return False

    def _send(self, entity: str, desired: Desired) -> None:
        if self.config.shadow or self.blocked or not self.config.active_authorized:
            raise RuntimeError("Actuator writes disabled")
        if desired.mode is None:
            self.port.call("number/set_value", {"entity_id": entity, "value": desired.temperature})
        else:
            # TS0601: heat forces the valve open; auto + manual preset regulates temperature.
            self.port.call(
                "climate/set_hvac_mode", {"entity_id": entity, "hvac_mode": desired.mode}
            )
            if desired.preset:
                self.port.call(
                    "climate/set_preset_mode", {"entity_id": entity, "preset_mode": desired.preset}
                )
            self.port.call(
                "climate/set_temperature", {"entity_id": entity, "temperature": desired.temperature}
            )
