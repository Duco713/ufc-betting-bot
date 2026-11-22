# UFC Betting Bot – Projectplan

> Doel: een model bouwen dat UFC-gevechten voorspelt, en **eerlijk meten** hoe goed het is: niet alleen "hoe vaak klopt de winnaar", maar vooral of het model **beter is dan de bookmakers** (de enige maatstaf die telt bij wedden).

---

## 0. Realistische verwachting vooraf

- De closing odds van bookmakers zijn al erg scherp. Favorieten winnen ongeveer 65–70% van de UFC-gevechten, dus "65% goed voorspeld" is **geen prestatie**, want dat haal je al door simpelweg steeds de favoriet te kiezen.
- De echte vraag is: **vindt het model value?** Dat is het geval wanneer de kans volgens het model hoger is dan de kans die in de odds zit, en dat over honderden weddenschappen winstgevend blijkt.
- Daarom bouwen we eerst een **papieren-handel-systeem** (paper trading) en zetten we geen echt geld in voordat het model zich over minstens één jaar aan events heeft bewezen.
- MMA heeft veel ruis: één klap kan alles beslissen, er zijn weinig gevechten per vechter, last-minute vervangers en gewichtsproblemen. Verwacht dus bescheiden resultaten.

---

## 1. Fases in het kort

| Fase | Wat | Resultaat |
|---|---|---|
| 1 | Data verzamelen (scrapers) | Database met alle UFC-events, gevechten, vechters, statistieken per ronde, odds |
| 2 | Data opschonen en koppelen | Eén schone tabel per gevecht met beide vechters, zonder lekken uit de toekomst |
| 3 | Features bouwen | Honderden kenmerken per matchup (vorm, stijl, fysiek, ervaring …) |
| 4 | Baseline-modellen | Elo-rating + "kies altijd de favoriet" + logistische regressie |
| 5 | Geavanceerd model | Gradient boosting (LightGBM/XGBoost), gekalibreerde kansen |
| 6 | Backtesten tegen odds | ROI, CLV, log-loss tegenover de bookmaker, per periode |
| 7 | Kwalitatieve laag | Nieuws, trainingskamp, blessures, weigh-ins (handmatig + AI-samenvatting) |
| 8 | Live voorspellen + paper trading | Elke fight-week automatisch voorspellingen en "virtuele" weddenschappen |
| 9 | Dashboard / rapportage | Overzicht van voorspellingen, resultaten en modelprestaties |

---

## 2. Databronnen

### 2.1 Gevechten & statistieken (de kern)
| Bron | Wat je krijgt | Opmerking |
|---|---|---|
| **ufcstats.com** | Alle UFC-events sinds 1993, statistieken per gevecht **per ronde**: significant strikes (hoofd/lichaam/benen, afstand/clinch/grond), takedowns + pogingen, submission-pogingen, reversals, controletijd, knockdowns; vechterprofiel (lengte, reach, stance, geboortedatum) | Officiële bron, goed te scrapen, beste startpunt |
| **Sherdog / Tapology** | Volledig record **inclusief niet-UFC-gevechten** (regionale circuits, Bellator, PFL, ONE, LFA, Contender Series), teams/gyms | Belangrijk voor debutanten en vechters met weinig UFC-gevechten. Let op de gebruiksvoorwaarden bij het scrapen; houd het tempo laag en sla data lokaal op |
| **Kaggle UFC-datasets** | Kant-en-klare historische datasets | Handig om snel te starten en je eigen scraper te controleren |
| **ESPN / UFC.com** | Rankings, vechterbio's, sommige extra statistieken | Aanvulling |

### 2.2 Odds (onmisbaar om te kunnen evalueren)
| Bron | Wat |
|---|---|
| **BestFightOdds.com** | Historische odds per bookmaker, inclusief **openings- en slotodds** en de beweging ertussen |
| **The Odds API** (betaald/gratis tier) | Actuele odds via een API voor live gebruik |
| Odds voor props | Methode van winst (KO/sub/beslissing), ronde, over/under rondes |

