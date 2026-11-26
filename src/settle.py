"""Uitslagen verwerken: virtuele bets afrekenen, CLV en modelscore per event.

1. Vul `data/results/uitslagen.json` aan (na het event; bron vermelden), formaat:
   {"ufc-fn-2026-12-05": {"bron": "https://...", "gevechten": [
       {"winnaar": "Israel Adesanya", "verliezer": "Shara Magomedov", "methode": "KO/TKO", "ronde": 2},
       {"a": "X", "b": "Y", "uitslag": "draw"}          # draw / nc / afgelast
   ]}}
2. .venv/bin/python -m src.settle

Slotodds = laatste odds-meting vóór de aanvang van het event (Unibet voor CLV, consensus voor de modelscore).
CLV = genomen odds / slotodds - 1 (positief = je had een betere prijs dan de markt bij aanvang).
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src import db
from src.importers.kaggle import norm_name
from src.models.train import am_to_dec, fair_prob
from src.predict.upcoming import BET_BOOK, PREDICTIONS_DDL, UPCOMING_JSON
from src.scrapers.bestfightodds import odds_for

RESULTS_JSON = db.ROOT / "data" / "results" / "uitslagen.json"
NL = ZoneInfo("Europe/Amsterdam")

RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS paper_results (
    fight_id VARCHAR PRIMARY KEY, event_id VARCHAR, winner_name VARCHAR, outcome VARCHAR, method VARCHAR,
    end_round INTEGER, y_a INTEGER, prob_final_a DOUBLE, close_market_a DOUBLE, close_odds_a INTEGER,
    close_odds_b INTEGER, settled_at TIMESTAMP, source VARCHAR
);
"""


def event_start_utc(ev: dict) -> datetime:
    """Aanvang (UTC, naive) uit `aanvang_nl`; zonder prelim-tijd: main card - 2 uur. Tijden voor 12:00 = nacht erna."""
    t = ev.get("aanvang_nl") or {}
    raw, shift = (t.get("prelims"), 0) if t.get("prelims") else (t.get("main_card", "19:00"), 2)
    hh, mm = (int(x) for x in raw[:5].split(":"))
    day = datetime.fromisoformat(ev["datum"])
    if hh < 12:
        day += timedelta(days=1)
    local = day.replace(hour=hh, minute=mm, tzinfo=NL) - timedelta(hours=shift)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def _match(pred, entry) -> tuple[str, int | None] | None:
    """-> (outcome, y_a) als deze uitslag bij de voorspelling hoort, anders None."""
    names = {norm_name(pred["fighter_a_name"]), norm_name(pred["fighter_b_name"])}
    if "winnaar" in entry:
        w, l = norm_name(entry["winnaar"]), norm_name(entry["verliezer"])
        if {w, l} != names:
            return None
        return "win", int(w == norm_name(pred["fighter_a_name"]))
    if {norm_name(entry["a"]), norm_name(entry["b"])} != names:
        return None
    return entry["uitslag"], None


def settle(con, results: dict, events: dict) -> list[dict]:
    con.execute(PREDICTIONS_DDL)
    con.execute(RESULTS_DDL)
    preds = con.execute("SELECT * FROM predictions WHERE locked_at IS NOT NULL").df()
    bets = con.execute("SELECT * FROM bets").df()
    now = datetime.now()
    summary = []
    for ev_id, res in results.items():
        ev = events.get(ev_id)
        if ev is None:
            print(f"! onbekend event {ev_id}")
            continue
        start = event_start_utc(ev)
        P = preds[preds.event_id == ev_id]
        if P.empty:
            print(f"! {ev_id}: geen vastgezette voorspellingen")
            continue
        n_match = 0
        for _, p in P.iterrows():
            hit = next(((e, r) for e in res["gevechten"] if (r := _match(p, e))), None)
            if not hit:
                continue
            n_match += 1
            e, (outcome, y) = hit
            close = odds_for(con, p.fighter_a_name, p.fighter_b_name, before=start)
            cm = float(fair_prob(close["odds_a"], close["odds_b"])) if close and close["kind"] == "sportsbooks" else None
            con.execute("INSERT OR REPLACE INTO paper_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [
                p.fight_id, ev_id, e.get("winnaar"), outcome, e.get("methode"), e.get("ronde"), y,
                float(p.prob_final_a), cm, close and close["odds_a"], close and close["odds_b"], now, res.get("bron")])
            for _, b in bets[bets.fight_id == p.fight_id].iterrows():
                pick_is_a = b.pick_id == p.fighter_a_id
                if outcome == "win":
                    won = (y == 1) == pick_is_a
                    result, pnl = ("W", b.stake * (b.odds_taken - 1)) if won else ("L", -b.stake)
                else:
                    result, pnl = "push", 0.0
                bo = ((close or {}).get("books") or {}).get(BET_BOOK)
                oc = float(am_to_dec(bo[0] if pick_is_a else bo[1])) if bo else None
                clv = b.odds_taken / oc - 1 if oc else None
                con.execute("UPDATE bets SET result=?, pnl=?, odds_closing=?, clv=? WHERE bet_id=?",
                            [result, float(pnl), oc, clv, b.bet_id])
        missing = len(P) - n_match
        summary.append({"event": ev_id, "matched": n_match, "missing": missing})
        print(f"{ev_id}: {n_match} uitslagen verwerkt" + (f", {missing} zonder uitslag" if missing else ""))
    return summary


def scorecard(con) -> dict:
    """Totaalscore paper trading (alle afgerekende events)."""
    con.execute(RESULTS_DDL)
    R = con.execute("SELECT * FROM paper_results WHERE y_a IS NOT NULL").df()
    B = con.execute("SELECT * FROM bets WHERE result IN ('W','L','push')").df()
    out = {"fights": len(R), "bets": len(B)}
    if len(R):
        p = R.prob_final_a.clip(1e-6, 1 - 1e-6)
        out["accuracy"] = float(((p > .5) == (R.y_a == 1)).mean())
        out["log_loss"] = float(-(R.y_a * p.map(math.log) + (1 - R.y_a) * (1 - p).map(math.log)).mean())
        M = R.dropna(subset=["close_market_a"])
        if len(M):
            q = M.close_market_a.clip(1e-6, 1 - 1e-6)
            out["market_accuracy"] = float(((q > .5) == (M.y_a == 1)).mean())
            out["market_log_loss"] = float(-(M.y_a * q.map(math.log) + (1 - M.y_a) * (1 - q).map(math.log)).mean())
            pm = M.prob_final_a.clip(1e-6, 1 - 1e-6)
            out["model_log_loss_same"] = float(-(M.y_a * pm.map(math.log) + (1 - M.y_a) * (1 - pm).map(math.log)).mean())
            out["n_market"] = len(M)
    if len(B):
        out.update(staked=float(B.stake.sum()), pnl=float(B.pnl.sum()), roi=float(B.pnl.sum() / B.stake.sum()),
                   hit=float((B.result == "W").mean()), avg_clv=float(B.clv.dropna().mean()) if B.clv.notna().any() else None)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(db.DEFAULT_DB))
    a = ap.parse_args(argv)
    con = db.connect(a.db)
    results = json.loads(RESULTS_JSON.read_text()) if RESULTS_JSON.exists() else {}
    data = json.loads(UPCOMING_JSON.read_text())
    events = {w["event"]["id"]: w["event"] for w in data["weekenden"] if w.get("event")}
    if not results:
        print(f"Nog geen uitslagen in {RESULTS_JSON.relative_to(db.ROOT)}")
    settle(con, results, events)
    sc = scorecard(con)
    print(json.dumps(sc, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
