from datetime import date

from rueda import holidays


def test_easter():
    assert [holidays.easter(y) for y in (2024, 2025, 2026, 2027)] == [
        date(2024, 3, 31), date(2025, 4, 20), date(2026, 4, 5), date(2027, 3, 28)]


def test_movable_rule_matches_published_years():
    # published dates from api.argentinadatos.com
    assert holidays.moved(date(2024, 11, 20)) == date(2024, 11, 18)  # Wed
    assert holidays.moved(date(2025, 6, 17)) == date(2025, 6, 16)  # Tue
    assert holidays.moved(date(2025, 11, 20)) == date(2025, 11, 24)  # Thu
    assert holidays.moved(date(2026, 11, 20)) == date(2026, 11, 23)  # Fri
    assert holidays.moved(date(2026, 8, 17)) == date(2026, 8, 17)  # Mon


def test_ar_fallback_warns():
    hs, w = holidays.ar(2028)
    assert date(2028, 11, 20) in hs and date(2028, 4, 13) in hs  # Soberanía (Mon), Jueves Santo
    assert "not published" in w


def test_us_federal_reserve_2026():
    hs, _ = holidays.us(2026)
    assert sorted(hs) == [date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 5, 25),
                          date(2026, 6, 19), date(2026, 9, 7), date(2026, 10, 12), date(2026, 11, 11),
                          date(2026, 11, 26), date(2026, 12, 25)]  # July 4 is a Saturday: not observed
