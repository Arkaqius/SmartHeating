"""Weekly evidence from long-term hourly statistics, independent of raw history retention."""

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import REPORT_SCHEMA, __version__
from .config import NAMES
from .energy import ENERGY_MODES
from .ha_api import reader_from_environment
from .metrics import COUNTERS, METRIC_MODES
from .validation import bounded, instant, mapping, number, sequence, string, utc

GAS_FACTOR = 11.594
ENERGY_CH = "sensor.boiler_energy_heating"
ENERGY_DHW = "sensor.boiler_dhw_energy"
OUTSIDE = "sensor.boiler_outside_temperature_2"


@dataclass(frozen=True)
class Point:
    start: datetime
    total: float | None
    mean: float | None


def parse_statistics(raw: object) -> dict[str, list[Point]]:
    result: dict[str, list[Point]] = {}
    for entity, values in mapping(raw).items():
        points: dict[datetime, Point] = {}
        for record in sequence(values):
            item = mapping(record)
            start = item["start"]
            if isinstance(start, int | float):
                # HA websocket uses milliseconds, exports may use seconds or ISO strings.
                timestamp = number(start)
                at = datetime.fromtimestamp(
                    timestamp / 1000 if timestamp > 1e11 else timestamp, timezone.utc
                )
            else:
                at = instant(start)
            total, mean = item.get("sum"), item.get("mean")
            points[at] = Point(
                at,
                number(total) if total is not None else None,
                number(mean) if mean is not None else None,
            )
        result[entity] = sorted(points.values(), key=lambda p: p.start)
    return result


def counter_delta(points: list[Point], start: datetime, end: datetime) -> float | None:
    # Sum is the end-of-hour cumulative statistic; require the preceding hour as baseline.
    selected = {p.start: p.total for p in points if start - timedelta(hours=1) <= p.start < end}
    hours = int((end - start).total_seconds() / 3600)
    expected = [start + timedelta(hours=i) for i in range(-1, hours)]
    if any(selected.get(at) is None for at in expected):
        return None
    values = [selected[at] for at in expected]
    if any(
        a is not None and b is not None and b < a for a, b in zip(values, values[1:], strict=False)
    ):
        return None
    first, last = values[0], values[-1]
    return last - first if first is not None and last is not None else None


def gas_comparison(
    m3: float,
    ems_kwh: float,
    invoice_from: str | None = None,
    invoice_to: str | None = None,
    period_from: str | None = None,
    period_to: str | None = None,
) -> dict[str, object]:
    volume = bounded(m3, 0.000001, 1e12)
    estimate = not (
        invoice_from
        and invoice_to
        and period_from
        and period_to
        and invoice_from <= period_from <= period_to <= invoice_to
    )
    energy = volume * GAS_FACTOR
    return {
        "m3": volume,
        "factor_kwh_m3": GAS_FACTOR,
        "factor_source": "user invoice",
        "invoice_from": invoice_from,
        "invoice_to": invoice_to,
        "estimated": estimate,
        "invoice_equivalent_kwh": energy,
        "ems_kwh": bounded(ems_kwh, 0, 1e12),
        "ems_difference_percent": 100 * (ems_kwh / energy - 1),
    }


@dataclass(frozen=True)
class Experiment:
    parameter: str
    before: float
    after: float
    hypothesis: str
    observation_hours: int
    rollback: str
    approved: bool = False

    def validate(self) -> None:
        # Initial scope excludes targets, burner service settings and boiler protections.
        allowed = (
            "warmup_rate",
            "short_drop",
            "long_cap",
            "weight",
            "safety_delay_s",
            "slew_per_minute",
        )
        if self.parameter.split(".")[-1] not in allowed:
            raise ValueError("Parameter is outside recommendation scope")
        number(self.before)
        number(self.after)
        if not self.hypothesis or not self.rollback or self.observation_hours < 48:
            raise ValueError("Experiment requires a hypothesis, >=48h and rollback condition")


