"""Payment schedule of an ON per 100 original face value, from a terms.json file.

Usage: rueda on schedule terms.json [--today YYYY-MM-DD] [--all] [--csv FILE]
       [--holidays FILE ...]
Prints a markdown table of future payments (past ones too with --all), marks the
next one, and checks last_payment_notice against the computed amounts.
terms.json format: `rueda on terms-example` prints an example. Every field is
{"value": ..., "source": "document and date"}. A missing required field aborts
the run: fill it from the documents or report it as not stated.
"""

import argparse
import calendar
import csv
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from typing import Any

from rueda import holidays

REQUIRED = [
    "issue_date",
    "maturity",
    "rate_type",
    "day_count",
    "frequency_months",
    "amortization",
    "business_day_rule",
    "business_day_calendars",
]
DAY_COUNTS = {"30/360", "30E/360", "ACT/365", "ACT/360", "ACT/ACT"}
RULES = {"following", "modified_following", "preceding", "none"}
NOTICE_TOL = 0.001  # per 100 face value
AMORT_TOL = 0.01  # percentage points: published tables round each installment
EXACT_TOL = 1e-9  # an amortization table that adds up to 100 exactly
MONTH_DAYS = 30  # 30/360 conventions

Terms = dict[str, Any]  # terms.json flattened to {field: value}


class TermsError(Exception):
    """A terms.json that is incomplete or inconsistent."""


@dataclass
class Flow:
    """One payment, per 100 original face value."""

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
    def total(self) -> float:
        """Interest plus amortization."""
        return self.interest + self.amortization

    @property
    def balance_after(self) -> float:
        """Outstanding principal once this flow is paid."""
        return self.balance_before - self.amortization


def d(s: str) -> date:
    """Parse a YYYY-MM-DD date."""
    return date.fromisoformat(s)


def local_today() -> date:
    """Return today's date in the local timezone."""
    return datetime.now().astimezone().date()


def norm_day_count(s: str) -> str:
    """Return the canonical name of a day-count convention."""
    k = s.upper().replace(" ", "").replace("ACTUAL", "ACT").replace("REAL", "ACT")
    k = {
        "ACT/365F": "ACT/365",
        "ACT/365FIXED": "ACT/365",
        "ACT/ACTICMA": "ACT/ACT",
        "30/360US": "30/360",
        "30U/360": "30/360",
    }.get(k, k)
    if k not in DAY_COUNTS:
        msg = f"day_count {s!r} not supported; use one of {sorted(DAY_COUNTS)}"
        raise TermsError(msg)
    return k


def add_months(x: date, n: int, day: int) -> date:
    """Return x plus n months, on the given day capped to the month's length."""
    m = x.month - 1 + n
    y, m = x.year + m // 12, m % 12 + 1
    return date(y, m, min(day, calendar.monthrange(y, m)[1]))


def year_frac(a: date, b: date, dc: str, freq_months: int | None = None) -> float:
    """Return the fraction of a year from a to b under day count dc."""
    if dc == "ACT/365":
        return (b - a).days / 365
    if dc == "ACT/360":
        return (b - a).days / 360
    if dc in ("30/360", "30E/360"):
        d1, d2 = min(a.day, MONTH_DAYS), b.day
        if dc == "30E/360" or d1 == MONTH_DAYS:
            d2 = min(d2, MONTH_DAYS)
        return (360 * (b.year - a.year) + 30 * (b.month - a.month) + d2 - d1) / 360
    # ACT/ACT ICMA: days over (frequency x days of the reference period ending at b)
    if freq_months is None:
        msg = "ACT/ACT needs the coupon frequency in months"
        raise ValueError(msg)
    per_year = 12 / freq_months
    frac, end = 0.0, b
    while True:
        ref = add_months(end, -freq_months, end.day)
        if a >= ref:
            return frac + (end - a).days / ((end - ref).days * per_year)
        frac, end = frac + 1 / per_year, ref


def is_business(x: date, hols: set[date]) -> bool:
    """Return whether x is a weekday that is not a holiday."""
    return x.weekday() < holidays.SATURDAY and x not in hols


def adjust(x: date, rule: str, hols: set[date]) -> date:
    """Return x moved to a business day under the business-day rule."""
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


def add_business_days(x: date, n: int, hols: set[date]) -> date:
    """Return the n-th business day after x."""
    while n:
        x += timedelta(1)
        if is_business(x, hols):
            n -= 1
    return x


