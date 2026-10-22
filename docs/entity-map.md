# Mapa encji SmartHeating 2.0

Punkt odniesienia: odczyt MCP z 20 października 2026. Pełny prywatny eksport znajduje się w `runtime/migration/ha-before.json`.

| Pokój | Czujnik | Harmonogram | Fizyczne głowice | Waga |
| --- | --- | --- | --- | ---: |
| Salon | `sensor.salon_temperatura` | `switch.schedule_livingroomheating` | RTL — brak pomiaru położenia | 3 |
| Korytarz | `sensor.korytarz_temperatura` | `switch.schedule_corridorheating` | RTL — brak pomiaru położenia | 3 |
| Łazienka | `sensor.lazienka_temperatura` | `switch.schedule_bathroomheating` | RTL — brak pomiaru położenia | 3 |
| Wiatrołap | `sensor.wiatrolap_temperatura` | `switch.schedule_entranceheating` | RTL — brak pomiaru położenia | 1 |
| Korytarz górny | `sensor.korytarz_gorny_temperatura` | `switch.schedule_uppercorridorheating` | RTL — brak pomiaru położenia | 2 |
| Garderoba | `sensor.garderoba_temperatura` | `switch.schedule_wardrobeheating` | RTL — brak pomiaru położenia | 1 |
| Łazienka górna | `sensor.lazienka_gorna_temperatura` | `switch.schedule_upperbathroomheating` | RTL — brak pomiaru położenia | 3 |
| Biuro | `sensor.biuro_temperatura` | `switch.schedule_officeheating` | `climate.office_trv` | 2 |
| Pokój dzieci | `sensor.pokoj_dzieci_temperatura` | `switch.schedule_kidsroomheating` | `climate.kidsroom_trv` | 8 |
| Sypialnia | `sensor.sypialnia_temperatura` | `switch.schedule_bedroomheating` | `climate.bedroom_left_trv` / `climate.bedroom_right_trv` | 8 |
| Garaż | `sensor.garaz_temperatura` | `switch.schedule_garageheating` | `climate.garage_trv` | 1 |

Wyjście CW400: `number.thermostat_hc1_manual_temperature_2`.

W obserwacji klimaty mają identyfikatory `climate.sh2_*`; po przejęciu zachowują `climate.sh_*`. Safety: sypialnia i pokój dziecka. Obecne flagi safety oraz dogrzania były wyłączone; jednorazowy eksport zachowuje również ręczne cele i wyłączone pokoje.

Dla wszystkich pętli RTL pozycja około 3 pozostaje założeniem użytkownika. Długości pętli, rzeczywiste nastawy i ograniczenia posadzki wymagają spisu na instalacji.
