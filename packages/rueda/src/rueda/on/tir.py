"""Yield (TIR), duration and parity of an ON from terms.json and a market price.
Usage: rueda on tir terms.json --price P [--quote-date YYYY-MM-DD] [--settle-days 1]
       [--convention dirty-original] [--compare-tir PCT] [--calls-all] [--holidays FILE ...]
P is the quoted price per 100 face value. Conventions: dirty-original (BYMA usual,
default), clean-original, dirty-residual, clean-residual.
Settlement is T+settle-days business days (AR calendar) from the quote date.
TIR is effective annual on ACT/365 time from settlement; parity = dirty / (residual + accrued).
If terms.json has call_schedule (fixed-price call windows), it also prints the yield if the
whole issue is called at each window start and each payment date inside a window, the yield
to worst, and whether the price is above the current call value. Make-whole periods are not modeled."""
import argparse, sys
from datetime import date, timedelta

from rueda import holidays
from rueda.on.schedule import TermsError, add_business_days, d, load_terms, norm_day_count, schedule, year_frac

CONVENTIONS = ["dirty-original", "clean-original", "dirty-residual", "clean-residual"]


def dirty_price(price, conv, residual, accrued):
    """Dirty price per 100 original face value under a quoting convention."""
    base = price * residual / 100 if conv.endswith("residual") else price
    return base + accrued if conv.startswith("clean") else base


def solve(cfs, target):
    """Effective annual rate y with sum(cf / (1+y)^t) = target, by bisection."""
    pv = lambda y: sum(c / (1 + y) ** t for t, c in cfs)
    lo, hi = -0.99, 10.0
    if not pv(hi) <= target <= pv(lo):
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if pv(mid) > target else (lo, mid)
    return (lo + hi) / 2


def accrued_at(t, f, when):
    """Interest accrued in flow f's period up to `when`, per 100 original face value."""
    if when <= f.accrual_start:
        return 0.0
    return f.balance_before * f.rate / 100 * year_frac(
        f.accrual_start, min(when, f.accrual_end), norm_day_count(t["day_count"]), int(t["frequency_months"]))


def analyse(t, flows, price, settle, conv):
    future = [f for f in flows if f.pay_date > settle]
    if not future:
        raise TermsError(f"no payments after settlement {settle}")
    residual = future[0].balance_before
    accrued = accrued_at(t, future[0], settle)
    cfs = [((f.pay_date - settle).days / 365, f.total) for f in future]
    dirty = dirty_price(price, conv, residual, accrued)
    y = solve(cfs, dirty)
    mac = mod = None
    if y is not None:
        pvs = [(tt, c / (1 + y) ** tt) for tt, c in cfs]
        mac = sum(tt * v for tt, v in pvs) / sum(v for _, v in pvs)
        mod = mac / (1 + y)
    return {"convention": conv, "dirty": dirty, "residual": residual, "accrued": accrued,
            "tir": y, "macaulay": mac, "modified": mod, "parity": dirty / (residual + accrued) * 100,
            "flows": len(future)}


def call_windows(t, maturity):
    """[(from, to exclusive, price % of outstanding principal)] from the terms' call_schedule."""
    out = []
    for w in t.get("call_schedule") or []:
        try:
            out.append((d(w["from"]), d(w["to"]) if w.get("to") else maturity + timedelta(1), float(w["price_pct"])))
        except (KeyError, TypeError, ValueError) as e:
            raise TermsError(f"call_schedule entry {w}: needs from (YYYY-MM-DD), price_pct and optional to") from e
    return out


def calls(t, flows, settle, dirty):
    """Full call at each window start and each payment date inside a window: cash, total return, TIR."""
    maturity = flows[-1].pay_date
    future = [f for f in flows if f.pay_date > settle]
    out = []
    for lo, hi, px in call_windows(t, maturity):
        for c in sorted({x for x in [lo] + [f.pay_date for f in future] if lo <= x < hi and settle < x < maturity}):
            cfs = []
            for f in future:
                if f.pay_date < c:
                    cfs.append((f.pay_date, f.total))
                elif f.pay_date == c:  # scheduled payment, then the balance at the call price
                    cfs.append((c, f.total + f.balance_after * px / 100)); break
                else:  # between payment dates: balance at the call price plus accrued interest
                    cfs.append((c, f.balance_before * px / 100 + accrued_at(t, f, c))); break
            cash = sum(v for _, v in cfs)
            y = solve([((x - settle).days / 365, v) for x, v in cfs], dirty)
            out.append({"date": c, "price_pct": px, "cash": cash, "return": cash / dirty - 1, "tir": y})
    return out


