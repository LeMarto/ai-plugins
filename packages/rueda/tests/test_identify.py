from rueda.identify import check, cuit_digit, from_roman, isin_digit, to_roman


def test_cuit():
    assert cuit_digit("3067822401") == 0  # Pluspetrol
    assert cuit_digit("3052532274") == 9  # IRSA
    assert check("30-67822401-0")[1]
    assert not check("30-67822401-1")[1]


def test_isin():
    assert isin_digit("US037833100") == 5  # Apple
    assert isin_digit("USP7924AAC2") == 9  # PLC5
    assert check("USP7924AAC29")[1]
    assert not check("USP7924AAC28")[1]


def test_roman():
    assert [to_roman(n) for n in (5, 14, 23, 49)] == ["V", "XIV", "XXIII", "XLIX"]
    assert from_roman("XXIII") == 23
    assert from_roman("IIII") is None


def test_ticker():
    line, ok = check("PLC5O")
    assert ok and "base PLC5" in line and "pesos" in line and "class 5 (V)" in line
    assert "class not in ticker" in check("IRCOD")[0]
    assert "MEP" in check("IRCOD")[0]
    assert check("clase V")[0].split("\t")[2] == "5"
