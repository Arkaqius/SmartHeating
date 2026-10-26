# SmartHeating 2.0 — rejestr wdrożenia i odbioru

Rejestr rozróżnia zakres uzgodniony, dowody techniczne i wyniki pracy instalacji. Punktem odniesienia jest repozytorium `08347d9` z 20 października 2026 r. Obecnie działa `2.0.0-rc.2` wyłącznie w obserwacji; instalacją nadal steruje 1.x. Poniższe wcześniejsze odczyty rc.1 zachowano jako historię. Aktualny odbiór rc.2 znajduje się na końcu dokumentu. Procedura przejścia przez kolejne bramki znajduje się w [runbooku](runbook.md).

## Potwierdzone informacje wyjściowe

| Obszar | Ustalenie | Granica wiedzy |
| --- | --- | --- |
| Instalacja | Dom około 110 m², Wieliczka; grzejniki i podłogówka z RTL pracują we wspólnym obiegu | Brak kompletnego spisu pętli, ich długości i nastaw RTL |
| Sterowanie | CW400 i kocioł CerapurAcu-Smart według danych użytkownika | Dokładne oznaczenie kotła należy porównać z tabliczką znamionową |
| Głowice | Sypialnia ma dwie głowice; cele i tryby głowic mogą się różnić | Wymagane sprawdzenie wszystkich potwierdzeń i normalnego trybu regulacji |
| Wersja dodatku | AppDaemon HA App 0.19.2, `a0d7b954_appdaemon` | Python procesu potwierdzony w logu inicjalizacji: 3.13.15 |
| Recorder | Odczyt rozmiaru bazy około 1,4 GiB | Rozmiar nie określa retencji ani kompletności statystyk |
| Retencja | Odczyt działającej konfiguracji: `purge_keep_days: 7`; wybrane encje `sh2` nie są wykluczone | Lokalny stary plik z 3 dniami nie odpowiada wdrożeniu |
| Dostęp do wdrożenia | Odczyt SMB dostępny poza sandboxem; 8 plików aplikacji zgadza się z `legacy/`, 3 pliki `appdaemon_common` z lokalną kopią | Prywatna kopia i skróty: `runtime/migration/deployment-audit.json` |
| Gaz | Gazomierz zasila wyłącznie kocioł; współczynnik z faktury: 11,594 kWh/m³ | Okres obowiązywania faktury nie został podany |
| Wentylacja | Nawiew przez wywietrzniki w oknach | Brak ilościowego pomiaru strat wentylacyjnych |

Informacje o domu, współczynniku faktury i wentylacji pochodzą od użytkownika. Informacje o dodatku i bazie pochodzą z odczytów wykonanych podczas analizy. Nie należy traktować ich jako dowodu bieżącego stanu po późniejszych zmianach konfiguracji.

## Bramki wdrożenia

| Etap | Co ma powstać | Dowód wymagany do zamknięcia |
| --- | --- | --- |
| 0. Stan wyjściowy | Kopie wdrożenia i konfiguracji, mapa encji i harmonogramów, wersja runtime, spis RTL | Porównanie plików, zweryfikowany runtime i Recorder, sprawdzona procedura odtworzenia |
| 1. Charakterystyka | Testy zachowania starego WAM, zapotrzebowania grzejników, safety i komend | Wyniki testów dla punktu odniesienia oraz udokumentowane różnice w 2.0 |
| 2. Struktura | Typowany rdzeń, komponenty i adaptery, wersje schematów, narzędzia jakości | Lint, formatter, strict mypy i testy; zgodność podstawowych obliczeń |
| 3. Wykonanie poleceń | Normalne tryby TS0601, obie głowice sypialni, potwierdzenia, ograniczone ponowienia | Testy restartu, braku odpowiedzi, niezgodnego trybu i nieprawidłowego pomiaru |
| 4. Dane i safety | Liczniki HA, diagnostyka decyzji, sypialnia i pokój dziecka, histereza i arbitraż | Testy wspólnego żądania bez sumowania, ograniczenia eskalacji i odtwarzania metryk |
| 5. Away | Profile, termin, przygotowanie pokojów, ręczne nadpisania, dashboard | Testy przejść, DST, granic harmonogramu, restartu i terminów |
| 6a. Obserwacja | Równoległe obliczenia w `sh2` / `smart_heating_v2` | Co najmniej 72 godziny reprezentatywnych danych i zero fizycznych zapisów |
| 6b. Pilotaż | Kontrolowane przejęcie `sh` / `smart_heating`, jeden aktywny sterownik | 7–14 dni danych, potwierdzone komendy, brak niewyjaśnionego pogorszenia |
| 7. Kalibracja i AI | Cotygodniowe raporty i pojedyncze eksperymenty | Co najmniej 14 dni wiarygodnych danych; pokrycie wymaganymi danymi co najmniej 95% przed rekomendacją strojenia |

