# Backtest v0.1-20261122

Walk-forward 2016-2026: per jaar getraind op alle gevechten vanaf 2008-01-01 tot 1 januari van dat jaar.
Gekozen model voor voorspellingen: **mm** (laagste log-loss op gevechten met odds).

## Alle gevechten (ook zonder odds)
| model    |    n |   accuracy |   log_loss |   brier |
|:---------|-----:|-----------:|-----------:|--------:|
| elo_prob | 5772 |     0.5502 |     0.6848 |  0.2459 |
| logreg   | 5772 |     0.6183 |     0.6524 |  0.2305 |
| gbm      | 5772 |     0.6143 |     0.6517 |  0.2302 |
| blend    | 5772 |     0.6187 |     0.6497 |  0.2293 |

## Gevechten met odds: model vs. markt (mkt_p = slotodds zonder marge)
| model    |    n |   accuracy |   log_loss |   brier |
|:---------|-----:|-----------:|-----------:|--------:|
| elo_prob | 4056 |     0.5528 |     0.6872 |  0.2470 |
| logreg   | 4056 |     0.6146 |     0.6544 |  0.2313 |
| gbm      | 4056 |     0.6171 |     0.6507 |  0.2296 |
| blend    | 4056 |     0.6171 |     0.6500 |  0.2293 |
| mm       | 4056 |     0.6733 |     0.6042 |  0.2088 |
| mkt_p    | 4056 |     0.6677 |     0.6044 |  0.2087 |

Lager is beter voor log-loss en Brier. **Het model moet onder `mkt_p` komen om echt value te vinden.**

## Log-loss per jaar (gevechten met odds)
|      jaar |        n |   ll_blend |   ll_mm |   ll_mkt_p |
|----------:|---------:|-----------:|--------:|-----------:|
| 2017.0000 | 410.0000 |     0.6591 |  0.6148 |     0.6134 |
| 2018.0000 | 436.0000 |     0.6522 |  0.6020 |     0.6010 |
| 2019.0000 | 457.0000 |     0.6826 |  0.6378 |     0.6296 |
| 2020.0000 | 408.0000 |     0.6567 |  0.6137 |     0.6153 |
| 2021.0000 | 468.0000 |     0.6588 |  0.6282 |     0.6288 |
| 2022.0000 | 475.0000 |     0.6521 |  0.6040 |     0.6055 |
| 2023.0000 | 413.0000 |     0.6431 |  0.5828 |     0.5857 |
| 2024.0000 | 378.0000 |     0.6423 |  0.5883 |     0.5900 |
| 2025.0000 | 498.0000 |     0.6171 |  0.5863 |     0.5896 |
| 2026.0000 | 113.0000 |     0.6026 |  0.5142 |     0.5212 |

## Bet-simulatie op slotodds (edge ≥ 3%, 0.25 Kelly, max 2% per bet, start €1.000)
| model   |   bets |    hit |   roi_kelly |   roi_flat |   bankroll |   max_dd |
|:--------|-------:|-------:|------------:|-----------:|-----------:|---------:|
| blend   |   3358 | 0.3737 |     -0.1061 |    -0.0964 |     0.6949 |   0.9993 |
| mm      |   1277 | 0.6437 |     -0.0070 |     0.0076 |   894.4359 |   0.5626 |

Let op: gebet op slotodds uit de data; in het echt krijg je eerdere odds (vaak slechter of beter). Geen CLV mogelijk zonder openingsodds.

## Kalibratie (mm)
|   bucket |         n |   predicted |   actual |
|---------:|----------:|------------:|---------:|
|   0.0000 |   60.0000 |      0.0831 |   0.1000 |
|   0.1000 |  476.0000 |      0.1589 |   0.1261 |
|   0.2000 | 1008.0000 |      0.2547 |   0.2609 |
|   0.3000 | 1286.0000 |      0.3510 |   0.3663 |
|   0.4000 | 1226.0000 |      0.4481 |   0.4282 |
|   0.5000 | 1226.0000 |      0.5519 |   0.5718 |
|   0.6000 | 1286.0000 |      0.6490 |   0.6337 |
|   0.7000 | 1008.0000 |      0.7453 |   0.7391 |
|   0.8000 |  476.0000 |      0.8411 |   0.8739 |
|   0.9000 |   60.0000 |      0.9169 |   0.9000 |
