"""Payment schedule of an ON per 100 original face value, from a terms.json file.
Usage: rueda on schedule terms.json [--today YYYY-MM-DD] [--all] [--csv FILE] [--holidays FILE ...]
Prints a markdown table of future payments (past ones too with --all), marks the
next one, and checks last_payment_notice against the computed amounts.
terms.json format: `rueda on terms-example` prints an example. Every field is
{"value": ..., "source": "document and date"}. A missing required field aborts
the run: fill it from the documents or report it as not stated."""
import argparse, calendar, csv, json, sys
from dataclasses import dataclass
from datetime import date, timedelta
from importlib.resources import files

from rueda import holidays

REQUIRED = ["issue_date", "maturity", "rate_type", "day_count", "frequency_months",
            "amortization", "business_day_rule", "business_day_calendars"]
DAY_COUNTS = {"30/360", "30E/360", "ACT/365", "ACT/360", "ACT/ACT"}
RULES = {"following", "modified_following", "preceding", "none"}
NOTICE_TOL = 0.001  # per 100 face value
AMORT_TOL = 0.01  # percentage points: published tables round each installment


class TermsError(Exception):
    pass


@dataclass
class Flow:
    n: int
    accrual_start: date
    accrual_end: date
    scheduled: date  # unadjusted payment date
    pay_date: date
    rate: float  # percent per year
    balance_before: float
    interest: float
    amortization: float
    estimate: bool

    @property
    def total(self):
        return self.interest + self.amortization

    @property
    def balance_after(self):
        return self.balance_before - self.amortization


def d(s):
    return date.fromisoformat(s)


def norm_day_count(s):
    k = s.upper().replace(" ", "").replace("ACTUAL", "ACT").replace("REAL", "ACT")
    k = {"ACT/365F": "ACT/365", "ACT/365FIXED": "ACT/365", "ACT/ACTICMA": "ACT/ACT",
         "30/360US": "30/360", "30U/360": "30/360"}.get(k, k)
    if k not in DAY_COUNTS:
        raise TermsError(f"day_count {s!r} not supported; use one of {sorted(DAY_COUNTS)}")
    return k


def add_months(x, n, day):
    m = x.month - 1 + n
    y, m = x.year + m // 12, m % 12 + 1
    return date(y, m, min(day, calendar.monthrange(y, m)[1]))


def year_frac(a, b, dc, freq_months=None):
    if dc == "ACT/365":
        return (b - a).days / 365
    if dc == "ACT/360":
        return (b - a).days / 360
    if dc in ("30/360", "30E/360"):
        d1, d2 = min(a.day, 30), b.day
        if dc == "30E/360" or d1 == 30:
            d2 = min(d2, 30)
        return (360 * (b.year - a.year) + 30 * (b.month - a.month) + d2 - d1) / 360
    # ACT/ACT ICMA: days over (frequency x days of the reference period ending at b)
    per_year = 12 / freq_months
    frac, end = 0.0, b
    while True:
        ref = add_months(end, -freq_months, end.day)
        if a >= ref:
            return frac + (end - a).days / ((end - ref).days * per_year)
        frac, end = frac + 1 / per_year, ref


def is_business(x, hols):
    return x.weekday() < 5 and x not in hols


def adjust(x, rule, hols):
    if rule == "none" or is_business(x, hols):
        return x
    step = -1 if rule == "preceding" else 1
    y = x
    while not is_business(y, hols):
        y += timedelta(step)
    if rule == "modified_following" and y.month != x.month:
        y = x
        while not is_business(y, hols):
            y -= timedelta(1)
    return y


def add_business_days(x, n, hols):
    while n:
        x += timedelta(1)
        if is_business(x, hols):
            n -= 1
    return x


