"""Point-in-time features per gevecht (PLAN.md §3, §5).

Kernidee: één "lange" tabel met een rij per vechter per gevecht, chronologisch. Elke
feature wordt berekend met `shift(1)`, dus alleen uit EERDERE gevechten van die vechter.
Komende gevechten worden als rijen zonder uitslag toegevoegd; hun features zijn dan
automatisch "de stand na het laatste bekende gevecht".
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from src.importers.kaggle import norm_name

EW_ALPHA = 0.35          # gewicht van het meest recente gevecht in de gewogen gemiddelden
ELO_START, ELO_K = 1500.0, 40.0

# (naam, teller, noemer, schaal) -> gewogen ratio teller/noemer * schaal
RATES = [
    ("slpm", "sig_l", "minutes", 1),            # sig. strikes landed per minuut
    ("sapm", "o_sig_l", "minutes", 1),          # sig. strikes absorbed per minuut
    ("sig_acc", "sig_l", "sig_a", 1),
    ("sig_def", "o_sig_miss", "o_sig_a", 1),
    ("td15", "td_l", "minutes", 15),
    ("td_acc", "td_l", "td_a", 1),
    ("td_def", "o_td_miss", "o_td_a", 1),
    ("ctrl_share", "ctrl", "seconds", 1),
    ("o_ctrl_share", "o_ctrl", "seconds", 1),
    ("sub15", "sub_att", "minutes", 15),
    ("kd15", "kd", "minutes", 15),
    ("kd_abs15", "o_kd", "minutes", 15),
    ("head_share", "head_l", "sig_l", 1),
    ("leg_share", "leg_l", "sig_l", 1),
    ("dist_share", "dist_l", "sig_l", 1),
    ("ground_share", "ground_l", "sig_l", 1),
]


# ------------------------------------------------------------------ laden
def load_fights(con) -> pd.DataFrame:
    return con.execute("""
        SELECT f.fight_id, f.event_id, f.event_date AS date, f.fighter_a_id AS a, f.fighter_b_id AS b,
               f.result_a, f.method, f.end_round, f.end_time_sec, f.scheduled_rounds,
               f.weight_class, f.is_title_fight, f.is_womens
        FROM fights f WHERE f.event_date IS NOT NULL
    """).df()


def load_stats(con) -> pd.DataFrame:
    return con.execute("""
        SELECT fight_id, fighter_id, kd, sig_str_landed sig_l, sig_str_att sig_a, td_landed td_l,
               td_att td_a, sub_att, ctrl_sec ctrl, head_landed head_l, leg_landed leg_l,
               distance_landed dist_l, ground_landed ground_l
        FROM fight_stats_round WHERE round = 0
    """).df()


def load_fighters(con) -> pd.DataFrame:
    return con.execute("SELECT fighter_id, name, height_cm, reach_cm, stance, dob FROM fighters").df()


# ------------------------------------------------------------------ lange tabel
def long_table(fights: pd.DataFrame, stats: pd.DataFrame) -> pd.DataFrame:
    """Twee rijen per gevecht: perspectief van A en van B (met stats van de tegenstander)."""
    f = fights.copy()
    f["date"] = pd.to_datetime(f["date"])
    f["seconds"] = np.where(f.end_round.notna(),
                            (f.end_round.fillna(1) - 1) * 300 + f.end_time_sec.fillna(0), np.nan)
    a = f.rename(columns={"a": "fighter_id", "b": "opp_id"})
    a["result"] = f.result_a
    b = f.rename(columns={"b": "fighter_id", "a": "opp_id"})
    b["result"] = f.result_a.map({"W": "L", "L": "W", "D": "D", "NC": "NC"})
    long = pd.concat([a, b], ignore_index=True).drop(columns=["result_a"])

    st = stats.copy()
    long = long.merge(st, on=["fight_id", "fighter_id"], how="left")
    opp = st.rename(columns={c: "o_" + c for c in st.columns if c not in ("fight_id", "fighter_id")})
    opp = opp.rename(columns={"fighter_id": "opp_id"})
    long = long.merge(opp, on=["fight_id", "opp_id"], how="left")

    long["minutes"] = long.seconds / 60
    long.loc[long.sig_l.isna(), ["minutes", "seconds"]] = np.nan  # geen stats -> niet meetellen
    long["o_sig_miss"] = long.o_sig_a - long.o_sig_l
    long["o_td_miss"] = long.o_td_a - long.o_td_l
    m = long.method.fillna("")
    long["won"] = (long.result == "W").astype(float)
    long.loc[long.result.isna(), "won"] = np.nan
    long["lost"] = (long.result == "L").astype(float)
    long["finish_win"] = ((long.result == "W") & ~m.str.startswith("Decision")).astype(float)
    long["ko_loss"] = ((long.result == "L") & m.str.contains("KO")).astype(float)
    long["sub_loss"] = ((long.result == "L") & m.str.contains("Submission")).astype(float)
    return long.sort_values(["date", "fight_id"]).reset_index(drop=True)


# ------------------------------------------------------------------ Elo
def add_elo(long: pd.DataFrame, fights: pd.DataFrame) -> pd.DataFrame:
    """Elo vóór elk gevecht. Finishes tellen zwaarder; komende gevechten updaten niets."""
    elo: dict[str, float] = {}
    pre: dict[tuple, float] = {}
    f = fights.assign(date=pd.to_datetime(fights.date)).sort_values(["date", "fight_id"])
    for r in f.itertuples(index=False):
        ea, eb = elo.get(r.a, ELO_START), elo.get(r.b, ELO_START)
        pre[(r.fight_id, r.a)], pre[(r.fight_id, r.b)] = ea, eb
        if r.result_a not in ("W", "L", "D"):
            continue
        sa = {"W": 1.0, "L": 0.0, "D": 0.5}[r.result_a]
        exp_a = 1 / (1 + 10 ** ((eb - ea) / 400))
        k = ELO_K * (1.25 if isinstance(r.method, str) and not r.method.startswith("Decision") else 1.0)
        elo[r.a], elo[r.b] = ea + k * (sa - exp_a), eb - k * (sa - exp_a)
    long["elo"] = [pre.get((fid, x), ELO_START) for fid, x in zip(long.fight_id, long.fighter_id)]
    long["o_elo"] = [pre.get((fid, x), ELO_START) for fid, x in zip(long.fight_id, long.opp_id)]
    return long


# ------------------------------------------------------------------ point-in-time features
def prefight_features(long: pd.DataFrame) -> pd.DataFrame:
    long = long.sort_values(["fighter_id", "date", "fight_id"]).reset_index(drop=True)
    g = long.groupby("fighter_id", sort=False)
    out = long[["fight_id", "fighter_id", "opp_id", "date", "elo", "o_elo"]].copy()

    def prev_cumsum(col):
        return g[col].transform(lambda s: s.fillna(0).cumsum().shift(1)).fillna(0)

    out["n_fights"] = g.cumcount()
    out["wins"] = prev_cumsum("won")
    out["losses"] = prev_cumsum("lost")
    out["win_pct"] = (out.wins + 1) / (out.n_fights + 2)          # gladgestreken
    out["finish_rate"] = (prev_cumsum("finish_win") + 0.5) / (out.wins + 1)
    out["ko_losses"] = prev_cumsum("ko_loss")
    out["sub_losses"] = prev_cumsum("sub_loss")
    out["cage_minutes"] = prev_cumsum("minutes")
    out["days_since"] = g["date"].diff().dt.days
    out["last_ko_loss"] = g["ko_loss"].shift(1)
    out["last3_win"] = g["won"].transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean())
    out["ew_win"] = g["won"].transform(lambda s: s.shift(1).ewm(alpha=EW_ALPHA, ignore_na=True).mean())
    out["opp_elo_avg"] = g["o_elo"].transform(lambda s: s.shift(1).expanding().mean())
    out["elo_trend"] = out.elo - g["elo"].shift(3)

    # winst-/verliesreeks (positief = winstreeks)
    def streak(s):
        res, cur = [], 0.0
        for v in s:
            res.append(cur)
            if v == 1:
                cur = cur + 1 if cur > 0 else 1
            elif v == 0:
                cur = cur - 1 if cur < 0 else -1
        return pd.Series(res, index=s.index)
    out["streak"] = g["won"].transform(streak)

    # gewogen ratio's: EW-gemiddelde van teller en noemer apart
    ew = lambda col: g[col].transform(lambda s: s.shift(1).ewm(alpha=EW_ALPHA, ignore_na=True).mean())
    cache = {}
    for name, num, den, scale in RATES:
        for c in (num, den):
            if c not in cache:
                cache[c] = ew(c)
        out[name] = cache[num] / cache[den].replace(0, np.nan) * scale
    out["sig_diff_pm"] = out.slpm - out.sapm

    # output in de laatste geregistreerde ronde vs ronde 1 volgt later (cardio, PLAN §3.5)
    return out


# ------------------------------------------------------------------ matchups
DIFF_COLS = ["elo", "n_fights", "win_pct", "finish_rate", "ko_losses", "cage_minutes", "days_since",
             "last_ko_loss", "last3_win", "ew_win", "opp_elo_avg", "elo_trend", "streak",
             "age", "height_cm", "reach_cm", "southpaw"] + [r[0] for r in RATES] + ["sig_diff_pm"]


def add_static(pf: pd.DataFrame, fighters: pd.DataFrame) -> pd.DataFrame:
    fx = fighters.set_index("fighter_id")
    pf = pf.join(fx[["height_cm", "reach_cm", "stance", "dob"]], on="fighter_id")
    pf["age"] = (pf.date - pd.to_datetime(pf.dob)).dt.days / 365.25
    pf["southpaw"] = pf.stance.isin(["Southpaw", "Switch"]).astype(float)
    pf.loc[pf.stance.isna(), "southpaw"] = np.nan
    return pf.drop(columns=["stance", "dob"])


def matchups(fights: pd.DataFrame, pf: pd.DataFrame) -> pd.DataFrame:
    """Eén rij per gevecht: A-features, B-features en verschil A-B, plus context."""
    key = pf.set_index(["fight_id", "fighter_id"])
    A = key.loc[list(zip(fights.fight_id, fights.a)), DIFF_COLS].reset_index(drop=True)
    B = key.loc[list(zip(fights.fight_id, fights.b)), DIFF_COLS].reset_index(drop=True)
    X = pd.DataFrame(index=fights.index)
    base = fights.reset_index(drop=True)
    X = base[["fight_id", "date", "a", "b"]].copy()
    for c in DIFF_COLS:
        X["d_" + c] = A[c].values - B[c].values
    for c in ("age", "n_fights", "elo"):
        X["a_" + c], X["b_" + c] = A[c].values, B[c].values
    X["a_debut"] = (A.n_fights.values == 0).astype(float)
    X["b_debut"] = (B.n_fights.values == 0).astype(float)
    X["five_rounds"] = (base.scheduled_rounds == 5).astype(float).values
    X["title"] = base.is_title_fight.astype(float).values
    X["womens"] = base.is_womens.astype(float).values
    X["elo_prob"] = 1 / (1 + 10 ** (-(A.elo.values - B.elo.values) / 400))
    X["y"] = base.result_a.map({"W": 1.0, "L": 0.0}).values
    return X


def build_all(con, upcoming: pd.DataFrame | None = None, return_pf: bool = False):
    """Alle historische gevechten (+ optioneel komende) als matchup-tabel.
    Met return_pf=True ook de per-vechter-per-gevecht features (voor het dashboard)."""
    fights = load_fights(con)
    if upcoming is not None and len(upcoming):
        fights = pd.concat([fights, upcoming], ignore_index=True)
    fights["date"] = pd.to_datetime(fights["date"])
    fights = fights.sort_values(["date", "fight_id"]).reset_index(drop=True)
    long = long_table(fights, load_stats(con))
    long = add_elo(long, fights)
    pf = prefight_features(long)
    pf = add_static(pf, load_fighters(con))
    X = matchups(fights, pf)
    return (X, pf) if return_pf else X


# ------------------------------------------------------------------ namen -> ID's
def resolve_fighter(con, name: str, weight_class: str | None = None) -> str:
    """Zoek fighter_id op naam; bij meerdere kandidaten wint wie het laatst in deze klasse vocht.
    Onbekende vechters (UFC-debuut, nog niet in de data) krijgen een synthetisch ID."""
    df = con.execute("""
        SELECT fi.fighter_id, fi.name, max(f.event_date) last,
               arg_max(f.weight_class, f.event_date) last_wc
        FROM fighters fi LEFT JOIN fights f ON fi.fighter_id IN (f.fighter_a_id, f.fighter_b_id)
        GROUP BY 1, 2""").df()
    df = df[df.name.map(norm_name) == norm_name(name)]
    if df.empty:
        return "new:" + norm_name(name).replace(" ", "-")
    if len(df) > 1 and weight_class:
        wc = df[df.last_wc.fillna("").str.lower() == weight_class.lower()]
        if len(wc):
            df = wc
    return df.sort_values("last", na_position="first").iloc[-1].fighter_id
