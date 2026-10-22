"""Validate untrusted HA, MQTT, configuration and persisted JSON at the boundary."""

from datetime import datetime, timezone
from math import isfinite
from typing import cast


def mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        raise ValueError("Expected an object with string keys")
    return cast(dict[str, object], value)


def sequence(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Expected a list")
    return cast(list[object], value)


def number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        raise ValueError("Expected a finite number")
    result = float(value)
    if not isfinite(result):
        raise ValueError("Expected a finite number")
    return result


def bounded(value: object, minimum: float, maximum: float) -> float:
    result = number(value)
    if not minimum <= result <= maximum:
        raise ValueError(f"Value outside {minimum}..{maximum}")
    return result


def string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected text")
    return value


def boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("Expected true/false")
    return value


def instant(value: object) -> datetime:
    result = datetime.fromisoformat(string(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp must include timezone offset")
    return result.astimezone(timezone.utc)


def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Clock must include timezone")
    return value.astimezone(timezone.utc)
