"""Build the rueda wheel and place it in the skills that use it.
Usage: uv run build
Builds the wheel of the rueda project into a temporary directory. For each skill
folder in plugins/rueda/skills/ whose SKILL.md names a rueda-*.whl, replaces the
wheel in that folder and rewrites the filename in SKILL.md."""
import os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

WHEEL = re.compile(r"rueda-[0-9][A-Za-z0-9_.+!]*-py3-none-any\.whl")


def repo_root():
    """The directory holding .claude-plugin/marketplace.json, searched upwards from this file."""
    for p in Path(__file__).resolve().parents:
        if (p / ".claude-plugin" / "marketplace.json").exists():
            return p
    sys.exit(f"no .claude-plugin/marketplace.json above {__file__}")


def main():
    root = repo_root()
    written = []
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([os.environ.get("UV", "uv"), "build", "--wheel", "--package", "rueda", "--out-dir", tmp],
                       cwd=root / "packages" / "rueda", check=True)
        wheel, = Path(tmp).glob("rueda-*.whl")
        for skill_md in sorted((root / "plugins" / "rueda" / "skills").glob("*/SKILL.md")):
            text = skill_md.read_text(encoding="utf8")
            if not WHEEL.search(text):
                continue
            for old in skill_md.parent.glob("rueda-*.whl"):
                old.unlink()
            written.append(shutil.copy(wheel, skill_md.parent / wheel.name))
            if WHEEL.sub(wheel.name, text) != text:
                skill_md.write_text(WHEEL.sub(wheel.name, text), encoding="utf8")
    if not written:
        sys.exit("no SKILL.md in plugins/rueda/skills names a rueda-*.whl")
    for path in written:
        print(path)
