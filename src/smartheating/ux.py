"""Presentation metadata; no control decisions or HA writes."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import Config
from .model import Mode, Reading, Room, Target
from .schedules import DailySchedule
from .targets import Override

MODE_NAMES = {
    Mode.HOME: "Dom",
    Mode.SHORT: "Krótka nieobecność",
    Mode.LONG: "Wyjazd",
    Mode.PREHEAT: "Przygotowanie powrotu",
}
REASONS = {
    "wam": "Regulacja temperatur pokojów",
    "radiator_demand": "Dogrzewanie pokoi z grzejnikami",
    "safety": "Ochrona komfortu sypialni lub dziecka",
    "output_blocked_missing_input": "Brak danych do sterowania kotłem",
    "shared_circuit_overheating_conflict": "Dogrzewanie koliduje z ciepłymi pokojami",
    "boiler_device_limits_conflict": "Nastawa poza zakresem urządzenia",
}


def room_attributes(
    cfg: Config,
    room: Room,
    target: Target,
    schedule: DailySchedule | None,
    reading: Reading | None,
    override: Override | None,
    disabled: bool,
    confirmed: bool,
    now: datetime,
    arrival: datetime | None,
) -> dict[str, object]:
    point = schedule.at(now) if schedule else None
    if disabled:
        source, label = "off", "Wyłączone w tym pokoju"
    elif override:
        source = "manual"
        until = override.until.astimezone(ZoneInfo(cfg.timezone)).strftime("%d.%m %H:%M")
        label = f"Ręcznie do {until}"
    elif not point:
        source, label = "missing", "Brak harmonogramu"
    elif target.mode is Mode.PREHEAT:
        source, label = "preheat", "Przygotowanie powrotu"
    elif target.mode is Mode.HOME:
        source, label = "schedule", "Harmonogram"
    else:
        source, label = target.mode.value, MODE_NAMES[target.mode]
    start: datetime | None = None
    if arrival and reading and not room.away_exempt and target.mode is not Mode.HOME:
        needed = max(0, target.comfort - reading.value) / room.warmup_rate * 3600
        start = arrival - timedelta(seconds=min(needed + cfg.margin_s, cfg.max_lead_s))
    error = target.value - reading.value if reading else None
    return {
        "target_source": source,
        "target_source_label": label,
        "manual_override": override is not None,
        "override_until": override.until.isoformat() if override else None,
        "scheduled_temperature": point.temperature if point else None,
        "next_schedule_at": point.until.isoformat() if point else None,
        "mode_label": MODE_NAMES[target.mode],
        "measurement_available": reading is not None,
        "schedule_available": point is not None,
        "commands_confirmed": confirmed,
        "needs_heat": error is not None and error > 0.5 and not disabled,
        "in_comfort": error is not None and abs(error) <= 0.5,
        "ready_at": target.ready_at.isoformat() if target.ready_at else None,
        "preheat_start": start.isoformat() if start else None,
    }


def control_reason(reasons: list[str]) -> str:
    return "; ".join(REASONS.get(reason, reason) for reason in reasons) or "Oczekiwanie na dane"