def build_report(
    raw: object,
    end: datetime,
    prefix: str = "sh",
    rooms: tuple[str, ...] = tuple(NAMES),
    experiment: Experiment | None = None,
    arrivals: list[object] | None = None,
    evaluation_started: datetime | None = None,
) -> dict[str, object]:
    end = utc(end).replace(minute=0, second=0, microsecond=0)
    start, baseline = end - timedelta(days=7), end - timedelta(days=14)
    points = parse_statistics(raw)
    issues: list[str] = []
    if evaluation_started is not None and utc(evaluation_started) > baseline:
        issues.append("need_14_days_in_current_evaluation")
    room_reports: dict[str, object] = {}
    baseline_ok = True
    for room in rooms:
        modes: dict[str, object] = {}
        measured = 0.0
        baseline_measured = 0.0
        totals = dict.fromkeys(COUNTERS, 0.0)
        for mode in METRIC_MODES:
            values: dict[str, float | None] = {}
            for metric in COUNTERS:
                series = points.get(f"sensor.{prefix}_{room}_{mode}_{metric}", [])
                values[metric] = counter_delta(series, start, end)
                if values[metric] is None:
                    issues.append(f"missing_statistics:{room}/{mode}/{metric}")
                totals[metric] += values[metric] or 0
                if metric == "measured_h":
                    measured += values[metric] or 0
                    baseline_value = counter_delta(series, baseline, end)
                    if baseline_value is None:
                        baseline_ok = False
                    baseline_measured += baseline_value or 0
            modes[mode] = values
        coverage = min(1.0, measured / 168)
        if measured > 168.01:
            issues.append(f"overlapping_measured_time:{room}")
        if abs(totals["under_h"] + totals["over_h"] + totals["comfort_h"] - measured) > 0.01:
            issues.append(f"inconsistent_comfort_counters:{room}")
        if totals["command_confirmed_h"] > totals["command_expected_h"] + 0.01:
            issues.append(f"inconsistent_command_counters:{room}")
        if coverage < 0.95:
            issues.append(f"coverage_below_95:{room}")
        if baseline_measured / 336 < 0.95:
            baseline_ok = False
        command_coverage = (
            totals["command_confirmed_h"] / totals["command_expected_h"]
            if totals["command_expected_h"]
            else 0
        )
        if command_coverage < 0.95:
            issues.append(f"unconfirmed_commands:{room}")
        steady_h = totals["measured_h"] - totals["recovery_h"]
        recovery_comfort = (
            totals["recovery_h"] - totals["recovery_under_h"] - totals["recovery_over_h"]
        )
        room_reports[room] = {
            "coverage": coverage,
            "modes": modes,
            "totals": totals,
            "command_confirmation_coverage": command_coverage,
            "steady_comfort_fraction": (totals["comfort_h"] - recovery_comfort) / steady_h
            if steady_h
            else None,
        }
    if not baseline_ok:
        issues.append("need_14_days_of_reliable_data")
    ch = counter_delta(points.get(ENERGY_CH, []), start, end)
    dhw = counter_delta(points.get(ENERGY_DHW, []), start, end)
    previous_ch = counter_delta(points.get(ENERGY_CH, []), baseline, start)

    def degree_days(window_start: datetime, window_end: datetime) -> float | None:
        weather = {
            p.start: p.mean for p in points.get(OUTSIDE, []) if window_start <= p.start < window_end
        }
        expected = [window_start + timedelta(hours=i) for i in range(168)]
        if any(weather.get(at) is None for at in expected):
            return None
        return sum(max(0, 18 - number(weather[at])) / 24 for at in expected)

    hdd, previous_hdd = degree_days(start, end), degree_days(baseline, start)
    if ch is None or dhw is None or hdd is None or previous_ch is None or previous_hdd is None:
        issues.append("incomplete_energy_or_weather")
    allocation = {
        mode: counter_delta(points.get(f"sensor.{prefix}_energy_{mode}_kwh", []), start, end)
        for mode in ENERGY_MODES
    }
    if any(v is None for v in allocation.values()):
        issues.append("missing_energy_mode_allocation")
    if ch is not None and abs(sum(v or 0 for v in allocation.values()) - ch) > max(0.1, ch * 0.05):
        issues.append("energy_allocation_does_not_reconcile")
    if ch and ((allocation.get("unobserved") or 0) + (allocation.get("mixed") or 0)) / ch > 0.05:
        issues.append("energy_mode_coverage_below_95")
    # Preserve report evidence without allowing a recommendation when required data is missing.
    if experiment is not None:
        experiment.validate()
    arrival_results = assess_arrivals(arrivals or [], start, end)
    if (
        experiment is not None
        and experiment.parameter.endswith("warmup_rate")
        and not any(mapping(value)["completed_forecasts"] for value in arrival_results.values())
    ):
        issues.append("warmup_experiment_needs_completed_recovery")
    allowed = not issues
    proposed = asdict(experiment) if allowed and experiment is not None else None
    return {
        "schema": REPORT_SCHEMA,
        "version": __version__,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "rooms": room_reports,
        "issues": sorted(set(issues)),
        "tuning_eligible": allowed,
        "recommendation": proposed or "continue_observation",
        "energy": {
            "ch_kwh": ch,
            "dhw_kwh": dhw,
            "degree_days_base18": hdd,
            "ch_kwh_per_degree_day": ch / hdd if ch is not None and hdd else None,
            "previous_ch_kwh_per_degree_day": previous_ch / previous_hdd
            if previous_ch is not None and previous_hdd
            else None,
            "mode_allocation_kwh": allocation,
            "caution": "Weather normalization is descriptive, not causal proof of savings",
        },
        "arrivals": arrival_results,
        "gas_factor_kwh_m3": GAS_FACTOR,
        "invoice_period": "not_supplied",
        "control": "recommendations_only",
        "evaluation_started": evaluation_started.isoformat() if evaluation_started else None,
    }


