# Experiment: recente data, minder data, minder kenmerken

Selectie = 2018-2023 (hierop kiezen), controle = 2024-2026 (pas daarna kijken). Log-loss: lager is beter. Bets: model+markt, slotodds, edge ≥ 3%, ¼ Kelly, max 2% (odds t/m mrt 2026).

| Variant | Log-loss selectie | Log-loss controle | Goed controle | Model+markt vs markt (controle) | Bets / ROI selectie | Bets / ROI controle |
|---|---|---|---|---|---|---|
| Huidig: alle data sinds 2008, alle kenmerken | 0.6597 | 0.6388 | 63.3% | 0.5795 / 0.5819 | 419 / -4.9% | 268 / +5.3% |
| Alleen laatste 8 jaar trainen | 0.6620 | 0.6383 | 63.7% | 0.5797 / 0.5819 | 401 / -5.6% | 264 / +3.4% |
| Alleen laatste 5 jaar trainen | 0.6630 | 0.6398 | 63.5% | 0.5795 / 0.5819 | 347 / -6.0% | 268 / +5.5% |
| Alleen laatste 3 jaar trainen | 0.6649 | 0.6402 | 62.9% | 0.5796 / 0.5819 | 260 / -4.4% | 281 / +4.0% |
| Recente jaren zwaarder (halveert per 6 jaar) | 0.6601 | 0.6379 | 63.6% | 0.5795 / 0.5819 | 394 / -5.5% | 267 / +5.2% |
| Recente jaren zwaarder (halveert per 3 jaar) | 0.6614 | 0.6391 | 63.2% | 0.5795 / 0.5819 | 373 / -5.4% | 275 / +5.2% |
| Zonder striking-stats | 0.6652 | 0.6458 | 62.9% | 0.5803 / 0.5819 | 338 / -1.1% | 267 / -2.5% |
| Minimaal: Elo, record, vorm, leeftijd, lengte/reach | 0.6654 | 0.6490 | 61.9% | 0.5797 / 0.5819 | 327 / -5.8% | 267 / +2.0% |
