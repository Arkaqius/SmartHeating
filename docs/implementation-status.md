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
