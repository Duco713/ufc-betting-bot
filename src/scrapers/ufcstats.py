"""Scraper voor ufcstats.com: events, gevechten (totalen + per ronde), vechters, komende kaarten.

Gebruik:
    python -m src.scrapers.ufcstats --limit-events 3
    python -m src.scrapers.ufcstats --upcoming --fighters
    python -m src.scrapers.ufcstats --all --fighters      # volledige historie (uren)

Beleefd: ~1 request/seconde, ruwe HTML wordt gecachet onder data/raw/ufcstats/
(sleutel = sha1 van de URL). Afgeronde event- en fight-pagina's worden nooit
opnieuw gedownload. Als de site een bot-challenge ("Checking your browser")
teruggeeft, stopt de scraper met een duidelijke foutmelding; die challenge
wordt bewust NIET omzeild.
"""
from __future__ import annotations

import argparse
import hashlib
import random
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

from src import db
from src.scrapers.parse_utils import (
    clean,
    id_from_url,
    inches_to_cm,
    parse_date,
    parse_height_in,
    parse_int,
    parse_mmss,
    parse_of,
    parse_reach_in,
    parse_record,
    parse_time_format,
    parse_weight_lbs,
)

BASE = "http://ufcstats.com"
COMPLETED_URL = f"{BASE}/statistics/events/completed?page=all"
UPCOMING_URL = f"{BASE}/statistics/events/upcoming"
CACHE_DIR = db.ROOT / "data" / "raw" / "ufcstats"
USER_AGENT = "Mozilla/5.0 (compatible; ufc-stats-research/0.1; personal non-commercial research)"

HOUR = 3600
DAY = 24 * HOUR


# --------------------------------------------------------------------------- #
# HTTP + cache
# --------------------------------------------------------------------------- #
class ScrapeError(RuntimeError):
    pass


class BotChallengeError(ScrapeError):
    """De site gaf een JavaScript bot-challenge in plaats van content."""


class CacheMiss(ScrapeError):
    pass


def looks_like_challenge(html: str) -> bool:
    head = html[:4000]
    return "Checking your browser" in head or "/__c" in head or "<title>Loading" in head


class Fetcher:
    def __init__(self, cache_dir: Path = CACHE_DIR, delay: float = 1.0, offline: bool = False,
                 max_retries: int = 4, timeout: float = 30.0):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.offline = offline
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html"})
        self._last = 0.0
        self.n_network = 0
        self.n_cache = 0

    def cache_path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".html")

    def _throttle(self):
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait + random.uniform(0, 0.25))
        self._last = time.monotonic()

    def get(self, url: str, max_age: float | None = None) -> str:
        """Haal een pagina op. max_age=None: cache is permanent geldig."""
        url = url.strip()
        path = self.cache_path(url)
        if path.exists():
            age = time.time() - path.stat().st_mtime
            if max_age is None or age < max_age or self.offline:
                self.n_cache += 1
                return path.read_text(encoding="utf-8")
        if self.offline:
            raise CacheMiss(f"niet in cache (offline-modus): {url}")

        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                r = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as e:
                last_err = e
            else:
                if r.status_code == 200:
                    html = r.text
                    if looks_like_challenge(html):
                        raise BotChallengeError(
                            f"ufcstats.com gaf een bot-challenge ('Checking your browser') voor {url}. "
                            "De scraper omzeilt dit bewust niet. Opties: later opnieuw proberen, "
                            "de site-eigenaar om toegang vragen, of een andere bron (bv. Kaggle-dataset)."
                        )
                    path.write_text(html, encoding="utf-8")
                    with open(self.cache_dir / "_index.tsv", "a", encoding="utf-8") as f:
                        f.write(f"{path.name}\t{url}\t{datetime.now().isoformat(timespec='seconds')}\n")
                    self.n_network += 1
                    return html
                if r.status_code == 404:
                    raise ScrapeError(f"404 voor {url}")
                last_err = ScrapeError(f"HTTP {r.status_code} voor {url}")
            if attempt < self.max_retries:
                time.sleep(min(60, 2 ** (attempt + 1)) + random.uniform(0, 1))
        raise ScrapeError(f"opgeven na {self.max_retries + 1} pogingen: {url} ({last_err})")