> Odds-beweging is zelf ook een feature: als de lijn zwaar beweegt, weet de markt vaak iets (blessure, slechte cut).

### 2.3 Kwalitatieve en actuele informatie (fight week)
| Bron | Wat |
|---|---|
| MMA Fighting, MMA Junkie, MMA Mania, Bloody Elbow, Sherdog News | Nieuws, blessures, vervangers, kampwissels |
| Ariel Helwani / The MMA Hour, persconferenties, media days | Uitspraken van vechters en coaches |
| Instagram / YouTube / X van vechters en gyms | Trainingsbeelden, vlogs over het kamp (subjectief!) |
| Reddit r/MMA en r/MMAbetting | Geruchten, sentiment (met korrel zout) |
| Officiële weigh-in-resultaten | Gewicht gemist, moeite met de cut |
| Atletiekcommissies (NSAC, enz.) | Schorsingen, medische schorsingen, dopingzaken (USADA tot 2023, daarna Drug Free Sport) |

**Eerlijk over het trainingskamp:** daar is weinig harde, objectieve data over. Wat wel te vinden is:
- Waar en met wie iemand traint (gym, nieuwe coach, kampwissel)
- Duur van het kamp (normaal kamp of vervanger op korte termijn)
- Gemelde blessures tijdens het kamp
- Uitspraken over de gewichtscut, ziekte, privéproblemen
- Sparringpartners (bijv. "traint met een wereldkampioen worstelen")

Dit leggen we vast als **gestructureerde vlaggen** (zie §3.7), zodat het meetbaar wordt in plaats van een onderbuikgevoel.

---

## 3. Alle factoren (features)

Elke feature wordt berekend **met alleen informatie die vóór het gevecht bekend was**. Dat is cruciaal (zie §5). Voor de meeste features maken we ook een **verschil-feature** (vechter A min vechter B), omdat het model vooral de matchup moet begrijpen.

### 3.1 Fysiek
- Lengte, reach, reach-verschil
- Leeftijd op de vechtdag (en leeftijd² — prestaties dalen sterk na ~33–35, in de lichtere klassen eerder)
- Stance (orthodox / southpaw / switch) en de combinatie (southpaw tegen orthodox)
- Gewichtsklasse; **verandering van klasse** (omhoog of omlaag gaan)
- Gemiste gewichten in het verleden (aantal, hoe recent)

### 3.2 Record & ervaring
- Totaal record (W-L-D), UFC-record, record buiten de UFC
- Aantal gevechten in de UFC, totale kooitijd (minuten)
- Ervaring in 5-ronde gevechten / main events / titelgevechten
- Kwaliteit van tegenstanders (gemiddelde Elo van verslagen en verloren tegenstanders)
- Winst/verlies-methodes: % KO, % submission, % beslissing, en hetzelfde voor verliezen
- Is er ooit KO gegaan? Hoe vaak? Hoe recent? (afbrokkelende kin)

### 3.3 Vorm & momentum
- Resultaat laatste 1, 3 en 5 gevechten
- Win- of verliesreeks
- **Rating-trend** (Elo/Glicko nu tegenover één jaar geleden)
- Tijd sinds het laatste gevecht (ringroest bij >12–18 maanden, of juist te snel weer vechten na een KO-verlies)
- Activiteit: aantal gevechten in de afgelopen 2 jaar
- Laatste gevecht verloren door KO (bekende negatieve factor)
- Gewogen statistieken: recente gevechten tellen zwaarder (exponentieel verval)

### 3.4 Vechtstijl (per minuut, op basis van ufcstats)
**Striking**
- Significant strikes landed per minuut (SLpM) en absorbed per minuut (SApM)
- Striking-nauwkeurigheid en verdediging (%)
- Verdeling hoofd / lichaam / benen
- Verdeling afstand / clinch / grond
- Knockdowns per 15 min, knockdowns gekregen
- Striking-differentiaal (landed min absorbed)

**Grappling**
- Takedowns per 15 min, takedown-nauwkeurigheid
- Takedown-verdediging (%)
- Controletijd per gevecht / per minuut, en controletijd van de tegenstander
- Submission-pogingen per 15 min
- Reversals, opstaan na een takedown

