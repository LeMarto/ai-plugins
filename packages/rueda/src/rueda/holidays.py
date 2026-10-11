"""Bank holidays for business-day adjustment (stdlib only).

Usage: rueda holidays AR|US <year> [<year> ...]
AR: api.argentinadatos.com (published years, cached in ./holidays/), plus Jueves
Santo (día no laborable, banks closed). Years the API has not published fall back
to fixed-date and Easter-based holidays plus the movable ones placed by the law
27.399 rule (Tue/Wed -> previous Monday, Thu/Fri -> next Monday), with a warning:
the executive can move them and decrees puentes each year.
US: Federal Reserve holidays (New York banks), computed by rule.
"""

import http.client
import json
import sys
import urllib.request
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

CACHE = "holidays"
AR_FIXED = [
    (1, 1),
    (3, 24),
    (4, 2),
    (5, 1),
    (5, 25),
    (6, 20),
    (7, 9),
    (12, 8),
    (12, 25),
]
AR_MOVABLE = [(6, 17), (8, 17), (10, 12), (11, 20)]  # trasladables
SATURDAY, SUNDAY = 5, 6  # date.weekday()
DECEMBER = 12
JUNETEENTH_SINCE = 2022
MIN_ARGS = 2  # calendar and one year


def easter(y: int) -> date:
    """Return Easter Sunday of year y (anonymous Gregorian algorithm)."""
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    g = (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    n = h + ell - 7 * m + 114
    return date(y, n // 31, n % 31 + 1)


def _fetch_ar(y: int) -> list[dict[str, str]] | None:
    path = Path(CACHE) / f"AR_{y}.json"
    if path.exists():
        cached: list[dict[str, str]] = json.loads(path.read_text())
        return cached
    try:
        with urllib.request.urlopen(
            urllib.request.Request(
                f"https://api.argentinadatos.com/v1/feriados/{y}",
                headers={"User-Agent": "Mozilla/5.0"},
            ),
            timeout=30,
        ) as r:
            data: list[dict[str, str]] = json.load(r)
    except (OSError, ValueError, http.client.HTTPException):
        return None  # 404 for unpublished years, or no network
    Path(CACHE).mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data


def moved(x: date) -> date:
    """Apply law 27.399 to a movable holiday.

    Tue/Wed moves to the previous Monday, Thu/Fri to the next Monday.
    """
    wd = x.weekday()
    return (
        x - timedelta(wd)
        if wd in (1, 2)
        else x + timedelta(7 - wd)
        if wd in (3, 4)
        else x
    )


def ar(y: int) -> tuple[set[date], str | None]:
    """Return (set of dates, warning or None) for Argentina."""
    e = easter(y)
    rule = {e - timedelta(3), e - timedelta(2)}  # Jueves and Viernes Santo
    data = _fetch_ar(y)
    if data:
        hs = {date.fromisoformat(x["fecha"]) for x in data}
        nominal = [
            date(y, m, d)
            for m, d in AR_MOVABLE
            if date(y, m, d) in hs and moved(date(y, m, d)) != date(y, m, d)
        ]
        w = (
            f"AR {y}: movable holidays listed at nominal dates "
            f"({', '.join(map(str, nominal))}); they may still move by decree"
            if nominal
            else None
        )
        return hs | rule, w
    rule |= {date(y, m, d) for m, d in AR_FIXED} | {
        e - timedelta(48),
        e - timedelta(47),
    }
    rule |= {moved(date(y, m, d)) for m, d in AR_MOVABLE}
    w = (
        f"AR {y}: holidays not published; fixed, Easter-based and law 27.399 "
        "movable dates used, puentes unknown"
    )
    return rule, w


def _nth(y: int, m: int, wd: int, n: int) -> date:
    # n-th weekday wd (0=Mon) of month; n=-1 for last
    if n > 0:
        d = date(y, m, 1)
        return d + timedelta((wd - d.weekday()) % 7 + 7 * (n - 1))
    d = date(y, m + 1, 1) - timedelta(1) if m < DECEMBER else date(y, 12, 31)
    return d - timedelta((d.weekday() - wd) % 7)


def us(y: int) -> tuple[set[date], str | None]:
    """Return (Federal Reserve holidays, None) for the United States."""
    fixed = [(1, 1), (7, 4), (11, 11), (12, 25)]
    if y >= JUNETEENTH_SINCE:
        fixed.append((6, 19))
    out = set()
    for m, d in fixed:
        h = date(y, m, d)
        if h.weekday() == SUNDAY:
            out.add(h + timedelta(1))  # Sunday -> Monday; Saturday is not observed
        elif h.weekday() < SATURDAY:
            out.add(h)
    out |= {
        _nth(y, 1, 0, 3),
        _nth(y, 2, 0, 3),
        _nth(y, 5, 0, -1),
        _nth(y, 9, 0, 1),
        _nth(y, 10, 0, 2),
        _nth(y, 11, 3, 4),
    }
    return out, None


def load(calendars: Sequence[str], years: Sequence[int]) -> tuple[set[date], list[str]]:
    """Return (holidays, warnings): the union of the calendars over the years."""
    out: set[date] = set()
    warns: list[str] = []
    for cal in calendars:
        fn = {"AR": ar, "US": us}.get(cal.upper())
        if fn is None:
            msg = f"unknown calendar {cal!r}; supported: AR, US"
            raise ValueError(msg)
        for y in years:
            s, w = fn(y)
            out |= s
            if w:
                warns.append(w)
    return out, warns


def load_file(path: str | Path) -> set[date]:
    """Return the dates in a JSON list of 'YYYY-MM-DD' strings or 'fecha' objects."""
    return {
        date.fromisoformat(x if isinstance(x, str) else x["fecha"])
        for x in json.loads(Path(path).read_text())
    }


def main(argv: list[str] | None = None) -> None:
    """Run `rueda holidays`."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) < MIN_ARGS or args[0] in ("-h", "--help"):
        sys.exit(__doc__)
    hs, warns = load([args[0]], [int(y) for y in args[1:]])
    for d in sorted(hs):
        sys.stdout.write(f"{d.isoformat()} {d:%a}\n")
    for w in warns:
        sys.stderr.write(f"WARN {w}\n")


if __name__ == "__main__":
    main()
