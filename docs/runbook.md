# SmartHeating 2.0 — uruchomienie, obserwacja i kalibracja

Ten dokument prowadzi przez uruchomienie wersji 2.0 w domu ze wspólnym obiegiem grzejników i podłogówki ograniczanej zaworami RTL. Odbiór kodu, uruchomienie obserwacji i odbiór ogrzewania to osobne decyzje. Aktualne dowody i braki zapisujemy w [rejestrze wdrożenia](implementation-status.md).

## Zakres i odpowiedzialność

AppDaemon oblicza cele i polecenia. Home Assistant udostępnia fizyczne urządzenia, harmonogramy i dashboard. Encje aplikacji powstają przez MQTT discovery; ich polecenia wracają przez MQTT. Obowiązuje [kontrakt architektury](../ARCHITECTURE.md).

Wersja obserwacyjna domyślnie korzysta z prefiksu encji `sh2` i tematów `smart_heating_v2`. Nie może publikować discovery ani stanów pod identyfikatorami działającego sterownika `sh` i `smart_heating`. Dotyczy to również encji zdrowia aplikacji. Oddzielne nazwy nie zastępują blokady fizycznych poleceń: tryb obserwacyjny musi blokować wszystkie zapisy do kotła i TRV, także podczas inicjalizacji, restartu, ponowień i obsługi błędu.

Przejęcie istniejących identyfikatorów `climate.sh_*`, przełącznika safety oraz tematów `smart_heating` następuje dopiero podczas kontrolowanego przełączenia. W danej chwili tylko jedna wersja może sterować fizycznymi urządzeniami. Samo wdrożenie plików lub zielone testy nie rozpoczynają pilotażu.

## 1. Zapisz stan wyjściowy

Przed uruchomieniem na instalacji przygotuj prywatny pakiet odtworzeniowy:

1. Zapisz commit i wersję aplikacji, kopię wdrożonych plików, konfigurację AppDaemon oraz wersję wspólnej biblioteki `appdaemon_common`. Porównaj skróty wdrożonych plików z repozytorium; punkt odniesienia repo to `08347d9`.
2. Potwierdź rzeczywistą wersję Pythona procesu AppDaemon i wersję AppDaemon. Numer wersji dodatku ani Python Home Assistant Core nie są wystarczającym dowodem.
3. Wyeksportuj definicje wszystkich harmonogramów ogrzewania, ich odbiorców oraz powiązane elementy dashboardu. Zapisz aktywny slot, jego granice, cel i strefę czasową `Europe/Warsaw`.
4. Zapisz ustawienie przełącznika `switch.sh_force_flow_safety_rooms`, przełącznika podbicia temperatury, cele pokojów oraz tryby fizycznych TRV. Ustawienie safety należy przenieść, zamiast przyjmować nową wartość domyślną.
5. Dla każdego pomieszczenia zapisz identyfikator czujnika, fizyczne głowice i harmonogram. W sypialni sprawdź obie głowice oddzielnie.
6. Potwierdź w działającym HA konfigurację Recordera, wykluczenia encji i dostępność statystyk. Lokalny plik z retencją trzech dni nie potwierdza retencji działającej instancji.
7. Zapisz rzeczywiste nastawy RTL i pomieszczenia obsługiwane przez poszczególne pętle. Podana w rozmowie pozycja „około 3” jest założeniem, a nie wykonanym spisem.
8. Zapisz odczyt gazomierza z datą i godziną oraz odczyty energii EMS z tego samego momentu. Zanotuj okres faktury określającej współczynnik gazu.

Kopie konfiguracji mogą zawierać dane prywatne. Przechowuj je poza publikowaną historią Git. Brak dostępu do któregoś źródła zapisuj jako brak dowodu; nie zastępuj go zgodnością lokalnego pliku.

## 2. Zweryfikuj pakiet przed wdrożeniem

Przegląd obejmuje oddzielnie zachowanie WAM, poprawki obsługi urządzeń oraz nowe tryby. Dla prawidłowych pomiarów i tej samej konfiguracji refaktor ma zachować dotychczasowe obliczenia podstawowe:

