"""Tests of the yield, duration and call analysis of an ON."""

from datetime import date

import pytest

from rueda.on.schedule import Flow, Terms, load_terms, schedule
from rueda.on.tir import analyse, calls, current_call_value, dirty_price
from tests.conftest import EXAMPLE

Plc5 = tuple[Terms, list[Flow]]


@pytest.fixture
def plc5() -> Plc5:
    """Return the example terms (PLC5) and their flows."""
    t = load_terms(EXAMPLE)
    return t, schedule(t)[0]


def test_issue_yield_matches_aviso_de_resultados(plc5: Plc5) -> None:
    """The issue price gives the yield the issuer published."""
    # Aviso de resultados 12/11/2025: price 98.916, rendimiento 8.375% semiannual
    t, flows = plc5
    r = analyse(t, flows, 98.916, date(2025, 11, 18), "clean-original")
    assert r["accrued"] == 0
    assert r["tir"] == pytest.approx(1.041875**2 - 1, abs=2e-4)


def test_par_and_accrued(plc5: Plc5) -> None:
    """A clean price of 100 gives parity 100 and a yield equal to the coupon."""
    t, flows = plc5
    r = analyse(t, flows, 100, date(2026, 10, 5), "clean-original")
    assert r["accrued"] == pytest.approx(8.125 * 137 / 360)
    assert r["parity"] == pytest.approx(100)
    assert r["tir"] == pytest.approx(1.040625**2 - 1, abs=3e-4)
    modified, macaulay = r["modified"], r["macaulay"]
    assert modified is not None
    assert macaulay is not None
    assert 0 < modified < macaulay < 5


def test_conventions() -> None:
    """Each quoting convention gives its dirty price per 100 original."""
    assert dirty_price(100, "dirty-original", 50, 2) == 100
    assert dirty_price(100, "clean-original", 50, 2) == 102
    assert dirty_price(100, "dirty-residual", 50, 2) == 50
    assert dirty_price(100, "clean-residual", 50, 2) == 52


def test_calls(plc5: Plc5) -> None:
    """A call pays the balance at the call price, on a payment date or between two."""
    t, flows = plc5
    t = dict(
        t,
        call_schedule=[
            {"from": "2026-11-18", "to": "2027-11-18", "price_pct": 102},
            {"from": "2027-11-18", "price_pct": 100},
        ],
    )
    settle = date(2026, 10, 5)
    r = analyse(t, flows, 100, settle, "dirty-original")
    cl = {c["date"]: c for c in calls(t, flows, settle, r["dirty"])}
    # on a payment date: the coupon plus the balance at the call price
    assert cl[date(2026, 11, 18)]["cash"] == pytest.approx(4.0625 + 102)
    assert cl[date(2026, 11, 18)]["return"] == pytest.approx(0.060625)
    assert date(2031, 5, 19) not in cl  # maturity is the TIR case, not a call
    # not callable yet
    assert current_call_value(t, flows, settle, 100, r["accrued"]) is None
    t2 = dict(t, call_schedule=[{"from": "2027-01-18", "price_pct": 101}])
    c = calls(t2, flows, settle, r["dirty"])[0]
    # between payment dates: price plus 60 days of accrued interest (30/360)
    assert c["date"] == date(2027, 1, 18)
    assert c["cash"] == pytest.approx(4.0625 + 101 + 8.125 * 60 / 360)


def test_current_call_value_above_price(plc5: Plc5) -> None:
    """An issue inside a call window reports its call price and value."""
    t, flows = plc5
    t = dict(t, call_schedule=[{"from": "2026-01-01", "price_pct": 104.25}])
    cur = current_call_value(t, flows, date(2026, 10, 5), 100, 3.0)
    assert cur is not None
    px, value = cur
    assert px == 104.25
    assert value == pytest.approx(107.25)