# --------------------------------------------------------------------------- #
# Parsers (pure functies: html -> dicts)
# --------------------------------------------------------------------------- #
def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _label_value(item) -> tuple[str, str | None]:
    """Voor <li>/<i> met een label-element ('Date:', 'Method:' ...) -> (label, waarde)."""
    lab = item.select_one("i.b-list__box-item-title, i.b-fight-details__label")
    label = clean(lab.get_text()) if lab else ""
    full = clean(item.get_text(" ")) or ""
    value = full[len(label):] if label and full.startswith(label) else full
    return (label or "").rstrip(":").strip().lower(), clean(value)


def parse_event_list(html: str) -> list[dict]:
    """Tabel van /statistics/events/{completed,upcoming}."""
    out = []
    for row in _soup(html).select("tr.b-statistics__table-row"):
        a = row.select_one('a[href*="event-details"]')
        if not a:
            continue
        tds = row.find_all("td")
        ds = row.select_one("span.b-statistics__date")
        out.append({
            "event_id": id_from_url(a["href"]),
            "url": a["href"].strip(),
            "name": clean(a.get_text()),
            "date": parse_date(ds.get_text() if ds else None),
            "location": clean(tds[1].get_text()) if len(tds) > 1 else None,
        })
    return out


_BONUS_IMGS = {"perf.png": "bonus_perf", "fight.png": "bonus_fight", "sub.png": "bonus_sub", "ko.png": "bonus_ko"}


def _img_flags(node) -> dict:
    srcs = [img.get("src", "").rsplit("/", 1)[-1].lower() for img in node.find_all("img")]
    flags = {v: (k in srcs) for k, v in _BONUS_IMGS.items()}
    flags["is_title_fight"] = "belt.png" in srcs
    return flags


def parse_event_page(html: str, url: str | None = None) -> dict:
    """Event-detailpagina -> {'event': {...}, 'fights': [...]}, werkt voor afgeronde en komende events."""
    s = _soup(html)
    title = s.select_one("span.b-content__title-highlight")
    info = dict(_label_value(li) for li in s.select("li.b-list__box-list-item"))
    event = {
        "event_id": id_from_url(url) if url else None,
        "url": url,
        "name": clean(title.get_text()) if title else None,
        "date": parse_date(info.get("date")),
        "location": info.get("location"),
    }

    fights = []
    table = s.select_one("table.b-fight-details__table")
    if table is not None:
        headers = [(clean(th.get_text()) or "").lower() for th in table.select("thead th")]

        def col(tds, name, fallback):
            i = headers.index(name) if name in headers else fallback
            return tds[i] if i < len(tds) else None

        def ptexts(td):
            return [clean(p.get_text()) for p in td.select("p")] if td is not None else []

        rows = [r for r in table.select("tbody tr") if r.find("td")]
        for pos, row in enumerate(rows):
            link = row.get("data-link") or ""
            if not link:
                a = row.select_one('a[href*="fight-details"]')
                link = a["href"] if a else ""
            link = link.strip()
            fighters = row.select('a[href*="fighter-details"]')
            tds = row.find_all("td")
            flags_txt = [clean(x.get_text()) for x in (tds[0].select(".b-flag__text") if tds else [])]
            flags_txt = [f.lower() for f in flags_txt if f]
            wc = ptexts(col(tds, "weight class", 6))
            method = ptexts(col(tds, "method", 7))
            rnd = col(tds, "round", 8)
            tm = col(tds, "time", 9)
            f = {
                "fight_id": id_from_url(link),
                "url": link or None,
                "card_position": pos,
                "fighter_a_id": id_from_url(fighters[0]["href"]) if len(fighters) > 0 else None,
                "fighter_a_name": clean(fighters[0].get_text()) if len(fighters) > 0 else None,
                "fighter_b_id": id_from_url(fighters[1]["href"]) if len(fighters) > 1 else None,
                "fighter_b_name": clean(fighters[1].get_text()) if len(fighters) > 1 else None,
                "flag": flags_txt[0] if flags_txt else None,  # 'win' | 'draw' | 'nc' | None
                "weight_class": wc[0] if wc else None,
                "method_short": method[0] if method else None,
                "method_detail": method[1] if len(method) > 1 else None,
                "end_round": parse_int(rnd.get_text()) if rnd is not None else None,
                "end_time_sec": parse_mmss(tm.get_text()) if tm is not None else None,
            }
            f.update(_img_flags(row))
            if f["fight_id"]:
                fights.append(f)
    return {"event": event, "fights": fights}


