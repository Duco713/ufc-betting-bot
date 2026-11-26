"""Backtest 'underdog-value': af en toe een onderbouwde underdog-bet.

Regels (vooraf vastgelegd op 26-11-2026, vóór het bekijken van uitslagen):
  1. Underdog in de markt met kans 25-40% (zonder marge), dus geen longshots.
  2. Model zonder odds (walk-forward, out-of-sample) geeft de underdog >= 15 procentpunt meer dan de markt.
  3. Geen UFC-debutant aan een van beide kanten.
  4. Max. 1 per event: het gevecht met het grootste verschil.
  5. Vaste inzet 0,5% van de startbankroll (1 eenheid), op de slotodds.

Vergelijking: willekeurige underdogs uit hetzelfde segment (regels 1, 3, 4, zonder regel 2), 2000 trekkingen.

    .venv/bin/python -m src.models.underdog
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src import db
from src.models.train import REPORT_DIR, am_to_dec

LO, HI, GAP = 0.25, 0.40, 0.15
UNIT = 5.0  # 0,5% van 1000


def load() -> pd.DataFrame:
    P = pd.read_csv(REPORT_DIR / "backtest_predictions.csv", parse_dates=["date"]).dropna(subset=["mkt_p", "odds_a", "odds_b"])
    con = db.connect()
    f = con.execute("SELECT fight_id, event_id, event_date, fighter_a_id, fighter_b_id, fighter_a_name, fighter_b_name FROM fights").df()
    P = P.merge(f, on="fight_id")
    # aantal eerdere UFC-gevechten per vechter (voor debuut-filter)
    long = pd.concat([f[["fight_id", "event_date", "fighter_a_id"]].rename(columns={"fighter_a_id": "fid"}),
                      f[["fight_id", "event_date", "fighter_b_id"]].rename(columns={"fighter_b_id": "fid"})])
    long = long.sort_values(["event_date", "fight_id"])
    long["n_prior"] = long.groupby("fid").cumcount()
    np_ = long.set_index(["fight_id", "fid"]).n_prior
    P["a_prior"] = [np_.get((r.fight_id, r.fighter_a_id), 0) for r in P.itertuples()]
    P["b_prior"] = [np_.get((r.fight_id, r.fighter_b_id), 0) for r in P.itertuples()]
    dog_a = P.mkt_p < 0.5
    P["dog_name"] = np.where(dog_a, P.fighter_a_name, P.fighter_b_name)
    P["dog_mkt"] = np.where(dog_a, P.mkt_p, 1 - P.mkt_p)
    P["dog_model"] = np.where(dog_a, P.blend, 1 - P.blend)
    P["dog_dec"] = np.where(dog_a, P.odds_a.map(am_to_dec), P.odds_b.map(am_to_dec)).astype(float)
    P["dog_won"] = np.where(dog_a, P.y == 1, P.y == 0)
    P["gap"] = P.dog_model - P.dog_mkt
    P = P[(P.date >= "2017-01-01")]
    seg = P.dog_mkt.between(LO, HI) & (P.a_prior > 0) & (P.b_prior > 0) & P.y.isin([0, 1])
    return P[seg].copy()


def pnl(d: pd.DataFrame) -> pd.Series:
    return np.where(d.dog_won, UNIT * (d.dog_dec - 1), -UNIT)


def stats(d: pd.DataFrame) -> dict:
    if not len(d):
        return {"n": 0}
    p = pnl(d)
    bank = 1000 + np.cumsum(p)
    return {"n": len(d), "hit": d.dog_won.mean(), "avg_odds": d.dog_dec.mean(), "profit": p.sum(),
            "roi": p.sum() / (UNIT * len(d)), "max_dd": float((np.maximum.accumulate(bank) - bank).max())}


def main() -> int:
    S = load()
    picks = S[S.gap >= GAP].sort_values("gap").groupby("event_id").tail(1).sort_values("date")
    rng = np.random.default_rng(42)
    by_ev = {e: g for e, g in S.groupby("event_id")}
    ev_with_pick = picks.event_id.unique()
    # baseline: in dezelfde events een willekeurige underdog uit het segment
    base_rois = []
    for _ in range(2000):
        rows = [g.iloc[rng.integers(len(g))] for e, g in by_ev.items() if e in ev_with_pick]
        b = pd.DataFrame(rows)
        base_rois.append(stats(b)["roi"])
    base_rois = np.array(base_rois)
    st = stats(picks)
    p_value = float((base_rois >= st["roi"]).mean())

    lines = ["# Backtest underdog-value (vooraf vastgelegde regels)", "",
             f"Regels: underdog {LO:.0%}-{HI:.0%} marktkans, model >= +{GAP*100:.0f} pp, geen debutanten, max 1 per event, "
             f"vaste inzet €{UNIT:.0f} op slotodds. Periode 2017 - mrt 2026 (zolang er odds zijn).", "",
             "| Periode | Bets | Geraakt | Gem. odds | Winst | ROI | Max. drawdown |", "|---|---|---|---|---|---|---|"]
    for name, d in [("2017-2021", picks[picks.date < "2022-01-01"]), ("2022-2026", picks[picks.date >= "2022-01-01"]), ("Totaal", picks)]:
        s = stats(d)
        lines.append(f"| {name} | {s['n']} | {s['hit']:.1%} | {s['avg_odds']:.2f} | €{s['profit']:+.0f} | {s['roi']:+.1%} | €{s['max_dd']:.0f} |")
    lines += ["", "| Per jaar | Bets | Winst | ROI |", "|---|---|---|---|"]
    for y, d in picks.groupby(picks.date.dt.year):
        s = stats(d)
        lines.append(f"| {y} | {s['n']} | €{s['profit']:+.0f} | {s['roi']:+.1%} |")
    allseg = stats(S)
    lines += ["", "## Vergelijking",
              f"- Alle underdogs in dit segment (zonder model-regel): {allseg['n']} bets, ROI {allseg['roi']:+.1%}",
              f"- Willekeurige underdog per event (zelfde events, 2000x): gem. ROI {base_rois.mean():+.1%} "
              f"(90%-band {np.percentile(base_rois, 5):+.1%} tot {np.percentile(base_rois, 95):+.1%})",
              f"- Strategie: ROI {st['roi']:+.1%} · kans dat willekeurig even goed of beter is: {p_value:.1%}",
              "", "## Grootste treffers",
              "| Datum | Underdog | Markt | Model | Odds | Winst |", "|---|---|---|---|---|---|"]
    for r in picks[picks.dog_won].nlargest(8, "dog_dec").itertuples():
        lines.append(f"| {r.date.date()} | {r.dog_name} | {r.dog_mkt:.0%} | {r.dog_model:.0%} | {r.dog_dec:.2f} | €{UNIT*(r.dog_dec-1):+.0f} |")
    md = "\n".join(lines) + "\n"
    (REPORT_DIR / "underdog_backtest.md").write_text(md)
    picks[["date", "event_id", "dog_name", "dog_mkt", "dog_model", "gap", "dog_dec", "dog_won"]].to_csv(
        REPORT_DIR / "underdog_bets.csv", index=False)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
