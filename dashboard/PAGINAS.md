# Dashboard: alle pagina's

Specificatie om het dashboard visueel te ontwerpen. Per pagina: **doel**, **onderdelen** (van boven naar beneden), **welke data** (tabel/kolom in `data/ufc.duckdb`, of nog te bouwen), **interactie** en **lege of uitzonderingstoestanden**.

Prioriteit: **MVP** = nodig voor de testweekenden van 5 en 12 dec · **Later** = na de test.

Bestaande mockup als vertrekpunt: [`mockup.html`](mockup.html) (dekt pagina 1, 3, 4 en 7 grof).

---

## Overzicht

| # | Pagina | Doel in één zin | Prioriteit |
|---|---|---|---|
| 1 | Overzicht | In 5 seconden zien hoe het model ervoor staat en wat er aankomt | MVP |
| 2 | Events | Alle komende en afgelopen events kiezen | MVP |
| 3 | Event-detail (fight card) | Per event alle voorspellingen, edges en adviezen | MVP |
| 4 | Matchup-detail | Eén gevecht volledig uitgelegd: waarom deze kans | MVP |
| 5 | Vechterprofiel | Alles over één vechter: historie, stijl, vorm | MVP (light) |
| 6 | Bet-log (paper trading) | Elke virtuele weddenschap vastleggen en afrekenen | MVP |
| 7 | Modelprestaties | Is het model goed? Kalibratie, CLV, ROI, segmenten | MVP |
| 8 | Backtest-verkenner | Spelen met drempel/inzet en zien wat het historisch had opgeleverd | Later |
| 9 | Nieuws & kamp | Kwalitatieve vlaggen (blessure, kampwissel, gewicht) invoeren en controleren | Later (MVP: alleen tonen) |
| 10 | Data-status | Is de data compleet en actueel? Gaten en fouten | MVP (simpel) |
| 11 | Instellingen | Bankroll, Kelly-fractie, edge-drempel, bookmakers | MVP (simpel) |

---

## Globale elementen (op elke pagina)

- **Navigatie:** zijbalk (desktop) of tabbalk (mobiel) met pagina 1–11; 8–11 mogen onder een "Meer"-menu.
- **Bovenbalk:** modelversie (bv. `v0.1`), modus-badge **PAPER TRADING** (altijd zichtbaar zolang er geen echt geld in zit), datum laatste data-update, zoekveld (vechter of event).
- **Kleurafspraken** (overal hetzelfde):
  - Vechter A = **blauw**, vechter B = **rood** (zoals rode/blauwe hoek)
  - Value bet / winst = **groen**, verlies = **rood**, waarschuwingsvlag = **oranje**, onzeker of onbevestigd = **grijs**
  - 5-ronde gevecht = **paars** label
- **Getallen:** kansen in % met 1 decimaal, odds standaard **decimaal** (1.60) met Amerikaans (−168) als tooltip, geld in € zonder centen.
- **Voorbeeld- of nepdata** altijd markeren met een gele badge.

---

## 1. Overzicht

**Doel:** in één oogopslag zien hoe het model ervoor staat en wat de volgende actie is.

| Onderdeel | Inhoud | Data |
|---|---|---|
| KPI-rij (6 tegels) | Bankroll · Aantal bets · ROI · Gem. CLV · Log-loss model vs. markt · Brier-score. Elke tegel met een kleine trendpijl t.o.v. vorige maand | `bets` (nog bouwen), `predictions`, `odds` |
| Bankroll-curve | Lijngrafiek over tijd, drawdown-periodes rood gearceerd, schakelaar **Backtest / Live** | `bets` + backtest-resultaat |
| Volgend event | Naam, datum, aftelklok (NL-tijd), # gevechten, # met odds, # value bets, # vlaggen; knop "Naar fight card" | `upcoming_fights`, `data/upcoming/testweekenden.json` |
| Value bets deze week | Compacte lijst: gevecht · pick · odds · edge · inzet. Max 5, "alles bekijken" → pagina 3 | `predictions` |
| Laatste resultaten | Laatste 5 afgerekende bets met ✓/✗ en W/V | `bets` |
| Waarschuwingen | Bv. "Odds 3 dagen oud", "2 gevechten gewijzigd op de kaart", "Stats lopen achter tot 8 aug" | data-status (pag. 10) |