_TOTALS_MAP = {
    "kd": ("kd", "int"),
    "sig. str.": ("sig_str", "of"),
    "total str.": ("total_str", "of"),
    "td": ("td", "of"),
    "sub. att": ("sub_att", "int"),
    "rev.": ("rev", "int"),
    "ctrl": ("ctrl_sec", "mmss"),
}
_SIG_MAP = {
    "sig. str": ("sig_str", "of"),
    "sig. str.": ("sig_str", "of"),
    "head": ("head", "of"),
    "body": ("body", "of"),
    "leg": ("leg", "of"),
    "distance": ("distance", "of"),
    "clinch": ("clinch", "of"),
    "ground": ("ground", "of"),
}


def _norm_header(t: str | None) -> str:
    return re.sub(r"\s+", " ", (t or "").strip().lower())


def _parse_stat_table(table, fighter_ids_fallback: list[str | None]) -> dict:
    """Één statistiek-tabel -> {(fighter_id, round): {kolom: waarde}}.

    Werkt voor zowel totalen (round 0) als per-ronde tabellen (th 'Round N').
    """
    headers = [_norm_header(th.get_text()) for th in table.find_all("th")]
    headers = [h for h in headers if not re.match(r"^round \d+$", h)]
    is_sig = "head" in headers
    mapping = _SIG_MAP if is_sig else _TOTALS_MAP
    out: dict = {}
    current_round = 0
    for tr in table.find_all("tr"):
        th = tr.find("th")
        if th is not None:
            m = re.match(r"^round (\d+)$", _norm_header(th.get_text()))
            if m:
                current_round = int(m.group(1))
            continue
        tds = tr.find_all("td")
        if not tds:
            continue
        ids = [id_from_url(a["href"]) for a in tds[0].select('a[href*="fighter-details"]')]
        if len(ids) < 2:
            ids = fighter_ids_fallback
        for ci, td in enumerate(tds[1:], start=1):
            if ci >= len(headers):
                break
            key = mapping.get(headers[ci])
            if not key:
                continue
            name, kind = key
            vals = [p.get_text() for p in td.select("p")]
            for fi, raw in enumerate(vals[:2]):
                fid = ids[fi] if fi < len(ids) else None
                rec = out.setdefault((fid, current_round), {})
                if kind == "of":
                    l, a = parse_of(raw)
                    rec[f"{name}_landed"], rec[f"{name}_att"] = l, a
                elif kind == "mmss":
                    rec[name] = parse_mmss(raw)
                else:
                    rec[name] = parse_int(raw)
    return out