```text
błąd pokoju = jego cel − jego temperatura
WAM = suma(błąd pokoju × jego waga) / suma wag uwzględnionych pokojów
zwykłe żądanie = WAM + dotychczasowe korekty + zapotrzebowanie grzejników
wynik arbitrażu = większe ze zwykłego żądania i dopuszczalnego żądania safety
nastawa bazowa CW400 = temperatura korytarza + końcowa korekta
```

Wagi startowe podłogówki to: salon 3, korytarz 3, łazienka 3, wiatrołap 1, korytarz górny 2, garderoba 1, łazienka górna 3. Wagi grzejników to: biuro 2, pokój dziecka 8, sypialnia 8, garaż 1. Dotychczasowe zapotrzebowanie grzejników jest uruchamiane przy ujemnej sumie błędu korytarza i bieżącej korekty oraz dodatnim błędzie co najmniej jednego pokoju grzejnikowego. Dodaje sumę dodatnich ważonych błędów grzejników pomnożoną przez 4. Charakterystyka starego kodu określa także kolejność pozostałych korekt i zaokrągleń.

Odrzucenie nieprawidłowego pomiaru, ponowna normalizacja wag, arbitraż safety oraz ograniczanie szybkości zmian są jawnymi zmianami zachowania. Nie należy ukrywać ich jako samego przeniesienia kodu. Zmiana bazowej nastawy CW400 pozostaje osobnym, późniejszym eksperymentem.

Przed dopuszczeniem pakietu zapisz wynik lintowania, formatowania, `mypy --strict` i testów dla konkretnego commitu. Sprawdź również instalację na wersji Pythona zgodnej z rzeczywistym AppDaemon. Testy muszą wykazać brak wszystkich poleceń fizycznych w trybie obserwacyjnym, a nie tylko brak zmiany jednej nastawy.

## 3. Połącz harmonogramy z nowym modelem celów

Źródło zmiany celu musi być rozpoznawalne. Zwykła liczba na wspólnym temacie ustawiania temperatury nie pozwala niezawodnie rozróżnić działania harmonogramu i ręcznego nadpisania.

Most wysyła cel, identyfikator źródłowego harmonogramu i indeks slotu na osobny temat `smart_heating/<pokój>/schedule/set`. Wiążącą temperaturę i granice przedziału aplikacja oblicza z aktualnej definicji harmonogramu HA, zamiast ufać opóźnionemu pakietowi MQTT. Ręczne komendy mają osobne tematy sesyjne przekazywane HA przez discovery. Zmiana lub odtworzenie pakietu harmonogramu nie usuwa nowszego nadpisania ręcznego.

Kolejność migracji:

1. Wyeksportuj obecne akcje harmonogramów i sprawdź wszystkich ich odbiorców. Zachowaj plik do cofnięcia zmiany.
2. W trybie obserwacyjnym aplikacja odczytuje definicje harmonogramów HA; dotychczasowy sterownik nadal otrzymuje swoje akcje. Nie zmieniaj tych akcji przed przejęciem.
3. Sprawdź inicjalizację celu z aktywnego slotu po restarcie, odczyt celu obowiązującego w chwili przyszłego przyjazdu oraz rozpoznanie następnej granicy slotu.
4. Sprawdź nadpisanie ręczne w slocie, którego następca ma identyczną temperaturę. Nadpisanie musi wygasnąć na granicy slotu mimo niezmienionej wartości planowej.
5. Sprawdź północ i obie zmiany czasu. Jesienna granica w adapterze wykonuje się raz przy pierwszym wystąpieniu; wiosenna pominięta godzina przechodzi na koniec luki. Potwierdź zgodność z Scheduler. Daty poleceń muszą zawierać strefę lub przesunięcie UTC.
6. Przy przejęciu sterowania skieruj akcje do nowego adaptera dokładnie raz. Zatrzymaj poprzedni tor dostarczania komend, aby harmonogram nie tworzył drugiego polecenia wyglądającego jak ręczne.
7. Po przełączeniu odczytaj z HA zapisane definicje i potwierdź cel aplikacji na najbliższej naturalnej granicy harmonogramu. Nie uruchamiaj całych domowych rutyn tylko w celu testowania.