**Leeg:** nog geen bets, dan tegels tonen "–" met de uitleg "na het eerste event".

---

## 2. Events

**Doel:** een event kiezen.

| Onderdeel | Inhoud | Data |
|---|---|---|
| Tabs | **Komend** / **Afgelopen** | `events.status` |
| Eventkaart (komend) | Naam, datum + NL-aanvangstijd, locatie, aantal gevechten, # value bets, status (kaart compleet / onvolledig) | `events`, `upcoming_fights` |
| Eventrij (afgelopen) | Naam, datum, # bets, model-trefkans op dat event, W/V van dat event | `fights`, `predictions`, `bets` |
| Filters | Jaar, type (PPV / Fight Night), alleen events met bets | – |
| Weekend zonder event | Grijze kaart "Geen UFC-event dit weekend" (bv. 28–29 nov) | – |

---

## 3. Event-detail (fight card)

**Doel:** voor één event alle voorspellingen en adviezen. **Belangrijkste werkpagina in fight week.**

| Onderdeel | Inhoud | Data |
|---|---|---|
| Kop | Eventnaam, datum, locatie, aanvang prelims/main card in NL-tijd, kooi (Apex klein/groot), hoogte locatie | `events` (+ `altitude_m`, `cage` later) |
| Samenvatting | # gevechten · # met odds · # value bets · totale geadviseerde inzet · **"voorspellingen vastgezet om [tijd]"** (na vastzetten niet meer wijzigen) | `predictions` |
| Filterchips | Alle · Alleen value bets · Met vlaggen · Main card · Prelims | – |
| Fight-tabel, gegroepeerd per kaartdeel | Per rij: vechter A + record · vechter B + record · klasse · rondes (3/5) · **kansbalk** model (blauw/rood) · markt-kans (zonder marge) · **edge** · advies (BET X @ odds / geen value / wacht op odds) · inzet · vlaggen | `upcoming_fights`, `predictions`, `odds`, `camp_flags` |
| Rij uitklappen (optioneel) | Mini-uitleg: top-3 redenen + methode-kansen; klik → pagina 4 | `predictions.shap` |
| Onbevestigde gevechten | Aparte grijze sectie onderaan | json `kaart: onbevestigd` |
| Na het event | Extra kolommen: uitslag, methode, ronde, ✓/✗, W/V | `fights` |

**Toestanden:** "wacht op odds" (geen odds), "gevecht van kaart" (doorgestreept), "vervanger" (oranje vlag + oude tegenstander in tooltip).

---

## 4. Matchup-detail

**Doel:** begrijpen **waarom** het model deze kans geeft, en zelf kunnen beoordelen of je het ermee eens bent.