def parse_fight_page(html: str, url: str | None = None) -> dict:
    """Fight-detailpagina -> {'fight': {...}, 'stats': [rij per vechter x ronde]}."""
    s = _soup(html)
    persons = []
    for p in s.select("div.b-fight-details__person"):
        a = p.select_one('a[href*="fighter-details"]')
        st = p.select_one("i.b-fight-details__person-status")
        persons.append({
            "id": id_from_url(a["href"]) if a else None,
            "name": clean(a.get_text()) if a else clean(p.select_one("h3").get_text() if p.select_one("h3") else None),
            "status": (clean(st.get_text()) or "").upper() or None,
        })
    head = s.select_one("div.b-fight-details__fight-head")
    title_el = s.select_one("i.b-fight-details__fight-title")
    bout_title = clean(title_el.get_text()) if title_el else None

    items = {}
    content = s.select_one("div.b-fight-details__content")
    if content is not None:
        for it in content.select("i.b-fight-details__text-item, i.b-fight-details__text-item_first"):
            k, v = _label_value(it)
            if k and k not in items:
                items[k] = v
        details = None
        for p in content.select("p.b-fight-details__text"):
            lab = p.select_one("i.b-fight-details__label")
            if lab and (clean(lab.get_text()) or "").lower().startswith("details"):
                k, details = _label_value(p)
        items["details"] = details

    a = persons[0] if persons else {}
    b = persons[1] if len(persons) > 1 else {}
    winner = a.get("id") if a.get("status") == "W" else b.get("id") if b.get("status") == "W" else None
    fight = {
        "fight_id": id_from_url(url) if url else None,
        "url": url,
        "fighter_a_id": a.get("id"), "fighter_a_name": a.get("name"), "result_a": a.get("status"),
        "fighter_b_id": b.get("id"), "fighter_b_name": b.get("name"), "result_b": b.get("status"),
        "winner_id": winner,
        "bout_title": bout_title,
        "method": items.get("method"),
        "end_round": parse_int(items.get("round")),
        "end_time_sec": parse_mmss(items.get("time")),
        "time_format": items.get("time format"),
        "scheduled_rounds": parse_time_format(items.get("time format")),
        "referee": items.get("referee"),
        "details": items.get("details"),
    }
    flags = _img_flags(head) if head is not None else {}
    fight.update(flags)
    if bout_title and "title" in bout_title.lower():
        fight["is_title_fight"] = True

    ids = [a.get("id"), b.get("id")]
    merged: dict = {}
    for table in s.select("table"):
        if not table.find("th"):
            continue
        for k, rec in _parse_stat_table(table, ids).items():
            merged.setdefault(k, {}).update(rec)
    stats = []
    for (fid, rnd), rec in sorted(merged.items(), key=lambda kv: (kv[0][1], ids.index(kv[0][0]) if kv[0][0] in ids else 9)):
        if fid is None:
            continue
        row = {"fight_id": fight["fight_id"], "fighter_id": fid, "round": rnd}
        row.update({c: rec.get(c) for c in db.STAT_COLUMNS})
        stats.append(row)
    return {"fight": fight, "stats": stats}


def parse_fighter_page(html: str, url: str | None = None) -> dict:
    s = _soup(html)
    name = s.select_one("span.b-content__title-highlight")
    nick = s.select_one("p.b-content__Nickname")
    rec = s.select_one("span.b-content__title-record")
    info = {}
    for li in s.select("li.b-list__box-list-item"):
        k, v = _label_value(li)
        if k and k not in info:
            info[k] = v
    h = parse_height_in(info.get("height"))
    r = parse_reach_in(info.get("reach"))
    record = parse_record(rec.get_text() if rec else None)
    return {
        "fighter_id": id_from_url(url) if url else None,
        "url": url,
        "name": clean(name.get_text()) if name else None,
        "nickname": clean(nick.get_text()) if nick else None,
        "height_in": h,
        "height_cm": inches_to_cm(h),
        "weight_lbs": parse_weight_lbs(info.get("weight")),
        "reach_in": r,
        "reach_cm": inches_to_cm(r),
        "stance": info.get("stance"),
        "dob": parse_date(info.get("dob")),
        "record_wins": record["wins"],
        "record_losses": record["losses"],
        "record_draws": record["draws"],
        "record_nc": record["nc"],
    }


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
FIGHT_COLUMNS = [
    "fight_id", "event_id", "event_date", "card_position",
    "fighter_a_id", "fighter_a_name", "fighter_b_id", "fighter_b_name",
    "result_a", "result_b", "winner_id", "weight_class", "bout_title",
    "is_title_fight", "is_womens", "method", "method_detail", "end_round", "end_time_sec",
    "time_format", "scheduled_rounds", "referee", "details",
    "bonus_perf", "bonus_fight", "bonus_sub", "bonus_ko", "url", "scraped_at",
]