def load_terms(path):
    t = json.load(open(path))
    ok = lambda k: isinstance(t.get(k), dict) and t[k].get("value") not in (None, "", []) and t[k].get("source")
    rt = (t.get("rate_type") or {}).get("value")
    need = ["rate"] if rt == "fixed" else ["base_rate", "margin"] if rt == "floating" else []
    missing = [k for k in REQUIRED + need if not ok(k)]
    if rt not in ("fixed", "floating"):
        missing.append("rate_type (fixed|floating)")
    if not ok("payment_dates") and not ok("first_payment_date"):
        missing.append("payment_dates or first_payment_date")
    if missing:
        raise TermsError("missing in terms.json (value and source): " + ", ".join(missing))
    return {k: v["value"] if isinstance(v, dict) and "value" in v else v for k, v in t.items()}


def payment_dates(t):
    mat, freq = d(t["maturity"]), int(t["frequency_months"])
    if t.get("payment_dates"):
        out = sorted(d(x) for x in t["payment_dates"])
    else:
        first = d(t["first_payment_date"])
        out, k = [], 0
        while (x := add_months(first, k * freq, first.day)) < mat:
            out.append(x); k += 1
        out.append(mat)
    if out[-1] != mat:
        raise TermsError(f"last payment date {out[-1]} differs from maturity {mat}")
    return out


def build(t, hols):
    """Every flow from the first coupon to maturity, per 100 original face value."""
    dc = norm_day_count(t["day_count"])
    rule = t["business_day_rule"]
    if rule not in RULES:
        raise TermsError(f"business_day_rule {rule!r}; use one of {sorted(RULES)}")
    dates = payment_dates(t)
    amort = {d(a["date"]): float(a["pct"]) for a in t["amortization"]}
    if abs(sum(amort.values()) - 100) > AMORT_TOL:
        raise TermsError(f"amortization percentages add up to {sum(amort.values()):.6f}, not 100")
    if not set(amort) <= set(dates):
        raise TermsError(f"amortization dates not among payment dates: {sorted(set(amort) - set(dates))}")
    floating = t["rate_type"] == "floating"
    rate = float(t["base_rate"]["rate"]) + float(t["margin"]) if floating else float(t["rate"])
    to_adjusted = bool(t.get("accrue_to_adjusted_date"))
    flows, start, bal = [], d(t.get("interest_start_date") or t["issue_date"]), 100.0
    for i, s in enumerate(dates, 1):
        pay = adjust(s, rule, hols)
        end = pay if to_adjusted else s
        interest = bal * rate / 100 * year_frac(start, end, dc, int(t["frequency_months"]))
        am = bal if i == len(dates) else amort.get(s, 0.0)  # last installment repays the rounding remainder
        f = Flow(i, start, end, s, pay, rate, bal, interest, am, floating)
        flows.append(f)
        bal, start = f.balance_after, end
    return flows


def calendar_for(t, flows, extra_files=()):
    years = range(d(t["issue_date"]).year, flows[-1].pay_date.year + 2) if flows else []
    hols, warns = holidays.load(t["business_day_calendars"], years)
    for p in extra_files:
        hols |= holidays.load_file(p)
    return hols, warns


def schedule(t, extra_files=()):
    """Builds the flows with the terms' calendars. Returns (flows, holidays, warnings)."""
    draft = build(t, set())  # unadjusted pass, only to know the years to load
    hols, warns = calendar_for(t, draft, extra_files)
    return build(t, hols), hols, warns


def check_notice(t, flows):
    n = t.get("last_payment_notice")
    if not n:
        return "No aviso de pago in terms.json: computed amounts not checked."
    when = d(n["date"])
    f = next((f for f in flows if when in (f.scheduled, f.pay_date)), None)
    if f is None:
        return f"MISMATCH: aviso de pago date {when} is not a computed payment date. Check dates and business-day rule."
    interest = f.interest
    if f.estimate:
        if "rate" not in n:
            return "Floating rate: add the rate applied in the aviso de pago (last_payment_notice.rate) to check it."
        interest = f.balance_before * float(n["rate"]) / 100 * year_frac(
            f.accrual_start, f.accrual_end, norm_day_count(t["day_count"]), int(t["frequency_months"]))
    di = interest - float(n.get("interest_per_100", 0))
    da = f.amortization - float(n.get("amortization_per_100", 0))
    status = "OK" if abs(di) <= NOTICE_TOL and abs(da) <= NOTICE_TOL else \
        "MISMATCH: check day count, dates and business-day rule before delivering"
    return (f"Aviso de pago {when}: interest {n.get('interest_per_100')} vs computed {interest:.6f} "
            f"(diff {di:+.6f}); amortization {n.get('amortization_per_100', 0)} vs {f.amortization:.6f}. {status}")


