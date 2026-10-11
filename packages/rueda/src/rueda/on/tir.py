"""Yield (TIR), duration and parity of an ON from terms.json and a market price.

Usage: rueda on tir terms.json --price P [--quote-date YYYY-MM-DD] [--settle-days 1]
       [--convention dirty-original] [--compare-tir PCT] [--calls-all]
       [--holidays FILE ...]
P is the quoted price per 100 face value. Conventions: dirty-original (BYMA usual,
default), clean-original, dirty-residual, clean-residual.
Settlement is T+settle-days business days (AR calendar) from the quote date.
TIR is effective annual on ACT/365 time from settlement; parity = dirty / (residual
+ accrued).
If terms.json has call_schedule (fixed-price call windows), it also prints the yield
if the whole issue is called at each window start and each payment date inside a
window, the yield to worst, and whether the price is above the current call value.
Make-whole periods are not modeled.
"""

import argparse
import sys
from datetime import date, timedelta
from typing import TypedDict

from rueda import holidays
from rueda.on.schedule import (
    Flow,
    Terms,
    TermsError,
    add_business_days,
    d,
    load_terms,
    local_today,
    norm_day_count,
    schedule,
    year_frac,
)

CONVENTIONS = ["dirty-original", "clean-original", "dirty-residual", "clean-residual"]
MAX_CALLS_SHOWN = 12  # longer call lists show window starts and the worst only


class Analysis(TypedDict):
    """Yield measures of a price under one quoting convention."""

    convention: str
    dirty: float
    residual: float
    accrued: float
    tir: float | None
    macaulay: float | None
    modified: float | None
    parity: float
    flows: int


Call = TypedDict(
    "Call",
    {
        "date": date,
        "price_pct": float,
        "cash": float,
        "return": float,
        "tir": float | None,
    },
)


def dirty_price(price: float, conv: str, residual: float, accrued: float) -> float:
    """Dirty price per 100 original face value under a quoting convention."""
    base = price * residual / 100 if conv.endswith("residual") else price
    return base + accrued if conv.startswith("clean") else base


def solve(cfs: list[tuple[float, float]], target: float) -> float | None:
    """Effective annual rate y with sum(cf / (1+y)^t) = target, by bisection."""

    def pv(y: float) -> float:
        total: float = sum(c / (1 + y) ** t for t, c in cfs)
        return total

    lo, hi = -0.99, 10.0
    if not pv(hi) <= target <= pv(lo):
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if pv(mid) > target else (lo, mid)
    return (lo + hi) / 2


def accrued_at(t: Terms, f: Flow, when: date) -> float:
    """Interest accrued in flow f's period up to `when`, per 100 original face value."""
    if when <= f.accrual_start:
        return 0.0
    frac = year_frac(
        f.accrual_start,
        min(when, f.accrual_end),
        norm_day_count(t["day_count"]),
        int(t["frequency_months"]),
    )
    return f.balance_before * f.rate / 100 * frac


def analyse(
    t: Terms, flows: list[Flow], price: float, settle: date, conv: str
) -> Analysis:
    """Return the dirty price, TIR, durations and parity of a price at settlement."""
    future = [f for f in flows if f.pay_date > settle]
    if not future:
        msg = f"no payments after settlement {settle}"
        raise TermsError(msg)
    residual = future[0].balance_before
    accrued = accrued_at(t, future[0], settle)
    cfs = [((f.pay_date - settle).days / 365, f.total) for f in future]
    dirty = dirty_price(price, conv, residual, accrued)
    y = solve(cfs, dirty)
    mac: float | None = None
    mod: float | None = None
    if y is not None:
        pvs = [(tt, c / (1 + y) ** tt) for tt, c in cfs]
        mac = sum(tt * v for tt, v in pvs) / sum(v for _, v in pvs)
        mod = mac / (1 + y)
    return {
        "convention": conv,
        "dirty": dirty,
        "residual": residual,
        "accrued": accrued,
        "tir": y,
        "macaulay": mac,
        "modified": mod,
        "parity": dirty / (residual + accrued) * 100,
        "flows": len(future),
    }


