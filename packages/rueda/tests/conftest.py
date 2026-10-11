"""Shared by every test: the example terms and an offline holiday calendar."""

from importlib.resources import files

import pytest

from rueda import holidays

EXAMPLE = str(files("rueda.on") / "terms.example.json")


@pytest.fixture(autouse=True)
def offline_holidays(monkeypatch: pytest.MonkeyPatch) -> None:
    """AR holidays from the rules only, so tests need no network."""
    monkeypatch.setattr(holidays, "_fetch_ar", lambda _y: None)
