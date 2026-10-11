from datetime import date

import pytest

from conftest import EXAMPLE
from rueda.on.schedule import load_terms, schedule
from rueda.on.tir import analyse, calls, current_call_value, dirty_price


@pytest.fixture
def plc5():
    t = load_terms(EXAMPLE)
    return t, schedule(t)[0]


def test_issue_yield_matches_aviso_de_resultados(plc5):
    # Aviso de resultados 12/11/2025: price 98.916, rendimiento 8.375% semiannual
    t, flows = plc5
    r = analyse(t, flows, 98.916, date(2025, 11, 18), "clean-original")
    assert r["accrued"] == 0
    assert r["tir"] == pytest.approx(1.041875 ** 2 - 1, abs=2e-4)


def test_par_and_accrued(plc5):
    t, flows = plc5
    r = analyse(t, flows, 100, date(2026, 10, 5), "clean-original")
    assert r["accrued"] == pytest.approx(8.125 * 137 / 360)
    assert r["parity"] == pytest.approx(100)
    assert r["tir"] == pytest.approx(1.040625 ** 2 - 1, abs=3e-4)
    assert 0 < r["modified"] < r["macaulay"] < 5


def test_conventions():
    assert dirty_price(100, "dirty-original", 50, 2) == 100
    assert dirty_price(100, "clean-original", 50, 2) == 102
    assert dirty_price(100, "dirty-residual", 50, 2) == 50
    assert dirty_price(100, "clean-residual", 50, 2) == 52


def test_calls(plc5):
    t, flows = plc5
    t = dict(t, call_schedule=[{"from": "2026-11-18", "to": "2027-11-18", "price_pct": 102},
                               {"from": "2027-11-18", "price_pct": 100}])
    settle = date(2026, 10, 5)
    r = analyse(t, flows, 100, settle, "dirty-original")
    cl = {c["date"]: c for c in calls(t, flows, settle, r["dirty"])}
    # on a payment date: the coupon plus the balance at the call price
    assert cl[date(2026, 11, 18)]["cash"] == pytest.approx(4.0625 + 102)
    assert cl[date(2026, 11, 18)]["return"] == pytest.approx(0.060625)
    assert date(2031, 5, 19) not in cl  # maturity is the TIR case, not a call
    assert current_call_value(t, flows, settle, 100, r["accrued"]) is None  # not callable yet
    t2 = dict(t, call_schedule=[{"from": "2027-01-18", "price_pct": 101}])
    c = calls(t2, flows, settle, r["dirty"])[0]
    # between payment dates: price plus 60 days of accrued interest (30/360)
    assert c["date"] == date(2027, 1, 18)
    assert c["cash"] == pytest.approx(4.0625 + 101 + 8.125 * 60 / 360)


def test_current_call_value_above_price(plc5):
    t, flows = plc5
    t = dict(t, call_schedule=[{"from": "2026-01-01", "price_pct": 104.25}])
    px, value = current_call_value(t, flows, date(2026, 10, 5), 100, 3.0)
    assert px == 104.25 and value == pytest.approx(107.25)
