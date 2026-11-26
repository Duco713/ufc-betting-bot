import json
from datetime import datetime

import src.tipsters as T
from src import db
from src.predict.upcoming import PREDICTIONS_DDL
from src.scrapers.bestfightodds import store
from src.settle import RESULTS_DDL


def test_scoreboard(tmp_path, monkeypatch):
    con = db.connect(str(tmp_path / "t.duckdb"))
    con.execute(PREDICTIONS_DDL)
    con.execute(RESULTS_DDL)
    con.execute("""INSERT INTO predictions (fight_id, model_version, event_id, fighter_a_name, fighter_b_name, prob_final_a)
                   VALUES ('ev1-01','v','ev1','Alpha One','Bravo Two',0.6)""")
    con.execute("INSERT INTO paper_results (fight_id, event_id, outcome, y_a) VALUES ('ev1-01','ev1','win',0)")
    f = lambda o: [{"name": "E", "url": None, "fights": [{"matchup_id": "1", "f1": "Alpha One", "f2": "Bravo Two", "odds": o}]}]
    store(con, f({"Unibet": (-150, 130)}), datetime(2026, 12, 4, 20))
    store(con, f({"Unibet": (-120, 100)}), datetime(2026, 12, 5, 14))
    up = tmp_path / "up.json"
    up.write_text(json.dumps({"weekenden": [{"event": {"id": "ev1", "datum": "2026-12-05", "aanvang_nl": {"prelims": "16:00"}}}]}))
    picks = tmp_path / "picks.json"
    picks.write_text(json.dumps({"ev1": {"x": [
        {"captured_at": "2026-12-04T21:00", "picks": [{"a": "Bravo Two", "b": "Alpha One", "pick": "Bravo Two"}]},
        {"captured_at": "2026-12-05T18:00", "picks": [{"a": "Bravo Two", "b": "Alpha One", "pick": "Alpha One"}]}]}}))
    monkeypatch.setattr(T, "UPCOMING_JSON", up)
    monkeypatch.setattr(T, "PICKS", picks)
    monkeypatch.setattr(T, "SOURCES", tmp_path / "none.json")
    monkeypatch.setattr(T, "_utcnow", lambda: datetime(2026, 12, 6))
    sb = T.scoreboard(con)[0]
    # de pick ná de aanvang telt niet: Bravo Two @ 2.30, gewonnen; model zat fout; slot 2.00 -> CLV +15%
    assert sb["accuracy"] == 1 and sb["model_accuracy_same"] == 0
    assert abs(sb["roi"] - 1.3) < 1e-9 and abs(sb["avg_clv"] - 0.15) < 1e-9
