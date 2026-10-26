"""Build native HA views; this module never writes to Home Assistant."""

import json
from pathlib import Path

from .config import NAMES


def section(cards: list[dict[str, object]]) -> dict[str, object]:
    return {"type": "grid", "cards": cards}


def heading(name: str, icon: str) -> dict[str, object]:
    return {"type": "heading", "heading": name, "icon": icon}


def markdown(content: str) -> dict[str, object]:
    return {"type": "markdown", "content": content}


def entities(title: str, rows: list[object]) -> dict[str, object]:
    return {"type": "entities", "title": title, "show_header_toggle": False, "entities": rows}


def button(
    name: str,
    icon: str,
    action: str,
    entity: str,
    data: dict[str, object] | None = None,
    confirmation: str | None = None,
) -> dict[str, object]:
    tap: dict[str, object] = {
        "action": "perform-action",
        "perform_action": action,
        "target": {"entity_id": entity},
    }
    if data:
        tap["data"] = data
    if confirmation:
        tap["confirmation"] = {"text": confirmation}
    return {"type": "button", "name": name, "icon": icon, "tap_action": tap}


def navigation() -> dict[str, object]:
    return {
        "type": "grid",
        "columns": 3,
        "square": False,
        "cards": [
            {
                "type": "button",
                "name": title,
                "icon": icon,
                "tap_action": {"action": "navigate", "navigation_path": f"/lovelace/{path}"},
            }
            for title, icon, path in (
                ("Dom", "mdi:home-thermometer", "smartheating"),
                ("Plan i powrót", "mdi:calendar-clock", "smartheating-control"),
                ("Diagnostyka", "mdi:stethoscope", "smartheating-debug"),
            )
        ],
    }


def room_cards(key: str) -> list[dict[str, object]]:
    entity = f"climate.sh_{key}"
    return [
        {
            "type": "tile",
            "entity": entity,
            "name": NAMES[key],
            "features": [
                {"type": "target-temperature"},
                {"type": "climate-hvac-modes", "style": "dropdown"},
            ],
        },
        markdown(
            "{% set e = '" + entity + "' %}\n"
            "{{ state_attr(e, 'target_source_label') or 'Oczekiwanie na dane' }}"
            "{% if not state_attr(e, 'measurement_available') %} · Brak pomiaru{% endif %}"
            "{% if state_attr(e, 'needs_heat') %} · Potrzebuje ciepła{% endif %}"
        ),
        {
            "type": "conditional",
            "conditions": [{"entity": f"sensor.sh_{key}_target_source", "state": "manual"}],
            "card": {
                "type": "vertical-stack",
                "cards": [
                    entities(
                        "Ręczne ustawienie",
                        [{"entity": f"sensor.sh_{key}_override_until", "name": "Obowiązuje do"}],
                    ),
                    button(
                        "Wróć do harmonogramu",
                        "mdi:calendar-refresh",
                        "button.press",
                        f"button.sh_{key}_resume",
                    ),
                ],
            },
        },
    ]


