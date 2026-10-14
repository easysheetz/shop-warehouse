# Skaner zakupów

Aplikacja webowa (telefon i komputer) do ewidencji towaru kupowanego w sklepach stacjonarnych:
pracownik skanuje kody EAN przy zakupie, na magazynie towar jest skanowany ponownie i przyjmowany,
a dokumenty magazynowe powstają automatycznie w Fakturowni przez API.

Aplikacja działa wyłącznie online – wszystkie dane są zapisywane na serwerze w chwili skanu.

## Przepływ towaru

```
Sklep (telefon)                                  Magazyn (telefon / czytnik / komputer)
  skan EAN → koszyk → „Zakończ zakup”              skan wszystkiego, co przyjechało → „Zatwierdź przyjęcie”
            │                                                    │
            ▼                                                    ▼
   Fakturownia: PZ ──► magazyn „W drodze” ──MM──► magazyn „Główny”
                                          └─MM──► magazyn „Reklamacje” (z opisem usterki)
                                          └─RW──  odpis braku (towar, który nie dotarł)
```

## Funkcje

**Zakup w sklepie**
- Skanowanie aparatem telefonu, czytnikiem Bluetooth/USB albo ręczne wpisanie kodu.
- Każdy skan od razu trafia na serwer – koszyk nie ginie po zamknięciu przeglądarki ani zmianie urządzenia.
- Nowy EAN pracownik opisuje raz (nazwa, rozmiar, kolor, cena netto, VAT); przy kolejnych zakupach
  podpowiada się ostatnia cena, którą można szybko zmienić.
- Ceny netto i brutto widoczne jednocześnie (zakupy na fakturę VAT).

**Partie i ceny**
- Ten sam produkt kupiony po innej cenie to osobna partia i osobna linia na PZ.
- Przy przyjęciu partie rozliczane są w kolejności FIFO (najpierw najstarsze).

**Dostawa ręczna / CSV**
- Towar z innych źródeł (hurtownie, zamówienia online) dodawany ręcznie albo z pliku CSV
  (podgląd przed zapisem, wzór pliku do pobrania).

**W drodze**
- Lista towaru kupionego, a jeszcze nieprzyjętego – według produktów lub według zakupów.
- Administrator może odpisać brak (dokument RW).

**Przyjęcie na magazyn**
- Porównanie zeskanowanego towaru z listą „W drodze”: zgadza się / brakuje / nadwyżka.
- Kilka osób może skanować jednocześnie to samo przyjęcie.
- Tryb reklamacji: produkt z usterką trafia na magazyn „Reklamacje” z opisem.
- Brakujące sztuki zostają „W drodze”, nadwyżka wchodzi z ostatnią znaną ceną zakupu.

**Kartoteka produktów**
- Wyszukiwanie po nazwie, EAN, rozmiarze; historia wszystkich partii (kto, gdzie, kiedy, za ile).
- Pracownicy dodają produkty, administrator je poprawia.

**Administracja**
- Konta pracowników (logowanie imieniem i PIN-em), uprawnienia administratora.
- Stan połączenia z Fakturownią, liczba niewysłanych dokumentów, dziennik wysyłek.
- Dokumenty, których nie udało się wysłać, są ponawiane automatycznie (oraz ręcznie przyciskiem).

## Technologia

| Warstwa | Wybór |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic |
| Baza danych | PostgreSQL 16 |
| Frontend | HTML + CSS + JavaScript (moduły ES), bez kroku budowania; skaner: html5-qrcode |
| Uruchomienie | Docker (jeden kontener, port z `PORT`), lokalnie docker compose |
| Chmura (docelowo) | Google Cloud Run + Cloud SQL + Cloud Scheduler, region europe-central2 |
| CI | GitHub Actions: pre-commit, migracje, testy na PostgreSQL, budowanie obrazu |

Aplikacja nie jest związana z Google Cloud – to zwykły kontener z PostgreSQL, więc da się ją
uruchomić u dowolnego dostawcy obsługującego kontenery.

### Spójność danych
- Skany tego samego koszyka i przyjęcia są serializowane blokadą wiersza w bazie
  (`SELECT … FOR UPDATE`) – równoległe skany nie gubią sztuk.
- Jeden otwarty koszyk na osobę i rodzaj, jedno otwarte przyjęcie – pilnują tego unikalne indeksy częściowe.
- Wysyłka do Fakturowni jest chroniona blokadą doradczą PostgreSQL, więc ten sam dokument
  nie powstanie dwa razy, nawet przy kilku instancjach aplikacji.
- Daty dokumentów liczone w strefie Europe/Warsaw.

## Struktura projektu

