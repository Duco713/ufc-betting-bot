"""Backtest: leert het model van gevechten buiten de UFC (Bellator, PFL, ONE, Rizin, Cage Warriors, LFA, ...)?

Vooraf vastgelegd (27-11-2026, vóór het bekijken van de uitkomst):
  * Baseline  = huidig model (alleen UFC-data), walk-forward.
  * Variant A = "zonder UFC-kennis": alle UFC-gevechten vóór 2018 worden weggegooid. Het model start in 2018
                met alleen kennis van andere organisaties en leert daarna jaar voor jaar de UFC erbij.
  * Variant B = alle UFC-data + andere organisaties (één rating over alle organisaties heen).
  * Testperiode: UFC-gevechten 2018 t/m 2026 (per jaar getraind op alles vóór 1 januari).
  * Model + markt (stacker) wordt voor alle drie op dezelfde manier getraind op hun eigen voorspellingen
    vanaf 2018, dus bets en ROI tellen vanaf 2019 (t/m mrt 2026, zolang er odds zijn).
  * Succes: variant vervangt het huidige model alleen als (1) de log-loss over alle UFC-gevechten 2018-2026
    lager is dan de baseline én (2) de ROI van de model+markt-bets niet lager is dan de baseline.

Rating over organisaties: Elo over alle gevechten samen. Nieuwe vechters starten op een niveau dat past bij de
organisatie van hun eerste gevecht (UFC 1500, sterke organisatie 1450, regionaal 1400); daarna stroomt de
rating mee via vechters die van organisatie wisselen.

    .venv/bin/python -m src.models.crossorg
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss

from src import db
from src.features.build import (ELO_K, add_static, load_fighters, load_fights, load_stats, long_table,
                                matchups, prefight_features)
from src.importers.kaggle import norm_name
from src.importers.wikipedia import ALIASES
from src.models.train import (REPORT_DIR, TRAIN_FROM, fair_prob, feature_cols, make_models, predict_sym,
                              simulate, stack_walk_forward, symmetrize)

TIER_START = {1: 1500.0, 2: 1450.0, 3: 1400.0}
TEST_YEARS = range(2018, 2027)
CUT_A = "2018-01-01"


# ------------------------------------------------------------------ data samenvoegen
def ext_as_fights(con) -> tuple[pd.DataFrame, dict]:
    """ext_fights in het formaat van load_fights, met vechter-ID's gekoppeld aan de UFC-data waar de naam uniek is."""
    ext = con.execute("SELECT * FROM ext_fights WHERE event_date < current_date").df()  # geen geplande gevechten
    fx = con.execute("SELECT fighter_id, name FROM fighters").df()
    fx["key"] = fx.name.map(norm_name)
    counts = fx.key.value_counts()
    ufc_id = fx[fx.key.map(counts) == 1].set_index("key").fighter_id.to_dict()
    alias = {norm_name(k): norm_name(v) for k, v in ALIASES.items()}

    def fid(key):
        key = alias.get(key, key)
        return ufc_id.get(key, "xf:" + key)

    f = pd.DataFrame({
        "fight_id": ext.fight_id, "event_id": "x:" + ext.org + ":" + ext.event_name.fillna(""),
        "date": pd.to_datetime(ext.event_date), "a": ext.a_key.map(fid), "b": ext.b_key.map(fid),
        "result_a": ext.kind.map({"W": "W", "D": "D", "NC": "NC"}), "method": ext.method,
        "end_round": ext.end_round, "end_time_sec": np.nan,
        "scheduled_rounds": np.where(ext.end_round.fillna(0) > 3, 5, 3),
        "weight_class": ext.weight_class, "is_title_fight": False,
        "is_womens": ext.weight_class.fillna("").str.startswith("Women"), "tier": ext.tier, "org": ext.org})
    f = f[(f.a != f.b) & f.result_a.notna()].reset_index(drop=True)
    matched = {k for k in set(ext.a_key) | set(ext.b_key) if alias.get(k, k) in ufc_id}
    return f, {"ext_fights": len(f), "ext_fighters": len(set(ext.a_key) | set(ext.b_key)), "matched_to_ufc": len(matched)}


