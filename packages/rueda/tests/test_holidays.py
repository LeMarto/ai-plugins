"""Tests of the AR and US bank holidays."""

from datetime import date

from rueda import holidays


def test_easter() -> None:
    """Easter Sunday falls on the known dates of four years."""
    assert [holidays.easter(y) for y in (2024, 2025, 2026, 2027)] == [
        date(2024, 3, 31),
        date(2025, 4, 20),
        date(2026, 4, 5),
        date(2027, 3, 28),
    ]


def test_movable_rule_matches_published_years() -> None:
    """The law 27.399 rule gives the dates the API published."""
    # published dates from api.argentinadatos.com
    assert holidays.moved(date(2024, 11, 20)) == date(2024, 11, 18)  # Wed
    assert holidays.moved(date(2025, 6, 17)) == date(2025, 6, 16)  # Tue
    assert holidays.moved(date(2025, 11, 20)) == date(2025, 11, 24)  # Thu
    assert holidays.moved(date(2026, 11, 20)) == date(2026, 11, 23)  # Fri
    assert holidays.moved(date(2026, 8, 17)) == date(2026, 8, 17)  # Mon


def test_ar_fallback_warns() -> None:
    """An unpublished year uses the rules and says so."""
    hs, w = holidays.ar(2028)
    assert date(2028, 11, 20) in hs  # Soberanía (Mon)
    assert date(2028, 4, 13) in hs  # Jueves Santo
    assert w is not None
    assert "not published" in w


def test_us_federal_reserve_2026() -> None:
    """The Federal Reserve holidays of 2026, a year with one on a Saturday."""
    hs, _ = holidays.us(2026)
    assert sorted(hs) == [
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 9, 7),
        date(2026, 10, 12),
        date(2026, 11, 11),
        date(2026, 11, 26),
        date(2026, 12, 25),
    ]  # July 4 is a Saturday: not observed
