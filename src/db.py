"""DuckDB-schema en upsert-helpers (PLAN.md §7)."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "ufc.duckdb"

SCHEMA = """
CREATE TABLE IF NOT EXISTS fighters (
    fighter_id      VARCHAR PRIMARY KEY,
    name            VARCHAR,
    nickname        VARCHAR,
    height_in       INTEGER,
    height_cm       DOUBLE,
    weight_lbs      DOUBLE,
    reach_in        DOUBLE,
    reach_cm        DOUBLE,
    stance          VARCHAR,
    dob             DATE,
    record_wins     INTEGER,   -- record zoals NU getoond (niet point-in-time!)
    record_losses   INTEGER,
    record_draws    INTEGER,
    record_nc       INTEGER,
    url             VARCHAR,
    details_scraped_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events (
    event_id    VARCHAR PRIMARY KEY,
    name        VARCHAR,
    date        DATE,
    location    VARCHAR,
    status      VARCHAR,      -- 'completed' | 'upcoming'
    altitude_m  DOUBLE,       -- later aanvullen (§3.6)
    cage        VARCHAR,      -- later aanvullen (Apex klein/groot)
    url         VARCHAR,
    scraped_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fights (
    fight_id         VARCHAR PRIMARY KEY,
    event_id         VARCHAR,
    event_date       DATE,
    card_position    INTEGER,  -- 0 = main event
    fighter_a_id     VARCHAR,
    fighter_a_name   VARCHAR,
    fighter_b_id     VARCHAR,
    fighter_b_name   VARCHAR,
    result_a         VARCHAR,  -- W / L / D / NC
    result_b         VARCHAR,
    winner_id        VARCHAR,  -- NULL bij draw / NC
    weight_class     VARCHAR,
    bout_title       VARCHAR,  -- bv. 'UFC Lightweight Title Bout'
    is_title_fight   BOOLEAN,
    is_womens        BOOLEAN,
    method           VARCHAR,  -- bv. 'KO/TKO', 'Decision - Unanimous'
    method_detail    VARCHAR,  -- bv. 'Punch' (event-pagina) of jury-scores
    end_round        INTEGER,
    end_time_sec     INTEGER,  -- tijd in de eindronde
    time_format      VARCHAR,
    scheduled_rounds INTEGER,
    referee          VARCHAR,
    details          VARCHAR,
    bonus_perf       BOOLEAN,
    bonus_fight      BOOLEAN,
    bonus_sub        BOOLEAN,
    bonus_ko         BOOLEAN,
    url              VARCHAR,
    scraped_at       TIMESTAMP
);

-- round 0 = totalen van het hele gevecht
CREATE TABLE IF NOT EXISTS fight_stats_round (
    fight_id   VARCHAR,
    fighter_id VARCHAR,
    round      INTEGER,
    kd                 INTEGER,
    sig_str_landed     INTEGER, sig_str_att     INTEGER,
    total_str_landed   INTEGER, total_str_att   INTEGER,
    td_landed          INTEGER, td_att          INTEGER,
    sub_att            INTEGER,
    rev                INTEGER,
    ctrl_sec           INTEGER,
    head_landed        INTEGER, head_att        INTEGER,
    body_landed        INTEGER, body_att        INTEGER,
    leg_landed         INTEGER, leg_att         INTEGER,
    distance_landed    INTEGER, distance_att    INTEGER,
    clinch_landed      INTEGER, clinch_att      INTEGER,
    ground_landed      INTEGER, ground_att      INTEGER,
    PRIMARY KEY (fight_id, fighter_id, round)
);

-- odds per gevecht en bron (Kaggle 'ultimate-ufc-dataset', later The Odds API / BestFightOdds)
CREATE TABLE IF NOT EXISTS odds (
    fight_id        VARCHAR,
    source          VARCHAR,
    captured        VARCHAR,   -- 'closing' | 'opening' | tijdstempel
    odds_a          DOUBLE,    -- Amerikaanse odds voor fighter_a van de fights-tabel
    odds_b          DOUBLE,
    dec_odds_a      DOUBLE,    -- methode-odds (beslissing / sub / KO) indien bekend
    dec_odds_b      DOUBLE,
    sub_odds_a      DOUBLE,
    sub_odds_b      DOUBLE,
    ko_odds_a       DOUBLE,
    ko_odds_b       DOUBLE,
    PRIMARY KEY (fight_id, source, captured)
);

-- uitslagen van andere organisaties (src/importers/wiki_orgs.py)
CREATE TABLE IF NOT EXISTS ext_fights (
    fight_id VARCHAR PRIMARY KEY, org VARCHAR, tier INTEGER, event_name VARCHAR, event_date DATE,
    a_name VARCHAR, b_name VARCHAR, a_key VARCHAR, b_key VARCHAR, kind VARCHAR,
    method VARCHAR, end_round INTEGER, weight_class VARCHAR, source VARCHAR
);

CREATE TABLE IF NOT EXISTS upcoming_fights (
    fight_id       VARCHAR PRIMARY KEY,
    event_id       VARCHAR,
    event_name     VARCHAR,
    event_date     DATE,
    location       VARCHAR,
    card_position  INTEGER,
    fighter_a_id   VARCHAR,
    fighter_a_name VARCHAR,
    fighter_b_id   VARCHAR,
    fighter_b_name VARCHAR,
    weight_class   VARCHAR,
    is_title_fight BOOLEAN,
    url            VARCHAR,
    scraped_at     TIMESTAMP
);
"""

STAT_COLUMNS = [
    "kd",
    "sig_str_landed", "sig_str_att",
    "total_str_landed", "total_str_att",
    "td_landed", "td_att",
    "sub_att", "rev", "ctrl_sec",
    "head_landed", "head_att",
    "body_landed", "body_att",
    "leg_landed", "leg_att",
    "distance_landed", "distance_att",
    "clinch_landed", "clinch_att",
    "ground_landed", "ground_att",
]

PRIMARY_KEYS = {
    "fighters": ["fighter_id"],
    "events": ["event_id"],
    "fights": ["fight_id"],
    "fight_stats_round": ["fight_id", "fighter_id", "round"],
    "upcoming_fights": ["fight_id"],
    "odds": ["fight_id", "source", "captured"],
    "ext_fights": ["fight_id"],
}


def connect(path: Path | str = DEFAULT_DB) -> duckdb.DuckDBPyConnection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(SCHEMA)
    return con


def upsert(con, table: str, rows: Iterable[dict], *, update: bool = True) -> int:
    """INSERT ... ON CONFLICT DO UPDATE (of DO NOTHING) voor een lijst dicts.

    Alleen kolommen die in de dicts staan worden geschreven; bij een update
    worden alleen die kolommen overschreven.
    """
    rows = list(rows)
    if not rows:
        return 0
    cols = list(rows[0].keys())
    pk = PRIMARY_KEYS[table]
    placeholders = ", ".join("?" for _ in cols)
    non_pk = [c for c in cols if c not in pk]
    if update and non_pk:
        conflict = "DO UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in non_pk)
    else:
        conflict = "DO NOTHING"
    sql = (
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({', '.join(pk)}) {conflict}"
    )
    con.executemany(sql, [[r.get(c) for c in cols] for r in rows])
    return len(rows)


def row_counts(con) -> dict[str, int]:
    return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in PRIMARY_KEYS}