def add_elo_tiers(long: pd.DataFrame, fights: pd.DataFrame) -> pd.DataFrame:
    """Elo zoals in build.add_elo, maar met startwaarde per organisatie-niveau."""
    elo: dict[str, float] = {}
    pre: dict[tuple, float] = {}
    f = fights.sort_values(["date", "fight_id"])
    for r in f.itertuples(index=False):
        start = TIER_START.get(int(r.tier), 1400.0)
        ea, eb = elo.get(r.a, start), elo.get(r.b, start)
        pre[(r.fight_id, r.a)], pre[(r.fight_id, r.b)] = ea, eb
        if r.result_a not in ("W", "L", "D"):
            continue
        sa = {"W": 1.0, "L": 0.0, "D": 0.5}[r.result_a]
        exp_a = 1 / (1 + 10 ** ((eb - ea) / 400))
        k = ELO_K * (1.25 if isinstance(r.method, str) and not r.method.startswith("Decision") else 1.0)
        elo[r.a], elo[r.b] = ea + k * (sa - exp_a), eb - k * (sa - exp_a)
    long["elo"] = [pre.get((fid, x), 1500.0) for fid, x in zip(long.fight_id, long.fighter_id)]
    long["o_elo"] = [pre.get((fid, x), 1500.0) for fid, x in zip(long.fight_id, long.opp_id)]
    return long


def build(con, ufc: pd.DataFrame, ext: pd.DataFrame | None) -> pd.DataFrame:
    """Matchup-tabel voor de UFC-gevechten (en ext-gevechten), features uit de gecombineerde historie."""
    ufc = ufc.assign(tier=1, org="UFC")
    fights = pd.concat([ufc, ext], ignore_index=True) if ext is not None else ufc
    fights["date"] = pd.to_datetime(fights["date"])
    fights = fights.sort_values(["date", "fight_id"]).reset_index(drop=True)
    long = long_table(fights, load_stats(con))
    long = add_elo_tiers(long, fights)
    pf = prefight_features(long)
    # UFC-ervaring apart (n_fights telt nu alle bekende profgevechten)
    is_ufc = pf.fight_id.isin(set(ufc.fight_id))
    pf = pf.sort_values(["fighter_id", "date", "fight_id"])
    pf["ufc_n"] = is_ufc.loc[pf.index].astype(int).groupby(pf.fighter_id).cumsum() - is_ufc.loc[pf.index].astype(int)
    pf = add_static(pf, load_fighters(con))
    X = matchups(fights, pf)
    key = pf.set_index(["fight_id", "fighter_id"]).ufc_n
    X["a_ufc_n"] = [key.get((f, a), 0) for f, a in zip(X.fight_id, X.a)]
    X["b_ufc_n"] = [key.get((f, b), 0) for f, b in zip(X.fight_id, X.b)]
    X["d_ufc_n"] = X.a_ufc_n - X.b_ufc_n
    X["a_ufc_debut"], X["b_ufc_debut"] = (X.a_ufc_n == 0).astype(float), (X.b_ufc_n == 0).astype(float)
    X["is_ufc"] = X.fight_id.isin(set(ufc.fight_id))
    return X


# ------------------------------------------------------------------ walk-forward
def cols_for(X: pd.DataFrame, extra: bool) -> list[str]:
    cols = feature_cols(X)
    return cols + (["a_ufc_debut", "b_ufc_debut"] if extra else [])


def walk_forward(X: pd.DataFrame, cols: list[str], train_mask) -> pd.DataFrame:
    hist = X[X.y.notna()]
    test = hist[hist.is_ufc]
    out = []
    for yr in TEST_YEARS:
        tr = hist[train_mask(hist) & (hist.date < f"{yr}-01-01")]
        te = test[(test.date >= f"{yr}-01-01") & (test.date < f"{yr + 1}-01-01")]
        if te.empty:
            continue
        trs = symmetrize(tr, cols)
        o = te[["fight_id", "date", "y", "elo_prob", "a_ufc_n", "b_ufc_n"]].copy()
        for name, m in make_models().items():
            m.fit(trs[cols], trs.y)
            o[name] = predict_sym(m, te, cols)
        out.append(o)
        print(f"    {yr}: train {len(tr):6d} (waarvan UFC {int(tr.is_ufc.sum()):5d})  test {len(te):4d}")
    P = pd.concat(out, ignore_index=True)
    P["blend"] = (P.logreg + P.gbm) / 2
    return P


