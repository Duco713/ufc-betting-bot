"""Odds van BestFightOdds.com (robots.txt staat dit toe; alleen /cnadm/ is verboden).

Elke run is een *snapshot*: alle moneylines per bookmaker worden met tijdstempel opgeslagen in
`odds_snapshots`. Zo bouwen we lijnbeweging (opening -> nu -> slot) op voor CLV.

    .venv/bin/python -m src.scrapers.bestfightodds           # homepage = alle komende events
    .venv/bin/python -m src.scrapers.bestfightodds --event ufc-saudi-arabia-4453

Rustig gebruiken: 1 request per run (homepage) of per event, niet vaker dan een paar keer per dag.
"""
from __future__ import annotations

import argparse
import re
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from src import db
from src.importers.kaggle import norm_name

BASE = "https://www.bestfightodds.com"
RAW_DIR = db.ROOT / "data" / "raw" / "bestfightodds"
USER_AGENT = "Mozilla/5.0 (compatible; fightmodel-research/0.1; personal non-commercial research)"
SPORTSBOOKS = {"FanDuel", "Caesars", "BetRivers", "BetWay", "Unibet", "BetMGM", "DraftKings", "Bet365",
               "Pinnacle", "BetOnline", "Bovada", "Bookmaker", "Betcris", "Jazz"}
PREDICTION_MARKETS = {"Polymarket", "Kalshi"}
NL_BOOKS = {"Unibet"}            # in deze lijst én met KSA-vergunning in Nederland

DDL = """
CREATE TABLE IF NOT EXISTS odds_snapshots (
    captured_at TIMESTAMP, source VARCHAR, event_name VARCHAR, event_url VARCHAR, matchup_id VARCHAR,
    fighter_1 VARCHAR, fighter_2 VARCHAR, book VARCHAR, odds_1 INTEGER, odds_2 INTEGER,
    PRIMARY KEY (captured_at, matchup_id, book)
);
"""


# ------------------------------------------------------------------ ophalen
def fetch(url: str) -> str:
    for attempt in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
            if r.status_code == 200:
                return r.text
            if r.status_code in (403, 429):
                raise RuntimeError(f"BestFightOdds weigert ({r.status_code}); later opnieuw proberen.")
        except requests.RequestException:
            pass
        time.sleep(2 ** attempt * 3)
    raise RuntimeError(f"Kon {url} niet ophalen")


def save_raw(html: str, slug: str, ts: datetime) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    p = RAW_DIR / f"{ts:%Y%m%dT%H%M%S}_{slug}.html"
    p.write_text(html)
    return p


# ------------------------------------------------------------------ parsen
def _odds(text: str) -> int | None:
    m = re.search(r"([+-]\d{3,5})", text or "")
    return int(m.group(1)) if m else None


def _book_name(th) -> str:
    t = th.get_text(" ", strip=True)
    t = re.sub(r"\$\d+\s*Bonus.*$", "", t).strip()
    return t


def parse_page(html: str) -> list[dict]:
    """Alle events op een pagina: [{name, url, date_text, fights: [{matchup_id, f1, f2, odds: {book: (o1, o2)}}]}]"""
    soup = BeautifulSoup(html, "lxml")
    events = []
    for wrap in soup.select("div.table-outer-wrapper"):
        head = wrap.select_one(".table-header")
        a = head.select_one("a[href^='/events/']") if head else None
        title = head.get_text(" ", strip=True) if head else ""
        name = re.sub(r"\s+Odds.*$", "", title).strip()
        date_m = re.search(r"Odds\s+([A-Z][a-z]+ \d{1,2}(?:st|nd|rd|th)?)", title)
        tables = wrap.select("table.odds-table")
        if not tables or name.lower().startswith("future events"):
            continue
        t = tables[-1]
        books = [_book_name(th) for th in t.select("thead th")]
        rows = [r for r in t.select("tbody tr") if r.find("th")]
        fights = []
        for r1, r2 in zip(rows[0::2], rows[1::2]):
            n1, n2 = r1.find("th").get_text(" ", strip=True), r2.find("th").get_text(" ", strip=True)
            tag = r1.find(attrs={"data-admin-matchup": True})
            mid = tag.get("data-admin-matchup") if tag else None
            if not mid:  # sommige rijen (bv. props/futures) hebben geen matchup-id
                mid = f"name:{norm_name(n1)}|{norm_name(n2)}"
            c1, c2 = r1.find_all(["th", "td"]), r2.find_all(["th", "td"])
            odds = {}
            for i, book in enumerate(books):
                if i == 0 or not book or book == "Props" or i >= len(c1) or i >= len(c2):
                    continue
                o1, o2 = _odds(c1[i].get_text(" ", strip=True)), _odds(c2[i].get_text(" ", strip=True))
                if o1 is not None and o2 is not None:
                    odds[book] = (o1, o2)
            if re.match(r"(over|under|fight )", n1, re.I):  # props, geen moneyline
                continue
            fights.append({"matchup_id": mid, "f1": n1, "f2": n2, "odds": odds})
        events.append({"name": name, "url": BASE + a["href"] if a else None,
                       "date_text": date_m.group(1) if date_m else None, "fights": fights})
    return events