Nie zamykamy etapów czasu rzeczywistego na podstawie testów jednostkowych. Obserwacja nie dowodzi oszczędności ani zdolności instalacji do utrzymania każdego celu. Przy braku dowodu wpisujemy „niezweryfikowane”.

## Stan formalnych odbiorów

| Odbiór | Status w chwili utworzenia rejestru | Co należy dopisać po wykonaniu |
| --- | --- | --- |
| Zgodność repo i wdrożenia | Potwierdzona dla kodu/config 1.x i wspólnego base | Odczyt SMB z 20.10.2026; kopie i SHA256 w `runtime/migration/` |
| Wersja Pythona AppDaemon | Potwierdzona: 3.13.15 | Ścieżka procesu w logu inicjalizacji dodatku |
| Retencja i wykluczenia Recordera | 7 dni; potwierdzono zapis pierwszych statystyk 5 min liczników, także nieaktywnego trybu i stopniogodzin | Metadane: `has_sum=true`; pierwsze agregaty godzinowe pozostają do potwierdzenia po zamknięciu godziny |
| Weryfikacja kodu 2.0 | Rc.2: Ruff lint/format, mypy strict oraz 79 testów przechodzą lokalnie | Python 3.10.5; Ruff 0.11.13, mypy 1.15.0, pytest 8.3.5; CI skonfigurowane dla 3.10/3.13, bez zdalnego przebiegu |
| Migracja harmonogramów | Eksport 41 encji i propozycje zapisane lokalnie; akcje pozostają przy 1.x | `runtime/migration/ha-before.json`, `scheduler-changes.json`, `initial-state.json`; przełączenie dopiero przy pilotażu |
| Obserwacja 72 h | Uruchomiona 20.10.2026 około 23:39:46 Europe/Warsaw | Pierwszy dodatni licznik i heartbeat potwierdzone; minimum 72 h upływa 23.10 około 23:40, lecz braki pomiarów wymagają oceny przed pilotażem |
| Przejęcie sterowania | Niewykonane | Jedyny aktywny sterownik, potwierdzenia TRV/CW400 i wynik restartu |
| Pilotaż 7–14 dni | Nierozpoczęty | Komfort każdego pokoju, błędy poleceń, safety i energia |
| Tygodniowa automatyzacja AI | Utworzona i aktywna: `smartheating-analiza-tygodniowa` | Niedziela 18:00 Europe/Warsaw; początkowo czeka cicho na wdrożenie i 14 dni wiarygodnych danych |
| Efekt ekonomiczny i hydrauliczny | Nieoceniony po zmianie | Okres porównania, pogoda, CO/CWU, odtworzenie temperatur po Away |

## Scenariusze odbioru technicznego

Każdy scenariusz powinien wskazywać test, wynik i wersję kodu:

- Różne cele pokojów, renormalizacja wag oraz pominięcie brakującego, starego lub niefinitywnego pomiaru.
- Ciepła podłogówka przy zimnej sypialni albo pokoju dziecka.
- Dwa równoczesne żądania safety: większe żądanie, bez podwójnego wymuszenia i bez obniżenia zwykłego żądania.
- Aktywacja safety dopiero po ciągłych 15 minutach deficytu większego niż 0,5°C; zakończenie poniżej 0,2°C; diagnostyka po 60 minutach bez automatycznego wyłączenia potrzebnego grzania.
- Brak eskalacji przy brakującym pomiarze albo niepotwierdzonym stanie głowicy.
- Niezgodne tryby i cele dwóch głowic sypialni, opóźnione potwierdzenie, wyczerpane ponowienia oraz odzyskanie łączności.
- Utrata HA/MQTT, restart i nieprawidłowy odczyt kotła; brak pozornej informacji o pracy palnika na podstawie samego żądania.
- Ręczny cel wygasający na następnej granicy harmonogramu, także gdy temperatura kolejnego slotu jest identyczna.
- Away bez terminu, zmiana i anulowanie terminu, „Wracam teraz”, restart po terminie oraz jawna zmiana trybu kończąca nadpisania.
- Zmiana czasu, granica doby, cel harmonogramu na przyjazd oraz niezależny start przygotowania podłogówki i grzejników.
- Odtworzenie liczników bez podwójnego naliczania, przerwa pomiarowa nieuwzględniana jako komfort oraz migracja schematu z kopią poprzedniego stanu.
- Raport tygodniowy oparty na długoterminowych statystykach po usunięciu historii surowej.
- Brak fizycznych komend w obserwacji we wszystkich ścieżkach, w tym inicjalizacji, ponowień, restartu i obsługi błędów.

