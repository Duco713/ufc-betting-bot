"""Exporteer alles wat het dashboard nodig heeft naar docs/data/*.json (statische site, GitHub Pages).

    .venv/bin/python -m src.export.site_data

Draai eerst: src.importers.kaggle -> src.models.train -> src.predict.upcoming.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss

from src import db
from src.features.build import build_all
from src.models.train import (EDGE_MIN, KELLY_FRAC, MAX_STAKE, MODEL_DIR, REPORT_DIR, am_to_dec, feature_cols)
from src.predict.upcoming import LABELS, UPCOMING_JSON, upcoming_rows
from src.settle import RESULTS_DDL, scorecard

OUT = db.ROOT / "docs" / "data"
MAIN_CLASSES = ["Flyweight", "Bantamweight", "Featherweight", "Lightweight", "Welterweight", "Middleweight",
                "Light Heavyweight", "Heavyweight", "Women's Strawweight", "Women's Flyweight",
                "Women's Bantamweight", "Women's Featherweight"]
STYLE = ["slpm", "sapm", "sig_acc", "sig_def", "td15", "td_acc", "td_def", "ctrl_share", "sub15", "kd15"]


def clean(o):
    """Maak JSON-veilig (NaN -> None, numpy -> python, datums -> iso)."""
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if math.isnan(o) or math.isinf(o) else round(float(o), 4)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (pd.Timestamp, datetime, date)):
        return o.isoformat()[:10] if not isinstance(o, datetime) or o.hour == 0 and o.minute == 0 else o.isoformat(timespec="minutes")
    if o is pd.NaT or (o is not None and not isinstance(o, (str, bool, int)) and pd.isna(o)):
        return None
    return o


def record(con, fid: str, before: str | None = None) -> str | None:
    if fid.startswith("new:"):
        return None
    q = "SELECT result_a r FROM fights WHERE fighter_a_id=? UNION ALL SELECT result_b FROM fights WHERE fighter_b_id=?"
    r = con.execute(q, [fid, fid]).df().r.value_counts()
    return f"{r.get('W', 0)}-{r.get('L', 0)}-{r.get('D', 0)}"


def fighter_history(con, fid: str) -> pd.DataFrame:
    return con.execute("""
        SELECT f.fight_id, f.event_date date, e.name event, f.weight_class,
               CASE WHEN f.fighter_a_id=? THEN f.fighter_b_name ELSE f.fighter_a_name END opp,
               CASE WHEN f.fighter_a_id=? THEN f.fighter_b_id ELSE f.fighter_a_id END opp_id,
               CASE WHEN f.fighter_a_id=? THEN f.result_a ELSE f.result_b END result,
               f.method, f.method_detail, f.end_round, f.end_time_sec, f.scheduled_rounds,
               CASE WHEN f.fighter_a_id=? THEN o.odds_a ELSE o.odds_b END odds
        FROM fights f LEFT JOIN events e USING(event_id) LEFT JOIN odds o USING(fight_id)
        WHERE ? IN (f.fighter_a_id, f.fighter_b_id) ORDER BY f.event_date DESC""", [fid] * 5).df()


def cardio(con, fid: str) -> list:
    df = con.execute("""SELECT round, avg(sig_str_landed) v, count(*) n FROM fight_stats_round
                        WHERE fighter_id=? AND round BETWEEN 1 AND 5 GROUP BY 1 ORDER BY 1""", [fid]).df()
    return df[df.n >= 2].to_dict("records")


# ------------------------------------------------------------------ simulatie met per-bet uitvoer
def sim_bets(W: pd.DataFrame, col: str, edge_min=EDGE_MIN, kelly=KELLY_FRAC, max_stake=MAX_STAKE) -> pd.DataFrame:
    bank, rows = 1000.0, []
    for r in W.sort_values("date").itertuples(index=False):
        p = getattr(r, col)
        da, dbb = float(am_to_dec(r.odds_a)), float(am_to_dec(r.odds_b))
        ea, eb = p - r.mkt_p, (1 - p) - (1 - r.mkt_p)
        side_a = ea >= eb
        edge = ea if side_a else eb
        if edge < edge_min:
            continue
        pp, dd = (p, da) if side_a else (1 - p, dbb)
        f = ((dd - 1) * pp - (1 - pp)) / (dd - 1)
        stake = min(max(f * kelly, 0), max_stake) * bank
        if stake <= 0:
            continue
        won = (r.y == 1) == side_a
        pnl = stake * (dd - 1) if won else -stake
        bank += pnl
        rows.append({"date": r.date, "fight_id": r.fight_id, "dec": dd, "won": won, "stake": stake, "pnl": pnl,
                     "bank": bank, "fav": dd < 2.0, "edge": edge, "wc": r.weight_class, "womens": r.is_womens,
                     "five": r.scheduled_rounds == 5})
    return pd.DataFrame(rows)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(db.DEFAULT_DB))
    con = db.connect(ap.parse_args(argv).db)
    bundle = joblib.load(MODEL_DIR / "model.joblib")
    version = bundle["version"]
    data = json.loads(UPCOMING_JSON.read_text())
    OUT.mkdir(parents=True, exist_ok=True)

    up, meta = upcoming_rows(con, data)
    X, pf = build_all(con, up, return_pf=True)
    pf_idx = pf.set_index(["fight_id", "fighter_id"])
    preds = con.execute("SELECT * FROM predictions WHERE model_version=?", [version]).df().set_index("fight_id")
    ms = con.execute("SELECT max(date) FROM events").fetchone()[0]

    # ---------------- divisiegemiddelden (laatste 3 jaar, voor stijlradar)
    recent = pf[pf.date >= pd.Timestamp(ms) - pd.Timedelta(days=3 * 365)]
    wc_of = con.execute("SELECT fight_id, weight_class FROM fights").df().set_index("fight_id").weight_class
    recent = recent.assign(wc=recent.fight_id.map(wc_of))
    div_avg = {wc: {s: recent[recent.wc == wc][s].median() for s in STYLE} for wc in MAIN_CLASSES}

    # ---------------- vechters op de komende kaarten
    fighters, fids = {}, {}
    for m in meta:
        for side in ("a", "b"):
            fids[m[f"{side}_id"]] = (m[side], m[f"{side}_record"], m["klasse"].split(" (")[0])
    finfo = con.execute("SELECT * FROM fighters").df().set_index("fighter_id")
    for fid, (name, rec_json, wc) in fids.items():
        h = fighter_history(con, fid) if not fid.startswith("new:") else pd.DataFrame()
        elo_hist = []
        if len(h):
            e = pf[pf.fighter_id == fid].sort_values("date")
            res = dict(zip(h.fight_id, h.result))
            elo_hist = [{"date": r.date, "elo": r.elo, "result": res.get(r.fight_id)} for r in e.itertuples()
                        if r.fight_id in res]
        info = finfo.loc[fid] if fid in finfo.index else None
        fighters[fid] = {
            "id": fid, "name": name, "record_pro": rec_json, "record_ufc": record(con, fid), "weight_class": wc,
            "nickname": None if info is None else info.nickname,
            "height_cm": None if info is None else info.height_cm, "reach_cm": None if info is None else info.reach_cm,
            "stance": None if info is None else info.stance, "dob": None if info is None else info.dob,
            "elo_history": elo_hist, "history": h.to_dict("records") if len(h) else [],
            "cardio": cardio(con, fid) if not fid.startswith("new:") else [],
            "division_avg": div_avg.get(wc, {}),
        }

    # ---------------- paper trading: vastgezette bets + uitslagen
    con.execute(RESULTS_DDL)
    res_idx = con.execute("SELECT * FROM paper_results").df().set_index("fight_id")
    bet_rows = con.execute("SELECT * FROM bets").df()
    bet_idx = bet_rows.set_index("fight_id") if len(bet_rows) else bet_rows

    def fight_result(fid):
        if fid not in res_idx.index:
            return None
        r = res_idx.loc[fid]
        return {"winner": r.winner_name, "outcome": r.outcome, "method": r.method,
                "round": None if pd.isna(r.end_round) else int(r.end_round),
                "y_a": None if pd.isna(r.y_a) else int(r.y_a),
                "close_market_a": None if pd.isna(r.close_market_a) else float(r.close_market_a)}

    def locked_bet(fid):
        if not len(bet_idx) or fid not in bet_idx.index:
            return None
        b = bet_idx.loc[fid]
        return {"pick": b.pick_name, "odds": float(b.odds_taken), "stake": float(b.stake), "result": b.result,
                "pnl": None if pd.isna(b.pnl) else float(b.pnl),
                "odds_closing": None if pd.isna(b.odds_closing) else float(b.odds_closing),
                "clv": None if pd.isna(b.clv) else float(b.clv)}

    # ---------------- events + fights
    events = []
    for w in data["weekenden"]:
        ev = w.get("event")
        if not ev:
            events.append({"weekend": w["weekend"], "none": True, "note": w.get("notitie")})
            continue
        fights = []
        for m in [x for x in meta if x["event"]["id"] == ev["id"]]:
            p = preds.loc[m["fight_id"]] if m["fight_id"] in preds.index else None
            A = pf_idx.loc[(m["fight_id"], m["a_id"])]
            B = pf_idx.loc[(m["fight_id"], m["b_id"])]

            def side(S, fid, nm, rec):
                h = fighters[fid]["history"]
                return {"id": fid, "name": nm, "record": rec, "elo": S.elo, "n_ufc": S.n_fights, "age": S.age,
                        "height_cm": S.height_cm, "reach_cm": S.reach_cm, "southpaw": S.southpaw,
                        "stance": fighters[fid]["stance"], "days_since": None,
                        "last_date": h[0]["date"] if h else None,
                        "last5": [x["result"] for x in h[:5]], "style": {s: S[s] for s in STYLE},
                        "streak": S.streak, "ko_losses": S.ko_losses, "elo_trend": S.elo_trend}
            a, b = side(A, m["a_id"], m["a"], m["a_record"]), side(B, m["b_id"], m["b"], m["b_record"])
            common = []
            ha = {x["opp_id"]: x for x in fighters[m["a_id"]]["history"]}
            for x in fighters[m["b_id"]]["history"]:
                if x["opp_id"] in ha:
                    common.append({"opp": x["opp"], "a": ha[x["opp_id"]]["result"], "b": x["result"]})
            fights.append({
                "id": m["fight_id"], "card": m["kaart"], "order": m["nr"], "weight_class": m["klasse"],
                "rounds": m["rondes"], "a": a, "b": b,
                "odds_a": None if p is None or pd.isna(p.odds_a) else int(p.odds_a),
                "odds_b": None if p is None or pd.isna(p.odds_b) else int(p.odds_b),
                "odds_info": None if p is None or not isinstance(p.get("odds_info"), str) else json.loads(p["odds_info"]),
                "p_model": None if p is None else p.prob_model_a, "p_market": None if p is None else p.prob_market_a,
                "p_final": None if p is None else p.prob_final_a, "edge": None if p is None else p.edge,
                "pick": None if p is None else p.pick, "stake": None if p is None else p.stake,
                "reasons": [] if p is None else json.loads(p["reasons"]), "method": {} if p is None else json.loads(p["method"]),
                "flags": [] if p is None else json.loads(p["flags"]), "common": common,
                "locked": bool(p is not None and not pd.isna(p.locked_at)),
                "locked_bet": locked_bet(m["fight_id"]), "result": fight_result(m["fight_id"]),
            })
        for x in [x for x in ev["fights"] if x["kaart"] == "onbevestigd"]:
            fights.append({"id": f"{ev['id']}-{x['nr']:02d}", "card": "onbevestigd", "order": x["nr"],
                           "weight_class": x["klasse"], "rounds": x["rondes"],
                           "a": {"name": x["a"], "record": x["a_record"]}, "b": {"name": x["b"], "record": x["b_record"]}})
        events.append({"weekend": w["weekend"], "id": ev["id"], "name": ev["naam"], "date": ev["datum"],
                       "location": ev["locatie"], "times": ev.get("aanvang_nl", {}), "note": ev.get("notitie"),
                       "type": "PPV" if "UFC 3" in ev["naam"] else "Fight Night",
                       "complete": not ev.get("notitie"), "fights": fights,
                       "locked_at": max((str(preds.loc[f["id"]].locked_at) for f in fights
                                         if f["id"] in preds.index and not pd.isna(preds.loc[f["id"]].locked_at)), default=None)})

    # ---------------- backtest / prestaties
    W = pd.read_csv(REPORT_DIR / "backtest_with_odds.csv", parse_dates=["date"])
    fx = con.execute("SELECT fight_id, weight_class, is_womens, scheduled_rounds, fighter_a_name, fighter_b_name, event_id FROM fights").df()
    W = W.merge(fx, on="fight_id", how="left")
    allP = pd.read_csv(REPORT_DIR / "backtest_predictions.csv", parse_dates=["date"])

    def mrow(d, c):
        return {"model": c, "n": len(d), "accuracy": float(((d[c] > .5) == (d.y == 1)).mean()),
                "log_loss": float(log_loss(d.y, d[c].clip(1e-4, 1 - 1e-4))), "brier": float(brier_score_loss(d.y, d[c]))}
    metrics = [mrow(W, c) for c in ("elo_prob", "blend", "mm", "mkt_p")]
    by_year = [{"year": int(y), "n": len(d), **{c: float(log_loss(d.y, d[c].clip(1e-4, 1 - 1e-4))) for c in ("blend", "mm", "mkt_p")}}
               for y, d in W.groupby(W.date.dt.year)]
    both = pd.DataFrame({"p": np.r_[W.mm, 1 - W.mm], "y": np.r_[W.y, 1 - W.y]})
    both["b"] = (both.p * 10).clip(0, 9.999).astype(int)
    calib = both.groupby("b").agg(n=("y", "size"), predicted=("p", "mean"), actual=("y", "mean")).reset_index().to_dict("records")

    bets = sim_bets(W, "mm")
    roi_year = [{"year": int(y), "n": len(d), "roi": float(d.pnl.sum() / d.stake.sum())} for y, d in bets.groupby(bets.date.dt.year)]

    def seg(name, mask):
        d = bets[mask]
        return {"segment": name, "bets": len(d), "roi": float(d.pnl.sum() / d.stake.sum()) if len(d) else None,
                "hit": float(d.won.mean()) if len(d) else None, "significant": len(d) >= 300}
    segments = [seg("Favorieten", bets.fav), seg("Underdogs", ~bets.fav), seg("5 rondes", bets.five),
                seg("3 rondes", ~bets.five), seg("Mannen", ~bets.womens.astype(bool)), seg("Vrouwen", bets.womens.astype(bool)),
                seg("Edge 3-5%", bets.edge < .05), seg("Edge > 5%", bets.edge >= .05)]
    segments += [seg(wc, bets.wc == wc) for wc in MAIN_CLASSES if (bets.wc == wc).sum() >= 30]

    lr = bundle["models"]["logreg"]
    imp, lrm = lr.steps[0][1], lr.steps[2][1]
    names = imp.get_feature_names_out(bundle["cols"])
    coef = pd.Series(np.abs(lrm.coef_[0]), index=names)
    coef = coef[~coef.index.str.startswith("missingindicator")].sort_values(ascending=False)[:15]
    importance = [{"feature": k, "label": LABELS.get(k, k), "weight": float(v / coef.sum())} for k, v in coef.items()]

    W["conf"] = (W.mm - .5).abs()
    wrong = W[(W.mm > .5) != (W.y == 1)].sort_values("conf", ascending=False).head(12)
    misses = [{"date": r.date, "fight": f"{r.fighter_a_name} vs {r.fighter_b_name}",
               "pick": r.fighter_a_name if r.mm > .5 else r.fighter_b_name, "prob": max(r.mm, 1 - r.mm),
               "mkt": max(r.mkt_p, 1 - r.mkt_p) if r.mm > .5 else max(r.mkt_p, 1 - r.mkt_p)} for r in wrong.itertuples()]

    # afgelopen events met modelscore (backtest, out-of-sample)
    ev_df = con.execute("SELECT event_id, name, date, location FROM events ORDER BY date DESC LIMIT 40").df()
    fights_n = con.execute("SELECT event_id, count(*) n FROM fights GROUP BY 1").df().set_index("event_id").n
    allP = allP.merge(fx[["fight_id", "event_id"]], on="fight_id", how="left")
    past = []
    for r in ev_df.itertuples():
        d = allP[allP.event_id == r.event_id]
        bb = bets[bets.fight_id.isin(d.fight_id)]
        past.append({"id": r.event_id, "name": r.name, "date": r.date, "location": r.location,
                     "n_fights": int(fights_n.get(r.event_id, 0)),
                     "type": "PPV" if r.name.startswith("UFC ") and r.name[4:5].isdigit() else "Fight Night",
                     "accuracy": float(((d.blend > .5) == (d.y == 1)).mean()) if len(d) else None,
                     "bets": len(bb), "pnl": float(bb.pnl.sum()) if len(bb) else 0.0})

    # ---------------- data-status
    counts = db.row_counts(con)
    allf = [f for e in events if not e.get("none") for f in e["fights"] if f["card"] != "onbevestigd"]
    n_sb = sum(1 for f in allf if (f.get("odds_info") or {}).get("kind") == "sportsbooks")
    n_pm = sum(1 for f in allf if (f.get("odds_info") or {}).get("kind") == "prediction market")
    last_snap = con.execute("SELECT max(captured_at) FROM odds_snapshots").fetchall()[0][0]
    n_snap = con.execute("SELECT count(DISTINCT captured_at) FROM odds_snapshots").fetchall()[0][0]
    odds_status = {"name": "Odds (komend)", "source": "BestFightOdds.com", "until": str(last_snap)[:16] if last_snap else None,
                   "status": "ok" if n_sb + n_pm == len(allf) else "deels",
                   "note": f"{n_sb + n_pm} van {len(allf)} gevechten: {n_sb} via bookmakers, {n_pm} alleen Polymarket · {n_snap} meting(en)"}
    status = {
        "counts": counts,
        "sources": [
            {"name": "Events & gevechten", "source": "Kaggle neelagiriaditya (ufcstats)", "until": str(ms), "status": "achter",
             "note": "Events na 8 aug 2026 ontbreken (~14 events)"},
            {"name": "Stats per ronde", "source": "Kaggle neelagiriaditya (ufcstats)", "until": str(ms), "status": "achter",
             "note": f"{counts['fight_stats_round']:,} rijen".replace(",", ".")},
            {"name": "Odds (historisch)", "source": "Kaggle mdabbert", "until": "2026-03-28", "status": "achter",
             "note": "Slotodds, 95% gekoppeld"},
            odds_status,
            {"name": "ufcstats-scraper", "source": "ufcstats.com", "until": None, "status": "fout",
             "note": "Site toont bot-controle; scraper stopt netjes"},
            {"name": "Nieuws & kamp", "source": "nog niet gebouwd", "until": None, "status": "uit", "note": "Fase 7"},
        ],
        "gaps": {
            "fighters_no_reach": int(con.execute("SELECT count(*) FROM fighters WHERE reach_cm IS NULL").fetchone()[0]),
            "fighters_no_dob": int(con.execute("SELECT count(*) FROM fighters WHERE dob IS NULL").fetchone()[0]),
            "fights_no_odds_since_2010": int(con.execute("""SELECT count(*) FROM fights f WHERE event_date>='2010-03-21'
                AND event_date<='2026-03-28' AND NOT EXISTS (SELECT 1 FROM odds o WHERE o.fight_id=f.fight_id)""").fetchone()[0]),
            "odds_unmatched": 340,
            "events_no_stats": int(con.execute("""SELECT count(*) FROM events e WHERE NOT EXISTS (SELECT 1 FROM fights f
                JOIN fight_stats_round s USING(fight_id) WHERE f.event_id=e.event_id)""").fetchone()[0]),
        },
        "pipeline": [
            {"step": "Kaggle-import", "ok": True}, {"step": "Features (point-in-time)", "ok": True},
            {"step": "Walk-forward backtest", "ok": True}, {"step": "Voorspellingen komende kaarten", "ok": True},
            {"step": "Live odds ophalen", "ok": True}, {"step": "Nieuws & kamp", "ok": False},
        ],
    }

    open_bets = con.execute("""SELECT b.*, p.event_id, p.event_date, p.fighter_a_name || ' vs ' || p.fighter_b_name AS fight
        FROM bets b LEFT JOIN predictions p ON p.fight_id=b.fight_id AND p.model_version=b.model_version
        ORDER BY b.placed_at""").df().to_dict("records")
    site = {
        "meta": {"version": version, "trained_until": bundle["trained_until"], "generated_at": datetime.now(),
                 "edge_min": EDGE_MIN, "kelly": KELLY_FRAC, "max_stake": MAX_STAKE, "bankroll": 1000},
        "events": events, "past_events": past, "fighters": fighters,
        "performance": {"metrics": metrics, "by_year": by_year, "calibration": calib, "roi_year": roi_year,
                        "segments": segments, "importance": importance, "misses": misses,
                        "sim": {"bets": len(bets), "roi": float(bets.pnl.sum() / bets.stake.sum()),
                                "hit": float(bets.won.mean()), "bankroll": float(bets.bank.iloc[-1]),
                                "max_dd": float((1 - bets.bank / bets.bank.cummax()).max()),
                                "curve": [{"date": r.date, "bank": r.bank} for r in bets.iloc[::5].itertuples()]}},
        "bets": open_bets, "paper": scorecard(con), "status": status,
    }
    (OUT / "site.json").write_text(json.dumps(clean(site), ensure_ascii=False))
    bt = W[["date", "y", "mm", "blend", "mkt_p", "odds_a", "odds_b"]].copy()
    bt["date"] = bt.date.dt.strftime("%Y-%m-%d")
    (OUT / "backtest.json").write_text(json.dumps(clean({"cols": list(bt.columns), "rows": bt.values.tolist()})))
    for f in ("site.json", "backtest.json"):
        print(f, f"{(OUT / f).stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
