"""Tipsters volgen: picks van publieke voorspellers vastleggen en na het event scoren.

picks.json:
  {"<event_id>": {"<bron_id>": [ {"captured_at": "2026-12-04T20:00", "url": "...",
                                   "picks": [{"a": "Naam", "b": "Naam", "pick": "Naam", "prob": 0.62}]} ]}}
  (meerdere metingen per bron mogen; de laatste vóór de aanvang telt)

    .venv/bin/python -m src.tipsters            # scorebord tonen
"""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from src import db
from src.importers.kaggle import norm_name
from src.models.train import am_to_dec
from src.predict.upcoming import BET_BOOK, UPCOMING_JSON
from src.scrapers.bestfightodds import odds_for
from src.settle import RESULTS_DDL, event_start_utc

DIR = db.ROOT / "data" / "tipsters"
PICKS = DIR / "picks.json"
SOURCES = DIR / "bronnen.json"


def _utcnow() -> datetime:
    return datetime.utcnow()


def _price(oi: dict | None, pick_is_a: bool) -> float | None:
    if not oi or oi.get("kind") != "sportsbooks":
        return None
    bo = (oi.get("books") or {}).get(BET_BOOK)
    o = (bo[0] if pick_is_a else bo[1]) if bo else (oi["odds_a"] if pick_is_a else oi["odds_b"])
    return float(am_to_dec(o))


def scored_picks(con) -> pd.DataFrame:
    """Eén rij per (bron, gevecht): pick, uitslag, odds bij pick en slotodds."""
    con.execute(RESULTS_DDL)
    allp = json.loads(PICKS.read_text()) if PICKS.exists() else {}
    events = {w["event"]["id"]: w["event"] for w in json.loads(UPCOMING_JSON.read_text())["weekenden"] if w.get("event")}
    preds = con.execute("SELECT fight_id, event_id, fighter_a_name, fighter_b_name, prob_final_a FROM predictions").df()
    res = con.execute("SELECT fight_id, outcome, y_a FROM paper_results").df().set_index("fight_id")
    rows = []
    for ev_id, by_src in allp.items():
        ev = events.get(ev_id)
        if not ev:
            continue
        start = event_start_utc(ev)
        P = preds[preds.event_id == ev_id]
        for src, caps in by_src.items():
            caps = [c for c in caps if datetime.fromisoformat(c["captured_at"]) < start]
            if not caps:
                continue
            cap = max(caps, key=lambda c: c["captured_at"])
            t = datetime.fromisoformat(cap["captured_at"])
            for pk in cap["picks"]:
                names = {norm_name(pk["a"]), norm_name(pk["b"])}
                m = P[[{norm_name(x), norm_name(y)} == names for x, y in zip(P.fighter_a_name, P.fighter_b_name)]]
                if m.empty:
                    continue
                p = m.iloc[0]
                pick_is_a = norm_name(pk["pick"]) == norm_name(p.fighter_a_name)
                r = res.loc[p.fight_id] if p.fight_id in res.index else None
                y = None if r is None or pd.isna(r.y_a) else int(r.y_a)
                at_pick = odds_for(con, p.fighter_a_name, p.fighter_b_name, before=t)
                started = _utcnow() >= start                  # slotodds/CLV pas na de aanvang
                close = odds_for(con, p.fighter_a_name, p.fighter_b_name, before=start) if started else None
                dec, dec_c = _price(at_pick, pick_is_a), _price(close, pick_is_a)
                mkt_fav_a = close and close["kind"] == "sportsbooks" and am_to_dec(close["odds_a"]) < am_to_dec(close["odds_b"])
                rows.append({
                    "source": src, "event_id": ev_id, "fight_id": p.fight_id, "fight": f"{p.fighter_a_name} vs {p.fighter_b_name}",
                    "pick": p.fighter_a_name if pick_is_a else p.fighter_b_name, "prob": pk.get("prob"),
                    "captured_at": cap["captured_at"], "url": cap.get("url"),
                    "outcome": None if r is None else r.outcome,
                    "correct": None if y is None else int((y == 1) == pick_is_a),
                    "model_correct": None if y is None or pd.isna(p.prob_final_a) else int((p.prob_final_a > .5) == (y == 1)),
                    "picked_fav": None if not close or close["kind"] != "sportsbooks" else int(bool(mkt_fav_a) == pick_is_a),
                    "fav_correct": None if y is None or not close or close["kind"] != "sportsbooks" else int(bool(mkt_fav_a) == (y == 1)),
                    "odds": dec, "odds_closing": dec_c, "clv": dec / dec_c - 1 if dec and dec_c else None,
                    "pnl": None if y is None or not dec else ((dec - 1) if (y == 1) == pick_is_a else -1.0),
                })
    return pd.DataFrame(rows)


def scoreboard(con) -> list[dict]:
    names = {s["id"]: s for s in json.loads(SOURCES.read_text())["bronnen"]} if SOURCES.exists() else {}
    D = scored_picks(con)
    out = []
    if D.empty:
        return out
    for src, d in D.groupby("source"):
        s = d.dropna(subset=["correct"])
        b = d.dropna(subset=["pnl"])
        out.append({
            "id": src, "name": names.get(src, {}).get("naam", src), "type": names.get(src, {}).get("type"),
            "picks": len(d), "settled": len(s), "accuracy": float(s.correct.mean()) if len(s) else None,
            "model_accuracy_same": float(s.model_correct.dropna().mean()) if s.model_correct.notna().any() else None,
            "fav_accuracy_same": float(s.fav_correct.dropna().mean()) if s.fav_correct.notna().any() else None,
            "fav_share": float(d.picked_fav.dropna().mean()) if d.picked_fav.notna().any() else None,
            "roi": float(b.pnl.sum() / len(b)) if len(b) else None,
            "avg_clv": float(d.clv.dropna().mean()) if d.clv.notna().any() else None,
            "last_capture": d.captured_at.max(),
        })
    return sorted(out, key=lambda x: (x["accuracy"] is None, -(x["accuracy"] or 0)))


def main() -> int:
    con = db.connect()
    sb = scoreboard(con)
    if not sb:
        print("Nog geen picks in data/tipsters/picks.json")
    for s in sb:
        print(json.dumps(s, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
