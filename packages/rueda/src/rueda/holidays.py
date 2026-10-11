"""Bank holidays for business-day adjustment (stdlib only).
Usage: rueda holidays AR|US <year> [<year> ...]
AR: api.argentinadatos.com (published years, cached in ./holidays/), plus Jueves
Santo (día no laborable, banks closed). Years the API has not published fall back
to fixed-date and Easter-based holidays plus the movable ones placed by the law
27.399 rule (Tue/Wed -> previous Monday, Thu/Fri -> next Monday), with a warning:
the executive can move them and decrees puentes each year.
US: Federal Reserve holidays (New York banks), computed by rule."""
import json, os, sys, urllib.request
from datetime import date, timedelta

API = "https://api.argentinadatos.com/v1/feriados/{y}"
CACHE = "holidays"
AR_FIXED = [(1, 1), (3, 24), (4, 2), (5, 1), (5, 25), (6, 20), (7, 9), (12, 8), (12, 25)]
AR_MOVABLE = [(6, 17), (8, 17), (10, 12), (11, 20)]  # trasladables


def easter(y):  # anonymous Gregorian algorithm
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    g = (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    n = h + l - 7 * m + 114
    return date(y, n // 31, n % 31 + 1)


def _fetch_ar(y):
    path = os.path.join(CACHE, f"AR_{y}.json")
    if os.path.exists(path):
        return json.load(open(path))
    try:
        req = urllib.request.Request(API.format(y=y), headers={"User-Agent": "Mozilla/5.0"})
        data = json.load(urllib.request.urlopen(req, timeout=30))
    except Exception:
        return None  # 404 for unpublished years, or no network
    os.makedirs(CACHE, exist_ok=True)
    json.dump(data, open(path, "w"))
    return data


def moved(x):
    """Law 27.399: a movable holiday on Tue/Wed moves to the previous Monday, Thu/Fri to the next."""
    wd = x.weekday()
    return x - timedelta(wd) if wd in (1, 2) else x + timedelta(7 - wd) if wd in (3, 4) else x


def ar(y):
    """Returns (set of dates, warning or None)."""
    e = easter(y)
    rule = {e - timedelta(3), e - timedelta(2)}  # Jueves and Viernes Santo
    data = _fetch_ar(y)
    if data:
        hs = {date.fromisoformat(x["fecha"]) for x in data}
        nominal = [date(y, m, d) for m, d in AR_MOVABLE if date(y, m, d) in hs and moved(date(y, m, d)) != date(y, m, d)]
        w = (f"AR {y}: movable holidays listed at nominal dates ({', '.join(map(str, nominal))}); "
             "they may still move by decree") if nominal else None
        return hs | rule, w
    rule |= {date(y, m, d) for m, d in AR_FIXED} | {e - timedelta(48), e - timedelta(47)}
    rule |= {moved(date(y, m, d)) for m, d in AR_MOVABLE}
    return rule, f"AR {y}: holidays not published; fixed, Easter-based and law 27.399 movable dates used, puentes unknown"


def _nth(y, m, wd, n):  # n-th weekday wd (0=Mon) of month; n=-1 for last
    if n > 0:
        d = date(y, m, 1)
        return d + timedelta((wd - d.weekday()) % 7 + 7 * (n - 1))
    d = date(y, m + 1, 1) - timedelta(1) if m < 12 else date(y, 12, 31)
    return d - timedelta((d.weekday() - wd) % 7)


def us(y):
    fixed = [(1, 1), (7, 4), (11, 11), (12, 25)] + ([(6, 19)] if y >= 2022 else [])
    out = set()
    for m, d in fixed:
        h = date(y, m, d)
        if h.weekday() == 6:
            out.add(h + timedelta(1))  # Sunday -> Monday; Saturday is not observed
        elif h.weekday() < 5:
            out.add(h)
    out |= {_nth(y, 1, 0, 3), _nth(y, 2, 0, 3), _nth(y, 5, 0, -1), _nth(y, 9, 0, 1),
            _nth(y, 10, 0, 2), _nth(y, 11, 3, 4)}
    return out, None


def load(calendars, years):
    """Union of the calendars' holidays over the years. Returns (set, warnings)."""
    out, warns = set(), []
    for cal in calendars:
        fn = {"AR": ar, "US": us}.get(cal.upper())
        if fn is None:
            raise ValueError(f"unknown calendar {cal!r}; supported: AR, US")
        for y in years:
            s, w = fn(y)
            out |= s
            if w:
                warns.append(w)
    return out, warns


def load_file(path):
    """A JSON list of 'YYYY-MM-DD' strings or of objects with 'fecha'."""
    return {date.fromisoformat(x if isinstance(x, str) else x["fecha"]) for x in json.load(open(path))}


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2 or args[0] in ("-h", "--help"):
        sys.exit(__doc__)
    hs, warns = load([args[0]], [int(y) for y in args[1:]])
    for d in sorted(hs):
        print(d.isoformat(), d.strftime("%a"))
    for w in warns:
        print("WARN", w, file=sys.stderr)


if __name__ == "__main__":
    main()