## Zapis pojedynczego eksperymentu

Eksperyment należy powiązać z wersją aplikacji i identyfikatorem konfiguracji. Minimalny zapis obejmuje:

| Pole | Treść |
| --- | --- |
| Hipoteza | Oczekiwany wpływ jednej zmiany na komfort lub zużycie |
| Parametr | Dokładny parametr oraz wartość przed i po |
| Zakres | Pomieszczenia i tryby, których dotyczy zmiana |
| Okres | Początek, planowany koniec i porównywany okres bazowy |
| Jakość danych | Pokrycie wymaganymi pomiarami, przerwy i ograniczenia |
| Warunek cofnięcia | Mierzalne pogorszenie lub błąd wymagający powrotu |
| Wynik | Komfort każdego pokoju, energia CO/CWU, pogoda i koszt ponownego nagrzania |
| Decyzja | Przyjąć, cofnąć albo zbierać dane dalej, wraz z uzasadnieniem |

Wynik gazowy musi podawać współczynnik 11,594 kWh/m³, źródło i znany okres faktury; poza potwierdzonym okresem jest oszacowaniem. Zmiana kalibracji EMS w trakcie eksperymentu sterowania uniemożliwia bezpośrednie porównanie i nie jest częścią tego pilotażu.

## Aktualizacja dokumentu

Uzupełniaj rejestr po wykonaniu danego sprawdzenia. Nie usuwaj niezamkniętego ograniczenia dlatego, że powstał kod obsługujący dany przypadek. Każda zmiana runtime, konfiguracji, schematu stanu lub źródła danych wymaga ponownej oceny powiązanych dowodów.

## Pierwszy odczyt działającej obserwacji

