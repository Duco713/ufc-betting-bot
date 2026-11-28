"""Experiment: helpt recente data zwaarder wegen, of minder (oude) data / minder kenmerken?

Eerlijk vergelijken met een apart controle-blok: varianten worden gekozen op 2018-2023 (selectie) en pas
daarna bekeken op 2024-2026 (controle). Wie alleen op de selectie wint, is waarschijnlijk toeval.

    .venv/bin/python -m src.models.sweep
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss

from src import db
from src.features.build import RATES, build_all
from src.models.train import (REPORT_DIR, TRAIN_FROM, fair_prob, feature_cols, make_models, mirror, simulate,
                              stack_walk_forward, symmetrize)

TEST_YEARS = range(2017, 2027)
SEL, HOLD = ("2018-01-01", "2024-01-01"), ("2024-01-01", "2027-01-01")
STRIKE = {"d_" + r[0] for r in RATES} | {"d_sig_diff_pm"}
MINIMAL = {"d_elo", "d_n_fights", "d_win_pct", "d_finish_rate", "d_ko_losses", "d_days_since", "d_last3_win",
           "d_ew_win", "d_streak", "d_age", "d_height_cm", "d_reach_cm", "a_age", "b_age", "a_debut", "b_debut",
           "five_rounds", "title", "womens"}

CONFIGS = {
    "Huidig: alle data sinds 2008, alle kenmerken": {},
    "Alleen laatste 8 jaar trainen": {"window": 8},
    "Alleen laatste 5 jaar trainen": {"window": 5},
    "Alleen laatste 3 jaar trainen": {"window": 3},
    "Recente jaren zwaarder (halveert per 6 jaar)": {"half_life": 6},
    "Recente jaren zwaarder (halveert per 3 jaar)": {"half_life": 3},
    "Zonder striking-stats": {"drop": STRIKE},
    "Minimaal: Elo, record, vorm, leeftijd, lengte/reach": {"keep": MINIMAL},
}


def fit_predict(cfg, tr, te, cols):
    trs = symmetrize(tr, cols)
    w = None
    if cfg.get("half_life"):
        age = (te.date.min() - trs.date).dt.days / 365.25
        w = 0.5 ** (age / cfg["half_life"]).values
    out = {}
    for name, m in make_models().items():
        step = m.steps[-1][0]
        m.fit(trs[cols], trs.y, **({f"{step}__sample_weight": w} if w is not None else {}))
        p1 = m.predict_proba(te[cols])[:, 1]
        p2 = m.predict_proba(mirror(te, cols)[cols])[:, 1]
        out[name] = (p1 + 1 - p2) / 2
    return (out["logreg"] + out["gbm"]) / 2


def run(X, odds, cfg):
    cols = feature_cols(X)
    if "drop" in cfg:
        cols = [c for c in cols if c not in cfg["drop"]]
    if "keep" in cfg:
        cols = [c for c in cols if c in cfg["keep"]]
    hist = X[X.y.notna() & (X.date >= TRAIN_FROM)]
    parts = []
    for yr in TEST_YEARS:
        lo = f"{yr - cfg['window']}-01-01" if cfg.get("window") else TRAIN_FROM
        tr = hist[(hist.date >= lo) & (hist.date < f"{yr}-01-01")]
        te = hist[(hist.date >= f"{yr}-01-01") & (hist.date < f"{yr + 1}-01-01")]
        if len(te):
            parts.append(te[["fight_id", "date", "y"]].assign(blend=fit_predict(cfg, tr, te, cols)))
    P = pd.concat(parts, ignore_index=True).merge(odds, on="fight_id", how="left")
    P["mkt_p"] = fair_prob(P.odds_a, P.odds_b)
    W = P[P.mkt_p.notna()].copy()
    W["mm"] = stack_walk_forward(W)
    return P, W[W.mm.notna()]


def summary(P, W, lo, hi):
    p, w = P[(P.date >= lo) & (P.date < hi)], W[(W.date >= lo) & (W.date < hi)]
    s = simulate(w, "mm")
    return {"ll": log_loss(p.y, p.blend.clip(1e-4, 1 - 1e-4)), "acc": ((p.blend > .5) == (p.y == 1)).mean(),
            "ll_mm": log_loss(w.y, w.mm.clip(1e-4, 1 - 1e-4)), "ll_mkt": log_loss(w.y, w.mkt_p),
            "bets": s["bets"], "roi": s["roi_kelly"]}


def main() -> int:
    con = db.connect()
    X = build_all(con)
    odds = con.execute("SELECT fight_id, odds_a, odds_b FROM odds WHERE source='kaggle_mdabbert'").df()
    rows = []
    for name, cfg in CONFIGS.items():
        print("…", name)
        P, W = run(X, odds, cfg)
        rows.append((name, summary(P, W, *SEL), summary(P, W, *HOLD)))
    lines = ["# Experiment: recente data, minder data, minder kenmerken", "",
             "Selectie = 2018-2023 (hierop kiezen), controle = 2024-2026 (pas daarna kijken). Log-loss: lager is beter. "
             "Bets: model+markt, slotodds, edge ≥ 3%, ¼ Kelly, max 2% (odds t/m mrt 2026).", "",
             "| Variant | Log-loss selectie | Log-loss controle | Goed controle | Model+markt vs markt (controle) | Bets / ROI selectie | Bets / ROI controle |",
             "|---|---|---|---|---|---|---|"]
    for name, s, h in rows:
        lines.append(f"| {name} | {s['ll']:.4f} | {h['ll']:.4f} | {h['acc']:.1%} | {h['ll_mm']:.4f} / {h['ll_mkt']:.4f} | "
                     f"{s['bets']} / {s['roi']:+.1%} | {h['bets']} / {h['roi']:+.1%} |")
    md = "\n".join(lines) + "\n"
    (REPORT_DIR / "sweep.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
