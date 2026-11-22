"""Parse-tests op HTML-fixtures.

LET OP: de fixtures (behalve bot_challenge.html) zijn synthetisch nagebouwd naar de
markup van ufcstats.com, omdat de live site bij het bouwen een bot-challenge gaf.
Vervang ze door echte pagina's uit data/raw/ufcstats/ zodra die beschikbaar zijn.
"""
from datetime import date
from pathlib import Path

import pytest

from src import db
from src.scrapers import ufcstats as u

FIX = Path(__file__).parent / "fixtures"


def read(name):
    return (FIX / name).read_text(encoding="utf-8")


def test_event_list():
    evs = u.parse_event_list(read("event_list.html"))
    assert [e["event_id"] for e in evs] == ["aaaa111122223333", "bbbb111122223333"]
    assert evs[0]["name"] == "UFC 999: Alpha vs. Bravo"
    assert evs[0]["date"] == date(2025, 11, 15)
    assert evs[1]["date"] == date(2025, 11, 8)
    assert evs[0]["location"] == "New York City, New York, USA"


def test_event_page():
    url = "http://ufcstats.com/event-details/aaaa111122223333"
    page = u.parse_event_page(read("event_page.html"), url)
    ev = page["event"]
    assert ev["event_id"] == "aaaa111122223333"
    assert ev["name"] == "UFC 999: Alpha vs. Bravo"
    assert ev["date"] == date(2025, 11, 15)
    assert ev["location"] == "New York City, New York, USA"
    f1, f2 = page["fights"]
    assert f1["fight_id"] == "ffff000011112222"
    assert f1["card_position"] == 0
    assert (f1["fighter_a_id"], f1["fighter_b_id"]) == ("1111aaaa1111aaaa", "2222bbbb2222bbbb")
    assert f1["flag"] == "win"
    assert f1["weight_class"] == "Lightweight"
    assert (f1["method_short"], f1["method_detail"]) == ("KO/TKO", "Punches")
    assert (f1["end_round"], f1["end_time_sec"]) == (2, 201)
    assert f1["is_title_fight"] and f1["bonus_perf"] and not f1["bonus_fight"]
    assert f2["flag"] == "draw"
    assert f2["weight_class"] == "Women's Strawweight"
    assert f2["method_detail"] is None
    assert not f2["is_title_fight"]


def test_fight_page():
    url = "http://ufcstats.com/fight-details/ffff000011112222"
    res = u.parse_fight_page(read("fight_page.html"), url)
    f = res["fight"]
    assert f["fight_id"] == "ffff000011112222"
    assert f["fighter_a_name"] == "Alex Alpha" and f["result_a"] == "W" and f["result_b"] == "L"
    assert f["winner_id"] == "1111aaaa1111aaaa"
    assert f["bout_title"] == "UFC Lightweight Title Bout"
    assert f["is_title_fight"] and f["bonus_perf"]
    assert f["method"] == "KO/TKO"
    assert (f["end_round"], f["end_time_sec"]) == (2, 201)
    assert f["time_format"] == "5 Rnd (5-5-5-5-5)" and f["scheduled_rounds"] == 5
    assert f["referee"] == "Herb Dean"
    assert f["details"] == "Punches to Head At Distance"

    stats = {(s["fighter_id"], s["round"]): s for s in res["stats"]}
    assert len(stats) == 6  # 2 vechters x (totaal + 2 rondes)
    a0 = stats[("1111aaaa1111aaaa", 0)]
    assert a0["kd"] == 1
    assert (a0["sig_str_landed"], a0["sig_str_att"]) == (30, 60)
    assert (a0["total_str_landed"], a0["total_str_att"]) == (45, 80)
    assert (a0["td_landed"], a0["td_att"]) == (2, 4)
    assert a0["sub_att"] == 0 and a0["rev"] == 0 and a0["ctrl_sec"] == 250
    assert (a0["head_landed"], a0["head_att"]) == (20, 45)
    assert (a0["ground_landed"], a0["ground_att"]) == (5, 7)
    b2 = stats[("2222bbbb2222bbbb", 2)]
    assert b2["ctrl_sec"] is None  # '--'
    assert (b2["distance_landed"], b2["distance_att"]) == (7, 18)
    a1 = stats[("1111aaaa1111aaaa", 1)]
    assert (a1["sig_str_landed"], a1["clinch_landed"], a1["ctrl_sec"]) == (18, 2, 120)
    # rondes tellen op tot de totalen
    for col in ("sig_str_landed", "head_landed", "td_landed"):
        assert a1[col] + stats[("1111aaaa1111aaaa", 2)][col] == a0[col]
    assert set(res["stats"][0]) == {"fight_id", "fighter_id", "round", *db.STAT_COLUMNS}