Nie używaj zatrzymanych wiadomości MQTT jako kolejki poleceń do ponownego wykonania po restarcie. Stan odtwarzaj z pliku aplikacji i aktualnego harmonogramu. Utrata źródła harmonogramu powinna być widoczna w diagnostyce.

## 4. Obserwuj co najmniej 72 godziny

Uruchom nową wersję z oddzielnymi encjami, magazynem stanu i blokadą fizycznych poleceń. Zapisz czas początku, commit, identyfikator konfiguracji i aktywnego sterownika instalacji. Minimum 72 godziny liczymy od uruchomienia działającego zbierania danych, nie od utworzenia plików.

W czasie obserwacji porównuj:

- WAM i składniki korekty dla takich samych prawidłowych danych;
- cele harmonogramów, ręczne nadpisania i ich wygasanie;
- kompletność i świeżość odczytów, zachowanie po restarcie oraz brak `NaN`;
- hipotetyczne decyzje obu safety rooms i widoczne konflikty komfortu;
- publikowane liczniki oraz ciągłość ich wartości po restarcie;
- całkowity brak zapisów do kotła i fizycznych TRV z nowej wersji.

Obserwacja nie potwierdza skuteczności fizycznych komend nowej wersji, ponieważ ta ich nie wysyła. Testy potwierdzeń wykonujemy na atrapach, a następnie sprawdzamy przy kontrolowanym przejęciu sterowania. Brak reprezentatywnych okresów grzania oznacza potrzebę dłuższej obserwacji.

## 5. Przejmij sterowanie i rozpocznij pilotaż

Przejście do aktywnego sterowania wymaga zamknięcia braków etapu wyjściowego, przejścia testów i zakończenia obserwacji bez niewyjaśnionych rozbieżności.

1. Zapisz aktualne cele, tryb domu, termin przyjazdu, flagi oraz kopię stanu obu wersji. Zapisz także stan fizycznych urządzeń.
2. Zatrzymaj poprzedni sterownik i potwierdź brak jego aktywnych timerów, subskrypcji oraz zapisów. Sam stan encji `running` nie wystarcza do ustalenia właściciela sterowania.
3. Przenieś zatwierdzony stan i ustawienie safety. Włącz docelowy profil identyfikatorów `sh` i tematów `smart_heating`; zachowaj dotychczasowe identyfikatory klimatów i przełącznika safety.
4. Przełącz most harmonogramów. Uruchom nową wersję aktywną jako jedynego właściciela komend fizycznych.
5. Dla każdej głowicy odczytaj tryb, preset i cel po komendzie. Obie głowice sypialni muszą potwierdzić odpowiedni stan. Dla TS0601 normalna regulacja temperatury wymaga właściwego trybu `auto` i presetu `manual`; `heat` tego modelu może wymuszać otwarcie zaworu. Potwierdź zachowanie na rzeczywistym wariancie urządzenia.
6. Potwierdź nastawę CW400 odczytem zwrotnym. Po przekroczeniu limitu ponowień pokaż błąd wykonania, zamiast wysyłać polecenie bez końca.
7. Sprawdź dashboard, dostępność encji, zapis statystyk oraz stan po kontrolowanym restarcie aplikacji.

Przez następne 7–14 dni oceniaj komfort każdego pomieszczenia, liczbę i wyniki poleceń, czas safety, pracę palnika oraz zużycie CO i CWU. Nie zmieniaj równocześnie kalibracji EMS, hydrauliki, krzywej CW400 i wag algorytmu. Pilotaż kończy się oceną danych, a nie automatycznie po upływie czasu.

### Cofnięcie przejęcia

Powodem cofnięcia jest m.in. dwóch aktywnych nadawców poleceń, niewyjaśnione nadpisywanie celów, niekontrolowane ponowienia lub trwałe pogorszenie komfortu powiązane z nowym sterowaniem.

Zatrzymaj nowego nadawcę poleceń. Zachowaj jego stan i log diagnostyczny do analizy. Przywróć zapisane konfiguracje, poprzedni tor harmonogramów i zgodną wersję aplikacji. Dopiero potem uruchom wcześniejszy sterownik. Potwierdź fizyczne nastawy oraz ustawienie safety. Nie podawaj starszej wersji pliku stanu o nieobsługiwanym schemacie; użyj kompatybilnej kopii lub jawnej procedury odtworzenia. Nie kasuj zbiorczo retained MQTT ani historii HA.