**Stijlprofiel (afgeleid)**
- Clustering van vechters in archetypes: *pressure striker, counter striker, kickboxer, wrestler, BJJ-specialist, all-rounder*
- **Stijlmatchup-features**: bijv. de takedown-aanval van A tegenover de takedown-verdediging van B, het striking-volume van A tegenover de verdediging van B
- Historische prestaties van een vechter **tegen een bepaald archetype** (bijv. "verliest vaak van wrestlers")

### 3.5 Cardio & duurvermogen
- Statistieken per ronde: zakt de output in ronde 3 (of 4–5)?
- Prestaties in late rondes tegenover vroege rondes
- Aantal gevechten dat tot de beslissing ging
- Slechte cardio gecombineerd met een tegenstander die op druk vecht → feature

### 3.6 Omstandigheden van het gevecht
- Aantal rondes (3 of 5) / titelgevecht
- **Korte-termijnvervanger** (minder dan 2–3 weken voorbereiding)
- Locatie: thuisvoordeel, reisafstand, tijdzone
- **Hoogte** (bijv. Mexico-Stad, Salt Lake City), want dat beïnvloedt de cardio
- Kooigrootte (de kleine kooi in de UFC Apex tegenover de grote octagon), wat in het voordeel van drukvechters en worstelaars werkt
- Plaats op de kaart (main card / prelims), of het een PPV of Fight Night is
- Scheidsrechter en jury's (sommige jury's geven bijv. vaker punten voor controle; geavanceerd)

### 3.7 Trainingskamp & fight week (kwalitatieve laag)
Gestructureerde vlaggen, in te vullen per gevecht (handmatig of met AI-hulp uit nieuwsartikelen):
- `camp_change` – nieuwe gym/hoofdcoach sinds het vorige gevecht
- `camp_gym_tier` – niveau van de gym (bijv. American Kickboxing Academy, City Kickboxing, Jackson-Wink …)
- `injury_reported` – blessure gemeld tijdens het kamp
- `short_notice` – aantal dagen voorbereiding
- `missed_weight` / `weight_cut_issues` – gewicht gemist of zichtbaar zware cut
- `personal_issues` – gemelde privéproblemen
- `layoff_reason` – reden van een lange pauze (blessure, schorsing, contract)
- `sentiment_score` – AI-samenvatting van het nieuws (positief/negatief), alleen als zwak signaal

> **Belangrijk:** deze laag is lastig te backtesten, omdat historisch nieuws moeilijk terug te vinden is. Plan: eerst het model bouwen op harde data; de kwalitatieve laag pas toevoegen nadat we die een paar maanden live hebben verzameld, en daarna meten of die echt waarde toevoegt.

### 3.8 Marktinformatie
- Geïmpliceerde kans uit de openings- en slotodds (gecorrigeerd voor de marge van de bookmaker / vig)
- Lijnbeweging (opening → nu)
- Verschil tussen bookmakers
- Gebruik: (a) als **benchmark**, (b) eventueel als feature in een apart "markt + model"-model

### 3.9 Ratingsystemen
- **Elo** per vechter (met een K-factor die afhangt van de methode: KO/sub telt zwaarder dan een split decision)
- **Glicko-2** (houdt rekening met onzekerheid: weinig gevechten = grote onzekerheid)
- Aparte ratings voor striking en grappling (bijv. op basis van de statistieken per gevecht)
- Startrating voor debutanten op basis van hun record buiten de UFC en de kwaliteit van die organisatie

---

## 4. Modellen

