"""Voorspellingen voor de komende kaarten uit data/upcoming/testweekenden.json.

    .venv/bin/python -m src.predict.upcoming            # alle events in het json-bestand
    .venv/bin/python -m src.predict.upcoming --lock     # vastzetten (paper trading, niet meer wijzigen)

Schrijft naar de tabellen `predictions` en `bets` (virtueel) en naar reports/predictions_<datum>.md.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime

import joblib
import numpy as np
import pandas as pd

from src import db
from src.features.build import build_all, resolve_fighter
from src.scrapers.bestfightodds import odds_for
from src.models.train import (EDGE_MIN, MODEL_DIR, REPORT_DIR, am_to_dec, apply_stacker, fair_prob,
                              kelly_stake, mirror, predict_sym)

UPCOMING_JSON = db.ROOT / "data" / "upcoming" / "testweekenden.json"
BANKROLL = 1000.0
MAX_EVENT = 0.06      # max. 6% van de bankroll per event
BET_BOOK = "Unibet"   # hier zet je echt in: advies en inzet rekenen met deze prijs

LABELS = {  # leesbare namen voor de uitleg
    "d_elo": "Elo-rating", "d_n_fights": "UFC-ervaring", "d_win_pct": "Winstpercentage",
    "d_finish_rate": "Finish-ratio", "d_ko_losses": "KO-verliezen", "d_cage_minutes": "Kooitijd",
    "d_days_since": "Tijd sinds laatste gevecht", "d_last_ko_loss": "Laatste gevecht KO-verlies",
    "d_last3_win": "Vorm (laatste 3)", "d_ew_win": "Recente vorm (gewogen)", "d_opp_elo_avg": "Niveau tegenstanders",
    "d_elo_trend": "Elo-trend", "d_streak": "Win-/verliesreeks", "d_age": "Leeftijd", "d_height_cm": "Lengte",
    "d_reach_cm": "Reach", "d_southpaw": "Stance (southpaw)", "d_slpm": "Sig. strikes per minuut",
    "d_sapm": "Strikes geïncasseerd per minuut", "d_sig_acc": "Striking-nauwkeurigheid",
    "d_sig_def": "Striking-verdediging", "d_td15": "Takedowns per 15 min", "d_td_acc": "Takedown-nauwkeurigheid",
    "d_td_def": "Takedown-verdediging", "d_ctrl_share": "Controletijd", "d_o_ctrl_share": "Controletijd tegenstander",
    "d_sub15": "Submission-pogingen", "d_kd15": "Knockdowns", "d_kd_abs15": "Knockdowns gekregen",
    "d_head_share": "Aandeel hoofdstoten", "d_leg_share": "Aandeel beentrappen", "d_dist_share": "Afstand-striking",
    "d_ground_share": "Grondwerk-striking", "d_sig_diff_pm": "Striking-verschil per minuut",
    "a_age": "Leeftijd A", "b_age": "Leeftijd B", "a_debut": "Debuut A", "b_debut": "Debuut B",
    "five_rounds": "5 rondes", "title": "Titelgevecht", "womens": "Vrouwen",
}

PREDICTIONS_DDL = """
CREATE TABLE IF NOT EXISTS predictions (
    fight_id VARCHAR, model_version VARCHAR, created_at TIMESTAMP, locked_at TIMESTAMP,
    event_id VARCHAR, event_date DATE, fighter_a_id VARCHAR, fighter_a_name VARCHAR,
    fighter_b_id VARCHAR, fighter_b_name VARCHAR, prob_model_a DOUBLE, prob_market_a DOUBLE,
    prob_final_a DOUBLE, odds_a DOUBLE, odds_b DOUBLE, pick VARCHAR, edge DOUBLE, stake DOUBLE,
    reasons JSON, method JSON, flags JSON,
    PRIMARY KEY (fight_id, model_version)
);
CREATE TABLE IF NOT EXISTS bets (
    bet_id VARCHAR PRIMARY KEY, fight_id VARCHAR, model_version VARCHAR, placed_at TIMESTAMP,
    pick_id VARCHAR, pick_name VARCHAR, odds_taken DOUBLE, odds_closing DOUBLE, prob DOUBLE,
    stake DOUBLE, result VARCHAR, pnl DOUBLE, clv DOUBLE, note VARCHAR
);
"""


def upcoming_rows(con, data: dict) -> tuple[pd.DataFrame, list[dict]]:
    rows, meta = [], []
    for w in data["weekenden"]:
        ev = w.get("event")
        if not ev:
            continue
        for f in ev["fights"]:
            if f["kaart"] == "onbevestigd":
                continue
            wc = f["klasse"].split(" (")[0]
            a, b = resolve_fighter(con, f["a"], wc), resolve_fighter(con, f["b"], wc)
            fid = f"{ev['id']}-{f['nr']:02d}"
            rows.append({"fight_id": fid, "event_id": ev["id"], "date": ev["datum"], "a": a, "b": b,
                         "result_a": None, "method": None, "end_round": None, "end_time_sec": None,
                         "scheduled_rounds": f["rondes"], "weight_class": wc,
                         "is_title_fight": "titel" in f["klasse"].lower(),
                         "is_womens": "women" in f["klasse"].lower()})
            meta.append({**f, "fight_id": fid, "event": ev, "a_id": a, "b_id": b})
    return pd.DataFrame(rows), meta


def explain(logreg, x: pd.DataFrame, cols: list[str], p: float, top: int = 6) -> list[dict]:
    """Bijdrage per feature in de logistische regressie (log-odds -> procentpunten, benadering)."""
    imp, sc, lr = logreg.steps[0][1], logreg.steps[1][1], logreg.steps[2][1]
    z = sc.transform(imp.transform(x[cols]))[0]
    names = imp.get_feature_names_out(cols)
    contrib = lr.coef_[0] * z * p * (1 - p) * 100
    s = pd.Series(contrib, index=names)
    s = s[~s.index.str.startswith("missingindicator")]
    s = s.reindex(s.abs().sort_values(ascending=False).index)[:top]
    return [{"feature": k, "label": LABELS.get(k, k), "pp": round(float(v), 1)} for k, v in s.items()]


def method_shares(con) -> pd.DataFrame:
    return con.execute("""
        SELECT winner_id AS fighter_id,
               sum(CASE WHEN method LIKE '%KO%' THEN 1 ELSE 0 END) ko,
               sum(CASE WHEN method LIKE 'Submission%' THEN 1 ELSE 0 END) sub,
               sum(CASE WHEN method LIKE 'Decision%' THEN 1 ELSE 0 END) dec
        FROM fights WHERE winner_id IS NOT NULL GROUP BY 1""").df().set_index("fighter_id")


def method_est(ms: pd.DataFrame, fid: str, p: float) -> dict:
    prior = np.array([0.32, 0.18, 0.50]) * 3          # UFC-gemiddelde als startpunt
    v = ms.loc[fid, ["ko", "sub", "dec"]].values.astype(float) if fid in ms.index else np.zeros(3)
    share = (v + prior) / (v.sum() + 3)
    return {k: round(float(p * s), 3) for k, s in zip(("ko", "sub", "dec"), share)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lock", action="store_true", help="alle voorspellingen nu vastzetten")
    ap.add_argument("--auto-lock", action="store_true",
                    help="events van vandaag of eerder vastzetten (draait in de ververs-taak op de vechtdag)")
    ap.add_argument("--db", default=str(db.DEFAULT_DB))
    a = ap.parse_args(argv)

    bundle = joblib.load(MODEL_DIR / "model.joblib")
    models, cols, version, stacker = bundle["models"], bundle["cols"], bundle["version"], bundle["stacker"]
    con = db.connect(a.db)
    con.execute(PREDICTIONS_DDL)
    con.execute("ALTER TABLE predictions ADD COLUMN IF NOT EXISTS odds_info VARCHAR")
    data = json.loads(UPCOMING_JSON.read_text())
    up, meta = upcoming_rows(con, data)
    locked = {r[0] for r in con.execute(
        "SELECT fight_id FROM predictions WHERE model_version=? AND locked_at IS NOT NULL", [version]).fetchall()}
    today = datetime.now().date().isoformat()

    X = build_all(con, up)
    U = X[X.fight_id.isin(up.fight_id)].set_index("fight_id").loc[up.fight_id].reset_index()
    p_lr, p_gbm = predict_sym(models["logreg"], U, cols), predict_sym(models["gbm"], U, cols)
    U["p_model"] = (p_lr + p_gbm) / 2
    ms = method_shares(con)
    now = datetime.now()
    out, report, new_bets = [], [], []
    for i, m in enumerate(meta):
        r = U.iloc[i]
        pm = float(r.p_model)
        oi = odds_for(con, m["a"], m["b"])
        if oi:
            oa, ob = oi["odds_a"], oi["odds_b"]
            odds_info = {k: oi[k] for k in ("kind", "n_books", "captured_at", "books", "nl_books", "opening", "history")}
            odds_info["source"] = "BestFightOdds"
        else:
            oa, ob = m.get("odds_a"), m.get("odds_b")
            odds_info = {"source": "ufcalendar (handmatig)", "kind": "sportsbooks"} if oa is not None else None
        mkt = float(fair_prob(oa, ob)) if oa is not None else None
        betable = odds_info is not None and odds_info["kind"] == "sportsbooks"
        bo = (odds_info or {}).get("books", {}).get(BET_BOOK)   # [odds_a, odds_b] bij Unibet
        if odds_info is not None:
            odds_info["bet_book"], odds_info["bet_odds"] = BET_BOOK, bo
        pf = float(apply_stacker(stacker, [mkt], [pm])[0]) if mkt is not None else pm
        pick, edge, stake = None, None, 0.0
        if mkt is not None:
            ea, eb = pf - mkt, (1 - pf) - (1 - mkt)
            side_a = ea >= eb
            edge = ea if side_a else eb
            if edge >= EDGE_MIN and betable and bo:
                pp, dd = (pf, am_to_dec(bo[0])) if side_a else (1 - pf, am_to_dec(bo[1]))
                stake = float(kelly_stake(pp, float(dd), BANKROLL))
                pick = (m["a"] if side_a else m["b"]) if stake > 0 else None  # edge > 0 maar EV < 0 door marge
        flags = []
        for side, nm in (("a", m["a"]), ("b", m["b"])):
            if r[f"{side}_debut"] == 1:
                flags.append({"type": "debuut", "fighter": nm, "text": "UFC-debuut: geen UFC-stats, lage betrouwbaarheid"})
        if r.get("d_days_since") is not None and not pd.isna(r.d_days_since) and abs(r.d_days_since) > 365:
            flags.append({"type": "layoff", "fighter": "", "text": "Groot verschil in tijd sinds laatste gevecht"})
        flags.append({"type": "data", "fighter": "", "text": "Stats t/m 8 aug 2026: recentere gevechten ontbreken"})
        if odds_info and odds_info["kind"] != "sportsbooks":
            flags.append({"type": "odds", "fighter": "", "text": "Alleen prediction-market-odds (Polymarket): indicatief, geen virtuele inzet"})
        lock_now = m["fight_id"] not in locked and (a.lock or (a.auto_lock and m["event"]["datum"] <= today))
        rec = {
            "fight_id": m["fight_id"], "model_version": version, "created_at": now,
            "locked_at": now if lock_now else None, "event_id": m["event"]["id"], "event_date": m["event"]["datum"],
            "fighter_a_id": m["a_id"], "fighter_a_name": m["a"], "fighter_b_id": m["b_id"], "fighter_b_name": m["b"],
            "prob_model_a": pm, "prob_market_a": mkt, "prob_final_a": pf, "odds_a": oa, "odds_b": ob,
            "pick": pick, "edge": edge, "stake": round(stake, 2),
            "reasons": json.dumps(explain(models["logreg"], U.iloc[[i]], cols, float(p_lr[i]))),
            "method": json.dumps({"a": method_est(ms, m["a_id"], pf), "b": method_est(ms, m["b_id"], 1 - pf)}),
            "flags": json.dumps(flags),
            "odds_info": json.dumps(odds_info) if odds_info else None,
        }
        if m["fight_id"] not in locked:  # vastgezet = bevroren: niet overschrijven
            out.append(rec)
        if pick and lock_now:
            dd = float(am_to_dec(bo[0] if pick == m["a"] else bo[1]))
            db_bet = {"bet_id": f"{m['fight_id']}-{version}", "fight_id": m["fight_id"], "model_version": version,
                      "placed_at": now, "pick_id": m["a_id"] if pick == m["a"] else m["b_id"], "pick_name": pick,
                      "odds_taken": dd, "prob": pf if pick == m["a"] else 1 - pf, "stake": round(stake, 2),
                      "result": "open"}
            new_bets.append({**db_bet, "event_id": m["event"]["id"]})
        report.append(f"| {m['event']['datum']} | {m['a']} vs {m['b']} | {pf:.1%} / {1 - pf:.1%} | "
                      f"{'' if mkt is None else f'{mkt:.1%}'} | {'' if edge is None else f'{edge:+.1%}'} | "
                      f"{'' if not bo else f'{bo[0]:+d} / {bo[1]:+d}'} | "
                      f"{pick or ('wacht op odds' if mkt is None else 'geen value' if bo or not betable else 'geen Unibet-odds')} | {stake:.0f} |")
    # max. MAX_EVENT van de bankroll per event: inzetten naar rato verlagen
    for ev_id in {b["event_id"] for b in new_bets}:
        evb = [b for b in new_bets if b["event_id"] == ev_id]
        tot = sum(b["stake"] for b in evb)
        if tot > MAX_EVENT * BANKROLL:
            for b in evb:
                b["stake"] = round(b["stake"] * MAX_EVENT * BANKROLL / tot, 2)
    for b in new_bets:
        b.pop("event_id")
        con.execute(f"INSERT OR REPLACE INTO bets ({', '.join(b)}) VALUES ({', '.join('?' * len(b))})", list(b.values()))
    if new_bets or any(r["locked_at"] for r in out):
        print(f"Vastgezet: {sum(1 for r in out if r['locked_at'])} voorspellingen, {len(new_bets)} virtuele bets")
    if not out:
        print("Alles is al vastgezet.")
        return 0
    keys = list(out[0])
    con.execute("DELETE FROM predictions WHERE model_version = ? AND locked_at IS NULL", [version])
    for rec in out:
        con.execute(f"INSERT OR REPLACE INTO predictions ({', '.join(keys)}) VALUES ({', '.join('?' * len(keys))})",
                    [rec[k] for k in keys])
    REPORT_DIR.mkdir(exist_ok=True)
    md = (f"# Voorspellingen ({version}, {now:%Y-%m-%d %H:%M})\n\n"
          "| Datum | Gevecht | Kans A / B | Markt A | Edge | Unibet A / B | Advies | Inzet € |\n|---|---|---|---|---|---|---|---|\n"
          + "\n".join(report) + "\n")
    (REPORT_DIR / f"predictions_{now:%Y%m%d}.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