## 6. Używaj Away i przygotowania powrotu

| Profil | Podłogówka | Grzejniki poza garażem |
| --- | --- | --- |
| Home | Cel bieżącego harmonogramu | Cel bieżącego harmonogramu |
| Away krótkie | Cel harmonogramu minus 0,5°C | Cel harmonogramu minus 1°C |
| Away wyjazdowe | Niższa z wartości: cel harmonogramu i 18°C | Niższa z wartości: cel harmonogramu i 17°C |
| Przygotowanie powrotu | Stopniowe odtworzenie celu na przyjazd | Odtworzenie celu na przyjazd |

Garaż zachowuje dotychczasowy cel. Parametry są konfigurowalne dla każdego pomieszczenia. Safety chroni cel aktualnego trybu; nie ma przywracać komfortu Home podczas zwykłego Away.

Bez terminu powrotu Away trwa do ręcznego zakończenia. Zmiana lub usunięcie terminu przelicza plan. „Wracam teraz” przełącza Home i pokazuje oszacowanie czasu dojścia do temperatur. Jawna zmiana trybu domu kończy wcześniejsze ręczne nadpisania pokojów.

Plan jest przeliczany co pięć minut osobno dla pomieszczeń. Startowe tempo to 0,25°C/h dla podłogówki i 0,5°C/h dla grzejników, z marginesem 30 minut i maksymalnym wyprzedzeniem 24 godzin. Celem jest temperatura z harmonogramu obowiązująca o godzinie przyjazdu. Są to wartości do kalibracji; wspólny obieg, pogoda i RTL mogą ograniczać faktyczny efekt. Brak pomiaru lub zbyt krótki czas do przyjazdu musi być widoczny.

Po restarcie odtwórz profil, termin i nadpisania. Termin, który minął podczas przerwy, powoduje Home. Sam restart nie wydłuża czasu ręcznego nadpisania ani nie nalicza komfortu za okres bez pomiarów.

## 7. Interpretuj safety i metryki

Sypialnia i pokój dziecka są oceniane niezależnie. Początkowo potrzeba safety powstaje po 15 minutach ciągłego niedogrzania większego niż 0,5°C; kończy się poniżej 0,2°C. Wspólne żądanie wynika z większej potrzeby, bez dodawania dwóch wymuszeń. Arbitraż nie może obniżyć zwykłego żądania. Zmiany podlegają ustalonemu ograniczeniu szybkości.

Po 60 minutach utrzymującego się niedogrzania pokaż diagnostykę braku efektu. Nie wyłączaj z tego powodu potrzebnego grzania. Brak prawidłowego pomiaru albo niepotwierdzona praca głowicy blokują eskalację wymuszenia. Rozróżniaj polecenie, potwierdzoną nastawę, otwarcie zaworu i rzeczywistą pracę palnika; żadne pojedyncze pole MQTT nie jest dowodem wszystkich tych zdarzeń.

Metryki komfortu liczymy dla każdego pokoju i oddzielnie dla Home, Away oraz przygotowania powrotu:

- czas w zakresie celu ±0,5°C, poniżej i powyżej zakresu;
- skumulowane niedogrzanie i przegrzanie w stopniogodzinach;
- czas wymaganych i prawidłowych pomiarów, z których wynika pokrycie;
- czas aktywności safety i błędy wykonania poleceń;
- okresy dochodzenia do nowego celu, oceniane osobno od stabilnego komfortu.

Zmiany sterowania publikujemy na bieżąco, a liczniki zbiorcze co pięć minut. Recorder zapisuje encje MQTT. Statystyki długoterminowe wymagają poprawnych jednostek i klas; skumulowane liczniki nie mogą zmieniać znaczenia przy restarcie. Dane nie trafiają bezpośrednio do tabel bazy HA. Nie zwiększamy globalnej retencji w pierwszym wdrożeniu.