def build() -> list[dict[str, object]]:
    summary = """## {{ states('sensor.sh_actual_mode_label') }}
**Sterowanie:** {{ states('sensor.sh_system_status') }}
{% set s = 'sensor.sh_system_summary' %}
Pomiary: {{ state_attr(s, 'measurements_valid') }}/{{ state_attr(s, 'measurements_total') }}
Głowice: {{ state_attr(s, 'trvs_confirmed') }}/{{ state_attr(s, 'trvs_total') }}
{% set problems = state_attr(s, 'problems') %}
{% if problems %}{% for problem in problems %}
- {{ problem }}
{% endfor %}{% endif %}
{% set manual = state_attr(s, 'manual_overrides') %}
{% if manual %}**Ręczne ustawienia: {{ manual }}.**
Ich termin i powrót do planu znajdziesz przy pokojach.{% endif %}
"""
    boiler = """### Zapotrzebowanie i praca kotła
{% set rooms = state_attr('sensor.sh_system_summary', 'requesting_rooms') %}
**Poniżej celu:** {{ rooms | join(', ') if rooms else 'brak wskazanych pokojów' }}
**Decyzja sterownika:** {{ states('sensor.sh_control_reason') }}
{% set flame = states('sensor.boiler_flame_current_2') %}
**Palnik:** {% if is_number(flame) %}
{{ 'wykryty płomień' if flame | float > 0 else 'brak płomienia' }}
{% else %}brak danych{% endif %}
{% set co = states('binary_sensor.boiler_heating_active_2') %}
{% set cwu = states('binary_sensor.boiler_tapwater_active_2') %}
**CO:** {{ {'on': 'aktywne', 'off': 'nieaktywne'}.get(co, 'brak danych') }}
**CWU:** {{ {'on': 'aktywne', 'off': 'nieaktywne'}.get(cwu, 'brak danych') }}
Odczyt nastawy potwierdza ustawienie regulatora. Temperaturę pomieszczenia oceniaj osobno.
"""
    profiles = {
        "type": "grid",
        "columns": 3,
        "square": False,
        "cards": [
            button(
                title,
                icon,
                "select.select_option",
                "select.sh_profile",
                {"option": value},
                (
                    "Zmiana profilu zakończy ręczne nadpisania pokojów. Przejście do Dom "
                    "anuluje termin powrotu."
                ),
            )
            for title, icon, value in (
                ("Dom", "mdi:home", "home"),
                ("Na krótko", "mdi:walk", "away_short"),
                ("Wyjazd", "mdi:bag-suitcase", "away_long"),
            )
        ],
    }
    home_sections = [section([navigation(), markdown(summary), profiles, markdown(boiler)])]
    for label, icon, keys in (
        (
            "Parter",
            "mdi:home-floor-0",
            ("livingroom", "corridor", "bathroom", "entrance", "garage"),
        ),
        (
            "Piętro",
            "mdi:home-floor-1",
            ("bedroom", "kidsroom", "office", "upper_corridor", "upper_bathroom", "wardrobe"),
        ),
    ):
        cards = [heading(label, icon)]
        for key in keys:
            cards.extend(room_cards(key))
        home_sections.append(section(cards))
    home: dict[str, object] = {
        "title": "Dom",
        "path": "smartheating",
        "icon": "mdi:home-thermometer",
        "type": "sections",
        "max_columns": 3,
        "sections": home_sections,
    }
    arrivals = """### Plan przygotowania
{% set arrival = state_attr('sensor.sh_system_summary', 'arrival') %}
{% if arrival %}
Powrót: **{{ as_local(as_datetime(arrival)).strftime('%d.%m.%Y o %H:%M') }}**.
{% if is_state('select.sh_profile', 'home') %}
Wybierz profil nieobecności, aby uruchomić przygotowanie powrotu.
{% endif %}
{% else %}Nie ma zaplanowanego powrotu. Nieobecność trwa do ręcznego zakończenia.{% endif %}

| Pokój | Start przygotowania | Szacowana gotowość |
| :-- | :-- | :-- |
"""
    for key, name in NAMES.items():
        if key == "garage":
            continue
        e = f"climate.sh_{key}"
        arrivals += (
            "{% set start = state_attr('" + e + "', 'preheat_start') %}"
            "{% set ready = state_attr('" + e + "', 'ready_at') %}\n"
            f"| {name} | "
            "{{ as_local(as_datetime(start)).strftime('%d.%m %H:%M') if start else '—' }} | "
            "{{ as_local(as_datetime(ready)).strftime('%H:%M') if ready and arrival else '—' }} |\n"
        )
    arrivals += "\nTo oszacowanie. Brak pomiaru lub ograniczenia instalacji mogą opóźnić dogrzanie."
    room_config = [
        {"key": key, "name": name, "schedule": f"switch.schedule_{key.replace('_', '')}heating"}
        for key, name in NAMES.items()
    ]
    plan: dict[str, object] = {
        "title": "Plan i powrót",
        "path": "smartheating-control",
        "icon": "mdi:calendar-clock",
        "type": "sections",
        "max_columns": 2,
        "sections": [
            section(
                [
                    navigation(),
                    heading("Nieobecność i powrót", "mdi:bag-suitcase"),
                    profiles,
                    markdown(
                        "Krótka nieobecność: podłogówka −0,5°C, grzejniki −1°C. Wyjazd:"
                        " do 18°C i 17°C. Garaż zachowuje plan.\n\nWybierz termin powrotu"
                        " poniżej. Aplikacja sama rozpocznie przygotowanie wcześniej i "
                        "przejdzie do Dom o tej godzinie."
                    ),
                    entities(
                        "Termin powrotu",
                        [{"entity": "datetime.sh_arrival_at", "name": "Data i godzina przyjazdu"}],
                    ),
                    button(
                        "Anuluj termin",
                        "mdi:calendar-remove",
                        "button.press",
                        "button.sh_cancel_arrival",
                    ),
                    button(
                        "Jestem w domu",
                        "mdi:home",
                        "button.press",
                        "button.sh_return_now",
                        confirmation="Przywrócić Dom i zakończyć ręczne nadpisania?",
                    ),
                    entities(
                        "Ostatnie polecenie",
                        [{"entity": "sensor.sh_command_feedback", "name": "Wynik"}],
                    ),
                    markdown(arrivals),
                ]
            ),
            section(
                [
                    {"type": "custom:smartheating-schedule", "rooms": room_config},
                    markdown(
                        "Ręczna temperatura pokoju obowiązuje do kolejnego przedziału, "
                        "także gdy kolejny cel ma tę samą wartość. Wyłączenie "
                        "harmonogramu wyklucza pokój z automatycznego sterowania."
                    ),
                    entities("Włączone harmonogramy", [r["schedule"] for r in room_config]),
                ]
            ),
        ],
    }
    diagnostics: dict[str, object] = {
        "title": "Diagnostyka",
        "path": "smartheating-debug",
        "icon": "mdi:stethoscope",
        "type": "sections",
        "max_columns": 3,
        "sections": [
            section(
                [
                    navigation(),
                    markdown(summary),
                    entities(
                        "Aplikacja i wykonanie",
                        [
                            "sensor.sh_health",
                            "binary_sensor.sh_runtime",
                            "sensor.sh_version",
                            "sensor.sh_config_id",
                            "sensor.sh_command_status",
                            "sensor.sh_energy_issue",
                        ],
                    ),
                ]
            ),
            section(
                [
                    heading("Decyzja regulatora", "mdi:tune"),
                    entities(
                        "Obliczenia",
                        [
                            "sensor.sh_total_wam",
                            "sensor.sh_output_offset",
                            "sensor.sh_forced_burn_offset",
                            "sensor.sh_output_setpoint",
                            "sensor.sh_confirmed_setpoint",
                            "sensor.sh_control_reason",
                        ],
                    ),
                    entities(
                        "Funkcje dodatkowe",
                        [
                            {
                                "entity": "switch.sh_force_flow_safety_rooms",
                                "name": "Ochrona komfortu sypialni i dziecka",
                            },
                            {"entity": "switch.sh_warm_flag", "name": "Dodatkowe dogrzanie +0,5°C"},
                        ],
                    ),
                    markdown(
                        "Ochrona komfortu może podnieść korektę do +4°C po utrzymującym"
                        " się niedogrzaniu. Działa tylko z poprawnym pomiarem i "
                        "potwierdzonymi głowicami."
                    ),
                ]
            ),
            section(
                [
                    heading("Głowice i kocioł", "mdi:radiator"),
                    markdown(boiler),
                    entities(
                        "Potwierdzenia głowic",
                        [
                            f"sensor.sh_{key}_trv_status"
                            for key in ("office", "kidsroom", "bedroom", "garage")
                        ],
                    ),
                    entities(
                        "Odczyty kotła",
                        [
                            "sensor.boiler_current_flow_temperature_2",
                            "sensor.boiler_flame_current_2",
                            "sensor.boiler_energy_heating",
                            "sensor.boiler_dhw_energy",
                        ],
                    ),
                ]
            ),
            section(
                [
                    heading("Jakość danych", "mdi:database-check"),
                    entities(
                        "Źródła pomiarów", [f"sensor.sh_{key}_measurement_status" for key in NAMES]
                    ),
                ]
            ),
        ],
    }
    history: list[dict[str, object]] = [heading("Historia temperatur i energii", "mdi:chart-line")]
    for key in ("bedroom", "kidsroom", "upper_bathroom"):
        history.append(
            {
                "type": "history-graph",
                "title": NAMES[key],
                "hours_to_show": 24,
                "entities": [
                    {"entity": f"sensor.sh_{key}_temperature", "name": "Pomiar"},
                    {"entity": f"sensor.sh_{key}_target", "name": "Cel"},
                ],
            }
        )
    history.append(
        {
            "type": "statistics-graph",
            "title": "Energia CO i CWU — szacunek EMS",
            "chart_type": "bar",
            "period": "day",
            "days_to_show": 7,
            "stat_types": ["change"],
            "entities": [
                {"entity": "sensor.boiler_energy_heating", "name": "CO"},
                {"entity": "sensor.boiler_dhw_energy", "name": "CWU"},
            ],
        }
    )
    sections = diagnostics["sections"]
    assert isinstance(sections, list)
    sections.append(section(history))
    return [home, plan, diagnostics]


def main() -> None:
    import yaml

    views = build()
    Path("cfg/dashboard.pilot.yaml").write_text(
        yaml.safe_dump(
            {"title": "Ogrzewanie", "views": views}, sort_keys=False, allow_unicode=True
        ),
        encoding="utf-8",
    )
    Path("runtime/ux-20261026/views.json").write_text(
        json.dumps(views, ensure_ascii=True), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
