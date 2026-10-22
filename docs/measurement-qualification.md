# Kwalifikacja danych i obliczenia obserwacyjne od rc.2

Zmiany wynikają z audytu 22.10.2026. Sam czas ostatniej zmiany helpera temperatury
nie jest potwierdzeniem czasu otrzymania raportu z czujnika. Stały licznik energii
nie oznacza zerwania łączności. Konfiguracja źródeł jest jawna w
[`cfg/app_cfg.yaml`](../cfg/app_cfg.yaml).

## Źródła i czas

Każde źródło określa surową encję HA, dokładny temat MQTT, ścieżkę pola liczbowego,
maksymalny wiek i opcjonalny klucz czasu publikującego. Globalny TTL pozostaje
domyślnym kontraktem dla instalacji bez jawnych źródeł. Bieżąca instalacja ma jawne
źródła dla wszystkich 11 pokojów i licznika CO.

- Czujniki Zigbee: pole `temperature`, czas `last_seen` w epoch; granica 3900 s
  odpowiada godzinnemu raportowaniu i 5 min marginesu. Dla dolnej łazienki
  maksymalny interwał 3600 s potwierdzono w `configuredReportings` urządzenia.
  Dla TS0201 jest to początkowa polityka oparta na zaobserwowanych godzinnych
  raportach, wymagająca dalszej obserwacji.
- Korytarz: `ems/thermostat_data`, pole `hc1.currtemp`, granica 300 s.
- Energia CO: `ems/boiler_data`, pole `nrgheat`, granica 300 s między raportami,
  niezależnie od przyrostu licznika. Dodatni przyrost nie jest warunkiem dostępności.

Pakiet musi zawierać poprawną wartość właściwego pola. Pakiet bez temperatury
nie odświeża temperatury. NaN, wartości poza zakresem, przyszły czas albo
niedostępna/nieprawidłowa surowa encja HA nie uzyskują pokrycia pomiarami.
Starszy raport nie zastępuje nowszego. Czas odczytu nie zastępuje czasu publikującego.

AppDaemon nie zawsze przekazuje flagę retain. Dla raportów bez czasu publikującego
pierwszy pakiet bez tej informacji jest kwarantannowany; wymagany jest kolejny
raport po co najmniej 5 s. Jawnie zatrzymany pakiet bez czasu nie kwalifikuje źródła.
Po utracie połączenia dowody są kasowane i wymagają ponownego potwierdzenia.

Raporty Zigbee zawierają opublikowany stan urządzenia, który może obejmować wartości
z bufora Zigbee2MQTT. `last_seen` potwierdza czas kontaktu/publikowanego stanu,
nie stanowi osobnego znacznika sprzętowego pomiaru temperatury. Diagnostyka
`published_snapshot` celowo oznacza raport stanu. Jeżeli urządzenie przestanie
odświeżać temperaturę, lecz nadal raportuje inne pola wraz z buforowaną temperaturą,
sam odbiorca MQTT tego nie rozstrzygnie. Wymaga to diagnostyki interwałów i źródła;
nie należy przedstawiać pokrycia raportami jako dowodu kalibracji czujnika.

## Restart

Mały plik stanu zachowuje ostatnie raporty z czasem publikującego i tożsamością
źródła. Po restarcie ich czas pozostaje niezmieniony; bieżący limit wieku nadal
obowiązuje. Zmiana encji/tematu/pola nie pozwala użyć raportu starego źródła.
Nietimestampowane raporty EMS nie są odtwarzane jako świeże. Sam timestamp nowo
odtworzonej encji HA nie wystarcza do kwalifikacji jawnego źródła.

Przy przejściu z rc.1 raporty Zigbee pobrano przez diagnostykę MQTT HA, zachowując
oryginalne `last_seen`. Nie uzupełniono historycznych luk ani nie zmieniono liczników.
Ta operacja jest odtworzeniem bieżącego stanu, nie rekonstrukcją historii komfortu.

## Głosowanie i safety w obserwacji

Podstawowe zapotrzebowanie grzejników w shadow wynika z błędów pokojów, niezależnie
od trybów ustawionych przez v1. Różnice urządzeń pozostają w `*_trv_status`.
W aktywnym sterowaniu pozostaje dotychczasowy wymóg zgodności głowic.
`shadow_matches_observed` oznacza zgodność propozycji z odczytem, nie wykonanie
polecenia przez v2. V2 nie wysyła poleceń fizycznych w trybie obserwacyjnym.

Przełącznik safety nadal zachowuje własny zapisany stan. Dodatkowy komponent
obserwacyjny liczy oba pokoje tak, jakby poprawne komendy zostały wykonane:

- `*_safety_candidate`: `blocked_inputs`, `inactive`, `qualifying`,
  `active_assuming_commands`, `no_effect` lub `not_shadow`;
- `safety_candidate_offset`: maksimum potrzeby obu pokoi, bez sumowania;
- próg, czas kwalifikacji, histereza i diagnostyka odpowiadają zwykłemu safety.

Kandydat nie trafia do sterowania ani istniejących liczników działania safety.
Brak pomiaru lub dostępnej, zgodnej funkcjonalnie głowicy blokuje jego kwalifikację.
Nie jest potwierdzeniem ogrzewania ani sprawności hydrauliki.

## Okres oceny

Przy zmianie wersji/konfiguracji powstaje zapis `evaluation` ze stałym początkiem.
Restart tej samej wersji nie zmienia początku. Dawne liczniki pozostają monotoniczne.
CLI raportu wymaga aktualnego okresu z pliku stanu lub encji HA i blokuje strojenie,
gdy brakuje 14 dni w tym okresie. Wczesne, niepełne dane rc.1 pozostają w historii,
lecz nie kwalifikują rc.2 do strojenia.

## Podmiana pakietu

Samo usunięcie `apps.yaml` nie dało w tej instalacji potwierdzenia zakończenia appki.
Użyto usługi administracyjnej AppDaemon `admin/app/stop`, z dokładnym celem
`HeaterControllerShadow`, i potwierdzono `app.HeaterControllerShadow=terminated`.
Pakiet wymieniono z kopią poza katalogiem `apps`. V1 i cały AppDaemon nie były
restartowane. Nie należy opierać zatrzymania wyłącznie na zapamiętanym stanie MQTT.

Po podmianie wykonano kontrolowany stop/start samej v2. Pozwolił odtworzyć właściwe
raporty po końcowym zapisie starej instancji i sprawdzić ciągłość liczników.
Kopia stanu/kodu oraz dokładne skróty znajdują się w prywatnym pakiecie wdrożenia.