def call_windows(t: Terms, maturity: date) -> list[tuple[date, date, float]]:
    """Return the call_schedule as [(from, to exclusive, price % of principal)]."""
    out = []
    for w in t.get("call_schedule") or []:
        try:
            lo = d(w["from"])
            hi = d(w["to"]) if w.get("to") else maturity + timedelta(1)
            out.append((lo, hi, float(w["price_pct"])))
        except (KeyError, TypeError, ValueError) as e:
            msg = (
                f"call_schedule entry {w}: needs from (YYYY-MM-DD), price_pct "
                "and optional to"
            )
            raise TermsError(msg) from e
    return out


def calls(t: Terms, flows: list[Flow], settle: date, dirty: float) -> list[Call]:
    """Full call at each window start and each payment date inside a window.

    Each entry has the cash received, the total return and the TIR.
    """
    maturity = flows[-1].pay_date
    future = [f for f in flows if f.pay_date > settle]
    out: list[Call] = []
    for lo, hi, px in call_windows(t, maturity):
        dates = {
            x
            for x in [lo, *(f.pay_date for f in future)]
            if lo <= x < hi and settle < x < maturity
        }
        for c in sorted(dates):
            cfs = []
            for f in future:
                if f.pay_date < c:
                    cfs.append((f.pay_date, f.total))
                elif f.pay_date == c:
                    # scheduled payment, then the balance at the call price
                    cfs.append((c, f.total + f.balance_after * px / 100))
                    break
                else:
                    # between payment dates: the balance at the call price plus
                    # accrued interest
                    cfs.append((c, f.balance_before * px / 100 + accrued_at(t, f, c)))
                    break
            cash = sum(v for _, v in cfs)
            y = solve([((x - settle).days / 365, v) for x, v in cfs], dirty)
            out.append(
                {
                    "date": c,
                    "price_pct": px,
                    "cash": cash,
                    "return": cash / dirty - 1,
                    "tir": y,
                }
            )
    return out


def current_call_value(
    t: Terms, flows: list[Flow], settle: date, residual: float, accrued: float
) -> tuple[float, float] | None:
    """Return (price %, value per 100 original) if callable at settlement, else None."""
    for lo, hi, px in call_windows(t, flows[-1].pay_date):
        if lo <= settle < hi:
            return px, residual * px / 100 + accrued
    return None


def pct(x: float | None, nd: int = 2) -> str:
    """Format a ratio as a percentage, or n/a."""
    return "n/a" if x is None else f"{x * 100:.{nd}f}%"


def num(x: float | None, nd: int = 2) -> str:
    """Format a number, or n/a."""
    return "n/a" if x is None else f"{x:.{nd}f}"


def _print_calls(
    cl: list[Call], m: Analysis, convention: str, *, show_all: bool
) -> None:
    out = sys.stdout.write
    rated = [(tir, c) for c in cl if (tir := c["tir"]) is not None]
    worst = min(rated, key=lambda r: r[0], default=None)
    shown, note = cl, ""
    if not show_all and len(cl) > MAX_CALLS_SHOWN:
        firsts = {c["price_pct"]: c for c in reversed(cl)}.values()
        picked = [*firsts, *([worst[1]] if worst else [])]
        shown = sorted({id(c): c for c in picked}.values(), key=lambda c: c["date"])
        note = (
            f"; {len(cl)} call dates, showing window starts and the worst; "
            "--calls-all lists all"
        )
    out(
        "\nCalls (whole issue; cash per 100 original; "
        f"price assumed {convention}{note}):\n"
    )
    out("| Call date | Call price | Cash if called | Total return | TIR |\n")
    out("|---|---|---|---|---|\n")
    for c in shown:
        out(
            f"| {c['date']} | {c['price_pct']:g}% | {c['cash']:.4f} | "
            f"{pct(c['return'])} | {pct(c['tir'])} |\n"
        )
    tirs = [x for x in (worst[0] if worst else None, m["tir"]) if x is not None]
    ytw = min(tirs, default=None)
    where = f"call on {worst[1]['date']}" if worst and worst[0] == ytw else "maturity"
    out(f"Yield to worst {pct(ytw)} ({where}); TIR to maturity {pct(m['tir'])}.\n")


