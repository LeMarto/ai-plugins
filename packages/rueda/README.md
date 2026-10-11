# rueda

Python tools for Argentine market instruments. The skills of the `rueda` plugin (`plugins/rueda`) run them from a wheel stored in each skill folder:

    uvx --from <skill folder>/rueda-<version>-py3-none-any.whl rueda <command>

## Commands

| Command | Output |
|---|---|
| `rueda identify` | Check digits of a CUIT or ISIN; base, currency and class of a ticker |
| `rueda holidays` | Bank holidays, AR or US |
| `rueda cnv list` | Documents on an issuer's CNV company page |
| `rueda cnv dl` | Attachments of a CNV publicview presentation, with their text |
| `rueda sec 20f` | An issuer's 20-F filings from SEC EDGAR, with the debt sections |
| `rueda on find-terms` | Term passages in extracted document text |
| `rueda on terms-example` | An example `terms.json` |
| `rueda on schedule` | Payment schedule of an ON from `terms.json` |
| `rueda on tir` | Yield, duration and parity from `terms.json` and a price |

`rueda <command> -h` prints a command's usage.

## Development

    uv run pytest      # tests
    uv run rueda ...   # run from source
    uv run build       # build the wheel into the skills

`uv run build` comes from `tools/rueda-build`, a workspace member listed in the `dev` dependency group; the `rueda` wheel does not contain it. It builds the wheel and, for each folder in `plugins/rueda/skills/` whose `SKILL.md` names a `rueda-*.whl`, replaces the wheel there and rewrites the filename in `SKILL.md`. A new skill gets the wheel by naming it in its `SKILL.md`.

`tests/test_dist.py` fails while a skill's wheel differs from `src/rueda`.

## Release

In Claude Code, the project skill `rueda-release` (`.claude/skills/rueda-release`) runs steps 1 to 4 after a change to `packages/rueda` or `plugins/rueda`; `/rueda-release [patch|minor|major]` starts it by hand. Step 5 is manual: the skill runs no git command.

1. Bump `version` in `pyproject.toml`.
2. `uv run build`
3. `uv run pytest`
4. Bump `version` in `plugins/rueda/.claude-plugin/plugin.json`. Claude Code keeps an installed plugin on its version until that field changes.
5. Commit the wheels in the skill folders.
