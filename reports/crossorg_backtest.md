# Backtest: leren van andere organisaties

Vooraf vastgelegd (27-11-2026): een variant vervangt het huidige model alleen als de log-loss over alle UFC-gevechten 2018-2026 lager is **én** de ROI van de model+markt-bets niet lager is.

Data: 11,482 gevechten buiten de UFC (Wikipedia: Bellator, PFL, WSOF, ONE, Strikeforce, Rizin, DREAM, ACA, M-1, Cage Warriors, LFA, Brave, Road FC, Oktagon, Jungle Fight, UAE Warriors), 9,710 vechters, waarvan 1,859 gekoppeld aan UFC-vechters. Van de UFC-debutanten sinds 2018 hebben we bij 463 van 1437 (32%) minstens één eerder gevecht gevonden.

## Voorspellen (alle UFC-gevechten 2018 - nov 2026, model zonder odds)

| Model | Gevechten | Log-loss | Goed | Log-loss debutanten | Goed debutanten | Log-loss 1-2 UFC-gevechten |
|---|---|---|---|---|---|---|
| Huidig model (alleen UFC) | 4995 | 0.6525 | 61.7% | 0.6629 (1014) | 60.2% | 0.6559 |
| B: UFC + andere organisaties | 4995 | 0.6547 | 61.4% | 0.6700 (1014) | 58.8% | 0.6558 |
| A: zonder UFC-kennis tot 2018 | 4995 | 0.6626 | 59.9% | 0.6739 (1316) | 57.4% | 0.6683 |

Lager is beter voor log-loss.

## Log-loss per jaar

| Jaar | Huidig model (alleen UFC) | B: UFC + andere organisaties | A: zonder UFC-kennis tot 2018 |
|---|---|---|---|
| 2018 | 0.6541 | 0.6554 | 0.6954 |
| 2019 | 0.6821 | 0.6796 | 0.7140 |
| 2020 | 0.6555 | 0.6571 | 0.6661 |
| 2021 | 0.6624 | 0.6658 | 0.6664 |
| 2022 | 0.6519 | 0.6526 | 0.6579 |
| 2023 | 0.6521 | 0.6508 | 0.6522 |
| 2024 | 0.6403 | 0.6484 | 0.6436 |
| 2025 | 0.6325 | 0.6365 | 0.6437 |
| 2026 | 0.6442 | 0.6480 | 0.6284 |

## Met odds: model + markt en bets (2019 - mrt 2026, slotodds, edge ≥ 3%, ¼ Kelly, max 2%)

| Model | Gevechten | Log-loss model+markt | Log-loss markt | Debutanten: model+markt / markt | Bets | Geraakt | ROI | Eindstand | Max. daling |
|---|---|---|---|---|---|---|---|---|---|
| Huidig model (alleen UFC) | 3210 | 0.6027 | 0.6038 | 0.5463 / 0.5515 | 651 | 76.2% | -1.7% | €910 | 21% |
| B: UFC + andere organisaties | 3210 | 0.6026 | 0.6038 | 0.5449 / 0.5515 | 689 | 75.5% | -1.4% | €924 | 17% |
| A: zonder UFC-kennis tot 2018 | 3210 | 0.6024 | 0.6038 | 0.5702 / 0.5736 | 667 | 74.7% | -1.7% | €910 | 17% |

## Oordeel (volgens de vooraf vastgelegde regel)

- **B: UFC + andere organisaties**: log-loss niet lager ✗ (0.6547 vs 0.6525), ROI niet lager ✓ (-1.4% vs -1.7%) → **niet overnemen**
- **A: zonder UFC-kennis tot 2018**: log-loss niet lager ✗ (0.6626 vs 0.6525), ROI niet lager ✓ (-1.7% vs -1.7%) → **niet overnemen**
