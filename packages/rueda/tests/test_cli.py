"""Tests of the `rueda` command dispatcher."""

import importlib
from pathlib import Path

import pytest

from rueda import cli
from rueda.on.schedule import load_terms


def test_every_command_resolves() -> None:
    """Every entry of COMMANDS names an importable callable."""
    for target in cli.COMMANDS.values():
        module, fn = target.split(":")
        assert callable(getattr(importlib.import_module(module), fn))


def test_one_and_two_word_commands(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """One-word and two-word commands both reach their module."""
    with pytest.raises(SystemExit) as e:
        cli.main(["identify", "USP7924AAC29"])
    assert e.value.code == 0
    assert "ISIN\tvalid" in capsys.readouterr().out
    cli.main(["on", "terms-example"])
    p = tmp_path / "terms.json"
    p.write_text(capsys.readouterr().out)
    assert load_terms(p)["rate"] == 8.125


def test_unknown_command_exits_with_the_command_list() -> None:
    """No command, half a command and an unknown one all exit with the usage."""
    for args in ([], ["on"], ["nope"]):
        with pytest.raises(SystemExit) as e:
            cli.main(args)
        assert isinstance(e.value.code, str)
        assert "on schedule" in e.value.code
