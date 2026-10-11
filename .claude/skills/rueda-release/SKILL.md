---
name: rueda-release
description: "Releases the rueda plugin after a change: bumps the package and plugin versions, rebuilds the wheel into the skills and runs the tests. Use whenever you finish editing anything under packages/rueda or plugins/rueda, before reporting the work as done."
argument-hint: "[patch|minor|major]"
allowed-tools:
  - Bash(uv --directory ${CLAUDE_PROJECT_DIR}/packages/rueda version *)
  - Bash(uv --directory ${CLAUDE_PROJECT_DIR}/packages/rueda run build)
  - Bash(uv --directory ${CLAUDE_PROJECT_DIR}/packages/rueda run pytest *)
---

# Release the rueda plugin

Run once per piece of work, after the last edit under `packages/rueda` or `plugins/rueda`.

- Never run git commands, not even `git status`. The user commits.
- Bump size: `$ARGUMENTS` (`patch` when empty).
- If you already bumped the versions in this session for the same work, skip the bumps in steps 2 and 3: rebuild and test only.

## 1. Classify the change

Go by the files edited in this session.

- **Package**: `packages/rueda/src/rueda/**`, or `dependencies`, `requires-python` or `[project.scripts]` in `packages/rueda/pyproject.toml`. These change the wheel.
- **Plugin**: anything under `plugins/rueda/` except a wheel.
- **Neither** (tests, `README.md`, `tools/rueda-build`): go to step 4.

## 2. Package change: bump and rebuild

```sh
uv --directory ${CLAUDE_PROJECT_DIR}/packages/rueda version --bump <size>
uv --directory ${CLAUDE_PROJECT_DIR}/packages/rueda run build
```

`build` replaces the wheel in each skill folder whose `SKILL.md` names a `rueda-*.whl`, and rewrites that filename in the `SKILL.md`.

A new skill that uses the package: name the wheel in its `SKILL.md` the way `plugins/rueda/skills/argentina-on-factsheet/SKILL.md` §0 does, then run `build`. That alone is a plugin change and needs no package bump.

## 3. Package or plugin change: bump the plugin

Raise `version` in `plugins/rueda/.claude-plugin/plugin.json` by the same bump size. Claude Code keeps an installed plugin on its version until this field changes.

## 4. Test

```sh
uv --directory ${CLAUDE_PROJECT_DIR}/packages/rueda run pytest -q
```

`tests/test_dist.py` fails when a skill's wheel differs from `src/rueda` or its `SKILL.md` names another file; `build` fixes both. The release is done only when every test passes.

## 5. Report

Give the old and new versions and the files for the user to commit: the edited sources, `packages/rueda/pyproject.toml`, `packages/rueda/uv.lock`, the wheels and `SKILL.md` files under `plugins/rueda/skills/`, and `plugin.json`.