def assess_arrivals(events: list[object], start: datetime, end: datetime) -> dict[str, object]:
    summaries: dict[str, dict[str, object]] = {}
    for event_raw in events:
        event = mapping(event_raw)
        at = instant(event.get("scheduled") or event["observed"])
        if not start <= at < end:
            continue
        timely = abs((instant(event["observed"]) - at).total_seconds()) <= 300
        for key, room_raw in mapping(event["rooms"]).items():
            room = mapping(room_raw)
            summary = summaries.setdefault(
                key,
                {
                    "events": 0,
                    "timely_observations": 0,
                    "within_band": 0,
                    "completed_forecasts": 0,
                    "forecast_abs_error_minutes": [],
                    "arrival_errors_c": [],
                },
            )
            summary["events"] = number(summary["events"]) + 1
            temperature = room.get("temperature")
            if timely and temperature is not None:
                error = number(temperature) - number(room["target"])
                sequence(summary["arrival_errors_c"]).append(error)
                summary["timely_observations"] = number(summary["timely_observations"]) + 1
                summary["within_band"] = number(summary["within_band"]) + (
                    1 if abs(error) <= 0.5 else 0
                )
            forecast_raw = room.get("forecast")
            if forecast_raw is not None:
                forecast = mapping(forecast_raw)
                predicted, observed = forecast.get("predicted"), forecast.get("observed_ready")
                if predicted and observed:
                    difference = abs((instant(observed) - instant(predicted)).total_seconds()) / 60
                    sequence(summary["forecast_abs_error_minutes"]).append(difference)
                    summary["completed_forecasts"] = number(summary["completed_forecasts"]) + 1
    for summary in summaries.values():
        errors = sequence(summary["forecast_abs_error_minutes"])
        summary["mean_forecast_abs_error_minutes"] = (
            sum(number(v) for v in errors) / len(errors) if errors else None
        )
    return dict(summaries)


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# SmartHeating — raport tygodniowy",
        "",
        f"Okres: {report['from']} – {report['to']}",
        "",
        f"Można proponować strojenie: {'tak' if report['tuning_eligible'] else 'nie'}.",
        "",
        "| Pokój | Pokrycie | Komfort po dojściu | Niedogrzanie h | Przegrzanie h | Safety h |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for room, raw in mapping(report["rooms"]).items():
        coverage = number(mapping(raw)["coverage"])
        values = mapping(raw)
        totals = mapping(values["totals"])
        fraction = values["steady_comfort_fraction"]
        comfort = f"{number(fraction):.1%}" if fraction is not None else "brak danych"
        lines.append(
            f"| {NAMES.get(room, room)} | {coverage:.1%} | {comfort} | "
            f"{number(totals['under_h']):.2f} | {number(totals['over_h']):.2f} | "
            f"{number(totals['safety_h']):.2f} |"
        )
    lines += [
        "",
        "Energia i pogoda:",
        "",
        "```json",
        json.dumps(report["energy"], ensure_ascii=False, indent=2),
        "```",
        "",
        "Rekomendacja:",
        "",
        "```json",
        json.dumps(report["recommendation"], ensure_ascii=False, indent=2),
        "```",
        "",
        "Braki i ograniczenia:",
        "",
    ]
    lines += [f"- {issue}" for issue in sequence(report["issues"])] or ["- Brak wykrytych braków."]
    lines += [
        "",
        "Pełne metryki komfortu według pokojów i trybów są w sąsiednim pliku JSON.",
        "Współczynnik gazu: 11,594 kWh/m³; okres faktury niepodany. "
        "Porównania historyczne są szacunkiem.",
        "Raport nie zmienia żadnych nastaw urządzeń.",
    ]
    lines += [
        "",
        "Przygotowanie powrotu (pierwszy zaobserwowany pomiar w paśmie celu):",
        "",
        "```json",
        json.dumps(report["arrivals"], ensure_ascii=False, indent=2),
        "```",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Offline export of HA statistics")
    parser.add_argument("--output", type=Path, default=Path("reports"))
    parser.add_argument("--prefix", default="sh")
    parser.add_argument("--end", help="Timezone-aware ISO timestamp")
    parser.add_argument(
        "--state", type=Path, help="Optional small runtime JSON for arrival evidence"
    )
    args = parser.parse_args()
    end = instant(args.end) if args.end else datetime.now(timezone.utc)
    end = end.replace(minute=0, second=0, microsecond=0)
    if args.input:
        raw: object = json.loads(Path(args.input).read_text(encoding="utf-8"))
    else:
        ids = (
            [
                f"sensor.{args.prefix}_{room}_{mode}_{metric}"
                for room in NAMES
                for mode in METRIC_MODES
                for metric in COUNTERS
            ]
            + [ENERGY_CH, ENERGY_DHW, OUTSIDE]
            + [f"sensor.{args.prefix}_energy_{mode}_kwh" for mode in ENERGY_MODES]
        )
        raw = reader_from_environment().statistics(end - timedelta(days=14, hours=1), end, ids)
    state = mapping(json.loads(Path(args.state).read_text(encoding="utf-8"))) if args.state else {}
    evaluation = mapping(state.get("evaluation", {})).get("started")
    if evaluation is None and not args.input:
        try:
            epoch_state = mapping(
                reader_from_environment().state(f"sensor.{args.prefix}_evaluation_started")
            )
            evaluation = epoch_state.get("state")
        except (OSError, ValueError, KeyError, RuntimeError):
            pass
    try:
        epoch = instant(evaluation) if evaluation is not None else None
    except ValueError:
        epoch = None
    report = build_report(
        raw,
        end,
        string(args.prefix),
        arrivals=sequence(state.get("arrivals", [])),
        evaluation_started=epoch,
    )
    if epoch is None:
        sequence(report["issues"]).append("evaluation_epoch_unavailable")
        report.update(tuning_eligible=False, recommendation="continue_observation")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    basename = output / f"weekly-{end:%Y%m%dT%H%MZ}"
    basename.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    basename.with_suffix(".md").write_text(markdown(report), encoding="utf-8")
    print(basename.with_suffix(".md"))


if __name__ == "__main__":
    main()
