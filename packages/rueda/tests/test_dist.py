"""Tests that the wheel in each skill folder is the current build."""

import re
import tomllib
import zipfile
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
SRC = PROJECT / "src"
VERSION = tomllib.loads((PROJECT / "pyproject.toml").read_text())["project"]["version"]
NAME = f"rueda-{VERSION}-py3-none-any.whl"
WHEEL = re.compile(r"rueda-[0-9][A-Za-z0-9_.+!]*-py3-none-any\.whl")
SKILLS = [
    p.parent
    for p in sorted(
        (PROJECT.parents[1] / "plugins" / "rueda" / "skills").glob("*/SKILL.md")
    )
    if WHEEL.search(p.read_text(encoding="utf8"))
]


def test_a_skill_names_the_wheel() -> None:
    """At least one skill of the plugin names a rueda wheel."""
    assert SKILLS


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.name)
def test_skill_wheel_is_the_current_build(skill: Path) -> None:
    """The skill holds one wheel, named in its SKILL.md and equal to src/rueda."""
    # fails after a source edit or a version bump until `uv run build` is run
    assert [p.name for p in skill.glob("*.whl")] == [NAME]
    assert set(WHEEL.findall((skill / "SKILL.md").read_text(encoding="utf8"))) == {NAME}
    with zipfile.ZipFile(skill / NAME) as z:
        built = {
            n: z.read(n)
            for n in z.namelist()
            if n.startswith("rueda/") and not n.endswith("/")
        }
    source = {
        p.relative_to(SRC).as_posix(): p.read_bytes()
        for p in (SRC / "rueda").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    assert sorted(built) == sorted(source)
    assert [n for n in source if built[n] != source[n]] == []
