# UFC Betting Bot (FightModel)

Persoonlijk onderzoeksproject: een statistisch model dat MMA-gevechten voorspelt en met **virtuele inzetten** (paper trading) test of het beter is dan de bookmakers. Geen gokadvies.

**Dashboard (live):** https://duco713.github.io/ufc-betting-bot/

## Snel overzicht

| Stap | Commando | Wat |
|---|---|---|
| 1 | `.venv/bin/python -m src.importers.kaggle --download` | Historische data (gevechten, stats per ronde, odds) in `data/ufc.duckdb` |
| 2 | `.venv/bin/python -m src.models.train` | Point-in-time features + Elo, walk-forward backtest 2016-2026, eindmodel → `reports/backtest.md` |
| 2b | `.venv/bin/python -m src.scrapers.bestfightodds` | Actuele odds per bookmaker (snapshot met tijdstempel → `odds_snapshots`); draai dit een paar keer per week voor lijnbeweging |
| ⏱ | `scripts/refresh_odds.sh` | **Automatisch verversen:** stap 2b + 3 + 4 + push in één keer. Draait elke dag om 09:00 en 21:00 als geplande taak in de Claude-app (macOS blokkeert launchd/cron op de Bureaublad-map) |
| 🔒 | `.venv/bin/python -m src.predict.upcoming --auto-lock` | Op de vechtdag (09:00-run) worden voorspellingen en virtuele bets **vastgezet** tegen de Unibet-prijs; daarna worden ze nooit meer overschreven. Max. 2% per bet en 6% per event |
| ✅ | `.venv/bin/python -m src.settle` | Na het event: uitslagen uit `data/results/uitslagen.json` → bets afrekenen, slotodds (laatste meting vóór aanvang) en **CLV**, modelscore vs. markt. Zichtbaar op de Bet-log-pagina |
| 3 | `.venv/bin/python -m src.predict.upcoming` | Voorspellingen voor `data/upcoming/testweekenden.json` (`--lock` om vast te zetten) |
| 4 | `.venv/bin/python -m src.export.site_data` | Data voor het dashboard → `docs/data/*.json` |
| 5 | `git add docs && git commit -m "Data update" && git push` | Dashboard bijwerken (GitHub Pages serveert `docs/`) |

Lokaal bekijken: `python3 -m http.server 8766 --directory docs` en open http://localhost:8766.

## Huidige stand (22 nov 2026)

- Model zonder odds: log-loss 0,650 vs. markt 0,604: **de markt is duidelijk beter**.
- Model gecombineerd met de markt: 0,6042 vs. 0,6044: nauwelijks beter; backtest-ROI ≈ 0% (−0,7%).
- Conclusie: nog geen bewezen edge. De testweekenden (5 en 12 dec) testen vooral de pijplijn.

Zie [PLAN.md](PLAN.md) voor het volledige plan en [reports/backtest.md](reports/backtest.md) voor alle cijfers.

## Projectstructuur

```
src/importers/kaggle.py   Kaggle-datasets -> DuckDB
src/scrapers/ufcstats.py  eigen scraper (ufcstats.com toont nu een bot-controle)
src/features/build.py     point-in-time features + Elo
src/models/train.py       walk-forward backtest, markt+model-stacking, eindmodel
src/predict/upcoming.py   voorspellingen komende kaarten
src/export/site_data.py   JSON voor het dashboard
docs/                     statisch dashboard (GitHub Pages)
```

**Bronnen & licenties:** Kaggle `neelagiriaditya/ufc-datasets-1994-2025` (CC0), Kaggle `mdabbert/ultimate-ufc-dataset` (CC BY 4.0), kaarten van ufcalendar.com, actuele odds van BestFightOdds.com (robots.txt staat dit toe; 1 request per run). Niet gelieerd aan de UFC.

