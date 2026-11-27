"""Uitslagen van andere MMA-organisaties (Bellator, PFL, ONE, Rizin, Cage Warriors, LFA, ...) van Wikipedia.

Doel: het model voorkennis geven over vechters vóór hun UFC-debuut (zie src/features/crossorg.py).
Alleen uitslagen (winnaar, methode, ronde, datum); geen stats. Opslag in een eigen tabel `ext_fights`,
los van de UFC-tabellen, zodat de bestaande pipeline niet verandert.

    .venv/bin/python -m src.importers.wiki_orgs --dry-run      # alleen tellen
    .venv/bin/python -m src.importers.wiki_orgs                # importeren (duurt even: ~1 pagina per 2,5 s)

Bron: Wikipedia API (CC BY-SA), met cache in data/raw/wikipedia/ en nette pauzes (429 -> wachten).
"""
from __future__ import annotations

import argparse
import hashlib
import re
import time
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

from src import db
from src.importers.kaggle import norm_name
from src.importers.wikipedia import API, RAW, UA, parse_event

# organisatie -> sterkte-niveau (1 = UFC-niveau, 2 = sterke organisatie, 3 = regionaal/opleiding)
ORGS = {
    "Bellator MMA": 2, "Professional Fighters League": 2, "World Series of Fighting": 2, "ONE Championship": 2,
    "Strikeforce": 2, "Rizin Fighting Federation": 2, "DREAM": 2, "Absolute Championship Akhmat": 2,
    "M-1 Global": 3, "Cage Warriors": 3, "Legacy Fighting Alliance": 3, "Brave Combat Federation": 3,
    "Road FC": 3, "Oktagon MMA": 3, "Jungle Fight": 3, "UAE Warriors": 3,
}
YEARS = range(2000, 2027)

DDL = """
CREATE TABLE IF NOT EXISTS ext_fights (
    fight_id VARCHAR PRIMARY KEY, org VARCHAR, tier INTEGER, event_name VARCHAR, event_date DATE,
    a_name VARCHAR, b_name VARCHAR, a_key VARCHAR, b_key VARCHAR, kind VARCHAR,
    method VARCHAR, end_round INTEGER, weight_class VARCHAR, source VARCHAR
);
"""


# ------------------------------------------------------------------ ophalen (met nette pauzes)
_session = requests.Session()


def fetch(title: str, *, max_age_h: float = 24 * 30) -> str | None:
    """HTML van een Wikipedia-pagina (cache 30 dagen: oude uitslagen veranderen niet). None = bestaat niet."""
    RAW.mkdir(parents=True, exist_ok=True)
    p = RAW / (re.sub(r"[^A-Za-z0-9_.-]", "_", title) + ".html")
    if p.exists() and (time.time() - p.stat().st_mtime) < max_age_h * 3600:
        txt = p.read_text()
        return None if txt == "<missing>" else txt
    for attempt in range(6):
        time.sleep(2.5)
        try:
            r = _session.get(API, params={"action": "parse", "page": title, "prop": "text", "format": "json",
                                          "formatversion": 2, "redirects": 1}, headers={"User-Agent": UA}, timeout=30)
        except requests.RequestException as e:
            print(f"    (verbinding mislukt: {type(e).__name__}; opnieuw over {20 * (attempt + 1)}s)")
            time.sleep(20 * (attempt + 1))
            continue
        if r.status_code == 429:
            wait = int(r.headers.get("retry-after") or 30 * (attempt + 1))
            print(f"    (Wikipedia: even wachten {wait}s)")
            time.sleep(wait)
            continue
        r.raise_for_status()
        js = r.json()
        if "error" in js:
            p.write_text("<missing>")
            return None
        html = js["parse"]["text"]
        p.write_text(html)
        return html
    raise RuntimeError(f"Wikipedia blijft weigeren voor {title}")


# ------------------------------------------------------------------ datums
_DATE_FMTS = ("%B %d, %Y", "%d %B %Y", "%b %d, %Y", "%d %b %Y", "%B %d %Y")


def parse_date(text: str) -> date | None:
    t = re.sub(r"\[.*?\]|\(.*?\)", "", text or "").replace("\xa0", " ").strip()
    for m in re.finditer(r"([A-Z][a-z]+\.? \d{1,2},? \d{4}|\d{1,2} [A-Z][a-z]+\.? \d{4})", t):
        s = m.group(1).replace(".", "")
        for f in _DATE_FMTS:
            try:
                return datetime.strptime(s, f).date()
            except ValueError:
                pass
    return None


def infobox_info(box) -> tuple[str | None, date | None]:
    title = box.select_one("tr th, caption")
    name = title.get_text(" ", strip=True) if title else None
    d = None
    for r in box.select("tr"):
        th = r.find("th")
        if th and th.get_text(strip=True).lower() == "date":
            td = r.find("td")
            d = parse_date(td.get_text(" ", strip=True)) if td else None
            break
    return name, d