| Onderdeel | Inhoud | Data |
|---|---|---|
| Kop (VS-blok) | Foto/initialen, naam, bijnaam, record, Elo + trend · grote kans per vechter · markt-kans en odds · advieslabel (bv. "VALUE: B · edge +5,7% · €16") | `fighters`, `predictions`, `odds` |
| Tale of the tape | Lengte, reach, leeftijd, stance, gewichtsklasse-historie, tijd sinds laatste gevecht, laatste 5 (W/L-bolletjes), UFC-record, record buiten de UFC | `fighters`, `fights` |
| Stijlvergelijking | Gespiegelde balken: sig. strikes landed/absorbed per min, striking-nauwkeurigheid/-verdediging, TD per 15 min, TD-verdediging, controletijd, sub-pogingen, knockdowns. **Point-in-time** (alleen vóór dit gevecht) | `fight_stats_round` → features |
| Stijl-archetype | Label per vechter (bv. "Pressure striker" vs. "Wrestler") + hoe elk historisch presteerde tegen het archetype van de ander | features (later) |
| Cardio | Output per ronde (R1→R3/R5) als kleine lijngrafiek per vechter | `fight_stats_round` |
| Waarom dit oordeel? | Top 5 SHAP-redenen met +/− procentpunt, groen/rood | `predictions.shap` |
| Methode & ronde | Gestapelde balk KO / Sub / Beslissing per vechter, kans op de afstand, eventueel per ronde | methode-model (later) |
| Odds-beweging | Lijn van opening → nu per vechter, met de modelkans als horizontale lijn | `odds` (meerdere `captured`) |
| Kamp & fight week | Lijst vlaggen met type, korte tekst, **bron-link**, datum; status "gecontroleerd" ✓ | `camp_flags` |
| Head-to-head & gemeenschappelijke tegenstanders | Tabel: tegenstander · resultaat A · resultaat B | `fights` |
| Notitie | Vrij tekstveld voor eigen analyse (wordt bij de bet opgeslagen) | `bets.note` |

---

## 5. Vechterprofiel

| Onderdeel | Inhoud | Data |
|---|---|---|
| Kop | Naam, bijnaam, land, gym/team, klasse, stance, leeftijd, lengte, reach, record | `fighters` |
| Rating-grafiek | Elo over de loopbaan, gevechten als punten (groen W / rood L, groot = finish) | ratings (bouwen) |
| Gevechtshistorie | Tabel: datum · tegenstander · uitslag · methode · ronde/tijd · odds vooraf · was het model goed? | `fights`, `odds`, `predictions` |
| Stijlprofiel | Radar of balken t.o.v. het gemiddelde van de gewichtsklasse | features |
| Trend | Belangrijkste stats per gevecht (bv. sig. strikes-verschil) als lijn: wordt hij beter of slechter? | `fight_stats_round` |
| Komend gevecht | Kaartje met link naar pagina 4 | `upcoming_fights` |

---

## 6. Bet-log (paper trading)

**Doel:** eerlijke administratie. Elke voorspelling wordt **vóór** het gevecht vastgezet.

| Onderdeel | Inhoud | Data |
|---|---|---|
| Samenvatting | Open bets · inzet open · afgerekend W/V · ROI · gem. CLV | `bets` |
| Tabel | Datum · event · gevecht · pick · modelkans · odds bij bet · **slotodds** · CLV · inzet · uitslag · W/V · notitie | `bets` |
| Filters | Status (open/afgerekend), event, periode, alleen value bets, modelversie | – |
| Acties | "Voorspellingen vastzetten" (per event), "Slotodds ophalen", "Afrekenen" (na uitslag), export CSV | – |

**Regel:** een vastgezette voorspelling is alleen-lezen; wijzigingen worden een nieuwe regel met reden.

---

## 7. Modelprestaties

**Doel:** is het model goed genoeg, en waar zit de edge (of niet)?

| Onderdeel | Inhoud | Data |
|---|---|---|
| Schakelaar | **Backtest** (walk-forward per jaar) / **Live** (testperiode) · modelversie kiezen of twee vergelijken | `predictions` |
| Kerncijfers | Accuracy · log-loss model vs. markt vs. "altijd favoriet" · Brier · ROI · CLV · max drawdown · # bets + betrouwbaarheidsinterval | berekend |
| Kalibratiegrafiek | Voorspelde kans (buckets 10%) vs. werkelijke winst%, diagonaal = perfect, puntgrootte = aantal | `predictions` + `fights` |
| Per jaar | Lijn of balk: log-loss/ROI per jaar (is het stabiel?) | berekend |
| Per segment | Tabel: favoriet/underdog · gewichtsklasse · mannen/vrouwen · 3/5 rondes · edge-bucket → bets, ROI, CLV, significant ja/nee | berekend |
| Feature-belang | Top 20 features (gemiddelde SHAP) | model |
| Grootste missers | 10 gevechten waar het model het meest zeker was en fout zat (leren!) | `predictions` |

