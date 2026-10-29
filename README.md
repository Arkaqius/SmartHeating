# SmartHeating 2.0

Sterownik AppDaemon dla wspólnego obiegu podłogówki z RTL i grzejników. Wydanie `2.0.0-rc.4` zachowuje obliczenia ważonego głosowania i udostępnia jawny arbitraż safety, Away, przygotowanie powrotu oraz dane do późniejszego strojenia. Obsługuje również stan Scheduler `triggered` bez chwilowej utraty aktywnego planu.

W instalacji domowej aktywnie steruje `HeaterControllerV2` w wersji `2.0.0-rc.4`, z modułu `SmartHeating2.smartheating.appdaemon_app`. Zachowuje encje `sh_*` i tematy `smart_heating`. Dowody wdrożenia i pomiarów opisuje [rejestr](docs/implementation-status.md).

Repozytoryjny `cfg/app_cfg.yaml` pozostaje bezpiecznym szablonem **obserwacji dla nowej instalacji**: encje `sh2`, tematy `smart_heating_v2`, zero poleceń do fizycznych urządzeń. Nie jest kopią aktywnej konfiguracji domowej. Nowa instalacja przechodzi do sterowania po minimum 72 godzinach obserwacji i ocenie wyników zgodnie z [runbookiem](docs/runbook.md).

## Rozwój i kontrola jakości