def current_call_value(t, flows, settle, residual, accrued):
    """(price %, value per 100 original) if the issue is callable at settlement, else None."""
    for lo, hi, px in call_windows(t, flows[-1].pay_date):
        if lo <= settle < hi:
            return px, residual * px / 100 + accrued
    return None


def pct(x, nd=2):
    return "n/a" if x is None else f"{x * 100:.{nd}f}%"


def num(x, nd=2):
    return "n/a" if x is None else f"{x:.{nd}f}"


def main(argv=None):
    p = argparse.ArgumentParser(prog="rueda on tir", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("terms")
    p.add_argument("--price", type=float, required=True)
    p.add_argument("--quote-date", type=d, default=date.today())
    p.add_argument("--settle-days", type=int, default=1)
    p.add_argument("--convention", choices=CONVENTIONS, default="dirty-original")
    p.add_argument("--compare-tir", type=float, help="TIR in percent from a public source")
    p.add_argument("--calls-all", action="store_true", help="list every call date, not only window starts and the worst")
    p.add_argument("--holidays", action="append", default=[], help="extra JSON list of dates")
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
    est = " Flows are estimates (floating rate)." if t["rate_type"] == "floating" else ""
    print(f"Settlement {settle} (T+{a.settle_days} from quote date {a.quote_date}). "
          f"{m['flows']} future payments.{est}")
    print(f"Price {a.price} per 100, assumed {a.convention}. Residual {m['residual']:.4f}, "
          f"accrued {m['accrued']:.4f}, technical value {m['residual'] + m['accrued']:.4f} (per 100 original).")
    print(f"TIR {pct(m['tir'])} effective annual. Macaulay duration {num(m['macaulay'])} years, "
          f"modified {num(m['modified'])}. Parity {m['parity']:.2f}%.")
    if a.compare_tir is not None and m["tir"] is not None:
        print(f"Public TIR {a.compare_tir:.2f}% vs computed {pct(m['tir'])}: "
              f"{(m['tir'] * 100 - a.compare_tir) * 100:+.0f} bp.")
    print()
    print("| Price convention | Dirty per 100 original | TIR | Modified duration | Parity |")
    print("|---|---|---|---|---|")
    for c, r in res.items():
        mark = " (assumed)" if c == a.convention else ""
        print(f"| {c}{mark} | {r['dirty']:.4f} | {pct(r['tir'])} | {num(r['modified'])} | {r['parity']:.2f}% |")
    if cl:
        worst = min((c for c in cl if c["tir"] is not None), key=lambda c: c["tir"], default=None)
        firsts = {c["price_pct"]: c for c in reversed(cl)}.values()
        shown = cl if a.calls_all or len(cl) <= 12 else sorted({id(c): c for c in [*firsts, worst] if c}.values(),
                                                                     key=lambda c: c["date"])
        print()
        print(f"Calls (whole issue; cash per 100 original; price assumed {a.convention}"
              + ("" if shown is cl else f"; {len(cl)} call dates, showing window starts and the worst; --calls-all lists all") + "):")
        print("| Call date | Call price | Cash if called | Total return | TIR |")
        print("|---|---|---|---|---|")
        for c in shown:
            print(f"| {c['date']} | {c['price_pct']:g}% | {c['cash']:.4f} | {pct(c['return'])} | {pct(c['tir'])} |")
        ytw = min([x for x in [worst and worst["tir"], m["tir"]] if x is not None], default=None)
        where = f"call on {worst['date']}" if worst and worst["tir"] == ytw else "maturity"
        print(f"Yield to worst {pct(ytw)} ({where}); TIR to maturity {pct(m['tir'])}.")
        cur = current_call_value(t, flows, settle, m["residual"], m["accrued"])
        if cur and m["dirty"] > cur[1]:
            print(f"Callable now at {cur[0]:g}%: call value {cur[1]:.4f} per 100 original is below the dirty price "
                  f"{m['dirty']:.4f}, so a call would return less than the price paid.")
    if t.get("min_denomination"):
        mn = float(t["min_denomination"])
        inc = f" and multiples of {t['increment']}" if t.get("increment") else ""
        print()
        print(f"Minimum lot {mn:g} face value{inc}: residual value {mn * m['residual'] / 100:.2f}, "
              f"approximate cost {m['dirty'] * mn / 100:.2f} (dirty price per 100 original x minimum / 100).")
    for w in warns + w2:
        print("WARN", w)


if __name__ == "__main__":
    main()