---

## 8. Backtest-verkenner (later)

| Onderdeel | Inhoud |
|---|---|
| Instellingen | Edge-drempel (schuif 0–15%), Kelly-fractie (¼, ½, vast bedrag), max inzet per gevecht/event, periode, segmenten aan/uit, alleen slotodds of openingsodds |
| Resultaat | Bankroll-curve, # bets, ROI, drawdown, verdeling winst per bet |
| Vergelijk | Tot 3 instellingen naast elkaar |

---

## 9. Nieuws & kamp (later; MVP = alleen tonen op pag. 4)

| Onderdeel | Inhoud | Data |
|---|---|---|
| Feed | Nieuwsberichten per vechter in de komende kaarten, nieuwste eerst | `news` (bouwen) |
| AI-voorstel | Per bericht een voorgestelde vlag (kampwissel / blessure / korte termijn / gewicht / privé) + samenvatting | Claude API |
| Validatie | Knoppen **Accepteren / Afwijzen / Aanpassen**; alleen geaccepteerde vlaggen gaan het model in | `camp_flags.status` |
| Weigh-in | Per gevecht: gewicht beide vechters, gemist ja/nee | `camp_flags` |

---

## 10. Data-status

| Onderdeel | Inhoud |
|---|---|
| Bronnen | Per bron: laatste update, # rijen, status (OK / achter / fout). Nu: Kaggle-stats t/m 8 aug 2026, Kaggle-odds t/m 28 mrt 2026, ufcstats-scraper geblokkeerd |
| Gaten | Events zonder stats, gevechten zonder odds, vechters zonder reach/geboortedatum |
| Koppelfouten | Odds die niet aan een gevecht gekoppeld konden worden (nu 340), met naam en datum om handmatig op te lossen |
| Acties | "Import opnieuw draaien", "Komende kaarten verversen" |

---

## 11. Instellingen

- Start-bankroll (nu €1.000), Kelly-fractie (¼), edge-drempel (3%), max % per gevecht (2%) en per event (6%)
- Odds-weergave decimaal/Amerikaans, tijdzone (Europe/Amsterdam)
- Bookmakers die meetellen (alleen KSA-vergunning)
- Modelversie die "live" is

---

## Benodigde extra tabellen (nog te bouwen)

| Tabel | Belangrijkste kolommen |
|---|---|
| `predictions` | fight_id, model_version, created_at, locked_at, prob_a, prob_method_*, shap_top (json), features_hash |
| `bets` | bet_id, fight_id, prediction_id, pick, odds_taken, odds_closing, stake, result, pnl, clv, note |
| `camp_flags` | fight_id, fighter_id, type, text, source_url, status (voorstel/geaccepteerd/afgewezen), created_at |
| `news` | id, fighter_id, url, title, published_at, summary |
| `ratings` | fighter_id, date, elo, glicko_mu, glicko_sigma |

---

## Wat ik van jouw visuele ontwerp nodig heb

1. Per pagina een scherm (desktop; mobiel minimaal voor pag. 1, 3 en 4)
2. Hoe navigatie, kaarten en tabellen eruitzien (dan bouw ik dat als vaste componenten)
3. Kleuren en lettertype (anders gebruik ik de afspraken hierboven)
4. Eventueel wat er weg mag of mist: het ontwerp is leidend, deze lijst is de inhoud

Bouwen gebeurt in **Streamlit** (`dashboard/app.py`): één Python-bestand per pagina in `dashboard/pages/`. Lukt een ontwerp niet in Streamlit (bv. complexe animaties), dan kan het ook als losse webapp, maar Streamlit is het snelst.
