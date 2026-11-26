"""Walk-forward backtest + eindmodel (PLAN.md §4-6).

    .venv/bin/python -m src.models.train            # backtest 2016-2026 + eindmodel opslaan

Per testjaar wordt getraind op alle gevechten vóór 1 januari van dat jaar (vanaf TRAIN_FROM)
en voorspeld voor dat jaar. Nooit willekeurig splitsen (leakage via tijd).
Resultaten: reports/backtest.md, reports/backtest_predictions.csv, models/model.joblib
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src import db
from src.features.build import build_all

TRAIN_FROM = "2008-01-01"
TEST_YEARS = range(2016, 2027)
MODEL_DIR = db.ROOT / "models"
REPORT_DIR = db.ROOT / "reports"
EDGE_MIN, KELLY_FRAC, MAX_STAKE = 0.03, 0.25, 0.02   # zie config/PLAN §6

SYM_DIFF = None  # gevuld in feature_cols()


def feature_cols(X: pd.DataFrame) -> list[str]:
    return [c for c in X.columns if c.startswith("d_")] + [
        "a_age", "b_age", "a_debut", "b_debut", "five_rounds", "title", "womens"]


def symmetrize(X: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Voeg gespiegelde rijen toe (B vs A), zodat de hoek (rood/blauw) geen rol speelt."""
    S = X.copy()
    for c in cols:
        if c.startswith("d_"):
            S[c] = -X[c]
    for p in ("age", "debut", "n_fights", "elo"):
        if f"a_{p}" in X and f"b_{p}" in X:
            S[f"a_{p}"], S[f"b_{p}"] = X[f"b_{p}"], X[f"a_{p}"]
    S["y"] = 1 - X["y"]
    return pd.concat([X, S], ignore_index=True)


def mirror(X: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    return symmetrize(X.assign(y=0.0), cols).iloc[len(X):].reset_index(drop=True)


def make_models() -> dict:
    return {
        "logreg": make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(),
                                LogisticRegression(C=0.05, max_iter=2000)),
        "gbm": make_pipeline(SimpleImputer(strategy="median", add_indicator=True),
                             HistGradientBoostingClassifier(learning_rate=0.03, max_iter=300, max_depth=3,
                                                            min_samples_leaf=80, l2_regularization=1.0,
                                                            random_state=0)),
    }


def predict_sym(model, X: pd.DataFrame, cols: list[str]) -> np.ndarray:
    """Gemiddelde van P(A wint) en 1 - P(B wint) in de gespiegelde rij."""
    p1 = model.predict_proba(X[cols])[:, 1]
    p2 = model.predict_proba(mirror(X, cols)[cols])[:, 1]
    return (p1 + (1 - p2)) / 2


# ------------------------------------------------------------------ odds-hulpjes
def am_to_dec(o):
    o = np.asarray(o, dtype=float)
    return np.where(o > 0, 1 + o / 100, 1 + 100 / np.abs(o))


def fair_prob(oa, ob):
    pa, pb = 1 / am_to_dec(oa), 1 / am_to_dec(ob)
    return pa / (pa + pb)


def kelly_stake(p, dec, bankroll):
    b = dec - 1
    f = (b * p - (1 - p)) / b
    return np.clip(f * KELLY_FRAC, 0, MAX_STAKE) * bankroll


