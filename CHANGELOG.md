# Changelog

## 2.0.0-rc.3 — 2026-10-26

- UX HA: Dom, Plan i powrót, Diagnostyka; zachowane identyfikatory klimatów i ścieżki widoków.
- Źródło celu, koniec ręcznego nadpisania i osobny powrót pokoju do harmonogramu.
- Natywna encja MQTT datetime z lokalnym wyborem przyjazdu i anulowaniem terminu;
  dotychczasowe pole tekstowe pozostaje zgodne. Data z przeszłości jest odrzucana.
- Czytelne stany sterowania i komunikaty o odrzuconych poleceniach; zapotrzebowanie,
  potwierdzenie nastawy i praca palnika pozostają oddzielnymi informacjami.
- Edytor codziennego planu z walidacją mostu MQTT, pełnej doby i konfliktów,
  jawnym zapisem oraz potwierdzeniem odczytem HA; testy JS dodane do CI.
- Nie zmieniono wzorów WAM, warunków dogrzewania, safety, wag ani nastaw urządzeń.
  Zachowany schemat stanu 2; wersja rc.3 rozpoczyna nową epokę oceny zgodnie
  z dotychczasową zasadą, bez zerowania liczników ani zmiany bieżącego trybu.

## 2.0.0-rc.2 — 2026-10-22

- Źródła temperatur są kwalifikowane osobno: surowa encja, temat i pole raportu MQTT,
  znacznik publikującego oraz maksymalny wiek. Stała temperatura nie wymaga zmiany
  helpera HA. Pakiet bez temperatury nie odświeża pomiaru; stare retained, przyszłe
  znaczniki czasu, NaN i niedostępne źródła nie uzyskują pozornego pokrycia.
- EMS jest kwalifikowany przez obecność pola w żywym raporcie, niezależnie od
  przyrostu energii. Bez metadanych retain pierwszy pakiet EMS jest kwarantannowany;
  wymagany jest kolejny raport. Przywrócenie tej samej wartości kasuje niedostępność.
- Shadow oblicza zapotrzebowanie grzejników niezależnie od ustawień v1. Rzeczywiste
  potwierdzenia oraz blokady aktywnego sterowania pozostają oddzielne.
- Dodatkowa obserwacja safety sypialni i pokoju dziecka działa niezależnie od
  przełącznika głównej funkcji. Wynik jawnie zakłada wykonanie komend, nie steruje
  urządzeniami i nie jest doliczany do czasu rzeczywistego safety.
- Nowy okres oceny jest zapisywany przy zmianie wersji/konfiguracji. Dotychczasowe
  liczniki pozostają monotoniczne; raport nie dopuszcza strojenia przed 14 dniami
  w bieżącym okresie. Nie zmieniono schematu stanu ani identyfikatorów encji.

## 2.0.0-rc.1 — 2026-10-20

### Struktura i zgodność

- Typowane komponenty zastępują zależne mixiny; AppDaemon pozostaje cienkim adapterem `HealthAppBase`.
- Zachowane wagi oraz podstawowe wzory WAM, dotychczasowych korekt i zapotrzebowania grzejników; 500 deterministycznych porównań z zamrożoną wersją1.x.
- SemVer, osobne schematy konfiguracji/stanu/raportu, manifest wdrożenia i identyfikator konfiguracji.
- Ruff, strict mypy, pytest i CI dla Python 3.10/3.13.

### Jawne zmiany działania

- Błędne i stare pomiary są wyłączane z głosowania; wagi są ponownie normalizowane. Brak korytarza blokuje nowe polecenie CW400.
- TS0601 korzysta z `auto/manual`; obie głowice sypialni są uzgadniane oddzielnie. Polecenia mają ograniczone próby, potwierdzenia i diagnostykę.
- Statyczne nastawy urządzeń mają inną kwalifikację niż świeżość pomiarów temperatury. Jawne `off` zastępuje stare żądanie, także podczas cooldownu.
- Safety obejmuje sypialnię i pokój dziecka, z progiem 0,5°C przez 15 minut, zwolnieniem poniżej 0,2°C, wspólnym maksimum i diagnostyką po 60 minutach. Zastępuje bezwarunkowe przypisanie `+4` arbitrażem i ograniczaniem szybkości zmian.
- Home, Away krótkie, Away wyjazdowe i przygotowanie do terminu przyjazdu; garaż domyślnie bez obniżenia. Ręczna nastawa wygasa na następnej granicy harmonogramu, również z identyczną temperaturą.

### Dane i bezpieczna obserwacja

- Historia i statystyki przez MQTT/Recorder HA; mały atomowy JSON przechowuje stan restartu i liczniki.
- Osobne liczniki niedogrzania, przegrzania, stopniogodzin, komfortu, dochodzenia do celu, potwierdzeń i luk pomiarowych.
- CO według trybów, z jawnym `mixed/unobserved`, oraz małe zapisy przygotowania powrotu i trafności prognoz.
- Raport godzinowych statystyk działa po usunięciu surowej historii. Brak 14 dni/95% danych lub niespójność bilansu blokuje strojenie.
- Przelicznik faktury11,594 kWh/m³; okresy niepotwierdzone oznaczane jako oszacowanie.
- Obserwacja domyślnie blokuje wszystkie polecenia fizyczne i używa osobnych encji/modułu. Sesje komend MQTT uniemożliwiają odtworzenie starych ręcznych nastaw.

### Wymagane dalsze odbiory

- Minimum 72 godziny reprezentatywnej obserwacji, następnie kontrolowany pilotaż 7–14 dni.
- Potwierdzenie komfortu, dynamiki powrotu i zużycia w rzeczywistej instalacji.
- Krzywa CW400, wpływ pomieszczenia, hydraulika i kalibracja EMS pozostają osobnymi eksperymentami.
