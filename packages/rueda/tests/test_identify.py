"""Tests of the identifier checks: CUIT, ISIN, class number and ticker."""

from rueda.identify import check, cuit_digit, from_roman, isin_digit, to_roman


def test_cuit() -> None:
    """A CUIT check digit is computed and a wrong one rejected."""
    assert cuit_digit("3067822401") == 0  # Pluspetrol
    assert cuit_digit("3052532274") == 9  # IRSA
    assert check("30-67822401-0")[1]
    assert not check("30-67822401-1")[1]


def test_isin() -> None:
    """An ISIN check digit is computed and a wrong one rejected."""
    assert isin_digit("US037833100") == 5  # Apple
    assert isin_digit("USP7924AAC2") == 9  # PLC5
    assert check("USP7924AAC29")[1]
    assert not check("USP7924AAC28")[1]


def test_roman() -> None:
    """Roman numerals convert both ways; a non-canonical one is rejected."""
    assert [to_roman(n) for n in (5, 14, 23, 49)] == ["V", "XIV", "XXIII", "XLIX"]
    assert from_roman("XXIII") == 23
    assert from_roman("IIII") is None


def test_ticker() -> None:
    """A ticker gives its base, currency and class; a class gives its number."""
    line, ok = check("PLC5O")
    assert ok
    assert "base PLC5" in line
    assert "pesos" in line
    assert "class 5 (V)" in line
    assert "class not in ticker" in check("IRCOD")[0]
    assert "MEP" in check("IRCOD")[0]
    assert check("clase V")[0].split("\t")[2] == "5"
