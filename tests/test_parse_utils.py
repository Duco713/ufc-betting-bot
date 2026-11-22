from datetime import date

import pytest

from src.scrapers.parse_utils import (
    clean, id_from_url, inches_to_cm, parse_date, parse_height_in, parse_int, parse_mmss,
    parse_of, parse_pct, parse_reach_in, parse_record, parse_time_format, parse_weight_lbs,
)


@pytest.mark.parametrize("raw,exp", [("  a \n b ", "a b"), ("--", None), ("", None), (None, None), ("---", None)])
def test_clean(raw, exp):
    assert clean(raw) == exp


def test_id_from_url():
    assert id_from_url("http://ufcstats.com/fight-details/ABCdef0123456789 ") == "abcdef0123456789"
    assert id_from_url("http://ufcstats.com/fighter-details/1111aaaa1111aaaa") == "1111aaaa1111aaaa"
    assert id_from_url(None) is None


@pytest.mark.parametrize("raw,exp", [("12 of 30", (12, 30)), (" 0 of 0 ", (0, 0)), ("--", (None, None)), ("x", (None, None))])
def test_parse_of(raw, exp):
    assert parse_of(raw) == exp


@pytest.mark.parametrize("raw,exp", [("4:59", 299), ("0:05", 5), ("15:00", 900), ("1:02:03", 3723), ("--", None), ("abc", None)])
def test_parse_mmss(raw, exp):
    assert parse_mmss(raw) == exp


@pytest.mark.parametrize("raw,exp", [("5' 11\"", 71), ("6' 0\"", 72), ("5'11\"", 71), ("--", None)])
def test_parse_height(raw, exp):
    assert parse_height_in(raw) == exp


@pytest.mark.parametrize("raw,exp", [('72"', 72.0), ('74.5"', 74.5), ("--", None)])
def test_parse_reach(raw, exp):
    assert parse_reach_in(raw) == exp


def test_cm_and_weight_and_pct_and_int():
    assert inches_to_cm(71) == 180.3
    assert inches_to_cm(None) is None
    assert parse_weight_lbs("155 lbs.") == 155.0
    assert parse_weight_lbs("--") is None
    assert parse_pct("45%") == 0.45
    assert parse_pct("---") is None
    assert parse_int(" 3 ") == 3
    assert parse_int("--") is None


@pytest.mark.parametrize("raw,exp", [
    ("November 15, 2025", date(2025, 11, 15)),
    ("Jul 13, 1988", date(1988, 7, 13)),
    ("Sept 1, 2020", None),
    ("--", None),
])
def test_parse_date(raw, exp):
    assert parse_date(raw) == exp


def test_parse_record():
    assert parse_record("Record: 22-6-0 (1 NC)") == {"wins": 22, "losses": 6, "draws": 0, "nc": 1}
    assert parse_record("Record: 10-0-0") == {"wins": 10, "losses": 0, "draws": 0, "nc": 0}


@pytest.mark.parametrize("raw,exp", [("3 Rnd (5-5-5)", 3), ("5 Rnd (5-5-5-5-5)", 5), ("No Time Limit", None), ("1 Rnd + OT (15-3)", 1)])
def test_time_format(raw, exp):
    assert parse_time_format(raw) == exp
