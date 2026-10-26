# Obsługa ogrzewania w Home Assistant

Dom jest głównym widokiem `/lovelace/smartheating`. Plan i powrót ma ścieżkę
`smartheating-control`, diagnostyka `smartheating-debug`. Dawny link
`smartheating-v2` pozostaje ukrytym widokiem tego samego panelu. CWU zachowuje
oryginalne karty i akcje w głównym widoku.

## Zasady interfejsu

Interfejs dziedziczy motyw i font HA. Akcent sterowania używa `--primary-color`
(domyslnie #1565c0), tekst #1b263b, tekst pomocniczy #5a6575, podziały #d7dde5,
błędy #b3261e; własny CSS jest ograniczony do edytora harmonogramu.
Dom układa podsumowanie, parter i piętro w sekcjach reflow HA (jedna kolumna
na telefonie). Plan skupia wybór przyjazdu i przedziały temperatur. Diagnostyka
pokazuje techniczne odczyty osobno. Brak dekoracyjnej animacji; pola i przyciski
mają min. 44 px, widoczny focus, etykiety i komunikaty aria-live.

## Cele i nadpisania

Każdy pokój pokazuje pomiar, cel i źródło. Ręczna zmiana trwa do kolejnej granicy
harmonogramu. Przy ręcznym źródle pojawia się lokalny termin oraz przycisk
powrotu do planu tylko tego pokoju. Zmiana profilu domu kończy wszystkie ręczne
nadpisania. Nie oznacza to przywrócenia ogrzewania pokoju wyłączonego przyciskiem off.

## Powrót

Natywna `datetime.sh_arrival_at` korzysta z istniejącego stanu terminu v2;
HA prezentuje datę lokalnie i wysyła ISO UTC. Nie ma nowego helpera ani
równoległej automatyki sterowania. Brak terminu jest reprezentowany jako unknown
w encji datetime i jawnie opisany w panelu. Przycisk anulowania usuwa termin,
pozostawiając profil nieobecności. W Home termin może być zapisany, lecz plan
przygotowania wymaga wybrania nieobecności. Jestem w domu przywraca Home.
Prognoza gotowości jest oszacowaniem, nie potwierdzonym grzaniem.

## Edycja planu

`frontend/smartheating-schedule.mjs` jest modułem Lovelace bez zależności.
Obsługuje obecny kontrakt: codziennie, pełna doba, rosnące godziny od 00:00,
cele 5–30°C co 0,5°C i osobny temat MQTT pokoju. Zmiany w formularzu nie sterują
urządzeniami, dopóki użytkownik nie zapisze. Potwierdzenie wymaga nowego stanu
harmonogramu z HA; samo przyjęcie usługi nie wystarcza. Konflikt z innym edytorem
wymaga ponownego wczytania. Wyłączenie harmonogramu blokuje udział pokoju
w automatycznym sterowaniu. Edytor nie zmienia tagów, nazwy ani stanu włączenia.

## Granice

Gotowe oznacza gotowość sterowania i potwierdzenia, nie komfort we wszystkich
pokojach. Potrzebuje ciepła jest zapotrzebowaniem; palnik i CO/CWU pochodzą
z osobnych odczytów EMS. Ochrona komfortu i dogrzanie są w diagnostyce.
Odczyty raw oraz stare encje zachowują kompatybilność; zamrożony czas pętli v1
nie jest już pokazywany. Widoki generuje `python -m smartheating.dashboard`.