def load_terms(path: str | Path) -> Terms:
    """Return the terms as {field: value}; a missing required field raises."""
    t = json.loads(Path(path).read_text())

    def ok(k: str) -> bool:
        v = t.get(k)
        return (
            isinstance(v, dict)
            and v.get("value") not in (None, "", [])
            and bool(v.get("source"))
        )

    rt = (t.get("rate_type") or {}).get("value")
    need = (
        ["rate"]
        if rt == "fixed"
        else ["base_rate", "margin"]
        if rt == "floating"
        else []
    )
    missing = [k for k in REQUIRED + need if not ok(k)]
    if rt not in ("fixed", "floating"):
        missing.append("rate_type (fixed|floating)")
    if not ok("payment_dates") and not ok("first_payment_date"):
        missing.append("payment_dates or first_payment_date")
    if missing:
        raise TermsError(
            "missing in terms.json (value and source): " + ", ".join(missing)
        )
    return {
        k: v["value"] if isinstance(v, dict) and "value" in v else v
        for k, v in t.items()
    }


def payment_dates(t: Terms) -> list[date]:
    """Return the scheduled (unadjusted) payment dates; the last one is maturity."""
    mat, freq = d(t["maturity"]), int(t["frequency_months"])
    if t.get("payment_dates"):
        out = sorted(d(x) for x in t["payment_dates"])
    else:
        first = d(t["first_payment_date"])
        out, k = [], 0
        while (x := add_months(first, k * freq, first.day)) < mat:
            out.append(x)
            k += 1
        out.append(mat)
    if out[-1] != mat:
        msg = f"last payment date {out[-1]} differs from maturity {mat}"
        raise TermsError(msg)
    return out


def build(t: Terms, hols: set[date]) -> list[Flow]:
    """Every flow from the first coupon to maturity, per 100 original face value."""
    dc = norm_day_count(t["day_count"])
    rule = t["business_day_rule"]
    if rule not in RULES:
        msg = f"business_day_rule {rule!r}; use one of {sorted(RULES)}"
        raise TermsError(msg)
    dates = payment_dates(t)
    amort = {d(a["date"]): float(a["pct"]) for a in t["amortization"]}
    if abs(sum(amort.values()) - 100) > AMORT_TOL:
        msg = f"amortization percentages add up to {sum(amort.values()):.6f}, not 100"
        raise TermsError(msg)
    if not set(amort) <= set(dates):
        stray = sorted(set(amort) - set(dates))
        msg = f"amortization dates not among payment dates: {stray}"
        raise TermsError(msg)
    floating = t["rate_type"] == "floating"
    rate = (
        float(t["base_rate"]["rate"]) + float(t["margin"])
        if floating
        else float(t["rate"])
    )
    to_adjusted = bool(t.get("accrue_to_adjusted_date"))
    freq = int(t["frequency_months"])
    flows: list[Flow] = []
    start, bal = d(t.get("interest_start_date") or t["issue_date"]), 100.0
    for i, s in enumerate(dates, 1):
        pay = adjust(s, rule, hols)
        end = pay if to_adjusted else s
        interest = bal * rate / 100 * year_frac(start, end, dc, freq)
        # the last installment repays the rounding remainder
        am = bal if i == len(dates) else amort.get(s, 0.0)
        f = Flow(i, start, end, s, pay, rate, bal, interest, am, floating)
        flows.append(f)
        bal, start = f.balance_after, end
    return flows


def calendar_for(
    t: Terms, flows: list[Flow], extra_files: Sequence[str] = ()
) -> tuple[set[date], list[str]]:
    """Return (holidays, warnings) for the terms' calendars over the flows' years."""
    years = range(d(t["issue_date"]).year, flows[-1].pay_date.year + 2) if flows else []
    hols, warns = holidays.load(t["business_day_calendars"], years)
    for p in extra_files:
        hols |= holidays.load_file(p)
    return hols, warns


def schedule(
    t: Terms, extra_files: Sequence[str] = ()
) -> tuple[list[Flow], set[date], list[str]]:
    """Build the flows with the terms' calendars.

    Returns (flows, holidays, warnings).
    """
    draft = build(t, set())  # unadjusted pass, only to know the years to load
    hols, warns = calendar_for(t, draft, extra_files)
    return build(t, hols), hols, warns


def check_notice(t: Terms, flows: list[Flow]) -> str:
    """Compare last_payment_notice with the flow computed for its date."""
    n = t.get("last_payment_notice")
    if not n:
        return "No aviso de pago in terms.json: computed amounts not checked."
    when = d(n["date"])
    f = next((f for f in flows if when in (f.scheduled, f.pay_date)), None)
    if f is None:
        return (
            f"MISMATCH: aviso de pago date {when} is not a computed payment date. "
            "Check dates and business-day rule."
        )
    interest = f.interest
    if f.estimate:
        if "rate" not in n:
            return (
                "Floating rate: add the rate applied in the aviso de pago "
                "(last_payment_notice.rate) to check it."
            )
        frac = year_frac(
            f.accrual_start,
            f.accrual_end,
            norm_day_count(t["day_count"]),
            int(t["frequency_months"]),
        )
        interest = f.balance_before * float(n["rate"]) / 100 * frac
    di = interest - float(n.get("interest_per_100", 0))
    da = f.amortization - float(n.get("amortization_per_100", 0))
    status = (
        "OK"
        if abs(di) <= NOTICE_TOL and abs(da) <= NOTICE_TOL
        else "MISMATCH: check day count, dates and business-day rule before delivering"
    )
    return (
        f"Aviso de pago {when}: interest {n.get('interest_per_100')} vs computed "
        f"{interest:.6f} (diff {di:+.6f}); amortization "
        f"{n.get('amortization_per_100', 0)} vs {f.amortization:.6f}. {status}"
    )


