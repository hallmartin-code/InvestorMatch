"""Money, check-size and date parsing."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

from app.models import Money

_CUR_PRE = r"(?P<pre>US\$|USD\s?|CAD\s?|C\$|A\$|AUD\s?|EUR\s?|€|GBP\s?|£|\$)"
_NUM = r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_UNIT = r"(?:\s?(?P<unit>thousand|million|billion|MM|mm|mn|bn|[kKmMbB])(?![A-Za-z]))?"
_CUR_POST = r"(?:\s?(?P<post>USD|EUR|GBP|CAD|AUD)\b)?"
MONEY_RE = re.compile(_CUR_PRE + _NUM + _UNIT + _CUR_POST)
MONEY_POST_RE = re.compile(r"(?<![\w$€£.])" + _NUM + r"\s?(?P<unit>thousand|million|billion|MM|mn|bn|[kKmMbB])?"
                           r"\s?(?P<post>USD|EUR|GBP|CAD|AUD)\b")

_CURRENCY = {"$": "USD", "US$": "USD", "USD": "USD", "C$": "CAD", "CAD": "CAD", "A$": "AUD", "AUD": "AUD",
             "€": "EUR", "EUR": "EUR", "£": "GBP", "GBP": "GBP"}
_UNITS = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9,
          "billion": 1e9}


@dataclass(frozen=True)
class MoneyMention:
    money: Money
    start: int
    end: int
    text: str


def _to_money(num: str, unit: str | None, currency: str) -> Money:
    value = float(num.replace(",", ""))
    if unit:
        value *= _UNITS[unit.lower()]
    return Money(round(value, 2), currency)


def money_mentions(text: str) -> list[MoneyMention]:
    out: list[MoneyMention] = []
    for m in MONEY_RE.finditer(text or ""):
        cur = _CURRENCY[(m.group("post") or m.group("pre")).strip()]
        out.append(MoneyMention(_to_money(m.group("num"), m.group("unit"), cur), m.start(), m.end(), m.group(0)))
    taken = [(x.start, x.end) for x in out]
    for m in MONEY_POST_RE.finditer(text or ""):
        if any(s <= m.start() < e for s, e in taken):
            continue
        out.append(MoneyMention(_to_money(m.group("num"), m.group("unit"), _CURRENCY[m.group("post")]),
                                m.start(), m.end(), m.group(0)))
    return sorted(out, key=lambda x: x.start)


def parse_money(text: str, default_currency: str = "USD") -> Money | None:
    """A single amount; bare numbers ('2500000', '2.5M') are read in the default currency."""
    mentions = money_mentions(text)
    if mentions:
        return mentions[0].money
    m = re.fullmatch(r"\s*" + _NUM + _UNIT + r"\s*", text or "")
    if m:
        return _to_money(m.group("num"), m.group("unit"), default_currency)
    return None


# ------------------------------------------------------------------------------ check size


@dataclass(frozen=True)
class CheckRange:
    minimum: float | None
    maximum: float | None
    currency: str
    raw: str

    def display(self) -> str:
        lo = Money(self.minimum, self.currency).display() if self.minimum else None
        hi = Money(self.maximum, self.currency).display() if self.maximum else None
        if lo and hi:
            return lo if lo == hi else f"{lo}–{hi}"
        if hi:
            return f"up to {hi}"
        return f"{lo}+" if lo else self.raw


_RANGE = re.compile(
    r"(?P<pre>US\$|USD\s?|C\$|CAD\s?|€|EUR\s?|£|GBP\s?|\$)?\s?(?P<a>\d[\d,]*(?:\.\d+)?)\s?(?P<ua>thousand|million|MM|mm|[kKmM])?"
    r"\s?(?:-|–|—|to)\s?(?:US\$|USD\s?|C\$|CAD\s?|€|EUR\s?|£|GBP\s?|\$)?\s?(?P<b>\d[\d,]*(?:\.\d+)?)"
    r"\s?(?P<ub>thousand|million|MM|mm|[kKmM])?(?![A-Za-z])"
)


def parse_check(text: str | None, default_currency: str = "USD") -> CheckRange | None:
    raw = (text or "").strip()
    if not raw:
        return None
    m = _RANGE.search(raw)
    if m and (m.group("pre") or m.group("ua") or m.group("ub")):
        cur = _CURRENCY.get((m.group("pre") or "").strip(), default_currency)
        unit_b = m.group("ub")
        unit_a = m.group("ua") or unit_b
        lo = _to_money(m.group("a"), unit_a, cur).amount
        hi = _to_money(m.group("b"), unit_b, cur).amount
        if lo > hi and not m.group("ua"):      # "$500-2M": first unit differs from second
            lo = _to_money(m.group("a"), "k", cur).amount
        return CheckRange(min(lo, hi), max(lo, hi), cur, raw)
    mentions = money_mentions(raw)
    if not mentions:
        bare = parse_money(raw, default_currency)
        return CheckRange(bare.amount, bare.amount, bare.currency, raw) if bare else None
    first = mentions[0].money
    if re.search(r"\bup to\b|\bmax(?:imum)?\b|≤|<=?", raw, re.I):
        return CheckRange(None, first.amount, first.currency, raw)
    if re.search(r"\+|\bplus\b|\bmin(?:imum)?\b|\band (?:above|up)\b|≥|>=?", raw, re.I):
        return CheckRange(first.amount, None, first.currency, raw)
    if len(mentions) >= 2 and mentions[1].money.currency == first.currency:
        a, b = first.amount, mentions[1].money.amount
        return CheckRange(min(a, b), max(a, b), first.currency, raw)
    return CheckRange(first.amount, first.amount, first.currency, raw)


# ------------------------------------------------------------------------------ dates

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
_MONTHS["sept"] = 9
_MON = r"(?P<mon>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
_DATE_PATTERNS = [
    ("day", re.compile(r"\b(?P<y>20\d\d)-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b")),
    ("day", re.compile(r"\b(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>20\d\d)\b")),
    ("day", re.compile(rf"\b{_MON}\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y>20\d\d)\b", re.I)),
    ("day", re.compile(rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+{_MON},?\s+(?P<y>20\d\d)\b", re.I)),
    ("quarter", re.compile(r"\b(?:Q(?P<q>[1-4])|(?P<qw>first|second|third|fourth) quarter(?: of)?)\s*(?:FY)?\s*'?(?P<y>20\d\d|\d\d)\b", re.I)),
    ("month", re.compile(rf"\b{_MON},?\s+(?P<y>20\d\d)\b", re.I)),
]
_QWORD = {"first": 1, "second": 2, "third": 3, "fourth": 4}


def _month(token: str) -> int:
    t = token.lower().rstrip(".")
    return _MONTHS.get(t) or _MONTHS[t[:3]]


@dataclass(frozen=True)
class DateMention:
    value: date
    display: str
    precision: str
    start: int
    end: int


def date_mentions(text: str) -> list[DateMention]:
    found: list[DateMention] = []
    spans: list[tuple[int, int]] = []
    for precision, pat in _DATE_PATTERNS:
        for m in pat.finditer(text or ""):
            if any(s <= m.start() < e or s < m.end() <= e for s, e in spans):
                continue
            g = m.groupdict()
            try:
                year = int(g["y"]) if len(g["y"]) == 4 else 2000 + int(g["y"])
                if precision == "quarter":
                    q = int(g["q"]) if g.get("q") else _QWORD[g["qw"].lower()]
                    month = q * 3
                    value = date(year, month, calendar.monthrange(year, month)[1])
                    display = f"Q{q} {year}"
                else:
                    month = int(g["m"]) if g.get("m") else _month(g["mon"])
                    if precision == "month":
                        value = date(year, month, 1)
                        display = value.strftime("%B %Y")
                    else:
                        value = date(year, month, int(g["d"]))
                        display = f"{value:%B} {value.day}, {year}"
            except (ValueError, KeyError):
                continue
            found.append(DateMention(value, display, precision, m.start(), m.end()))
            spans.append((m.start(), m.end()))
    return sorted(found, key=lambda d: d.start)