@dataclass
class Scraper:
    fetcher: Fetcher
    con: object

    def scrape_completed(self, limit: int | None = None) -> None:
        events = parse_event_list(self.fetcher.get(COMPLETED_URL, max_age=12 * HOUR))
        today = date.today()
        events = [e for e in events if e["date"] and e["date"] <= today]
        events.sort(key=lambda e: e["date"], reverse=True)
        if limit:
            events = events[:limit]
        print(f"[events] {len(events)} afgeronde events te verwerken")
        n_fights = 0
        for ev in tqdm(events, desc="events", unit="event"):
            # Recente events (<3 dagen) kunnen nog onvolledig zijn -> korte cache.
            fresh = ev["date"] >= today - timedelta(days=3)
            page = parse_event_page(self.fetcher.get(ev["url"], max_age=6 * HOUR if fresh else None), ev["url"])
            e = {**ev, **{k: v for k, v in page["event"].items() if v is not None}}
            e.update(status="completed", scraped_at=datetime.now())
            fights, stats = [], []
            for f in tqdm(page["fights"], desc=ev["name"][:40], unit="fight", leave=False):
                try:
                    fp = parse_fight_page(self.fetcher.get(f["url"], max_age=6 * HOUR if fresh else None), f["url"])
                except BotChallengeError:
                    raise
                except ScrapeError as err:
                    tqdm.write(f"  ! fight overgeslagen: {err}")
                    continue
                fights.append(self._merge_fight(e, f, fp["fight"]))
                stats.extend(fp["stats"])
            self._store_completed(e, fights, stats)
            n_fights += len(fights)
        print(f"[events] klaar: {len(events)} events, {n_fights} gevechten")

    @staticmethod
    def _merge_fight(event: dict, ev_row: dict, fp: dict) -> dict:
        out = {c: None for c in FIGHT_COLUMNS}
        out.update({k: v for k, v in ev_row.items() if k in out})
        out.update({k: v for k, v in fp.items() if k in out and v is not None})
        out["method_detail"] = ev_row.get("method_detail")
        out["is_title_fight"] = bool(ev_row.get("is_title_fight") or fp.get("is_title_fight"))
        for b in ("bonus_perf", "bonus_fight", "bonus_sub", "bonus_ko"):
            out[b] = bool(ev_row.get(b) or fp.get(b))
        wc = out.get("weight_class") or out.get("bout_title") or ""
        out["is_womens"] = "women" in wc.lower()
        out["event_id"] = event["event_id"]
        out["event_date"] = event["date"]
        out["scraped_at"] = datetime.now()
        return out

    def _store_completed(self, event: dict, fights: list[dict], stats: list[dict]) -> None:
        con = self.con
        con.execute("BEGIN")
        try:
            db.upsert(con, "events", [{k: event.get(k) for k in
                      ("event_id", "name", "date", "location", "status", "url", "scraped_at")}])
            db.upsert(con, "fights", fights)
            db.upsert(con, "fight_stats_round", stats)
            fighters = {}
            for f in fights:
                for side in ("a", "b"):
                    fid = f.get(f"fighter_{side}_id")
                    if fid:
                        fighters[fid] = {"fighter_id": fid, "name": f.get(f"fighter_{side}_name"),
                                         "url": f"{BASE}/fighter-details/{fid}"}
            db.upsert(con, "fighters", fighters.values(), update=False)
            # Gevechten die nu afgerond zijn horen niet meer in upcoming_fights.
            if fights:
                con.execute(f"DELETE FROM upcoming_fights WHERE fight_id IN ({','.join('?' * len(fights))})",
                            [f["fight_id"] for f in fights])
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

    def scrape_upcoming(self) -> None:
        events = parse_event_list(self.fetcher.get(UPCOMING_URL, max_age=6 * HOUR))
        print(f"[upcoming] {len(events)} komende events")
        rows, ev_rows = [], []
        now = datetime.now()
        for ev in tqdm(events, desc="upcoming", unit="event"):
            page = parse_event_page(self.fetcher.get(ev["url"], max_age=6 * HOUR), ev["url"])
            e = {**ev, **{k: v for k, v in page["event"].items() if v is not None}}
            ev_rows.append({"event_id": e["event_id"], "name": e["name"], "date": e["date"],
                            "location": e["location"], "status": "upcoming", "url": e["url"], "scraped_at": now})
            for f in page["fights"]:
                rows.append({
                    "fight_id": f["fight_id"], "event_id": e["event_id"], "event_name": e["name"],
                    "event_date": e["date"], "location": e["location"], "card_position": f["card_position"],
                    "fighter_a_id": f["fighter_a_id"], "fighter_a_name": f["fighter_a_name"],
                    "fighter_b_id": f["fighter_b_id"], "fighter_b_name": f["fighter_b_name"],
                    "weight_class": f["weight_class"], "is_title_fight": f["is_title_fight"],
                    "url": f["url"], "scraped_at": now,
                })
        con = self.con
        con.execute("BEGIN")
        try:
            # Komende kaarten veranderen (afzeggingen, vervangers): volledig verversen.
            con.execute("DELETE FROM upcoming_fights")
            db.upsert(con, "upcoming_fights", rows)
            # Status 'completed' nooit terugzetten naar 'upcoming'.
            done = {r[0] for r in con.execute("SELECT event_id FROM events WHERE status = 'completed'").fetchall()}
            db.upsert(con, "events", [r for r in ev_rows if r["event_id"] not in done])
            fighters = {}
            for r in rows:
                for side in ("a", "b"):
                    fid = r.get(f"fighter_{side}_id")
                    if fid:
                        fighters[fid] = {"fighter_id": fid, "name": r.get(f"fighter_{side}_name"),
                                         "url": f"{BASE}/fighter-details/{fid}"}
            db.upsert(con, "fighters", fighters.values(), update=False)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        print(f"[upcoming] {len(rows)} komende gevechten opgeslagen")

    def scrape_fighters(self, refresh_days: int = 30) -> None:
        """Profielen ophalen voor alle vechters die in fights/upcoming_fights voorkomen."""
        ids = [r[0] for r in self.con.execute(
            """
            WITH ids AS (
                SELECT fighter_a_id AS id FROM fights UNION SELECT fighter_b_id FROM fights
                UNION SELECT fighter_a_id FROM upcoming_fights UNION SELECT fighter_b_id FROM upcoming_fights
            )
            SELECT ids.id FROM ids LEFT JOIN fighters f ON f.fighter_id = ids.id
            WHERE ids.id IS NOT NULL
              AND (f.details_scraped_at IS NULL OR f.details_scraped_at < now() - INTERVAL (?) DAY)
            ORDER BY ids.id
            """, [refresh_days]).fetchall()]
        print(f"[fighters] {len(ids)} vechterprofielen op te halen")
        batch = []
        for fid in tqdm(ids, desc="fighters", unit="fighter"):
            url = f"{BASE}/fighter-details/{fid}"
            try:
                row = parse_fighter_page(self.fetcher.get(url, max_age=refresh_days * DAY), url)
            except BotChallengeError:
                raise
            except ScrapeError as err:
                tqdm.write(f"  ! vechter overgeslagen: {err}")
                continue
            row["details_scraped_at"] = datetime.now()
            batch.append(row)
            if len(batch) >= 50:
                db.upsert(self.con, "fighters", batch)
                batch = []
        db.upsert(self.con, "fighters", batch)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ufcstats.com scraper -> data/ufc.duckdb")
    ap.add_argument("--limit-events", type=int, help="alleen de N meest recente afgeronde events")
    ap.add_argument("--all", action="store_true", help="alle afgeronde events (duurt uren)")
    ap.add_argument("--upcoming", action="store_true", help="komende events + gevechten")
    ap.add_argument("--fighters", action="store_true", help="vechterprofielen voor alle bekende vechters")
    ap.add_argument("--offline", action="store_true", help="alleen cache gebruiken, geen netwerk")
    ap.add_argument("--delay", type=float, default=1.0, help="seconden tussen requests (default 1.0)")
    ap.add_argument("--db", default=str(db.DEFAULT_DB), help="pad naar DuckDB-bestand")
    args = ap.parse_args(argv)
    if not (args.limit_events or args.all or args.upcoming or args.fighters):
        ap.error("kies minstens één van --limit-events N, --all, --upcoming, --fighters")

    fetcher = Fetcher(delay=max(args.delay, 0.5), offline=args.offline)
    con = db.connect(args.db)
    scraper = Scraper(fetcher, con)
    t0 = time.time()
    try:
        if args.all or args.limit_events:
            scraper.scrape_completed(limit=None if args.all else args.limit_events)
        if args.upcoming:
            scraper.scrape_upcoming()
        if args.fighters:
            scraper.scrape_fighters()
    except BotChallengeError as e:
        print(f"\nGESTOPT: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nAfgebroken; al opgeslagen data blijft staan (rerun gaat verder via cache).", file=sys.stderr)
        return 130
    finally:
        print(f"\n[requests] netwerk: {fetcher.n_network}, cache: {fetcher.n_cache}, "
              f"tijd: {time.time() - t0:.0f}s")
        print("[rijen per tabel]")
        for t, n in db.row_counts(con).items():
            print(f"  {t:<18} {n}")
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
