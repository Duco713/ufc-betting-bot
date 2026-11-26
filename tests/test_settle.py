from datetime import datetime

import pytest

from src import db
from src.predict.upcoming import PREDICTIONS_DDL
from src.scrapers.bestfightodds import store
from src.settle import event_start_utc, scorecard, settle

EV = {"id": "ev1", "datum": "2026-12-05", "aanvang_nl": {"prelims": "16:00"}}


def _setup(tmp_path):
    con = db.connect(str(tmp_path / "t.duckdb"))
    con.execute(PREDICTIONS_DDL)
    con.execute("ALTER TABLE predictions ADD COLUMN IF NOT EXISTS odds_info VARCHAR")
    con.execute("""INSERT INTO predictions (fight_id, model_version, created_at, locked_at, event_id, event_date,
        fighter_a_id, fighter_a_name, fighter_b_id, fighter_b_name, prob_final_a)
        VALUES ('ev1-01','v','2026-12-05 08:00','2026-12-05 08:00','ev1','2026-12-05','ida','Alpha One','idb','Bravo Two',0.6)""")
    con.execute("""INSERT INTO bets (bet_id, fight_id, model_version, placed_at, pick_id, pick_name, odds_taken, prob, stake, result)
        VALUES ('b1','ev1-01','v','2026-12-05 08:00','ida','Alpha One',2.0,0.6,20,'open')""")
    f = lambda o: [{"name": "E", "url": None, "fights": [{"matchup_id": "1", "f1": "Alpha One", "f2": "Bravo Two", "odds": o}]}]
    store(con, f({"Unibet": (100, -120), "FanDuel": (100, -120)}), datetime(2026, 12, 5, 8))
    store(con, f({"Unibet": (-125, 105), "FanDuel": (-125, 105)}), datetime(2026, 12, 5, 14))   # slot
    store(con, f({"Unibet": (-300, 250), "FanDuel": (-300, 250)}), datetime(2026, 12, 5, 16))   # na aanvang: negeren
    return con


def test_event_start():
    assert event_start_utc(EV) == datetime(2026, 12, 5, 15)
    assert event_start_utc({"datum": "2026-12-12", "aanvang_nl": {"main_card": "03:00 (zondag)"}}) == datetime(2026, 12, 13, 0)


def test_settle_win_and_clv(tmp_path):
    con = _setup(tmp_path)
    res = {"ev1": {"bron": "test", "gevechten": [{"winnaar": "Alpha One", "verliezer": "Bravo Two", "methode": "KO/TKO", "ronde": 1}]}}
    settle(con, res, {"ev1": EV})
    r, pnl, oc, clv = con.execute("SELECT result, pnl, odds_closing, clv FROM bets").fetchall()[0]
    assert r == "W" and pnl == pytest.approx(20)
    assert oc == pytest.approx(1.8) and clv == pytest.approx(2.0 / 1.8 - 1)
    sc = scorecard(con)
    assert sc["fights"] == 1 and sc["accuracy"] == 1 and sc["roi"] == pytest.approx(1.0)


def test_settle_loss_and_draw(tmp_path):
    con = _setup(tmp_path)
    settle(con, {"ev1": {"gevechten": [{"winnaar": "Bravo Two", "verliezer": "Alpha One"}]}}, {"ev1": EV})
    assert con.execute("SELECT result, pnl FROM bets").fetchall()[0] == ("L", -20)
    settle(con, {"ev1": {"gevechten": [{"a": "Bravo Two", "b": "Alpha One", "uitslag": "draw"}]}}, {"ev1": EV})
    assert con.execute("SELECT result, pnl FROM bets").fetchall()[0] == ("push", 0)