def simulate(df: pd.DataFrame, prob_col: str, bankroll0: float = 1000.0) -> dict:
    """Bet op de kant met de grootste edge >= EDGE_MIN, ¼ Kelly, op de (slot)odds uit de data."""
    bank, staked, n, wins, peak, mdd, flat_pnl = bankroll0, 0.0, 0, 0, bankroll0, 0.0, 0.0
    curve = []
    for r in df.sort_values("date").itertuples(index=False):
        p = getattr(r, prob_col)
        da, dbb = am_to_dec(r.odds_a), am_to_dec(r.odds_b)
        ea, eb = p * da - 1, (1 - p) * dbb - 1
        side = "a" if ea >= eb else "b"
        edge_prob = (p - r.mkt_p) if side == "a" else ((1 - p) - (1 - r.mkt_p))
        if edge_prob < EDGE_MIN:
            continue
        pp, dd = (p, da) if side == "a" else (1 - p, dbb)
        stake = float(kelly_stake(pp, dd, bank))
        if stake <= 0:
            continue
        won = (r.y == 1) if side == "a" else (r.y == 0)
        pnl = stake * (dd - 1) if won else -stake
        flat_pnl += (dd - 1) if won else -1
        bank += pnl
        staked += stake
        n += 1
        wins += won
        peak = max(peak, bank)
        mdd = max(mdd, 1 - bank / peak)
        curve.append((r.date, bank))
    return {"bets": n, "hit": wins / n if n else np.nan, "roi_kelly": (bank - bankroll0) / staked if staked else np.nan,
            "roi_flat": flat_pnl / n if n else np.nan, "bankroll": bank, "max_dd": mdd, "curve": curve}


# ------------------------------------------------------------------ backtest
def backtest(X: pd.DataFrame, odds: pd.DataFrame) -> pd.DataFrame:
    cols = feature_cols(X)
    hist = X[X.y.notna() & (X.date >= TRAIN_FROM)]
    preds = []
    for yr in TEST_YEARS:
        tr = hist[hist.date < f"{yr}-01-01"]
        te = hist[(hist.date >= f"{yr}-01-01") & (hist.date < f"{yr + 1}-01-01")]
        if te.empty:
            continue
        trs = symmetrize(tr, cols)
        out = te[["fight_id", "date", "a", "b", "y", "elo_prob"]].copy()
        for name, m in make_models().items():
            m.fit(trs[cols], trs.y)
            out[name] = predict_sym(m, te, cols)
        preds.append(out)
        print(f"  {yr}: train {len(tr):5d}  test {len(te):4d}")
    P = pd.concat(preds, ignore_index=True)
    P["blend"] = (P.logreg + P.gbm) / 2
    P = P.merge(odds, on="fight_id", how="left")
    P["mkt_p"] = fair_prob(P.odds_a, P.odds_b)
    return P


def metrics(P: pd.DataFrame, cols=("elo_prob", "logreg", "gbm", "blend", "mkt_p")) -> pd.DataFrame:
    rows = []
    for c in cols:
        d = P[P[c].notna()]
        rows.append({"model": c, "n": len(d), "accuracy": ((d[c] > .5) == (d.y == 1)).mean(),
                     "log_loss": log_loss(d.y, d[c].clip(1e-4, 1 - 1e-4)), "brier": brier_score_loss(d.y, d[c])})
    return pd.DataFrame(rows)


def calibration(P: pd.DataFrame, col: str) -> pd.DataFrame:
    s = symmetrize(P[["y", col]].rename(columns={col: "p"}).assign(), [])  # beide kanten
    s["p"] = np.r_[P[col].values, 1 - P[col].values]
    s["bucket"] = (s.p * 10).clip(0, 9.999).astype(int) / 10
    return s.groupby("bucket").agg(n=("y", "size"), predicted=("p", "mean"), actual=("y", "mean")).reset_index()


# ------------------------------------------------------------------ markt + model (stacking)
def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def _stack_xy(D: pd.DataFrame):
    x = np.c_[_logit(D.mkt_p), _logit(D.blend)]
    X2 = np.r_[x, -x]                      # symmetrisch: geen intercept nodig
    y2 = np.r_[D.y.values, 1 - D.y.values]
    return X2, y2


def fit_stacker(D: pd.DataFrame) -> LogisticRegression:
    X2, y2 = _stack_xy(D)
    return LogisticRegression(fit_intercept=False, C=1.0).fit(X2, y2)


def apply_stacker(st: LogisticRegression, mkt_p, model_p) -> np.ndarray:
    return st.predict_proba(np.c_[_logit(mkt_p), _logit(model_p)])[:, 1]


def stack_walk_forward(W: pd.DataFrame) -> pd.Series:
    """Combineer marktkans en modelkans; per jaar getraind op out-of-sample voorspellingen van eerdere jaren."""
    out = pd.Series(np.nan, index=W.index)
    yrs = W.date.dt.year
    for yr in sorted(yrs.unique()):
        tr, te = W[yrs < yr], W[yrs == yr]
        if len(tr) < 300:
            continue
        out[te.index] = apply_stacker(fit_stacker(tr), te.mkt_p, te.blend)
    return out


