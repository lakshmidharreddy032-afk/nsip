"""Deterministic normalisers for Indian insurance submissions (amounts in lakh/crore, dates, pincodes)."""
from __future__ import annotations

import re
from datetime import date, datetime

from app.adapters.data import lookup

_UNITS = {"crore": 10_000_000, "crores": 10_000_000, "cr": 10_000_000, "lakh": 100_000, "lakhs": 100_000,
          "lac": 100_000, "lacs": 100_000, "k": 1000, "thousand": 1000, "mn": 1_000_000, "million": 1_000_000}
_AMOUNT_RX = re.compile(r"(?:rs\.?|inr|₹)?\s*([\d][\d,]*(?:\.\d+)?)\s*(crores?|cr|lakhs?|lacs?|thousand|million|mn|k)?\b",
                        re.I)


def parse_amount(value, multiplier: int = 1) -> int | None:
    """'Rs 12,50,00,000' | '12.5 crore' | '125 lakh' | 125000000 -> rupees (int)."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(round(float(value) * multiplier))
    s = str(value).strip().lower()
    if s in ("nil", "none", "-", "na", "n/a"):
        return 0
    m = _AMOUNT_RX.search(s)
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    unit = _UNITS.get((m.group(2) or "").lower(), 1)
    return int(round(num * unit * (multiplier if unit == 1 else 1)))


def normalise_construction(value: str | None) -> str | None:
    if not value:
        return None
    s = str(value).lower()
    if any(k in s for k in ("kutcha", "kachha", "thatch", "temporary", "bamboo", "tin shed", "tarpaulin")):
        return "kutcha"
    if any(k in s for k in ("rcc", "reinforced", "pucca", "pukka", "concrete", "class 1", "class i")):
        return "rcc"
    if any(k in s for k in ("steel", "peb", "pre-engineered", "metal frame", "structural")):
        return "steel"
    if any(k in s for k in ("brick", "masonry", "load bearing", "stone", "class 2", "class ii")):
        return "masonry"
    return None


def parse_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_int(value) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int | float) and not isinstance(value, bool):
        return int(value)
    m = re.search(r"\d+", str(value))
    if not m:
        return 0 if str(value).strip().lower() in ("nil", "none", "no") else None
    return int(m.group())


def parse_year(value, today: date | None = None) -> int | None:
    n = parse_int(value)
    if n is None:
        return None
    today = today or date.today()
    if n < 200 and value is not None and "year" in str(value).lower():  # "15 years old"
        return today.year - n
    return n


def pincode_valid(pin) -> bool:
    s = str(pin or "").strip()
    return bool(re.fullmatch(r"[1-8]\d{5}", s)) and lookup(s) is not None


def collapse_initials(s: str) -> str:
    """'a.b.c. textiles' -> 'abc textiles'; 'm.i.d.c.' -> 'midc'."""
    return re.sub(r"(?<![a-z])(?:[a-z]\.\s?){2,}", lambda m: re.sub(r"[.\s]", "", m.group()) + " ", s)


_LEGAL = re.compile(r"\b(m/s|messrs|pvt|private|ltd|limited|llp|inc|co|company|corp|corporation|the|and|&)\b")


def normalise_name(name: str | None) -> str:
    s = re.sub(r"\b(m/s|messrs)\.?\s*", " ", (name or "").lower())
    s = collapse_initials(s)
    s = s.replace(".", " ")
    s = _LEGAL.sub(" ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_ADDR_ABBR = [(r"\brd\b", "road"), (r"\bst\b", "street"), (r"\bmarg\b", "road"), (r"\bno\b", ""),
              (r"\bplot\b", ""), (r"\bnear\b", ""), (r"\bopp\b", ""), (r"\bind\b", "industrial"),
              (r"\bindl\b", "industrial"), (r"\bestt?\b", "estate"), (r"\barea\b", ""), (r"\bph\b", "phase")]


def normalise_address(addr: str | None) -> str:
    s = collapse_initials((addr or "").lower())
    s = s.replace(".", " ").replace(",", " ")
    for rx, rep in _ADDR_ABBR:
        s = re.sub(rx, rep, s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()
