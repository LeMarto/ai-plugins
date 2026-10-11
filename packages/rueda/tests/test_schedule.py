"""Tests of the payment schedule of an ON."""

import json
from datetime import date
from pathlib import Path

import pytest

from rueda.on.schedule import (
    Terms,
    TermsError,
    adjust,
    build,
    check_notice,
    load_terms,
    schedule,
    year_frac,
)
from tests.conftest import EXAMPLE


def terms(**over: object) -> Terms:
    """Return the example terms with some fields replaced."""
    t = load_terms(EXAMPLE)
    t.update(over)
    return t


def test_plc5_matches_aviso_de_pago() -> None:
    """The example terms give the amounts of the issuer's aviso de pago."""
    t = terms()
    flows, _, _ = schedule(t)
    assert len(flows) == 11
    assert flows[0].accrual_start == date(2025, 11, 18)
    assert flows[0].pay_date == date(2026, 5, 18)
    assert all(f.interest == pytest.approx(4.0625) for f in flows)
    assert flows[-1].amortization == 100
    assert flows[-1].balance_after == 0
    assert flows[-1].pay_date == date(2031, 5, 19)  # Sunday 18th, next business day
    assert check_notice(t, flows).endswith("OK")


def test_notice_mismatch() -> None:
    """A notice with another interest amount is reported as a mismatch."""
    t = terms(last_payment_notice={"date": "2026-05-18", "interest_per_100": 4.1})
    assert "MISMATCH" in check_notice(t, schedule(t)[0])


def test_amortizing_interest_on_declining_balance() -> None:
    """Interest is computed on the balance left after each installment."""
    t = terms(
        rate=10,
        maturity="2027-11-18",
        first_payment_date="2026-05-18",
        amortization=[
            {"date": d, "pct": 25}
            for d in ("2026-05-18", "2026-11-18", "2027-05-18", "2027-11-18")
        ],
    )
    flows = build(t, set())
    assert [round(f.interest, 4) for f in flows] == [5.0, 3.75, 2.5, 1.25]
    assert [f.balance_after for f in flows] == [75, 50, 25, 0]


def test_floating_projects_latest_rate() -> None:
    """A floating rate projects the last base rate plus the margin, as an estimate."""
    t = terms(
        rate_type="floating",
        base_rate={"name": "TAMAR", "rate": 30.0, "date": "2026-10-01"},
        margin=2.0,
    )
    f = build(t, set())[0]
    assert f.estimate
    assert f.rate == 32.0
    assert f.interest == pytest.approx(16.0)


def test_year_frac() -> None:
    """Each day count gives its year fraction, ACT/ACT also on a short period."""
    approx = pytest.approx
    assert year_frac(date(2026, 1, 31), date(2026, 3, 31), "30/360") == approx(60 / 360)
    assert year_frac(date(2026, 1, 1), date(2026, 7, 1), "ACT/365") == approx(181 / 365)
    assert year_frac(date(2026, 1, 15), date(2026, 7, 15), "ACT/ACT", 6) == approx(0.5)
    short = year_frac(date(2026, 3, 15), date(2026, 7, 15), "ACT/ACT", 6)
    assert short == approx(122 / 181 / 2)


def test_business_day_rules() -> None:
    """Each business-day rule moves a Saturday and a holiday to the right day."""
    sat, may25 = date(2026, 1, 31), date(2026, 5, 25)
    assert adjust(sat, "following", set()) == date(2026, 2, 2)
    assert adjust(sat, "modified_following", set()) == date(2026, 1, 30)
    assert adjust(sat, "preceding", set()) == date(2026, 1, 30)
    assert adjust(may25, "following", {may25}) == date(2026, 5, 26)


def test_missing_fields_abort(tmp_path: Path) -> None:
    """A field without value or without source is listed in the error."""
    raw = json.loads(Path(EXAMPLE).read_text())
    del raw["day_count"]
    raw["rate"]["source"] = ""
    p = tmp_path / "t.json"
    p.write_text(json.dumps(raw))
    with pytest.raises(TermsError, match="day_count, rate"):
        load_terms(p)


def test_amortization_must_add_to_100() -> None:
    """An amortization table that does not add up to 100 is rejected."""
    with pytest.raises(TermsError, match="add up"):
        build(terms(amortization=[{"date": "2031-05-18", "pct": 90}]), set())


def test_rounded_amortization_table_last_installment_takes_remainder() -> None:
    """A table rounded by the issuer repays the remainder in the last installment."""
    t = terms(
        maturity="2026-11-18",
        first_payment_date="2026-05-18",
        amortization=[
            {"date": "2026-05-18", "pct": 33.3334},
            {"date": "2026-11-18", "pct": 66.6668},
        ],
    )
    flows = build(t, set())
    assert flows[-1].amortization == pytest.approx(66.6666)
    assert flows[-1].balance_after == 0


def test_accrual_to_adjusted_dates() -> None:
    """With accrue_to_adjusted_date, interest accrues to the day it is paid."""
    # AA2000 Clase I Serie 2021: 1 May 2026 holiday, paid and accrued to 4 May;
    # aviso de pago 24/07/2026
    t = terms(
        rate=8.5,
        issue_date="2026-02-02",
        interest_start_date="2026-02-02",
        maturity="2026-08-01",
        first_payment_date="2026-05-01",
        frequency_months=3,
        accrue_to_adjusted_date=True,
        amortization=[{"date": "2026-08-01", "pct": 100}],
    )
    hols = {date(2026, 5, 1)}
    flows = build(t, hols)
    assert flows[0].pay_date == date(2026, 5, 4)
    assert flows[1].pay_date == date(2026, 8, 3)  # Aug 1 is a Saturday
    assert flows[1].accrual_start == date(2026, 5, 4)
    assert flows[1].interest == pytest.approx(8.5 * 89 / 360)