1. **Baseline 1 – altijd de favoriet**: de minimale lat die het model moet halen.
2. **Baseline 2 – geïmpliceerde kans van de bookmaker**: de echte lat (log-loss van de markt).
3. **Baseline 3 – alleen Elo/Glicko**.
4. **Logistische regressie** met de belangrijkste verschil-features (makkelijk te interpreteren).
5. **Gradient boosting (LightGBM / XGBoost)** met alle features.
6. **Kalibratie** (Platt / isotonic), zodat 60% ook echt 60% betekent; dit is essentieel voor het bepalen van value.
7. Later: **aparte modellen voor de methode** (KO / sub / beslissing) en "gaat het gevecht de afstand" (over/under), omdat daar de markt vaak minder scherp is dan bij de winnaar.
8. **Symmetrie**: elk gevecht wordt twee keer in de data gezet (A tegen B en B tegen A) en de voorspellingen worden gemiddeld, zodat de volgorde van de vechters niet uitmaakt.

Uitleg per voorspelling met **SHAP-waarden** ("model kiest A vooral vanwege takedown-verschil en reach").

---

## 5. Valkuilen (heel belangrijk)

- **Data leakage**: gebruik nooit statistieken die het gevecht zelf of latere gevechten bevatten. Ufcstats toont *loopbaangemiddelden van nu*; die moeten we zelf opnieuw berekenen **per datum**, alleen uit eerdere gevechten.
- **Willekeurige train/test-split is verboden**: altijd **op tijd splitsen** (walk-forward: trainen t/m 2019, testen op 2020; trainen t/m 2020, testen op 2021, enz.).
- **Weinig data per vechter**: gebruik "shrinkage" (debutanten naar het gemiddelde van hun klasse trekken).
- **Overfitting**: honderden features en ~7.000–8.000 UFC-gevechten → strenge validatie, beperk de features.
- **De sport verandert**: vroeger UFC (vóór ~2005) is wezenlijk anders; geef oude data minder gewicht of laat die weg.
- **Survivorship**: vechters die eruit gegooid zijn verdwijnen uit de data; houd daar rekening mee.
- **Gelijkspel / no contest**: apart behandelen (meestal uit de training laten).
- **Odds-tijdstip**: backtesten op odds die je in werkelijkheid ook had kunnen krijgen (niet altijd de beste slotodds).

---

## 6. Evaluatie: hoe goed is de bot?

| Maatstaf | Wat het zegt |
|---|---|
| **Accuracy** | Hoe vaak de winnaar goed is (zegt weinig op zichzelf) |
| **Log-loss / Brier-score** | Hoe goed de **kansen** zijn; vergelijken met de log-loss van de bookmaker |
| **Kalibratiegrafiek** | Kloppen de kansen? (van alle gevechten met 70% wint ~70%) |
| **ROI bij flat betting** | Winst per ingezette euro als je steeds 1 eenheid inzet op value bets |
| **CLV (closing line value)** | Krijg je betere odds dan de slotodds? **De beste voorspeller van winst op lange termijn** |
| **Max drawdown** | Grootste verliesreeks: kun je dat aan? |
| **Resultaten per segment** | Per gewichtsklasse, favoriet/underdog, mannen/vrouwen, 3/5 rondes: waar zit de edge? |
| **Statistische significantie** | Bootstrap / aantal bets nodig: 100 bets zegt nog bijna niets |

**Inzetstrategie (alleen op papier)**
- Bet alleen als `modelkans × decimale odds − 1 > drempel` (bijv. > 5% edge)
- Inzet volgens een **fractionele Kelly** (¼ Kelly), met een maximum per gevecht en per event
- Simulatie van de bankroll over de hele testperiode

---

## 7. Technische opzet

**Taal:** Python 3.11+

**Libraries**
- Scrapen: `requests`, `beautifulsoup4`, `httpx`, eventueel `playwright` voor JavaScript-pagina's
- Data: `pandas` / `polars`, `duckdb` of `SQLite` als database
- Modellen: `scikit-learn`, `lightgbm`, `xgboost`, `shap`
- Ratings: eigen Elo/Glicko-implementatie (of `glicko2`)
- Visualisatie / dashboard: `matplotlib`/`plotly`, **Streamlit** voor het dashboard
- Planning: een cronjob of GitHub Actions voor automatisch updaten
- AI-laag voor nieuws: Claude API om artikelen samen te vatten in gestructureerde vlaggen (§3.7)