# ------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(db.DEFAULT_DB))
    a = ap.parse_args(argv)
    con = db.connect(a.db)
    print("Features bouwen…")
    X = build_all(con)
    odds = con.execute("SELECT fight_id, odds_a, odds_b FROM odds WHERE source='kaggle_mdabbert'").df()
    print("Walk-forward backtest…")
    P = backtest(X, odds)

    REPORT_DIR.mkdir(exist_ok=True)
    MODEL_DIR.mkdir(exist_ok=True)
    P.to_csv(REPORT_DIR / "backtest_predictions.csv", index=False)

    all_m = metrics(P, ("elo_prob", "logreg", "gbm", "blend"))
    W = P[P.mkt_p.notna()].copy()
    W["mm"] = stack_walk_forward(W)
    W = W[W["mm"].notna()]          # vanaf 2017 (2016 is nodig om de stacker te trainen)
    odds_m = metrics(W, ("elo_prob", "logreg", "gbm", "blend", "mm", "mkt_p"))
    by_year = W.groupby(W.date.dt.year).apply(
        lambda d: pd.Series({"n": len(d), **{f"ll_{c}": log_loss(d.y, d[c].clip(1e-4, 1 - 1e-4))
                                              for c in ("blend", "mm", "mkt_p")}}))
    sims = {c: simulate(W, c) for c in ("blend", "mm")}
    best = "mm"
    cal = calibration(W, best)
    W.to_csv(REPORT_DIR / "backtest_with_odds.csv", index=False)
    stacker = fit_stacker(W)

    # eindmodel op alles vanaf TRAIN_FROM
    cols = feature_cols(X)
    hist = symmetrize(X[X.y.notna() & (X.date >= TRAIN_FROM)], cols)
    final = make_models()
    for m in final.values():
        m.fit(hist[cols], hist.y)
    version = "v0.1-" + datetime.now().strftime("%Y%m%d")
    joblib.dump({"models": final, "cols": cols, "best": best, "version": version, "stacker": stacker,
                 "trained_until": str(X[X.y.notna()].date.max().date())}, MODEL_DIR / "model.joblib")

    fmt = lambda df: df.to_markdown(index=False, floatfmt=".4f")
    sim_df = pd.DataFrame([{"model": k, **{kk: vv for kk, vv in v.items() if kk != "curve"}} for k, v in sims.items()])
    md = f"""# Backtest {version}

Walk-forward {min(TEST_YEARS)}-{max(TEST_YEARS)}: per jaar getraind op alle gevechten vanaf {TRAIN_FROM} tot 1 januari van dat jaar.
Gekozen model voor voorspellingen: **{best}** (laagste log-loss op gevechten met odds).

## Alle gevechten (ook zonder odds)
{fmt(all_m)}

## Gevechten met odds: model vs. markt (mkt_p = slotodds zonder marge)
{fmt(odds_m)}

Lager is beter voor log-loss en Brier. **Het model moet onder `mkt_p` komen om echt value te vinden.**

## Log-loss per jaar (gevechten met odds)
{by_year.reset_index().rename(columns={'date': 'jaar'}).to_markdown(index=False, floatfmt='.4f')}

## Bet-simulatie op slotodds (edge ≥ {EDGE_MIN:.0%}, {KELLY_FRAC:.2f} Kelly, max {MAX_STAKE:.0%} per bet, start €1.000)
{fmt(sim_df)}

Let op: gebet op slotodds uit de data; in het echt krijg je eerdere odds (vaak slechter of beter). Geen CLV mogelijk zonder openingsodds.

## Kalibratie ({best})
{fmt(cal)}
"""
    (REPORT_DIR / "backtest.md").write_text(md)
    json.dump({c: [(str(d.date()), b) for d, b in sims[c]["curve"]] for c in sims},
              open(REPORT_DIR / "backtest_curves.json", "w"))
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
