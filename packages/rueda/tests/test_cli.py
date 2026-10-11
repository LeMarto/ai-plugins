import importlib

import pytest

from rueda import cli
from rueda.on.schedule import load_terms


def test_every_command_resolves():
    for target in cli.COMMANDS.values():
        module, fn = target.split(":")
        assert callable(getattr(importlib.import_module(module), fn))


def test_one_and_two_word_commands(capsys, tmp_path):
    with pytest.raises(SystemExit) as e:
        cli.main(["identify", "USP7924AAC29"])
    assert e.value.code == 0 and "ISIN\tvalid" in capsys.readouterr().out
    cli.main(["on", "terms-example"])
    p = tmp_path / "terms.json"
    p.write_text(capsys.readouterr().out)
    assert load_terms(p)["rate"] == 8.125


def test_unknown_command_exits_with_the_command_list():
    for args in ([], ["on"], ["nope"]):
        with pytest.raises(SystemExit) as e:
            cli.main(args)
        assert "on schedule" in e.value.code
