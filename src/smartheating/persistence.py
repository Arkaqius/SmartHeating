"""Small local state only. History is owned by Home Assistant Recorder."""

import json
import os
from pathlib import Path

from . import STATE_SCHEMA
from .validation import mapping, number


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.backup = path.with_suffix(path.suffix + ".previous")
        self.recovered = False

    def load(self) -> dict[str, object] | None:
        if not self.path.exists() and not self.backup.exists():
            return None
        for path in (self.path, self.backup):
            try:
                data = mapping(json.loads(path.read_text(encoding="utf-8")))
                schema = number(data["schema"])
                if schema not in (1, STATE_SCHEMA):
                    # A newer deployment must never be silently downgraded to an old backup.
                    raise RuntimeError(f"Unsupported state schema {schema}")
                if schema == 1:
                    data = {**data, "schema": STATE_SCHEMA, "counters": data.get("counters", {})}
                self.recovered = path == self.backup
                return data
            except (OSError, ValueError, KeyError):
                continue
        raise RuntimeError("State and backup unreadable; refusing to reset counters or mode")

    @staticmethod
    def _atomic(path: Path, payload: str) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def save(self, data: dict[str, object]) -> None:
        payload = json.dumps({**data, "schema": STATE_SCHEMA}, allow_nan=False, sort_keys=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and not self.recovered:
            previous = self.path.read_text(encoding="utf-8")
            mapping(json.loads(previous))
            self._atomic(self.backup, previous)
        self._atomic(self.path, payload)
        self.recovered = False