# ------------------------------------------------------------------ evaluatie
def ll(d, c):
    return log_loss(d.y, d[c].clip(1e-4, 1 - 1e-4), labels=[0, 1]) if len(d) else np.nan


def evaluate(P: pd.DataFrame, odds: pd.DataFrame) -> dict:
    P = P.merge(odds, on="fight_id", how="left")
    P["mkt_p"] = fair_prob(P.odds_a, P.odds_b)
    deb = (P.a_ufc_n == 0) | (P.b_ufc_n == 0)
    few = ((P.a_ufc_n <= 2) | (P.b_ufc_n <= 2)) & ~deb
    W = P[P.mkt_p.notna()].copy()
    W["mm"] = stack_walk_forward(W)
    W = W[W.mm.notna()]
    sim = simulate(W, "mm")
    wd = (W.a_ufc_n == 0) | (W.b_ufc_n == 0)
    return {
        "n": len(P), "ll": ll(P, "blend"), "acc": ((P.blend > .5) == (P.y == 1)).mean(),
        "n_deb": int(deb.sum()), "ll_deb": ll(P[deb], "blend"), "acc_deb": ((P[deb].blend > .5) == (P[deb].y == 1)).mean(),
        "ll_few": ll(P[few], "blend"),
        "by_year": P.groupby(P.date.dt.year).apply(lambda d: ll(d, "blend")).to_dict(),
        "n_odds": len(W), "ll_mm": ll(W, "mm"), "ll_mkt": ll(W, "mkt_p"), "ll_blend_odds": ll(W, "blend"),
        "ll_mm_deb": ll(W[wd], "mm"), "ll_mkt_deb": ll(W[wd], "mkt_p"),
        "bets": sim["bets"], "hit": sim["hit"], "roi": sim["roi_kelly"], "roi_flat": sim["roi_flat"],
        "bank": sim["bankroll"], "mdd": sim["max_dd"], "W": W,
    }