```
app/
  main.py            start aplikacji, /health, pliki statyczne
  config.py          konfiguracja ze zmiennych środowiskowych + walidacja produkcyjna
  db.py              połączenie z bazą, blokada synchronizacji
  models.py          tabele (produkty, warianty, zakupy, partie, przyjęcia, reklamacje, odpisy…)
  services.py        logika biznesowa (koszyk, przyjęcie FIFO, odpisy, synchronizacja)
  fakturownia.py     klient API Fakturowni
  schemas.py         zamiana obiektów bazy na JSON
  auth.py            PIN, tokeny sesji
  routers/           endpointy API (users, catalog, purchases, receipts, admin)
migrations/          migracje Alembic
static/
  index.html, style.css
  js/                moduły frontendu (api, ui, scanner, state, main) i ekrany (views/)
  vendor/            html5-qrcode
tests/               testy pytest na PostgreSQL (z atrapą Fakturowni)
scripts/             entrypoint kontenera, inicjalizacja testowej bazy
tools/wsl-setup/     playbook Ansible przygotowujący środowisko WSL
.github/workflows/   CI
```

## Konfiguracja

Cała konfiguracja pochodzi ze zmiennych środowiskowych. `.env.example` zawiera tylko nazwy
zmiennych z opisem; lokalnie kopiuje się go do `.env` (plik jest ignorowany przez git).
W produkcji wartości pochodzą z sekretów środowiska wdrożeniowego – w repozytorium nie ma żadnych kluczy.

| Zmienna | Opis |
|---|---|
| `APP_ENV` | `development` / `test` / `production` |
| `DATABASE_URL` | adres PostgreSQL (`postgresql+psycopg://…`) |
| `SECRET_KEY` | klucz podpisywania sesji (w produkcji min. 32 znaki) |
| `ADMIN_NAME`, `ADMIN_PIN` | pierwsze konto administratora, tworzone tylko przy pustej bazie |
| `SYNC_TOKEN` | token wywołania `/api/internal/sync` przez harmonogram (min. 32 znaki) |
| `TIMEZONE` | domyślnie `Europe/Warsaw` |
| `LOG_FORMAT`, `LOG_LEVEL` | `text` lokalnie, `json` w chmurze |
| `FAKTUROWNIA_ENABLED` | `false` = tryb testowy, nic nie jest wysyłane |
| `FAKTUROWNIA_DOMAIN`, `FAKTUROWNIA_TOKEN` | konto Fakturowni i kod API |
| `WAREHOUSE_TRANSIT_ID`, `WAREHOUSE_MAIN_ID`, `WAREHOUSE_RETURNS_ID` | ID magazynów w Fakturowni |
| `FAKTUROWNIA_DEPARTMENT_ID`, `FAKTUROWNIA_DEFAULT_SUPPLIER` | dział i domyślny dostawca na PZ |

W środowisku `production` aplikacja odmawia startu, jeśli klucze są domyślne lub za krótkie,
PIN administratora jest trywialny albo brakuje ustawień Fakturowni.

### Fakturownia
W Fakturowni trzeba założyć trzy magazyny: **W drodze**, **Główny**, **Reklamacje**, a ich ID
wpisać do zmiennych `WAREHOUSE_*`. Do rozwoju używamy wyłącznie konta testowego.

## Uruchomienie lokalne

Wymagany Docker (w WSL: Docker Desktop z integracją WSL).

```bash
cp .env.example .env          # uzupełnij ADMIN_PIN (np. 4321)
docker compose up --build
```

Aplikacja: <http://localhost:8000>. Kod w `app/` i `static/` przeładowuje się automatycznie.
Aparat w telefonie działa tylko przez `https://` albo na `localhost`.

## Migracje bazy

```bash
docker compose exec app alembic revision --autogenerate -m "opis zmiany"
docker compose exec app alembic upgrade head
```

Kontener uruchomiony z argumentem `migrate` wykonuje tylko migracje (do użycia jako osobne zadanie
przy wdrożeniu); z `RUN_MIGRATIONS=true` wykonuje je przed startem aplikacji.

## Testy i jakość kodu

```bash
pip install -r requirements.txt -r requirements-dev.txt
pre-commit install            # hooki: gitleaks, ruff, porządki w plikach
pytest                        # potrzebna baza skaner_test (tworzy ją docker compose)
```

Testy obejmują m.in.: zapis koszyka po każdym skanie, podział na partie cenowe, równoległe skany,
przyjęcie z reklamacją i nadwyżką, odpis RW, awarię Fakturowni i ponowienie, datę PZ w czasie
polskim, import CSV oraz walidację konfiguracji produkcyjnej.

CI (GitHub Actions) przy każdym pushu i pull requeście uruchamia pre-commit, sprawdza migracje
(upgrade / check / downgrade), testy na PostgreSQL 16 i buduje obraz Dockera.

## Plan rozwoju

1. **Etap 1 (ten kod)** – zakupy, przyjęcia, reklamacje, odpisy, integracja z Fakturownią.
2. **Wdrożenie** – Cloud Run, Cloud SQL, Cloud Scheduler, wydania z tagów `v*` przez GitHub Actions.
3. **Etap 2** – wystawianie na Allegro, Empik i Erli przez Sellasist: podpinanie do istniejących ofert
   po EAN, cena minimalna = najdroższa partia × (1 + narzut, domyślnie 30%) × (1 + VAT),
   wystawienie po „Zatwierdź do sprzedaży”.
4. **Etap 3** – raporty: obrót, zysk netto/brutto, marża, narzut, śledzenie każdej sprzedaży,
   koszty, miesięczny podział zysku.
