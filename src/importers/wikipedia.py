"""Uitslagen van recente UFC-events van Wikipedia (gat na de Kaggle-data, die stopt op 8 aug 2026).

Alleen uitslagen: winnaar, methode, ronde, tijd, gewichtsklasse. Geen stats per ronde; het model telt
deze gevechten mee voor Elo, record, vorm en tijd sinds laatste gevecht, niet voor striking-gemiddelden.

    .venv/bin/python -m src.importers.wikipedia --since 2026-08-09        # standaard: na laatste event in de DB
    .venv/bin/python -m src.importers.wikipedia --dry-run                 # alleen tonen

Bron: Wikipedia API (CC BY-SA), 1 request per seconde, met cache in data/raw/wikipedia/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import date, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from src import db
from src.features.build import resolve_fighter
from src.importers.kaggle import norm_name

API = "https://en.wikipedia.org/w/api.php"
UA = "fightmodel-research/0.1 (personal non-commercial research)"
RAW = db.ROOT / "data" / "raw" / "wikipedia"


# Wikipedia-naam -> naam in de ufcstats/Kaggle-data (handmatig gecontroleerd, 26-11-2026)
ALIASES = {
    "Beatriz Mesquita": "Bia Mesquita", "Nina Nikolija Milošević": "Nina Milosevic",
    "José Mauro Delano": "Jose Delano", "Zachary Reese": "Zach Reese", "Joseph Kropschot": "Joe Kropschot",
    "Abdul-Rakhman Yakhyaev": "Abdul Rakhman Yakhyaev", "Abusupiyan Magomedov": "Abus Magomedov",
    "Cameron Rowston": "Cam Rowston", "Timothy Cuamba": "Timmy Cuamba", "Nick Galanti": "Nicholas Galanti",
    "José Miguel Delgado": "Jose Delgado", "Thomas Gantt": "Tommy Gantt", "Matthieu Letho Duclos": "Matthieu Duclos",
    "Wesley Schultz": "Wes Schultz",
}


def _db_name(name: str) -> str:
    """Alias toepassen en achtervoegsels (Jr., III) weglaten als de kale naam bestaat."""
    return ALIASES.get(name, name)


def _hid(*parts) -> str:
    return "wiki-" + hashlib.md5("|".join(parts).encode()).hexdigest()[:14]


def fetch_page(title: str, *, cache: bool = True, max_age_h: float = 12) -> str:
    RAW.mkdir(parents=True, exist_ok=True)
    p = RAW / (re.sub(r"[^A-Za-z0-9_.-]", "_", title) + ".html")
    if cache and p.exists() and (time.time() - p.stat().st_mtime) < max_age_h * 3600:
        return p.read_text()
    time.sleep(1)
    r = requests.get(API, params={"action": "parse", "page": title, "prop": "text", "format": "json",
                                  "formatversion": 2, "redirects": 1}, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    js = r.json()
    if "error" in js:
        raise RuntimeError(f"Wikipedia: {js['error'].get('info')}")
    html = js["parse"]["text"]
    p.write_text(html)
    return html


# ------------------------------------------------------------------ eventlijst
def list_events(year: int) -> list[dict]:
    soup = BeautifulSoup(fetch_page(f"{year}_in_UFC"), "lxml")
    out = []
    for t in soup.select("table.wikitable"):
        head = [c.get_text(" ", strip=True) for c in t.select("tr")[0].find_all(["th", "td"])]
        if head[:3] != ["#", "Event", "Date"]:
            continue
        for r in t.select("tr")[1:]:
            c = r.find_all(["th", "td"])
            if len(c) < 6 or not c[0].get_text(strip=True).isdigit():
                continue
            a = c[1].find("a")
            try:
                d = datetime.strptime(c[2].get_text(" ", strip=True), "%b %d, %Y").date()
            except ValueError:
                continue
            out.append({"nr": int(c[0].get_text(strip=True)), "name": c[1].get_text(" ", strip=True),
                        "date": d, "page": a["href"].split("/wiki/")[-1] if a else None,
                        "location": ", ".join(x.get_text(" ", strip=True) for x in c[3:6])})
    return out


# ------------------------------------------------------------------ uitslagen van één event
def _clean_name(s: str) -> str:
    return re.sub(r"\s*\((?:c|ic|uc)\)\s*", " ", re.sub(r"\[.*?\]", "", s)).strip()


def _weight_class(s: str) -> str:
    s = re.sub(r"\[.*?\]", "", s).strip()
    return "Catch Weight" if s.lower().startswith("catchweight") else s


def parse_method(raw: str) -> tuple[str, str | None, str | None]:
    """-> (method zoals ufcstats, detail, resultaat-type: 'W' | 'D' | 'NC')"""
    m = re.sub(r"\[.*?\]", "", raw).strip()
    detail = (re.search(r"\(([^)]*)\)", m) or [None, None])[1]
    low = m.lower()
    if low.startswith("draw"):
        return "Decision - " + (detail or "").split()[0].capitalize() if detail else "Decision", detail, "D"
    if low.startswith("no contest") or low.startswith("nc"):
        return "Other", detail, "NC"
    if low.startswith("decision"):
        kind = (detail or "").split()[0].capitalize() if detail else ""
        return (f"Decision - {kind}" if kind in ("Unanimous", "Split", "Majority") else "Decision"), detail, "W"
    if low.startswith("submission") or low.startswith("technical submission"):
        return "Submission", detail, "W"
    if "doctor" in low:
        return "TKO - Doctor's Stoppage", detail, "W"
    if low.startswith("ko") or low.startswith("tko"):
        return "KO/TKO", detail, "W"
    if "disqualification" in low or low.startswith("dq"):
        return "DQ", detail, "W"
    return "Other", detail, "W"


def parse_event(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    fights = []
    for t in soup.select("table.toccolours"):
        rows = [[c.get_text(" ", strip=True) for c in r.find_all(["th", "td"])] for r in t.select("tr")]
        if not any("Method" in r for r in rows):
            continue
        card = None
        for r in rows:
            if len(r) == 1:
                card = r[0]
                continue
            if len(r) < 7 or r[0] == "Weight class" or r[2] not in ("def.", "vs."):
                continue
            method, detail, kind = parse_method(r[4])
            rnd = int(r[5]) if r[5].isdigit() else None
            mt = re.match(r"(\d+):(\d\d)", r[6])
            title = "(c)" in r[1] or "(c)" in r[3] or "(ic)" in r[1] or "(ic)" in r[3]
            fights.append({"card": card, "pos": len(fights), "weight_class": _weight_class(r[0]),
                           "a": _clean_name(r[1]), "b": _clean_name(r[3]), "kind": kind if r[2] == "def." else (kind if kind != "W" else "NC"),
                           "method": method, "detail": detail, "round": rnd,
                           "time_sec": int(mt.group(1)) * 60 + int(mt.group(2)) if mt else None,
                           "title": title, "notes": r[7] if len(r) > 7 else ""})
    return fights


# ------------------------------------------------------------------ naar de database
def to_rows(con, ev: dict, fights: list[dict]) -> tuple[dict, list[dict], list[dict]]:
    eid = _hid(ev["name"], str(ev["date"]))
    event = {"event_id": eid, "name": ev["name"], "date": ev["date"], "location": ev["location"],
             "status": "completed", "url": f"https://en.wikipedia.org/wiki/{ev['page']}"}
    new_fighters, rows = [], []
    for f in fights:
        ids = []
        for nm in (f["a"], f["b"]):
            fid = resolve_fighter(con, _db_name(nm), f["weight_class"])
            bare = re.sub(r"\s+(Jr\.?|Sr\.?|II|III|IV)$", "", nm)
            if fid.startswith("new:") and bare != nm:
                fid = resolve_fighter(con, bare, f["weight_class"])
            if fid.startswith("new:"):
                fid = _hid("fighter", norm_name(nm))
                if fid not in {x["fighter_id"] for x in new_fighters}:
                    new_fighters.append({"fighter_id": fid, "name": nm})
            ids.append(fid)
        ra, rb, win = {"W": ("W", "L", ids[0]), "D": ("D", "D", None), "NC": ("NC", "NC", None)}[f["kind"]]
        five = f["title"] or f["pos"] == 0 or (f["round"] or 0) > 3
        rows.append({
            "fight_id": _hid(eid, norm_name(f["a"]), norm_name(f["b"])), "event_id": eid, "event_date": ev["date"],
            "card_position": f["pos"], "fighter_a_id": ids[0], "fighter_a_name": f["a"], "fighter_b_id": ids[1],
            "fighter_b_name": f["b"], "result_a": ra, "result_b": rb, "winner_id": win,
            "weight_class": f["weight_class"], "is_title_fight": f["title"], "is_womens": f["weight_class"].startswith("Women"),
            "method": f["method"], "method_detail": f["detail"], "end_round": f["round"], "end_time_sec": f["time_sec"],
            "scheduled_rounds": 5 if five else 3, "details": f"bron: Wikipedia ({f['card']})", "url": event["url"],
        })
    return event, new_fighters, rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="YYYY-MM-DD (standaard: dag na laatste event in de DB)")
    ap.add_argument("--db", default=str(db.DEFAULT_DB))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    con = db.connect(a.db)
    last = con.execute("SELECT max(event_date) FROM fights").fetchall()[0][0]
    since = date.fromisoformat(a.since) if a.since else last
    today = date.today()
    evs = [e for y in range(since.year, today.year + 1) for e in list_events(y)]
    evs = sorted([e for e in evs if since < e["date"] < today and e["page"]], key=lambda e: e["date"])
    tot_f = tot_new = 0
    for ev in evs:
        fights = parse_event(fetch_page(ev["page"]))
        if not fights:
            print(f"  ! {ev['date']} {ev['name']}: geen uitslagen gevonden (overgeslagen)")
            continue
        event, new_f, rows = to_rows(con, ev, fights)
        tot_f += len(rows)
        tot_new += len(new_f)
        print(f"  {ev['date']} {ev['name']:<48} {len(rows):>2} gevechten, {len(new_f)} nieuwe vechters")
        if not a.dry_run:
            db.upsert(con, "events", [event])
            if new_f:
                db.upsert(con, "fighters", new_f, update=False)
            db.upsert(con, "fights", rows)
    print(f"{'(dry-run) ' if a.dry_run else ''}{len(evs)} events, {tot_f} gevechten, {tot_new} nieuwe vechters (na {since})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