Python 3.10 lub nowszy. CI sprawdza 3.10 i 3.13; obraz zainstalowanego dodatku AppDaemon 0.19.2 jest budowany z Pythonem 3.13. Wspólny `appdaemon_common` jest dostarczany przez instalację AppDaemon, a jego kontrakt opisują lokalne stuby typów.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev,report]"
.venv\Scripts\ruff check .
.venv\Scripts\ruff format --check .
.venv\Scripts\mypy --strict
.venv\Scripts\pytest -q
```

Na Linuxie odpowiedniki narzędzi znajdują się w `.venv/bin/`. Zewnętrzne AppDaemon API jest zastępowane atrapą w testach; rdzeń nie importuje AppDaemon.

## Komponenty

| Plik w `src/smartheating/` | Odpowiedzialność |
| --- | --- |
| `model.py`, `validation.py`, `config.py` | Typy, protokoły i walidacja granic |
| `schedules.py`, `targets.py` | Harmonogramy, nadpisania, Away i plan powrotu |
| `control.py` | Zachowany WAM, zapotrzebowanie grzejników, safety i arbitraż |
| `devices.py` | Tryby TS0601, granice urządzeń, potwierdzenia i ograniczone próby |
| `measurements.py` | Jawne źródła i wiek raportów temperatury/EMS, niezależnie od zmian wartości encji |
| `metrics.py`, `energy.py`, `forecast.py` | Komfort, pokrycie, CO według trybów i ocena prognoz |
| `persistence.py` | Mały atomowy JSON i poprzednia kopia |
| `mqtt.py`, `appdaemon_app.py`, `runtime.py` | MQTT, cykl życia i orkiestracja |
| `ha_api.py`, `reporting.py` | Odczyt API/statystyk HA i raport tygodniowy |
| `migration.py`, `bundle.py` | Lokalny eksport, propozycje migracji i ZIP obserwacyjny |

Pakiet uruchamia `SmartHeating2.smartheating.appdaemon_app`. `src/smart_heating_v2.py` i `src/SmartHeating.py` są punktami wejścia zgodności dla tego samego kodu v2 na standardowym PYTHONPATH; nie są starym sterownikiem. `legacy/` zawiera zamrożony historyczny punkt odniesienia `08347d9`, w tym konfigurację używaną przez testy; nie kopiuj tego katalogu do działającego AppDaemon razem z nową aplikacją. Zamrożona logika w `tests/legacy/` służy porównaniu obliczeń.

## Nowa instalacja: przygotowanie obserwacji

```powershell
.venv\Scripts\python -m smartheating.bundle
```

Powstaje ZIP w `dist/`, z manifestem SHA256, commitem i identyfikatorem konfiguracji. Rozpakuj go do katalogu aplikacji `SmartHeating2`. Zawiera jawny zewnętrzny `__init__.py`, pakiet i `apps.yaml`; pełna nazwa modułu pozwala AppDaemon poprawnie przeładowywać zależności. Konfiguracja wskazuje plik stanu `/config/smartheating/state/shadow.json` wewnątrz dodatku; sprawdź mapowanie tej ścieżki w konkretnej instalacji.

Jednorazowy eksport bieżących celów i harmonogramów:

```powershell
# HA_URL i HA_TOKEN pobierane są ze środowiska; nie zapisuj tokenu w repozytorium.
.venv\Scripts\python -m smartheating.migration --config cfg/app_cfg.yaml
```

Można przekazać `--snapshot runtime/migration/ha-before.json`, aby przygotować zmiany z istniejącego eksportu. Narzędzie zapisuje propozycje i kopie lokalnie. Migracja zachowuje wyłączone pokoje, przełączniki i ręczne cele do następnego przedziału harmonogramu. Pełna kolejność wdrożenia, odtworzenia i pilotażu znajduje się w [runbooku](docs/runbook.md).

W obserwacji harmonogramy są odczytywane bez zmiany ich działania. Przy przejęciu ich akcje otrzymują osobny temat `smart_heating/<pokój>/schedule/set`. Ręczne komendy korzystają z nowej sesji MQTT przy każdym uruchomieniu i odzyskaniu połączenia; HA otrzymuje aktualny temat przez discovery. Chroni to przed odtwarzaniem starych komend także przy pluginie AppDaemon, który nie przekazuje flagi MQTT retain. Stałe tematy stanu i identyfikatory aktywnych klimatów pozostają zachowane.

Wbudowany adapter harmonogramów obsługuje używane w domu pełne harmonogramy dobowe `daily`. Inny kalendarz jest jawnie niedostępny. Jesienna powtarzana granica wykonuje się raz, przy pierwszym wystąpieniu; wiosenna pominięta granica przechodzi na koniec luki bez przestawiania kolejności przedziałów. W nowej instalacji przed pilotażem porównaj to z zachowaniem działającego Scheduler.

Od rc.2 źródła MQTT są konfigurowane w `v2.measurement_sources`. Raporty Zigbee
zachowują czas `last_seen`; EMS bez czasu publikującego wymaga żywego raportu.
Samo odtworzenie encji przez HA nie odmładza temperatury. Zasady, ograniczenia
raportów zawierających buforowany stan i diagnostykę opisuje
[kwalifikacja pomiarów](docs/measurement-qualification.md).

## Away i dashboard

Działający dashboard ma trzy widoki: [Dom](https://ha.kojbito.org/lovelace/smartheating), [Plan i powrót](https://ha.kojbito.org/lovelace/smartheating-control) oraz [Diagnostyka](https://ha.kojbito.org/lovelace/smartheating-debug). Ścieżka [smartheating-v2](https://ha.kojbito.org/lovelace/smartheating-v2) pozostaje aktywnym aliasem zgodności.

Szablony dla nowej instalacji: [obserwacja](cfg/dashboard.shadow.yaml) i [pilotaż](cfg/dashboard.pilot.yaml). Zawierają profil, termin, „Wracam teraz”, cele i gotowość każdego pokoju oraz diagnostykę obu safety rooms. Termin przyjmuje ISO8601 z przesunięciem UTC; pusta wartość go usuwa. Czasy gotowości są oszacowaniem.

Normalny tryb TS0601 to `auto` z presetem `manual`. `heat` może wymuszać pełne otwarcie. Wykonanie usługi HA nie jest potwierdzeniem nastawy; aplikacja sprawdza oba atrybuty i temperaturę każdej głowicy. Informacja o żądaniu ciepła nie potwierdza palnika ani przepływu w RTL.

## Historia i raport

Historia jest zapisywana przez HA Recorder. Liczniki godzin i stopniogodzin mają `state_class: total_increasing`; temperatury i korekty — `measurement`. Liczniki są zapisywane na dysku przed publikacją. Przerwa po restarcie trafia do `unobserved`, bez zaliczania komfortu. Po odzyskaniu starszej kopii aplikacja wstrzymuje start do uzgodnienia liczników z Recorderem, aby nie opublikować spadku jako nowego cyklu sumowania.

```powershell
.venv\Scripts\python -m smartheating.reporting --prefix sh
```

Źródłem są godzinowe statystyki HA; `sh` wybiera aktywną instalację, a `sh2` oddzielną obserwację. `--input eksport.json` umożliwia raport offline po usunięciu surowej historii. JSON i Markdown trafiają do `reports/`. Brak 14 dni w aktualnym okresie oceny, pokrycie poniżej 95%, niepotwierdzone nastawy albo niespójny bilans blokują propozycję strojenia. Eksperyment dotyczący tempa nagrzewania dodatkowo wymaga zaobserwowanego zakończenia przygotowania. Przy eksporcie offline przekaż aktualny plik `--state`, zawierający początek okresu oceny; brak tego dowodu blokuje strojenie.

Współczynnik gazu wynosi **11,594 kWh/m³** z faktury użytkownika. Okres faktury nie został podany, więc wcześniejsze okresy są szacunkiem. Kalibracja EMS nie jest zmieniana. AI proponuje najwyżej jeden eksperyment; decyzja o nastawach pozostaje po stronie użytkownika.

## Wersje i odbiór

| Element | Wersja |
| --- | --- |
| Aplikacja | `2.0.0-rc.4` (pakiet Python: `2.0.0rc4`) |
| Konfiguracja | `2` |
| Stan trwały | `2`, testowana migracja z `1` |
| Raport | `1` |

Zmiany opisuje [changelog](CHANGELOG.md). Testy techniczne nie potwierdzają jeszcze komfortu ±0,5°C ani oszczędności gazu. Ocena ogrzewania wymaga pilotażu, danych pogodowych i kosztu ponownego nagrzania. Hydraulika wspólnego obiegu pozostaje ograniczeniem instalacji.

Odbiór aktywnego sterowania i aktualne luki danych są opisane w [rejestrze wdrożenia](docs/implementation-status.md).