# ------------------------------------------------------------------ één pagina -> events
def results_tables(soup):
    for t in soup.select("table.toccolours"):
        if "Method" in t.get_text(" ", strip=True):
            yield t


def page_events(html: str, fallback_date: date | None = None, fallback_name: str | None = None) -> list[dict]:
    """Alle uitslag-tabellen op een pagina, elk met de dichtstbijzijnde eerdere infobox (naam + datum)."""
    soup = BeautifulSoup(html, "lxml")
    groups: dict[int, dict] = {}     # uitslag-tabellen onder dezelfde infobox = één event (bv. main card + prelims)
    for t in results_tables(soup):
        box = t.find_previous("table", class_="infobox")
        head = t.find_previous(["h2", "h3"])
        key = id(box) if box is not None else id(head)
        if key not in groups:
            name, d = infobox_info(box) if box is not None else (None, None)
            name = name or (head.get_text(" ", strip=True) if head else None) or fallback_name
            groups[key] = {"name": name, "date": d or fallback_date, "fights": []}
        groups[key]["fights"] += parse_event(str(t))
    return [g for g in groups.values() if g["fights"] and g["date"]]


def event_links(html: str) -> list[dict]:
    """Eventlijst-tabellen (# | Event | Date ...) met links naar aparte eventpagina's."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for t in soup.select("table.wikitable"):
        rows = t.select("tr")
        if not rows:
            continue
        head = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])]
        if "event" not in head or "date" not in head:
            continue
        ie, idt = head.index("event"), head.index("date")
        for r in rows[1:]:
            c = r.find_all(["th", "td"])
            if len(c) <= max(ie, idt):
                continue
            a = c[ie].find("a")
            href = a.get("href", "") if a else ""
            if not href.startswith("/wiki/") or "#" in href:
                continue
            out.append({"title": href.split("/wiki/")[-1], "name": c[ie].get_text(" ", strip=True),
                        "date": parse_date(c[idt].get_text(" ", strip=True))})
    return out


# ------------------------------------------------------------------ alles verzamelen
def collect(orgs=ORGS, years=YEARS, log=print) -> list[dict]:
    events, seen_pages = [], set()
    for org in orgs:
        n0 = len(events)
        for y in years:
            title = f"{y}_in_{org.replace(' ', '_')}"
            html = fetch(title)
            if html is None:
                continue
            key = hashlib.md5(html[:5000].encode()).hexdigest()
            if key in seen_pages:          # doorverwijzing naar dezelfde (hoofd)pagina
                continue
            seen_pages.add(key)
            for ev in page_events(html):
                events.append({**ev, "org": org})
            for ln in event_links(html):
                if ln["title"] in seen_pages or re.match(r"\d{4}_in_", ln["title"]):
                    continue
                seen_pages.add(ln["title"])
                sub = fetch(ln["title"])
                if sub is None:
                    continue
                for ev in page_events(sub, ln["date"], ln["name"]):
                    events.append({**ev, "org": org})
        log(f"  {org:<32} {len(events) - n0:>4} events")
    # dubbele events (zelfde org, datum en vechters) eruit
    uniq, keys = [], set()
    for ev in events:
        k = (ev["org"], ev["date"], tuple(sorted(norm_name(f["a"]) + "|" + norm_name(f["b"]) for f in ev["fights"])))
        if k not in keys:
            keys.add(k)
            uniq.append(ev)
    return uniq


def to_rows(events: list[dict]) -> list[dict]:
    rows = {}
    for ev in events:
        for f in ev["fights"]:
            ka, kb = norm_name(f["a"]), norm_name(f["b"])
            fid = "x-" + hashlib.md5(f"{ev['date']}|{min(ka, kb)}|{max(ka, kb)}".encode()).hexdigest()[:14]
            rows[fid] = {"fight_id": fid, "org": ev["org"], "tier": ORGS.get(ev["org"], 3), "event_name": ev["name"],
                         "event_date": ev["date"], "a_name": f["a"], "b_name": f["b"], "a_key": ka, "b_key": kb,
                         "kind": f["kind"], "method": f["method"], "end_round": f["round"],
                         "weight_class": f["weight_class"], "source": "wikipedia"}
    return list(rows.values())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(db.DEFAULT_DB))
    ap.add_argument("--org", action="append", help="alleen deze organisatie(s)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    orgs = {o: ORGS[o] for o in a.org} if a.org else ORGS
    events = collect(orgs)
    rows = to_rows(events)
    print(f"{len(events)} events, {len(rows)} gevechten "
          f"({min(r['event_date'] for r in rows)} t/m {max(r['event_date'] for r in rows)})" if rows else "niets gevonden")
    if not a.dry_run and rows:
        con = db.connect(a.db)
        con.execute(DDL)
        db.upsert(con, "ext_fights", rows)
        print("Opgeslagen in ext_fights:", con.execute("SELECT count(*) FROM ext_fights").fetchone()[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