def table(t, flows, today, show_all=False):
    rows = flows if show_all else [f for f in flows if f.pay_date >= today]
    nxt = next((f for f in flows if f.pay_date >= today), None)
    est = " (est.)" if t["rate_type"] == "floating" else ""
    out = ["| # | Payment date | Interest | Amortization | Total | Balance after | |",
           "|---|---|---|---|---|---|---|"]
    for f in rows:
        out.append(f"| {f.n} | {f.pay_date} | {f.interest:.4f}{est} | {f.amortization:.4f} | "
                   f"{f.total:.4f}{est} | {f.balance_after:.4f} | {'next' if f is nxt else ''} |")
    return "\n".join(out)


def describe(t, flows):
    if t["rate_type"] == "floating":
        b = t["base_rate"]
        rate = (f"floating: {b['name']} {b['rate']}% (as of {b['date']}) + margin {t['margin']}% "
                f"= {flows[0].rate:.4f}%; amounts are estimates")
    else:
        rate = f"{float(t['rate'])}% fixed"
    lines = [f"Per 100 original face value. Rate {rate}. Day count {norm_day_count(t['day_count'])}. "
             f"Business days: {'+'.join(t['business_day_calendars'])}, rule {t['business_day_rule']}."]
    total = sum(float(a["pct"]) for a in t["amortization"])
    if abs(total - 100) > 1e-9:
        lines.append(f"- Amortization table adds up to {total:.4f}% (rounded installments): "
                     f"last installment set to the remaining {flows[-1].amortization:.4f}.")
    for f in flows:
        if f.pay_date != f.scheduled:
            lines.append(f"- {f.scheduled} ({f.scheduled:%a}) is not a business day: paid {f.pay_date}"
                         + ("" if t.get("accrue_to_adjusted_date") else ", interest accrues to the scheduled date") + ".")
    return "\n".join(lines)


def example(argv=None):
    """Prints the bundled terms.example.json (PLC5)."""
    sys.stdout.write(files(__package__).joinpath("terms.example.json").read_text(encoding="utf8"))


def main(argv=None):
    p = argparse.ArgumentParser(prog="rueda on schedule", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("terms")
    p.add_argument("--today", type=d, default=date.today())
    p.add_argument("--all", action="store_true", help="include past payments")
    p.add_argument("--csv", help="also write every flow to this CSV file")
    p.add_argument("--holidays", action="append", default=[], help="extra JSON list of dates")
    a = p.parse_args(argv)
    try:
        t = load_terms(a.terms)
        flows, _, warns = schedule(t, a.holidays)
    except TermsError as e:
        sys.exit(f"ERROR {e}")
    print(describe(t, flows))
    print()
    print(table(t, flows, a.today, a.all))
    print()
    print(check_notice(t, flows))
    for w in warns:
        print("WARN", w)
    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["n", "accrual_start", "accrual_end", "scheduled", "pay_date", "rate",
                        "balance_before", "interest", "amortization", "total", "balance_after", "estimate"])
            for f in flows:
                w.writerow([f.n, f.accrual_start, f.accrual_end, f.scheduled, f.pay_date, f.rate,
                            round(f.balance_before, 6), round(f.interest, 6), round(f.amortization, 6),
                            round(f.total, 6), round(f.balance_after, 6), f.estimate])


if __name__ == "__main__":
    main()