# ------------------------------------------------------------------ opslaan
def store(con, events: list[dict], ts: datetime) -> int:
    con.execute(DDL)
    n = 0
    for ev in events:
        for f in ev["fights"]:
            for book, (o1, o2) in f["odds"].items():
                con.execute("INSERT OR REPLACE INTO odds_snapshots VALUES (?,?,?,?,?,?,?,?,?,?)",
                            [ts, "bestfightodds", ev["name"], ev["url"], f["matchup_id"], f["f1"], f["f2"], book, o1, o2])
                n += 1
    return n


# ------------------------------------------------------------------ consensus voor een gevecht
def am_to_dec(o: float) -> float:
    return 1 + o / 100 if o > 0 else 1 + 100 / abs(o)


def dec_to_am(d: float) -> int:
    return round((d - 1) * 100) if d >= 2 else round(-100 / (d - 1))


def _consensus(rows: list[tuple]) -> dict | None:
    """rows = [(book, odds_a, odds_b)] -> mediaan van sportsbooks (anders prediction markets)."""
    sb = [r for r in rows if r[0] in SPORTSBOOKS]
    use, kind = (sb, "sportsbooks") if sb else ([r for r in rows if r[0] in PREDICTION_MARKETS], "prediction market")
    if not use:
        return None
    da = statistics.median(am_to_dec(r[1]) for r in use)
    db_ = statistics.median(am_to_dec(r[2]) for r in use)
    return {"odds_a": dec_to_am(da), "odds_b": dec_to_am(db_), "n_books": len(use), "kind": kind}


def odds_for(con, name_a: str, name_b: str) -> dict | None:
    """Laatste consensus + per bookmaker + historie voor een gevecht, op naam (volgorde maakt niet uit)."""
    con.execute(DDL)
    ka, kb = norm_name(name_a), norm_name(name_b)
    df = con.execute("SELECT * FROM odds_snapshots WHERE source='bestfightodds' ORDER BY captured_at").df()
    if df.empty:
        return None
    k1, k2 = df.fighter_1.map(norm_name), df.fighter_2.map(norm_name)
    straight, swapped = (k1 == ka) & (k2 == kb), (k1 == kb) & (k2 == ka)
    d = df[straight | swapped].copy()
    if d.empty:
        return None
    sw = swapped[d.index]
    d["oa"] = d.odds_2.where(sw, d.odds_1)
    d["ob"] = d.odds_1.where(sw, d.odds_2)
    hist = []
    for ts, g in d.groupby("captured_at"):
        c = _consensus(list(zip(g.book, g.oa, g.ob)))
        if c:
            hist.append({"captured_at": ts.isoformat(timespec="minutes"), "odds_a": c["odds_a"], "odds_b": c["odds_b"]})
    last_ts = d.captured_at.max()
    g = d[d.captured_at == last_ts]
    cons = _consensus(list(zip(g.book, g.oa, g.ob)))
    if not cons:
        return None
    books = {b: [int(a), int(b_)] for b, a, b_ in zip(g.book, g.oa, g.ob)}
    nl = {b: v for b, v in books.items() if b in NL_BOOKS}
    return {**cons, "captured_at": last_ts.isoformat(timespec="minutes"), "books": books, "nl_books": nl,
            "opening": hist[0] if hist else None, "history": hist, "event_name": g.event_name.iloc[0]}


# ------------------------------------------------------------------ CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", help="event-slug, bv. ufc-saudi-arabia-4453 (standaard: homepage)")
    ap.add_argument("--db", default=str(db.DEFAULT_DB))
    a = ap.parse_args(argv)
    ts = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    url = f"{BASE}/events/{a.event}" if a.event else BASE + "/"
    html = fetch(url)
    save_raw(html, a.event or "home", ts)
    events = parse_page(html)
    con = db.connect(a.db)
    n = store(con, events, ts)
    print(f"Snapshot {ts:%Y-%m-%d %H:%M} UTC: {n} odds-regels")
    for ev in events:
        with_odds = sum(1 for f in ev["fights"] if f["odds"])
        print(f"  {ev['name']:<28} {ev['date_text'] or '':<14} {len(ev['fights']):>2} gevechten, {with_odds} met odds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