def _print_min_lot(t: Terms, m: Analysis) -> None:
    mn = float(t["min_denomination"])
    inc = f" and multiples of {t['increment']}" if t.get("increment") else ""
    sys.stdout.write(
        f"\nMinimum lot {mn:g} face value{inc}: "
        f"residual value {mn * m['residual'] / 100:.2f}, "
        f"approximate cost {m['dirty'] * mn / 100:.2f} "
        "(dirty price per 100 original x minimum / 100).\n"
    )


def main(argv: list[str] | None = None) -> None:
    """Run `rueda on tir`."""
    p = argparse.ArgumentParser(
        prog="rueda on tir",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("terms")
    p.add_argument("--price", type=float, required=True)
    p.add_argument("--quote-date", type=d, default=local_today())
    p.add_argument("--settle-days", type=int, default=1)
    p.add_argument("--convention", choices=CONVENTIONS, default="dirty-original")
    p.add_argument(
        "--compare-tir", type=float, help="TIR in percent from a public source"
    )
    p.add_argument(
        "--calls-all",
        action="store_true",
        help="list every call date, not only window starts and the worst",
    )
    p.add_argument(
        "--holidays", action="append", default=[], help="extra JSON list of dates"
    )
    a = p.parse_args(argv)
    try:
        t = load_terms(a.terms)
        flows, _, warns = schedule(t, a.holidays)
        ar, w2 = holidays.load(["AR"], [a.quote_date.year, a.quote_date.year + 1])
        settle = add_business_days(a.quote_date, a.settle_days, ar)
        res = {c: analyse(t, flows, a.price, settle, c) for c in CONVENTIONS}
        m = res[a.convention]
        cl = calls(t, flows, settle, m["dirty"])
    except TermsError as e:
        sys.exit(f"ERROR {e}")
    out = sys.stdout.write
    est = (
        " Flows are estimates (floating rate)." if t["rate_type"] == "floating" else ""
    )
    out(
        f"Settlement {settle} (T+{a.settle_days} from quote date {a.quote_date}). "
        f"{m['flows']} future payments.{est}\n"
    )
    out(
        f"Price {a.price} per 100, assumed {a.convention}. "
        f"Residual {m['residual']:.4f}, accrued {m['accrued']:.4f}, "
        f"technical value {m['residual'] + m['accrued']:.4f} (per 100 original).\n"
    )
    out(
        f"TIR {pct(m['tir'])} effective annual. "
        f"Macaulay duration {num(m['macaulay'])} years, "
        f"modified {num(m['modified'])}. Parity {m['parity']:.2f}%.\n"
    )
    if a.compare_tir is not None and m["tir"] is not None:
        out(
            f"Public TIR {a.compare_tir:.2f}% vs computed {pct(m['tir'])}: "
            f"{(m['tir'] * 100 - a.compare_tir) * 100:+.0f} bp.\n"
        )
    out("\n| Price convention | Dirty per 100 original | TIR | Modified duration |")
    out(" Parity |\n|---|---|---|---|---|\n")
    for c, r in res.items():
        mark = " (assumed)" if c == a.convention else ""
        out(
            f"| {c}{mark} | {r['dirty']:.4f} | {pct(r['tir'])} | "
            f"{num(r['modified'])} | {r['parity']:.2f}% |\n"
        )
    if cl:
        _print_calls(cl, m, a.convention, show_all=a.calls_all)
        cur = current_call_value(t, flows, settle, m["residual"], m["accrued"])
        if cur and m["dirty"] > cur[1]:
            out(
                f"Callable now at {cur[0]:g}%: call value {cur[1]:.4f} per 100 "
                f"original is below the dirty price {m['dirty']:.4f}, "
                "so a call would return less than the price paid.\n"
            )
    if t.get("min_denomination"):
        _print_min_lot(t, m)
    for w in warns + w2:
        out(f"WARN {w}\n")


if __name__ == "__main__":
    main()
