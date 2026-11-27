from datetime import date

import pandas as pd

from src.importers.wiki_orgs import event_links, page_events, parse_date, to_rows
from src.models.crossorg import TIER_START, add_elo_tiers

RESULTS = """<table class="toccolours"><tr><th>Weight class</th><th></th><th></th><th></th><th>Method</th><th>Round</th><th>Time</th></tr>
<tr><td>Lightweight</td><td>John Doe</td><td>def.</td><td>Max Roe</td><td>Decision (unanimous) (30–27)</td><td>3</td><td>5:00</td></tr>
<tr><td>Welterweight</td><td>Ann Bee</td><td>def.</td><td>Cid Dee</td><td>TKO (punches)</td><td>1</td><td>2:10</td></tr></table>"""


def page(*events):
    html = ""
    for name, d, n_tables in events:
        html += f'<h2 id="x">{name}</h2><table class="infobox"><tr><th>{name}</th></tr><tr><th>Date</th><td>{d}</td></tr></table>'
        html += RESULTS * n_tables
    return html


def test_parse_date_formats():
    assert parse_date("January 21, 2017") == date(2017, 1, 21)
    assert parse_date("21 January 2017[1]") == date(2017, 1, 21)
    assert parse_date("Sept. nonsense") is None


def test_page_events_groups_tables_under_one_infobox():
    evs = page_events(page(("Bellator 1", "March 3, 2017", 2), ("Bellator 2", "4 April 2017", 1)))
    assert [(e["name"], e["date"], len(e["fights"])) for e in evs] == [
        ("Bellator 1", date(2017, 3, 3), 4), ("Bellator 2", date(2017, 4, 4), 2)]
    assert evs[0]["fights"][1]["a"] == "Ann Bee" and evs[0]["fights"][1]["method"] == "KO/TKO"


def test_page_events_fallback_date_for_event_page_without_infobox():
    evs = page_events(RESULTS, date(2019, 5, 9), "PFL 1")
    assert evs[0]["date"] == date(2019, 5, 9) and evs[0]["name"] == "PFL 1"


def test_event_links_skip_anchors():
    html = """<table class="wikitable"><tr><th>#</th><th>Event</th><th>Date</th></tr>
    <tr><td>1</td><td><a href="/wiki/PFL_1_(2019_season)">PFL 1</a></td><td>May 9, 2019</td></tr>
    <tr><td>2</td><td><a href="/wiki/2025_in_Cage_Warriors#CW_199">CW 199</a></td><td>6 December 2025</td></tr></table>"""
    assert event_links(html) == [{"title": "PFL_1_(2019_season)", "name": "PFL 1", "date": date(2019, 5, 9)}]


def test_to_rows_same_fight_twice_is_one_row():
    ev = page_events(page(("E", "March 3, 2017", 1)))[0]
    rows = to_rows([{**ev, "org": "Cage Warriors"}, {**ev, "org": "Cage Warriors"}])
    assert len(rows) == 2 and rows[0]["tier"] == 3


def test_elo_starts_per_tier_and_transfers():
    f = pd.DataFrame([
        {"fight_id": "1", "date": pd.Timestamp("2017-01-01"), "a": "x", "b": "y", "result_a": "W", "method": "Decision", "tier": 3},
        {"fight_id": "2", "date": pd.Timestamp("2018-01-01"), "a": "x", "b": "z", "result_a": "W", "method": "Decision", "tier": 1},
    ])
    long = pd.DataFrame({"fight_id": ["1", "1", "2", "2"], "fighter_id": ["x", "y", "x", "z"], "opp_id": ["y", "x", "z", "x"]})
    long = add_elo_tiers(long, f)
    assert long.elo.iloc[0] == TIER_START[3]                       # eerste gevecht regionaal
    assert long.elo.iloc[2] > TIER_START[3]                        # winst neemt hij mee naar de UFC
    assert long.elo.iloc[3] == TIER_START[1]                       # UFC-vechter start op UFC-niveau