def test_fighter_page():
    r = u.parse_fighter_page(read("fighter_page.html"), "http://ufcstats.com/fighter-details/1111aaaa1111aaaa")
    assert r["fighter_id"] == "1111aaaa1111aaaa"
    assert r["name"] == "Alex Alpha" and r["nickname"] == "The Alpha"
    assert r["height_in"] == 71 and r["height_cm"] == 180.3
    assert r["weight_lbs"] == 155.0 and r["reach_in"] == 72.0 and r["reach_cm"] == 182.9
    assert r["stance"] == "Southpaw" and r["dob"] == date(1988, 7, 13)
    assert (r["record_wins"], r["record_losses"], r["record_draws"], r["record_nc"]) == (22, 6, 0, 1)


def test_bot_challenge_detected():
    assert u.looks_like_challenge(read("bot_challenge.html"))
    assert not u.looks_like_challenge(read("event_page.html"))


def test_offline_pipeline_idempotent(tmp_path):
    """Volledige pipeline uit een vooraf gevulde cache, twee keer -> zelfde aantallen."""
    from datetime import timedelta
    cache = tmp_path / "cache"
    f = u.Fetcher(cache_dir=cache, offline=True)
    ev_list = read("event_list.html").replace("November 15, 2025", "January 01, 2020") \
                                     .replace("Nov 08, 2025", (date.today() + timedelta(days=30)).strftime("%b %d, %Y"))
    pages = {
        u.COMPLETED_URL: ev_list,
        "http://ufcstats.com/event-details/aaaa111122223333": read("event_page.html"),
        "http://ufcstats.com/fight-details/ffff000011112222": read("fight_page.html"),
        "http://ufcstats.com/fight-details/eeee000011112222": read("fight_page.html"),
        u.UPCOMING_URL: ev_list,
        "http://ufcstats.com/event-details/bbbb111122223333": read("event_page.html"),
    }
    for fid in ("1111aaaa1111aaaa", "2222bbbb2222bbbb", "3333cccc3333cccc", "4444dddd4444dddd"):
        pages[f"http://ufcstats.com/fighter-details/{fid}"] = read("fighter_page.html")
    for url, html in pages.items():
        f.cache_path(url).write_text(html, encoding="utf-8")
    con = db.connect(tmp_path / "t.duckdb")
    s = u.Scraper(f, con)
    for _ in range(2):
        s.scrape_completed()
        s.scrape_upcoming()
        s.scrape_fighters()
    counts = db.row_counts(con)
    assert counts["events"] == 2  # 1 afgerond (2020) + 1 komend (lijst gefilterd op datum)
    assert counts["fights"] == 2
    assert counts["fight_stats_round"] == 12  # 2 gevechten x 2 vechters x (totaal + 2 rondes)
    assert counts["fighters"] == 4
    row = con.execute("SELECT winner_id, is_title_fight, scheduled_rounds, referee FROM fights "
                      "WHERE fight_id='ffff000011112222'").fetchone()
    assert row == ("1111aaaa1111aaaa", True, 5, "Herb Dean")
    assert con.execute("SELECT height_cm FROM fighters WHERE fighter_id='1111aaaa1111aaaa'").fetchone()[0] == 180.3


def test_offline_cache_miss(tmp_path):
    f = u.Fetcher(cache_dir=tmp_path, offline=True)
    with pytest.raises(u.CacheMiss):
        f.get("http://ufcstats.com/fight-details/0000")
