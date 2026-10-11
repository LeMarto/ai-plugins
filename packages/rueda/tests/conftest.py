from importlib.resources import files

import pytest

EXAMPLE = str(files("rueda.on") / "terms.example.json")


@pytest.fixture(autouse=True)
def offline_holidays(monkeypatch):
    """AR holidays from the rules only, so tests need no network."""
    from rueda import holidays
    monkeypatch.setattr(holidays, "_fetch_ar", lambda y: None)
