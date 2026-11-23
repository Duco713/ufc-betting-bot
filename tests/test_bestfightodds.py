from src.scrapers.bestfightodds import _consensus, dec_to_am, am_to_dec, parse_page

HTML = """
<div class="table-outer-wrapper"><div class="table-header"><a href="/events/ufc-test-1">UFC Test</a> Odds December 5th</div>
<table class="odds-table"><tr><th>x</th></tr></table>
<table class="odds-table"><thead><tr><th></th><th>Polymarket$25 Bonusi</th><th>FanDuel</th><th>Unibet</th><th>Props</th></tr></thead>
<tbody>
<tr><th data-admin-matchup="1"><span>Alpha One</span></th><td class="but-sg">-150 ▼</td><td>-160</td><td>-155</td><td>+5</td></tr>
<tr><th><span>Bravo Two</span></th><td>+140</td><td>+130</td><td>+125</td><td></td></tr>
<tr><th><span>Over 2&#189; rounds</span></th><td>-200</td><td>-210</td><td></td><td></td></tr>
<tr><th><span>Under 2&#189; rounds</span></th><td>+150</td><td>+160</td><td></td><td></td></tr>
</tbody></table></div>
<div class="table-outer-wrapper"><div class="table-header">Future Events</div><table class="odds-table"></table></div>
"""


def test_parse_page_skips_props_and_future_events():
    ev = parse_page(HTML)
    assert len(ev) == 1 and ev[0]["name"] == "UFC Test" and ev[0]["url"].endswith("/events/ufc-test-1")
    f = ev[0]["fights"]
    assert len(f) == 1
    assert f[0]["matchup_id"] == "1" and f[0]["f1"] == "Alpha One"
    assert f[0]["odds"] == {"Polymarket": (-150, 140), "FanDuel": (-160, 130), "Unibet": (-155, 125)}


def test_consensus_prefers_sportsbooks():
    c = _consensus([("Polymarket", -300, 250), ("FanDuel", -160, 130), ("Unibet", -150, 125)])
    assert c["kind"] == "sportsbooks" and c["n_books"] == 2
    assert -160 <= c["odds_a"] <= -150
    pm = _consensus([("Polymarket", -300, 250)])
    assert pm["kind"] == "prediction market" and pm["odds_a"] == -300


def test_odds_roundtrip():
    for o in (-1150, -200, -101, 100, 125, 376):
        assert abs(dec_to_am(am_to_dec(o)) - o) <= 1


def test_history_only_same_kind(tmp_path):
    from datetime import datetime
    from src import db
    from src.scrapers.bestfightodds import odds_for, store
    con = db.connect(str(tmp_path / "t.duckdb"))
    ev = lambda odds: [{"name": "E", "url": None, "fights": [{"matchup_id": "1", "f1": "A B", "f2": "C D", "odds": odds}]}]
    store(con, ev({"Polymarket": (1150, -1150)}), datetime(2026, 11, 22))
    store(con, ev({"Polymarket": (285, -317), "Caesars": (250, -350)}), datetime(2026, 11, 23))
    o = odds_for(con, "C D", "A B")
    assert o["kind"] == "sportsbooks" and (o["odds_a"], o["odds_b"]) == (-350, 250)
    assert len(o["history"]) == 1 and o["opening"]["odds_a"] == -350