Mały plik JSON przechowuje stan wymagany po restarcie i ma poprzednią kopię. Historia pomiarów pozostaje w HA. Test raportowania musi odtworzyć tygodniowy wynik ze statystyk po usunięciu historii surowej; same średnie temperatur nie pozwalają odtworzyć czasu niedogrzania. Zobacz [Recorder](https://www.home-assistant.io/integrations/recorder/) i [historię HA](https://www.home-assistant.io/integrations/history/).

## 8. Kalibruj jedną rzecz naraz

Kolejność eksperymentów:

1. Porównaj czujniki pokojowe i każdą głowicę podczas grzania oraz po ostygnięciu.
2. Sprawdź rozdział ciepła i RTL; po jednej zmianie obserwuj zwykle 48–72 godziny.
3. Zbadaj krzywą CW400 i wpływ pomieszczenia przy kontrolowanej korekcie aplikacji.
4. Oceń wagi, zapotrzebowanie grzejników i safety na podstawie komfortu oraz czasu aktywności mechanizmów.
5. Oceń Away razem z energią ponownego nagrzania.
6. Dopasuj tempo nagrzewania pomieszczeń, uwzględniając pogodę i błąd przewidywania gotowości.
7. Dopiero później badaj obniżenia nocne i wyprzedzanie zwykłych harmonogramów.

Współczynnik faktury wynosi **11,594 kWh/m³**. Zapisz źródło i okres obowiązywania. Wcześniejsze porównania z wartością 11 należy przeliczyć; zastosowanie 11,594 poza potwierdzonym okresem faktury oznacz jako oszacowanie. Gazomierz obejmuje cały kocioł, więc bilans obejmuje CO i CWU. Oszacowanie EMS nie staje się pomiarem gazomierza przez samą zmianę współczynnika. Podczas eksperymentu ze sterowaniem nie zmieniaj kalibracji EMS.

Wspólny obieg nie pozwala niezależnie zadawać temperatury wody każdej części instalacji. Konflikt między zimnym pokojem grzejnikowym a przegrzaną podłogówką pozostaje jawnym wynikiem analizy. Sam refaktor nie potwierdza rozwiązania takiego konfliktu.

## 9. Uruchom tygodniowe rekomendacje

Analiza przy tym czacie jest przewidziana na niedzielę o 18:00 w `Europe/Warsaw`, po zgromadzeniu co najmniej 14 dni wiarygodnych danych. Lokalne wykonanie wymaga działającego komputera i aplikacji. Sam opis harmonogramu nie oznacza utworzenia automatyzacji; jej identyfikator, status i pierwszy przebieg zapisz w rejestrze wdrożenia.

Raport ocenia komfort każdego pokoju i pokrycie wymaganymi danymi; oddziela tryby, CO, CWU i koszt przygotowania powrotu; uwzględnia pogodę oraz wykonanie poleceń. Przy pokryciu poniżej 95% nie proponuje strojenia. Brak niezbędnych danych pogodowych lub rozdzielenia energii jest ograniczeniem analizy, a nie zerowym zużyciem.

Raport proponuje najwyżej jeden eksperyment albo dalszą obserwację. Eksperyment zawiera parametr, wartość przed i po, hipotezę, oczekiwany efekt, okres pomiaru i warunek cofnięcia. Przechowuj zaakceptowany eksperyment oraz wynik w małych plikach JSON/Markdown. AI początkowo rekomenduje; nie zmienia samodzielnie temperatur komfortu, nastaw serwisowych spalania ani zabezpieczeń kotła.

## Konkretne pliki tego wydania

Pakiet z `python -m smartheating.bundle` rozpakuj do katalogu aplikacji o nazwie `SmartHeating2`. Zawiera zewnętrzny `__init__.py`; konfiguracja używa pełnej nazwy `SmartHeating2.smartheating.appdaemon_app`. Jest to ważne dla zależności i przeładowań pakietów AppDaemon. Nie mieszaj plików pakietu z katalogiem starego sterownika.

CLI eksportu i propozycji migracji: `python -m smartheating.migration`; raportu: `python -m smartheating.reporting`. Widoki: `cfg/dashboard.shadow.yaml` oraz `cfg/dashboard.pilot.yaml`. Mapa urządzeń: [entity-map.md](entity-map.md). Wyniki przeliczenia gazu dla wszystkich wcześniejszych przedziałów: prywatny `runtime/migration/gas-recalculated.json`.
