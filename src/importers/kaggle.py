"""Importeer Kaggle-datasets in data/ufc.duckdb (alternatief voor live scrapen).

Bronnen (handmatig of via `--download` op te halen, staan in data/external/kaggle/):
- neelagiriaditya/ufc-datasets-1994-2025  (CC0)  -> events, fighters, fights, fight_stats_round
  Gescraped van ufcstats.com, dus dezelfde ID's als onze eigen scraper.
- mdabbert/ultimate-ufc-dataset          (CC BY 4.0) -> odds (2010 - mrt 2026)

Gebruik:
    .venv/bin/python -m src.importers.kaggle            # importeer uit data/external/kaggle
    .venv/bin/python -m src.importers.kaggle --download # eerst (opnieuw) downloaden

Let op: de loopbaangemiddelden in fighter.csv (SLpM e.d.) en de gemiddelden in
ufc-master.csv zijn bewust NIET geïmporteerd: die bevatten informatie uit de toekomst
(leakage, PLAN.md §5). Features worden zelf point-in-time berekend uit fight_stats_round.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import unicodedata
import zipfile
from datetime import timedelta
from pathlib import Path

import pandas as pd

from src import db
from src.scrapers import parse_utils as pu

KAGGLE_DIR = db.ROOT / "data" / "external" / "kaggle"
STATS_SLUG = "neelagiriaditya/ufc-datasets-1994-2025"
ODDS_SLUG = "mdabbert/ultimate-ufc-dataset"
UFCSTATS = "http://ufcstats.com"


# ---------------------------------------------------------------- download
def download(slug: str) -> Path:
    """Download een publieke Kaggle-dataset (zip) en pak alleen .csv-bestanden uit."""
    target = KAGGLE_DIR / slug.split("/")[1]
    target.mkdir(parents=True, exist_ok=True)
    zpath = target / "download.zip"
    subprocess.run(
        ["curl", "-sSLf", "-o", str(zpath), f"https://www.kaggle.com/api/v1/datasets/download/{slug}"],
        check=True,
    )
    with zipfile.ZipFile(zpath) as z:
        for name in z.namelist():
            base = Path(name).name
            if base.endswith(".csv") and base == name:  # geen submappen / paden
                (target / base).write_bytes(z.read(name))
    return target


# ---------------------------------------------------------------- helpers
def _none(v):
    return None if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT else v


def norm_name(name: str | None) -> str:
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z ]", "", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _records(df: pd.DataFrame) -> list[dict]:
    return [{k: _none(v) for k, v in r.items()} for r in df.to_dict("records")]


# ---------------------------------------------------------------- stats-dataset
def import_stats(con, src: Path) -> None:
    ev = pd.read_csv(src / "event.csv", dtype=str)
    fi = pd.read_csv(src / "fighter.csv", dtype=str)
    fg = pd.read_csv(src / "fight.csv", dtype=str)
    rd = pd.read_csv(src / "round.csv", dtype=str)
    bo = pd.read_csv(src / "fighter_bonus.csv", dtype=str)

    # events
    events = pd.DataFrame({
        "event_id": ev.event_id,
        "name": ev.event_name,
        "date": pd.to_datetime(ev.date).dt.date,
        "location": ev.location,
        "status": "completed",
        "url": UFCSTATS + "/event-details/" + ev.event_id,
    })
    db.upsert(con, "events", _records(events))

    # fighters (zonder loopbaangemiddelden: leakage)
    h = fi.height.map(pu.parse_height_in)
    reach = pd.to_numeric(fi.reach_inches, errors="coerce")
    fighters = pd.DataFrame({
        "fighter_id": fi.fighter_id,
        "name": fi.fighter_name,
        "nickname": fi.fighter_nick_name,
        "height_in": h,
        "height_cm": h.map(pu.inches_to_cm),
        "weight_lbs": pd.to_numeric(fi.weight_lbs, errors="coerce"),
        "reach_in": reach,
        "reach_cm": reach.map(pu.inches_to_cm),
        "stance": fi.stance,
        "dob": pd.to_datetime(fi.dob, errors="coerce").dt.date,
        "url": UFCSTATS + "/fighter-details/" + fi.fighter_id,
    })
    db.upsert(con, "fighters", _records(fighters))

    # fights
    names = dict(zip(fi.fighter_id, fi.fighter_name))
    dates = dict(zip(events.event_id, events.date))
    bonus = bo.groupby("fight_id").bonus_type.apply(set).to_dict()

    def res(row, side):
        s = row.result_status
        if s == "draw":
            return "D"
        if s == "no_contest":
            return "NC"
        return "W" if row.winner_id == row[side] else "L"

    rows = []
    for r in fg.itertuples(index=False):
        rr = r._asdict()
        b = bonus.get(r.fight_id, set())
        wc = r.weight_class or ""
        rows.append({
            "fight_id": r.fight_id,
            "event_id": r.event_id,
            "event_date": dates.get(r.event_id),
            "fighter_a_id": r.r_id,
            "fighter_a_name": names.get(r.r_id),
            "fighter_b_id": r.b_id,
            "fighter_b_name": names.get(r.b_id),
            "result_a": res(pd.Series(rr), "r_id"),
            "result_b": res(pd.Series(rr), "b_id"),
            "winner_id": r.winner_id if r.result_status == "win" else None,
            "weight_class": wc or None,
            "is_title_fight": str(r.title_fight) == "1",
            "is_womens": "women" in wc.lower(),
            "method": r.method,
            "method_detail": pu.clean(r.details) if isinstance(r.details, str) else None,
            "end_round": pu.parse_int(r.round),
            "end_time_sec": pu.parse_mmss(r.time),
            "time_format": r.time_format,
            "scheduled_rounds": pu.parse_time_format(r.time_format),
            "referee": r.referee,
            "details": pu.clean(r.details) if isinstance(r.details, str) else None,
            "bonus_perf": "Performance of the Night" in b,
            "bonus_fight": "Fight of the Night" in b,
            "bonus_sub": "Submission of the Night" in b,
            "bonus_ko": "Knockout of the Night" in b,
            "url": UFCSTATS + "/fight-details/" + r.fight_id,
        })
    db.upsert(con, "fights", [{k: _none(v) for k, v in x.items()} for x in rows])

    # fight_stats_round (+ ronde 0 = totalen)
    m = {  # doelkolom -> bronkolom-suffix
        "kd": "kd", "sig_str_landed": "sig_landed", "sig_str_att": "sig_atmp",
        "total_str_landed": "total_str_landed", "total_str_att": "total_str_atmp",
        "td_landed": "td_success", "td_att": "td_atmp", "sub_att": "sub_att", "rev": "rev",
        "head_landed": "sig_str_landed_head", "head_att": "sig_str_atmp_head",
        "body_landed": "sig_str_landed_body", "body_att": "sig_str_atmp_body",
        "leg_landed": "sig_str_landed_leg", "leg_att": "sig_str_atmp_leg",
        "distance_landed": "sig_str_landed_distance", "distance_att": "sig_str_atmp_distance",
        "clinch_landed": "sig_str_landed_clinch", "clinch_att": "sig_str_atmp_clinch",
        "ground_landed": "sig_str_landed_ground", "ground_att": "sig_str_atmp_ground",
    }
    parts = []
    for side in ("r", "b"):
        p = pd.DataFrame({"fight_id": rd.fight_id, "fighter_id": rd[f"{side}_id"],
                          "round": pd.to_numeric(rd.round_no)})
        for dst, s in m.items():
            p[dst] = pd.to_numeric(rd[f"{side}_{s}"], errors="coerce")
        p["ctrl_sec"] = rd[f"{side}_ctrl"].map(pu.parse_mmss)
        parts.append(p)
    per_round = pd.concat(parts, ignore_index=True)
    per_round = per_round.dropna(subset=["fight_id", "fighter_id", "round"])
    per_round = per_round.drop_duplicates(["fight_id", "fighter_id", "round"])
    stat_cols = list(m) + ["ctrl_sec"]
    totals = per_round.groupby(["fight_id", "fighter_id"], as_index=False)[stat_cols].sum(min_count=1)
    totals["round"] = 0
    allrows = pd.concat([per_round, totals], ignore_index=True)
    for c in stat_cols:
        allrows[c] = allrows[c].astype("Int64")
    allrows["round"] = allrows["round"].astype(int)
    con.register("stats_df", allrows[["fight_id", "fighter_id", "round"] + stat_cols])
    con.execute("DELETE FROM fight_stats_round WHERE fight_id IN (SELECT DISTINCT fight_id FROM stats_df)")
    con.execute(f"INSERT INTO fight_stats_round (fight_id, fighter_id, round, {', '.join(stat_cols)}) "
                f"SELECT fight_id, fighter_id, round, {', '.join(stat_cols)} FROM stats_df")
    con.unregister("stats_df")


# ---------------------------------------------------------------- odds-dataset
def import_odds(con, src: Path) -> tuple[int, int]:
    od = pd.read_csv(src / "ufc-master.csv")
    od["date"] = pd.to_datetime(od["date"]).dt.date
    fights = con.execute(
        "SELECT fight_id, event_date, fighter_a_name, fighter_b_name FROM fights WHERE event_date >= DATE '2010-01-01'"
    ).df()
    fights["event_date"] = pd.to_datetime(fights["event_date"]).dt.date
    idx: dict[tuple, list] = {}
    for f in fights.itertuples(index=False):
        key = frozenset((norm_name(f.fighter_a_name), norm_name(f.fighter_b_name)))
        idx.setdefault(key, []).append(f)

    out, unmatched = [], 0
    for o in od.itertuples(index=False):
        r, b = norm_name(o.R_fighter), norm_name(o.B_fighter)
        cands = [f for f in idx.get(frozenset((r, b)), [])
                 if f.event_date and abs(f.event_date - o.date) <= timedelta(days=1)]
        if len(cands) != 1:
            unmatched += 1
            continue
        f = cands[0]
        swap = norm_name(f.fighter_a_name) != r  # odds-rood is onze fighter_b
        g = lambda a, bb: (getattr(o, bb), getattr(o, a)) if swap else (getattr(o, a), getattr(o, bb))
        oa, ob = g("R_odds", "B_odds")
        da, dbb = g("r_dec_odds", "b_dec_odds")
        sa, sb = g("r_sub_odds", "b_sub_odds")
        ka, kb = g("r_ko_odds", "b_ko_odds")
        out.append({k: _none(v) for k, v in {
            "fight_id": f.fight_id, "source": "kaggle_mdabbert", "captured": "closing",
            "odds_a": oa, "odds_b": ob, "dec_odds_a": da, "dec_odds_b": dbb,
            "sub_odds_a": sa, "sub_odds_b": sb, "ko_odds_a": ka, "ko_odds_b": kb,
        }.items()})
    db.upsert(con, "odds", out)
    return len(out), unmatched


# ---------------------------------------------------------------- CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--download", action="store_true", help="datasets eerst (opnieuw) downloaden")
    ap.add_argument("--db", default=str(db.DEFAULT_DB))
    a = ap.parse_args(argv)

    stats_dir = KAGGLE_DIR / STATS_SLUG.split("/")[1]
    odds_dir = KAGGLE_DIR / ODDS_SLUG.split("/")[1]
    if a.download:
        stats_dir, odds_dir = download(STATS_SLUG), download(ODDS_SLUG)

    con = db.connect(a.db)
    con.execute("BEGIN")
    import_stats(con, stats_dir)
    matched, unmatched = import_odds(con, odds_dir)
    con.execute("COMMIT")

    print("Rijen per tabel:", db.row_counts(con))
    print(f"Odds gekoppeld: {matched}, niet gekoppeld: {unmatched}")
    print("Laatste event:", con.execute("SELECT max(date) FROM events").fetchone()[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