- AppDaemon: `sensor.sh2_health=running`, `shadow=true`, Python 3.13.15, konfiguracja `bc1b77beb2c05027`, commit `08347d9+dirty`. Stan `running` uzupełniono kontrolą heartbeat i rosnących liczników.
- Nowe encje: 843. Wszystkie 61 referencji widoku istnieje. Widok [Obserwacja](https://ha.kojbito.org/lovelace/smartheating-v2) został dopisany do istniejącego dashboardu przez API z kontrolą skrótu konfiguracji; pozostałe 6 widoków zachowano. Odczyt zwrotny potwierdził zapis i poprawne znaki Unicode.
- Weryfikacja wizualna nie została zakończona: silnik screenshotów HA jest wyłączony, a przeglądarka wymaga logowania. Nie wykonywano w niej żadnych poleceń ogrzewania.
- Dostępne były 9 z 11 pomiarów. Sypialnia i dolna łazienka miały starsze niż 30 min odczyty; 2.0 odrzuca je zamiast wstawiać cel lub nieograniczenie używać starej temperatury. Przed pilotażem trzeba zweryfikować rzeczywisty sposób raportowania tych źródeł i właściwy sygnał świeżości. Nie zwiększono TTL w celu sztucznego osiągnięcia 95% pokrycia.
- Dotychczasowy `sensor.sh_health` pozostał `running`, z ciągłym uptime około 24 h i niezmienionym hashem konfiguracji. Stara aplikacja pozostaje jedynym sterownikiem fizycznym; nowa ma blokady w managerze urządzeń i adapterze usług.
- Pierwsze statystyki 5 min: oczekiwany czas korytarza wzrósł do 0,084276 h, a nieaktywny tryb Away zachował poprawne statystyki zerowe. Statystyki stopniogodzin są przyjmowane z jednostką `°C·h` i `has_sum=true`.
- Kalibracja EMS, nastawy serwisowe kotła, RTL oraz działające akcje harmonogramów nie były zmieniane. Wcześniejsze przedziały gazowe przeliczono z 11,594; z braku okresu faktury wyniki pozostają oszacowaniami.

Do zamknięcia odbioru ogrzewania nadal potrzebne są: spis RTL, kwalifikacja świeżości wszystkich źródeł, pełny okres obserwacji, kontrolowane przejęcie i pilotaż. Ten rejestr nie potwierdza jeszcze utrzymania ±0,5°C ani oszczędności.

Zaplanowano jednorazowy odbiór obserwacji na 23.10.2026, 23:45 Europe/Warsaw,
przy tym czacie: `smartheating-odbi-r-obserwacji`. Ma przygotować raport i ocenić
braki, bez przejmowania sterowania. Lokalny komputer i aplikacja Codex muszą działać.
Cotygodniowe rekomendacje mają odrębny harmonogram niedzielny i bramkę 14 dni / 95%.

## Wdrożenie rc.2 — 22.10.2026

Audyt około 16:07 wykazał zbyt rygorystyczną kwalifikację opartą na zmianie helpera,
odrzucanie stałego licznika EMS oraz wyłączanie grzejników z obliczeń shadow przez
różnice ustawień v1. Zapis godzinowych statystyk i ciągłość liczników były poprawne.
Szczegóły poprawki i granice interpretacji raportów:
[kwalifikacja danych](measurement-qualification.md).

- Pakiet `2.0.0-rc.2` uruchomiono 22.10 około 17:02:58 Europe/Warsaw.
  Wersja/config: `3e3cff423b8c7639`, Python 3.13.15, `shadow=true`.
  Początek bieżącego `evaluation`: `2026-10-22T15:02:52.664351+00:00`.
- V1 nie była restartowana ani zmieniana: zachowała hash
  `26eb29d568640067d58bc6a2903eaec12e117445`, ciągły uptime i 8 zgodnych plików.
  Wszystkie 22 pliki nowego pakietu odpowiadają manifestowi SHA256.
- Przeprowadzono kontrolowany stop/start samej v2 przez admin API AppDaemon.
  Po zatrzymaniu potwierdzono `terminated` i zero callbacków instancji. Pierwsza
  podmiana ujawniła końcowy zapis starej instancji; po jej pełnym zatrzymaniu
  odtworzono tylko zweryfikowane raporty Zigbee z oryginalnym czasem publikującego.
  Kolejny start rc.2 o 17:06:38 zachował epokę, flagi i wartości liczników.
- Po restarcie dostępne są raporty wszystkich 11 pomieszczeń. W pierwszym pełnym
  zapisie 17:11:43 przyrost oczekiwanego czasu Home wyniósł około 5,073 min.
  Dziesięć pomieszczeń miało taki sam przyrost czasu kwalifikowanych raportów;
  korytarz 4,837 min, czyli około 95,36% (oczekiwanie na żywy raport EMS).
  Ten krótki odcinek nie potwierdza jeszcze dobowego pokrycia ani komfortu.
- `energy_issue=none` potwierdzono po żywych raportach kotła przy niezmienionym
  liczniku CO. Kandydaty safety obu pokoi publikują `inactive` dla obecnych
  temperatur. Ich aktywację, maksimum bez sumowania i blokady sprawdzają testy;
  nie wymuszano zmiany temperatur domu, aby sprowokować aktywację.
- Nowa sekcja diagnostyki została dodana wyłącznie do widoku `smartheating-v2`.
  Wszystkie 17 referencji nowej sekcji istnieje; odczyt zwrotny dashboardu
  potwierdził hash `a9fcd1652357e2fe`. Dotychczasowe widoki zachowano.
- Prywatny pakiet dowodowy i ścieżka rollbacku: `runtime/rc2/deployment.json`,
  `shadow-after.json`, `state-before-restart.json` i eksporty HA.
  Kopia zdalna: `codex-backups/smartheating-rc2-20261022T145758Z` AppDaemon.

Termin istniejącego jednorazowego odbioru `smartheating-odbi-r-obserwacji`
został przesunięty na **25.10.2026, 16:10 Europe/Warsaw**. Po zmianie czasu
72 godziny od bieżącej epoki upływają około 16:03 tego dnia. Raport ma ponownie
sprawdzić aktualną epokę i reprezentatywność danych, bez przejmowania sterowania.
Cotygodniowa analiza pozostaje w niedzielę o 18:00; strojenie wymaga 14 dni
wiarygodnych danych w aktualnym okresie. Lokalne wykonanie wymaga włączonego
komputera i aplikacji.

Pilotaż nadal nie został rozpoczęty. Nie zmieniono nastaw kotła, RTL, fizycznych
głowic ani aktualnego przełącznika safety v1. Historycznych luk rc.1 nie uzupełniono
wstecznie. Opublikowane raporty MQTT nie są niezależnym dowodem czasu sprzętowego
pomiaru ani kalibracji czujników; ograniczenia opisano w dokumencie źródeł.


## Odbiór obserwacji rc.2 — 25.10.2026

Wykonano około 22:32 Europe/Warsaw, po planowanym terminie 16:10. Pełny niewielki raport i dowody liczbowe: [raport odbioru](../reports/observation-acceptance-20261025.md) oraz sąsiedni JSON (lokalne, wykluczone z Git). Nie przejęto sterowania ani nie zmieniono HA, urządzeń, przełączników, harmonogramów lub TTL.

- Evaluation od 22.10 15:02:52 UTC potwierdzone w aktualnym pliku shadow.json; do checkpointu 25.10 21:27:23 UTC minęło 78,41 h. Komfort policzono od checkpointu 22.10 15:11:43 UTC, bez zaliczania rc.1: 78,26 h oczekiwanego czasu.
- Pokrycie zakwalifikowanymi raportami wszystkich pokojów 99,68–99,86%; 78,01–78,15 h mierzonych. Osobno porównano nominalne 72 h agregatów po korekcie trybów TRV 22.10; krótkie luki obniżają tam czas pomiarów do 71,82–71,92 h. Po przedłużeniu tej bazy do bieżącego checkpointu każdy pokój przekracza 72.32 h pomiarów po korekcie TRV.
- Wszystkie 22 pliki v2 i 8 plików v1 zgodne z manifestem, shadow=true, active_authorized=false, obie blokady usług fizycznych obecne. 156 próbek health bez spadku uptime; największy odstęp heartbeat 1804,166 s. Nie było nowego prowokowanego testu restartu lub reconnect.
- Recorder: 721 szeregów × 78 godzin = 56 238 rekordów; bez luk godzinowych i malejących sum. Checkpointy nie maleją, partycja komfortu i czasów jest spójna.
- Sprawdzono 12 surowych źródeł i próbki MQTT; dziewięć historii kontaktów nie ma odstępu ponad 3900 s. Dla łazienki dolnej sprawdzono niedawne MQTT i liczniki, bez pełnej dedykowanej historii kontaktu. Published_snapshot i last_seen nadal nie są sprzętowym znacznikiem pomiaru.
- EMS CO i v2 Home mają zgodny przyrost 68,51 kWh. Stały licznik CO nadal przyjmuje żywe raporty EMS co około 1 s; brak nowego energy_issue.
- Rzeczywiste safety pozostaje wyłączone, 0 h. Kandydat sypialni był aktywny przy założeniu komend i no_effect; kandydat dziecka nie był aktywny. Nie zaobserwowano jednoczesnej aktywacji dwóch kandydatów; nie utożsamiono symulacji z grzaniem.
- Cztery TRV nadal auto/manual/normal. Lewa sypialnia nadal auto/schedule, 15°C wobec celu pokoju 22°C. Wymaga wyjaśnienia i potwierdzenia przed pilotażem. Brak alarmu baterii nie dowodzi kondycji ogniw pod obciążeniem.
- Dane Home spełniają wymaganie obserwacji. **Pilotaż nadal zablokowany przez brak potwierdzenia lewej głowicy i wymagane kontrolowane przyjęcie ścieżki poleceń.** Away/return/arrivals nie wystąpiły. Brak podstaw do strojenia AI przed 14 dniami.


## Przejęcie sterowania przez v2 — 26.10.2026

Na bezpośrednie polecenie użytkownika rozpoczęto **aktywny pilotaż rc.2** o 14:51:59 Europe/Warsaw. Jedyny sterownik: `HeaterControllerV2`, commit `0ebd58c`, config `b340896ee8e71fd0`, `shadow=false`, `active_authorized=true`. V1 i obserwator mają 0 callbacków oraz trwałe `disable: true`; kod rc.2 pozostaje bez zmian. Aktualna prywatna konfiguracja: `runtime/pilot-20261026/active-app.yaml`; stan `/config/smartheating/state/active.json`. Dawna obserwacja i jej liczniki są zachowane, nowa epoka nie zalicza ich jako czasu pracy aktywnej v2.

Przełączono i odczytano 11 harmonogramów, zachowano identyfikatory pokojów, Home i oba przełączniki OFF. Przeniesiono zastane cele do następnej granicy harmonogramów. Kontrolowany restart v2 zachował tryb, flagi, nadpisania i liczniki; 79 testów, Ruff, formatter i mypy strict przeszły. CW400 i cztery sprawne TRV potwierdziły odczyty; 11/11 pomiarów pokojowych zakwalifikowano ponownie. Widok `/lovelace/smartheating-v2` jest aktywny; inne widoki pozostały identyczne.

**Jawny wyjątek zaakceptowany przez użytkownika:** lewa głowica sypialni nadal nie potwierdza komend. Użytkownik naprawi urządzenie; nie zmieniono przypisania głowic i nie sfabrykowano potwierdzenia. Dopóki obie głowice nie potwierdzą celu, sypialnia jest pomijana w głosowaniu i eskalacji safety. To warunkowy pilotaż, nie pełny odbiór urządzeń ani zgoda na strojenie AI.

Dowody i ograniczenia platformy: [raport przejęcia](../reports/pilot-takeover-20261026.md) oraz sąsiedni JSON (lokalne, poza Git), pakiet cofnięcia `runtime/pilot-20261026/`. AppDaemon miał błędy usług disable/create; konfigurację zweryfikowano w plikach, a kontrola aktualizacji odtworzyła również inne aplikacje. Nie wykonano celowo domowych rutyn. Ocena ogrzewania i oszczędności wymaga 7–14 dni pilotażu; rekomendacje strojenia co najmniej 14 dni wiarygodnej bieżącej epoki, nie wcześniej niż 9.11 około 14:52.

Końcowy checkpoint 14:58:40 Europe/Warsaw: 11/11 zakwalifikowanych źródeł, `energy_issue=none`, monotoniczne liczniki. Potwierdzono zapis historii i po dwa pięciominutowe agregaty trzech prób kontrolnych Recordera; agregaty godzinowe wymagają zamknięcia godziny. Wszystkie 64 referencje dashboardu istnieją. Sypialnia nadal rejestruje komfort, ale nie nalicza potwierdzonego wykonania poleceń. CW400 odczyt jest zgodny; nie wykonano sztucznego podbicia tylko w celu testowania.


## Przywrócenie celów Home — 26.10.2026, 17:31:59

Na polecenie użytkownika ponownie wybrano Home przez MCP, usuwając sześć odziedziczonych nadpisań z migracji. Trwały stan potwierdził `overrides={}`; wszystkie 11 celów porównano z aktywnymi slotami harmonogramów. Salon, korytarz i dolna łazienka 21°C; wiatrołap, górny korytarz i garderoba 20°C; górna łazienka i sypialnia 22°C; biuro 19°C, dziecko 20,5°C, garaż 15°C. Safety i podbicie pozostają OFF, brak terminu przyjazdu. Wersja, konfiguracja, epoka oceny i liczniki zachowane.

WAM zmienił się z około -1,71 do -0,02°C. CW400 podnosi nastawę z ograniczeniem szybkości zmian; odczyty i cele zapisano w `reports/home-targets-restored-20261026.json`, kopie przed/po w `runtime/pilot-20261026/home-reset-*`. Prawy TRV sypialni potwierdził w surowym MQTT 22°C, auto/manual/normal; lewy pozostaje niepotwierdzony.

Okres od wdrożenia do tej korekty obejmuje zaniżone cele odziedziczone z v1. Oddzielać go przy ocenie komfortu i zużycia od pracy z poprawnymi celami Home; brak grzania w tym okresie nie dowodzi oszczędności algorytmu.


## Lewa głowica potwierdzona — 26.10.2026, 17:40:55

Odczyt HA i świeże nie-retained MQTT potwierdziły lewy TRV sypialni: auto/manual, 22°C, force normal; raportowana pozycja zaworu 50%. Od 17:40:55 obie głowice mają `confirmed`, więc sypialnia nie jest już wykluczona przez brak potwierdzenia. Wszystkie pięć TRV i CW400 (20,5°C) potwierdzone. V1 i shadow nadal terminated, 0 callbacków; v2 jako jedyny sterownik. Nie wysyłano nowych komend w ramach kontroli.

Po przywróceniu Home potwierdzono w ostatnim checkpointcie 18,33 min danych: 100% pokrycia wszystkich pokojów; przyrost energii EMS i v2 identyczny 0,82 kWh, bez błędu energii i nadpisań. Safety nadal OFF. Komfort jeszcze nieosiągnięty: sypialnia 20,7/22°C, łazienka górna 20,5/22°C; inne pomieszczenia także mają odchylenia powyżej 0,5°C. To zamknięcie blokady komunikacji TRV, nie odbiór komfortu ani oszczędności. Dowód: lokalny `reports/trv-recovered-20261026.json`.


## UX rc.3 — 26.10.2026, 23:03:52

Wdrożono `2.0.0-rc.3`, commit `6b592a2bb048d213191c942e8d4c09dce289d061`,
config `2d768800b20d121b`. V2 pozostaje jedynym aktywnym sterownikiem;
v1 i obserwator są terminated, mają 0 callbacków oraz trwałe `disable: true`.
Wersja uruchamia nową epokę `2026-10-26T22:03:52.801221+00:00`, bez zerowania
liczników. Przy ocenie pilotażu oddzielać epoki i porównywać przyrosty; sama
zmiana UX nie dowodzi oszczędności. Bramka 14 dni bieżącej epoki pozostaje aktywna.

- Trzy widoki: Dom (`smartheating`), Plan i powrót (`smartheating-control`),
  Diagnostyka (`smartheating-debug`). Dawna ścieżka `smartheating-v2` pozostaje
  działającym podwidokiem Dom. Zachowano wcześniejsze karty CWU i pozostałe
  trzy widoki dashboardu bez zmiany.
- W pokojach widać pomiar, cel, źródło i koniec ręcznego nadpisania. Powrót do
  planu dotyczy pojedynczego pokoju. Plan ma natywny wybór daty przyjazdu,
  anulowanie i powrót do Home. Nie dodano helperów HA; nowe encje publikuje v2.
- Edytor obecnych codziennych harmonogramów ma walidację, jawny zapis,
  wykrywanie konfliktów i potwierdzenie odczytem HA. Moduł zarejestrowano
  przez API zasobów Lovelace; odczyt odpowiada plikowi źródłowemu.
- Zweryfikowano 90 odwołań do encji bez braków i 14 unikatowych szablonów Jinja.
  Hash końcowego dashboardu: `d1ebccdbc2c645c8`. Stan końcowy: Gotowe,
  11/11 źródeł, 5/5 TRV, potwierdzone komendy, `energy_issue=none`.
- Home, brak terminu i nadpisań oraz oba przełączniki OFF zachowane. Historia
  potwierdziła odrzucenie daty z przeszłości o 23:06:00; polecenie powrotu garażu
  do planu potwierdzono bez zmiany jego celu 15°C. Nie przełączano domu w Away
  i nie zmieniano rzeczywistych harmonogramów tylko na potrzeby testu.
- Hashami porównano niezmienione moduły regulatora: control, config, devices,
  measurements, schedules i targets. Pozostały te same wzory WAM, dogrzewanie,
  safety, wagi, TTL i nastawy urządzeń. Poprawiono natomiast publikację stanu
  energii po odzyskaniu raportów i usunięto z widoku odziedziczoną akcję HVAC v1.
- Pakiet podmieniono po zatrzymaniu samej v2, przy zweryfikowanym braku obcych
  zmian plików. Normalna kontrola plików AppDaemon załadowała nowy kod; nie
  używano globalnego reload ani restartu dodatku. Przywrócono production_mode.
- Walidacja: 87 testów pytest, 4 testy Node, Ruff, formatter i mypy strict.
  Wizualnie sprawdzono edytor na danych testowych przy szerokości 390 px:
  zapis z potwierdzeniem i błąd kroku temperatury. Pełny odbiór wyglądu natywnych
  widoków HA wymaga zalogowania w otwartej przeglądarce; MCP potwierdził ich
  konfigurację, encje i szablony.

Checkpoint liczników 23:08:57 Europe/Warsaw zachowuje wszystkie wartości względem
kopii sprzed UX i bieżący tryb. Dowody: lokalne `reports/ux-deployment-20261026.md`
i JSON oraz `runtime/ux-20261026/`. Kopia odtworzeniowa AppDaemon:
`codex-backups/smartheating-ux-20261026T214833Z`. Instrukcja UX: [ux.md](ux.md).