**Mappenstructuur**
```
ufc-betting-bot/
├── PLAN.md
├── README.md
├── requirements.txt
├── config.yaml              # drempels, Kelly-fractie, API-keys via .env
├── .env                     # API-keys (NIET committen)
├── data/
│   ├── raw/                 # ruwe HTML/JSON van scrapers
│   ├── processed/           # schone tabellen
│   └── ufc.duckdb           # centrale database
├── src/
│   ├── scrapers/
│   │   ├── ufcstats.py      # events, gevechten, statistieken per ronde, vechters
│   │   ├── tapology.py      # records buiten de UFC, gyms
│   │   ├── odds.py          # historische + live odds
│   │   └── news.py          # nieuws in de fight week
│   ├── cleaning/            # koppelen van namen, dubbele vechters, datatypes
│   ├── features/
│   │   ├── physical.py
│   │   ├── form.py
│   │   ├── style.py
│   │   ├── ratings.py       # Elo / Glicko
│   │   ├── context.py       # locatie, hoogte, korte termijn, kooigrootte
│   │   └── camp.py          # kwalitatieve vlaggen
│   ├── models/
│   │   ├── baselines.py
│   │   ├── train.py
│   │   └── calibrate.py
│   ├── backtest/
│   │   ├── walk_forward.py
│   │   ├── betting.py       # value, Kelly, bankroll-simulatie
│   │   └── metrics.py       # log-loss, ROI, CLV
│   └── predict/
│       └── upcoming.py      # voorspellingen voor het volgende event
├── notebooks/               # verkenning en analyses
├── dashboard/
│   └── app.py               # Streamlit
└── tests/
```

**Database (hoofdtabellen)**
- `fighters` (id, naam, geboortedatum, lengte, reach, stance, gym …)
- `events` (id, datum, locatie, hoogte, kooi)
- `fights` (id, event, vechter A/B, klasse, rondes, winnaar, methode, ronde, tijd, scheidsrechter)
- `fight_stats_round` (gevecht, vechter, ronde, alle statistieken)
- `odds` (gevecht, bookmaker, tijdstip, odds A/B)
- `camp_flags` (gevecht, vechter, vlaggen, bron-URL)
- `predictions` (gevecht, modelversie, kans, aanbevolen inzet, resultaat)

---

## 8. Stappenplan (volgorde van bouwen)

**Week 1–2: data**
- [ ] Scraper ufcstats: alle events → gevechten → statistieken per ronde → vechters
- [ ] Opslaan in DuckDB/SQLite, ruwe HTML cachen (niet opnieuw scrapen)
- [ ] Historische odds verzamelen en koppelen aan gevechten (namen matchen!)

**Week 3: features & baselines**
- [ ] "Point-in-time"-statistieken (alleen uit eerdere gevechten)
- [ ] Elo / Glicko-ratings
- [ ] Baselines + eerste logistische regressie
- [ ] Walk-forward backtest-framework

**Week 4–5: model verbeteren**
- [ ] Alle features uit §3.1–3.6 en 3.9
- [ ] LightGBM + kalibratie + SHAP
- [ ] Vergelijking met de bookmaker: log-loss, ROI, CLV per jaar

**Week 6: live**
- [ ] Script dat elke week de komende kaart ophaalt en voorspelt
- [ ] Paper-trading-log (virtuele inzetten opslaan en later afrekenen)
- [ ] Nieuws-scraper + camp-vlaggen (§3.7) gaan verzamelen

**Week 7+: dashboard & uitbreiding**
- [ ] Streamlit-dashboard: komende gevechten, kansen, edge, uitleg, historische prestaties
- [ ] Modellen voor methode/ronde (props)
- [ ] Na ~3–6 maanden: evalueren of de kwalitatieve laag iets toevoegt

---

## 8b. Testperiode: komende 3 weekenden (stand 22 nov 2026)

Volledige kaarten in [`data/upcoming/testweekenden.json`](data/upcoming/testweekenden.json).

