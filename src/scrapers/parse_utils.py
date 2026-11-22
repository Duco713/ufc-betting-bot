"""Kleine, pure parse-helpers voor ufcstats.com-tekst. Geen netwerk, goed te testen."""
from __future__ import annotations

import re
from datetime import date, datetime

NULL_TOKENS = {"", "--", "---", "n/a", "na", "null", "none"}

_ID_RE = re.compile(r"/(?:event|fight|fighter)-details/([0-9a-fA-F]+)")


def clean(text: str | None) -> str | None:
    """Collapse whitespace; '--' en lege strings -> None."""
    if not isinstance(text, str):  # None, of NaN uit pandas
        return None
    t = re.sub(r"\s+", " ", text).strip()
    return None if t.lower() in NULL_TOKENS else t


def id_from_url(url: str | None) -> str | None:
    """Stabiele id uit een ufcstats-URL (laatste padsegment, hex)."""
    if not url:
        return None
    m = _ID_RE.search(url)
    if m:
        return m.group(1).lower()
    seg = url.rstrip("/").rsplit("/", 1)[-1]
    return seg.lower() or None


def parse_int(text: str | None) -> int | None:
    t = clean(text)
    if t is None:
        return None
    m = re.search(r"-?\d+", t)
    return int(m.group()) if m else None


def parse_of(text: str | None) -> tuple[int | None, int | None]:
    """'12 of 30' -> (12, 30); '--' -> (None, None)."""
    t = clean(text)
    if t is None:
        return (None, None)
    m = re.match(r"^\s*(\d+)\s+of\s+(\d+)\s*$", t)
    if not m:
        return (None, None)
    return int(m.group(1)), int(m.group(2))


def parse_mmss(text: str | None) -> int | None:
    """'4:59' -> 299 seconden; '--' -> None. Ondersteunt ook 'H:MM:SS'."""
    t = clean(text)
    if t is None:
        return None
    parts = t.split(":")
    if not all(p.strip().isdigit() for p in parts) or not 2 <= len(parts) <= 3:
        return None
    secs = 0
    for p in parts:
        secs = secs * 60 + int(p)
    return secs


def parse_pct(text: str | None) -> float | None:
    """'45%' -> 0.45."""
    t = clean(text)
    if t is None:
        return None
    m = re.match(r"^(\d+(?:\.\d+)?)\s*%$", t)
    return float(m.group(1)) / 100 if m else None


def parse_height_in(text: str | None) -> int | None:
    """'5\\' 11"' -> 71 (inches)."""
    t = clean(text)
    if t is None:
        return None
    m = re.match(r"^(\d+)\s*'\s*(\d+)?\s*\"?$", t)
    if not m:
        return None
    return int(m.group(1)) * 12 + int(m.group(2) or 0)


def parse_reach_in(text: str | None) -> float | None:
    """'72"' -> 72.0 (inches)."""
    t = clean(text)
    if t is None:
        return None
    m = re.match(r"^(\d+(?:\.\d+)?)\s*\"?$", t)
    return float(m.group(1)) if m else None


def parse_weight_lbs(text: str | None) -> float | None:
    """'155 lbs.' -> 155.0."""
    t = clean(text)
    if t is None:
        return None
    m = re.match(r"^(\d+(?:\.\d+)?)\s*lbs?\.?$", t, re.I)
    return float(m.group(1)) if m else None


def inches_to_cm(v: float | None) -> float | None:
    return None if v is None else round(v * 2.54, 1)


_DATE_FORMATS = ("%B %d, %Y", "%b %d, %Y", "%b. %d, %Y", "%Y-%m-%d", "%d %B %Y")


def parse_date(text: str | None) -> date | None:
    """'November 15, 2025' / 'Jul 13, 1988' -> date."""
    t = clean(text)
    if t is None:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def parse_record(text: str | None) -> dict:
    """'Record: 22-6-0 (1 NC)' -> {'wins':22,'losses':6,'draws':0,'nc':1}."""
    out = {"wins": None, "losses": None, "draws": None, "nc": None}
    t = clean(text)
    if t is None:
        return out
    m = re.search(r"(\d+)-(\d+)-(\d+)", t)
    if m:
        out["wins"], out["losses"], out["draws"] = (int(x) for x in m.groups())
        nc = re.search(r"\((\d+)\s*NC\)", t, re.I)
        out["nc"] = int(nc.group(1)) if nc else 0
    return out


def parse_time_format(text: str | None) -> int | None:
    """'3 Rnd (5-5-5)' -> 3; '5 Rnd (5-5-5-5-5)' -> 5; 'No Time Limit' -> None."""
    t = clean(text)
    if t is None:
        return None
    m = re.match(r"^(\d+)\s*Rnd", t, re.I)
    return int(m.group(1)) if m else None