**Verantwoord:** alleen virtuele inzetten. Wedden in Nederland alleen bij aanbieders met een KSA-vergunning, 18+. Hulp: [loketkansspel.nl](https://www.loketkansspel.nl).

## Fase 1: data uit Kaggle (huidige bron)

ufcstats.com toont op dit moment een bot-controle ("Checking your browser"), waardoor de scraper niets binnenkrijgt. Daarom laden we de historie uit twee publieke Kaggle-datasets (geen account nodig):

| Dataset | Licentie | Inhoud | Tot |
|---|---|---|---|
| `neelagiriaditya/ufc-datasets-1994-2025` | CC0 | events, vechters, gevechten, stats per ronde (gescraped van ufcstats, zelfde ID's) | 8 aug 2026 |
| `mdabbert/ultimate-ufc-dataset` | CC BY 4.0 | moneyline- en methode-odds | 28 mrt 2026 |

```bash
# downloaden + importeren in data/ufc.duckdb (ca. 30 s, opnieuw draaien is veilig)
.venv/bin/python -m src.importers.kaggle --download
```

Resultaat (22-11-2026): 1.259 events, 11.441 gevechten, 4.581 vechters, 72.484 stat-rijen (per ronde + ronde 0 = totaal), 6.837 gevechten met odds (95% gekoppeld). Favorieten winnen 66,7%: klopt met wat bekend is.

**Gaten:** stats ontbreken van 8 aug t/m nu (~14 events), odds van eind mrt t/m nu. Die vullen we aan met de scraper (zodra ufcstats weer bereikbaar is) of een odds-API. De loopbaangemiddelden uit de Kaggle-bestanden zijn bewust niet geïmporteerd (leakage).

## Fase 1b: eigen scraper (ufcstats.com)

### Installatie
```bash
cd ufc-betting-bot
python3 -m venv .venv            # Python 3.11+
source .venv/bin/activate
pip install -r requirements.txt
```

### Scraper draaien
```bash
# Snelle test: de 3 meest recente afgeronde events + komende kaarten
python -m src.scrapers.ufcstats --limit-events 3 --upcoming

# Vechterprofielen (lengte, reach, stance, geboortedatum) voor alle bekende vechters
python -m src.scrapers.ufcstats --fighters

# Volledige historie (~770 events, ~8.700 gevechten, ~4.500 vechters).
# Duurt ca. 4-5 uur bij 1 request/seconde. Afbreken mag: een rerun gaat via de cache verder.
python -m src.scrapers.ufcstats --all --upcoming --fighters

# Alleen opnieuw parsen uit de cache, zonder netwerk
python -m src.scrapers.ufcstats --all --offline
```

Opties: `--delay 1.5` (trager scrapen), `--db pad/naar.duckdb`.

### Wat er gebeurt
- Ruwe HTML wordt gecachet in `data/raw/ufcstats/` (bestandsnaam = sha1 van de URL, overzicht in `_index.tsv`).
  Afgeronde event- en fight-pagina's worden nooit opnieuw gedownload; lijsten, komende events en vechterprofielen
  worden na een paar uur/dagen ververst.
- Ongeveer 1 request per seconde, generieke User-Agent, retries met backoff bij fouten/429/5xx.
- Gaat de site een bot-check ("Checking your browser") tonen, dan stopt de scraper met een melding. Die check
  wordt bewust **niet** omzeild.
- Data komt in `data/ufc.duckdb` (upserts, dus reruns zijn idempotent):

| Tabel | Inhoud |
|---|---|
| `fighters` | id, naam, bijnaam, lengte/reach (inch + cm), gewicht, stance, geboortedatum, huidig record |
| `events` | id, naam, datum, locatie, status (`completed`/`upcoming`) |
| `fights` | id, event, vechter A/B, uitslag, winnaar, klasse, titelgevecht, methode, ronde, tijd, rondeformat, scheidsrechter, bonussen, plek op de kaart |
| `fight_stats_round` | per gevecht × vechter × ronde (ronde 0 = totaal): KD, sig/total strikes, takedowns, sub-pogingen, reversals, controletijd, hoofd/lichaam/benen, afstand/clinch/grond (telkens landed + attempted) |
| `odds_snapshots` | per meting × gevecht × bookmaker: moneyline beide vechters (BestFightOdds). Consensus = mediaan van echte bookmakers; alleen Polymarket/Kalshi = indicatief, geen virtuele inzet |
| `upcoming_fights` | komende gevechten (wordt bij elke `--upcoming` volledig ververst) |

Let op: `fighters.record_*` is het record van **nu** (niet point-in-time); gebruik dat niet als feature (PLAN.md §5).

### Tests
```bash
python -m pytest -q
```