def main() -> int:
    con = db.connect()
    odds = con.execute("SELECT fight_id, odds_a, odds_b FROM odds WHERE source='kaggle_mdabbert'").df()
    ufc = load_fights(con)
    ext, cover = ext_as_fights(con)
    print(f"Andere organisaties: {cover['ext_fights']} gevechten, {cover['ext_fighters']} vechters, "
          f"waarvan {cover['matched_to_ufc']} gekoppeld aan UFC-vechters")

    res = {}
    print("Baseline (alleen UFC)…")
    Xb = build(con, ufc, None)
    res["Huidig model (alleen UFC)"] = evaluate(
        walk_forward(Xb, cols_for(Xb, False), lambda h: h.is_ufc & (h.date >= TRAIN_FROM)), odds)

    print("Variant B (UFC + andere organisaties)…")
    XB = build(con, ufc, ext)
    res["B: UFC + andere organisaties"] = evaluate(
        walk_forward(XB, cols_for(XB, True), lambda h: h.is_ufc & (h.date >= TRAIN_FROM)), odds)

    print("Variant A (vóór 2018 alleen andere organisaties)…")
    XA = build(con, ufc[pd.to_datetime(ufc.date) >= CUT_A], ext)
    res["A: zonder UFC-kennis tot 2018"] = evaluate(
        walk_forward(XA, cols_for(XA, True), lambda h: ~h.is_ufc | (h.date >= CUT_A)), odds)

    # dekking: UFC-debutanten 2018+ met minstens één bekend gevecht buiten de UFC
    deb = XB[XB.is_ufc & (XB.date >= CUT_A) & XB.y.notna()]
    n_deb_sides = int((deb.a_ufc_n == 0).sum() + (deb.b_ufc_n == 0).sum())
    n_deb_known = int(((deb.a_ufc_n == 0) & (deb.a_n_fights > 0)).sum() + ((deb.b_ufc_n == 0) & (deb.b_n_fights > 0)).sum())

    base = res["Huidig model (alleen UFC)"]
    lines = ["# Backtest: leren van andere organisaties", "",
             "Vooraf vastgelegd (27-11-2026): een variant vervangt het huidige model alleen als de log-loss over alle "
             "UFC-gevechten 2018-2026 lager is **én** de ROI van de model+markt-bets niet lager is.", "",
             f"Data: {cover['ext_fights']:,} gevechten buiten de UFC (Wikipedia: Bellator, PFL, WSOF, ONE, Strikeforce, Rizin, "
             f"DREAM, ACA, M-1, Cage Warriors, LFA, Brave, Road FC, Oktagon, Jungle Fight, UAE Warriors), "
             f"{cover['ext_fighters']:,} vechters, waarvan {cover['matched_to_ufc']:,} gekoppeld aan UFC-vechters. "
             f"Van de UFC-debutanten sinds 2018 hebben we bij {n_deb_known} van {n_deb_sides} "
             f"({n_deb_known / max(n_deb_sides, 1):.0%}) minstens één eerder gevecht gevonden.", "",
             "## Voorspellen (alle UFC-gevechten 2018 - nov 2026, model zonder odds)", "",
             "| Model | Gevechten | Log-loss | Goed | Log-loss debutanten | Goed debutanten | Log-loss 1-2 UFC-gevechten |",
             "|---|---|---|---|---|---|---|"]
    for k, r in res.items():
        lines.append(f"| {k} | {r['n']} | {r['ll']:.4f} | {r['acc']:.1%} | {r['ll_deb']:.4f} ({r['n_deb']}) | "
                     f"{r['acc_deb']:.1%} | {r['ll_few']:.4f} |")
    lines += ["", "Lager is beter voor log-loss.", "", "## Log-loss per jaar", "",
              "| Jaar | " + " | ".join(res) + " |", "|---" * (len(res) + 1) + "|"]
    for y in sorted(base["by_year"]):
        lines.append(f"| {y} | " + " | ".join(f"{r['by_year'].get(y, np.nan):.4f}" for r in res.values()) + " |")
    lines += ["", "## Met odds: model + markt en bets (2019 - mrt 2026, slotodds, edge ≥ 3%, ¼ Kelly, max 2%)", "",
              "| Model | Gevechten | Log-loss model+markt | Log-loss markt | Debutanten: model+markt / markt | Bets | Geraakt | ROI | Eindstand | Max. daling |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for k, r in res.items():
        lines.append(f"| {k} | {r['n_odds']} | {r['ll_mm']:.4f} | {r['ll_mkt']:.4f} | {r['ll_mm_deb']:.4f} / {r['ll_mkt_deb']:.4f} | "
                     f"{r['bets']} | {r['hit']:.1%} | {r['roi']:+.1%} | €{r['bank']:,.0f} | {r['mdd']:.0%} |")
    lines += ["", "## Oordeel (volgens de vooraf vastgelegde regel)", ""]
    for k in ("B: UFC + andere organisaties", "A: zonder UFC-kennis tot 2018"):
        r = res[k]
        c1, c2 = r["ll"] < base["ll"], r["roi"] >= base["roi"]
        lines.append(f"- **{k}**: log-loss {'lager ✓' if c1 else 'niet lager ✗'} ({r['ll']:.4f} vs {base['ll']:.4f}), "
                     f"ROI {'niet lager ✓' if c2 else 'lager ✗'} ({r['roi']:+.1%} vs {base['roi']:+.1%}) → "
                     f"**{'vervangt het huidige model' if c1 and c2 else 'niet overnemen'}**")
    md = "\n".join(lines) + "\n"
    (REPORT_DIR / "crossorg_backtest.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