| Weekend | Event | Gevechten |
|---|---|---|
| 28–29 nov | **Geen UFC-event** (Thanksgiving) | – |
| za 5 dec | UFC Fight Night: Adesanya vs. Magomedov – Riyadh (main card 19:00 NL) | 12 |
| za 12 dec | UFC 335: Oliveira vs. Lopes – Las Vegas (main card zo 03:00 NL) | 7 bevestigd (+ Pyfer vs. Nickal onbevestigd) |

Testprotocol:
1. Voorspellingen **vóór** het event vastleggen (tijdstempel + modelversie), daarna niet meer wijzigen.
2. Bij elke voorspelling de odds op dat moment opslaan, en na afloop de slotodds (voor CLV).
3. Alleen virtuele inzetten (¼ Kelly, max. 2% van de bankroll per gevecht).
4. ~20 gevechten is **veel te weinig** om iets te bewijzen: dit is een test van de pijplijn en het dashboard, niet van de winstgevendheid.

---

## 8c. Dashboard: wat erin komt

Gebaseerd op wat serieuze (algo-)bettors bijhouden: ROI alleen is te ruisgevoelig, dus **CLV, kalibratie (Brier/log-loss) en drawdown** staan centraal.

**Tab 1 – Overzicht**
- KPI's: aantal bets, trefkans, ROI, gemiddelde CLV, log-loss model vs. markt, Brier-score, bankroll en max. drawdown
- Bankroll-curve (virtueel) met de drawdown erin
- Volgend event met afteltimer + aantal value bets

**Tab 2 – Komende events**
- Per event een tabel: vechters, model-kans, markt-kans (zonder marge), **edge**, advies (bet / geen bet), inzet (¼ Kelly), betrouwbaarheid
- Waarschuwingsvlaggen: korte termijn, gewicht gemist, kampwissel, blessure, lijnbeweging
- Filter op "alleen value bets"

**Tab 3 – Matchup-detail**
- Tale of the tape (lengte, reach, leeftijd, stance, record, Elo)
- Stijlvergelijking (striking/grappling/cardio-balken)
- Waarom kiest het model dit? (top-SHAP-redenen)
- Kans op methode (KO / submission / beslissing) en ronde
- Odds-beweging sinds opening, laatste 5 gevechten, kampnotities met bron

**Tab 4 – Prestaties**
- Kalibratiegrafiek (voorspeld vs. werkelijk per kansbucket)
- Resultaten per segment (favoriet/underdog, gewichtsklasse, 3/5 rondes)
- Bet-log: elke voorspelling met odds, slotodds, CLV, uitkomst en winst/verlies

Mockup: [`dashboard/mockup.html`](dashboard/mockup.html). Het echte dashboard wordt in Streamlit gebouwd (`dashboard/app.py`).

---

## 9. Juridisch & verantwoord

- **Scrapen**: respecteer `robots.txt` en de gebruiksvoorwaarden, scrape langzaam, cache alles, en gebruik de data alleen voor jezelf.
- **Wedden in Nederland**: alleen legaal bij aanbieders met een vergunning van de **Kansspelautoriteit (KSA)**. Minimumleeftijd 18 jaar (online is 24 jaar de grens voor bepaalde extra beschermingsregels).
- **De bot plaatst zelf nooit weddenschappen**: hij geeft alleen voorspellingen en adviezen. Bookmakers verbieden geautomatiseerd wedden vaak, en winnende spelers worden vaak beperkt.
- Zet vooraf een vast budget en verwacht geen inkomen. Hulp nodig? **Loket Kansspel** (loketkansspel.nl) / stoppen via **Cruks**.

---

## 10. Succescriteria

Het project is geslaagd als:
1. De data en features volledig zijn en **geen leakage** bevatten (tests).
2. Het model een **lagere log-loss** heeft dan "altijd de favoriet" en dicht bij de bookmaker komt.
3. In de walk-forward-backtest én in minimaal 6 maanden paper trading een **positieve CLV** en ROI zichtbaar zijn, over genoeg bets (300+) om er iets over te kunnen zeggen.

Haalt het model punt 3 niet, dan is het nog steeds een waardevol analyse-tool voor fight-previews, maar dan **niet** om echt geld mee in te zetten.