def table(t: Terms, flows: list[Flow], today: date, *, show_all: bool = False) -> str:
    """Return the markdown table of the payments from today on, or of all of them."""
    rows = flows if show_all else [f for f in flows if f.pay_date >= today]
    nxt = next((f for f in flows if f.pay_date >= today), None)
    est = " (est.)" if t["rate_type"] == "floating" else ""
    out = [
        "| # | Payment date | Interest | Amortization | Total | Balance after | |",
        "|---|---|---|---|---|---|---|",
    ]
    out.extend(
        f"| {f.n} | {f.pay_date} | {f.interest:.4f}{est} | {f.amortization:.4f} | "
        f"{f.total:.4f}{est} | {f.balance_after:.4f} | {'next' if f is nxt else ''} |"
        for f in rows
    )
    return "\n".join(out)


def describe(t: Terms, flows: list[Flow]) -> str:
    """Return the lines above the table: rate, day count and date adjustments."""
    if t["rate_type"] == "floating":
        b = t["base_rate"]
        rate = (
            f"floating: {b['name']} {b['rate']}% (as of {b['date']}) + margin "
            f"{t['margin']}% = {flows[0].rate:.4f}%; amounts are estimates"
        )
    else:
        rate = f"{float(t['rate'])}% fixed"
    head = (
        f"Per 100 original face value. Rate {rate}. "
        f"Day count {norm_day_count(t['day_count'])}. "
        f"Business days: {'+'.join(t['business_day_calendars'])}, "
        f"rule {t['business_day_rule']}."
    )
    lines = [head]
    total = sum(float(a["pct"]) for a in t["amortization"])
    if abs(total - 100) > EXACT_TOL:
        lines.append(
            f"- Amortization table adds up to {total:.4f}% (rounded installments): "
            f"last installment set to the remaining {flows[-1].amortization:.4f}."
        )
    accrual = (
        ""
        if t.get("accrue_to_adjusted_date")
        else ", interest accrues to the scheduled date"
    )
    lines.extend(
        f"- {f.scheduled} ({f.scheduled:%a}) is not a business day: "
        f"paid {f.pay_date}{accrual}."
        for f in flows
        if f.pay_date != f.scheduled
    )
    return "\n".join(lines)


def example(_argv: list[str] | None = None) -> None:
    """Print the bundled terms.example.json (PLC5)."""
    sys.stdout.write(
        files(__package__).joinpath("terms.example.json").read_text(encoding="utf8")
    )


def main(argv: list[str] | None = None) -> None:
    """Run `rueda on schedule`."""
    p = argparse.ArgumentParser(
        prog="rueda on schedule",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("terms")
    p.add_argument("--today", type=d, default=local_today())
    p.add_argument("--all", action="store_true", help="include past payments")
    p.add_argument("--csv", help="also write every flow to this CSV file")
    p.add_argument(
        "--holidays", action="append", default=[], help="extra JSON list of dates"
    )
    a = p.parse_args(argv)
    try:
        t = load_terms(a.terms)
        flows, _, warns = schedule(t, a.holidays)
    except TermsError as e:
        sys.exit(f"ERROR {e}")
    sys.stdout.write(f"{describe(t, flows)}\n\n")
    sys.stdout.write(f"{table(t, flows, a.today, show_all=a.all)}\n\n")
    sys.stdout.write(f"{check_notice(t, flows)}\n")
    for w in warns:
        sys.stdout.write(f"WARN {w}\n")
    if a.csv:
        with Path(a.csv).open("w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                [
                    "n",
                    "accrual_start",
                    "accrual_end",
                    "scheduled",
                    "pay_date",
                    "rate",
                    "balance_before",
                    "interest",
                    "amortization",
                    "total",
                    "balance_after",
                    "estimate",
                ]
            )
            for f in flows:
                writer.writerow(
                    [
                        f.n,
                        f.accrual_start,
                        f.accrual_end,
                        f.scheduled,
                        f.pay_date,
                        f.rate,
                        round(f.balance_before, 6),
                        round(f.interest, 6),
                        round(f.amortization, 6),
                        round(f.total, 6),
                        round(f.balance_after, 6),
                        f.estimate,
                    ]
                )


if __name__ == "__main__":
    main()
