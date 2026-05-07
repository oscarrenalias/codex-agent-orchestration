---
name: "Repo version tracking: .takt/version.json"
id: spec-7c6b5145
description: Write a .takt/version.json on takt init and takt upgrade recording the installed takt version and timestamp; warn in takt summary when the repo version is behind the installed version.
dependencies: null
priority: medium
complexity: small
status: done
tags:
- onboarding
- cli
- observability
scope:
  in: "takt init, takt upgrade, takt summary, .takt/version.json"
  out: "Bead lifecycle, scheduler, TUI, runner, storage"
feature_root_id: null
---
# Repo version tracking: .takt/version.json

## Objective

When multiple repositories use takt and releases ship frequently, it is easy for a repo to fall behind the globally installed version without the operator noticing. Today there is no record of which takt version initialized or last upgraded a repo, so there is no way to detect or warn about this drift. This spec adds a `.takt/version.json` file written by `takt init` and `takt upgrade`, and a check in `takt summary` that warns when the repo version is older than the installed version.

## Problems to Fix

1. **No record of which takt version a repo is on.** There is no file in `.takt/` that records the version used during `takt init` or the last `takt upgrade`. Operators have no way to query this.
2. **Silent drift goes unnoticed.** A repo initialized with an old version of takt silently misses managed asset updates (skill catalogs, guardrail templates, agent definitions) until the operator remembers to run `takt upgrade`.
3. **`takt summary` gives no version hygiene signal.** It is the natural place to surface a version mismatch warning since operators run it frequently to check pipeline status.

## Changes

### 1. `.takt/version.json` schema

```json
{
  "takt_version": "0.1.38",
  "last_upgraded_at": "2026-04-17T09:00:00Z"
}
```

- `takt_version`: the installed package version at the time of the operation, read via `importlib.metadata.version("agent-takt")`.
- `last_upgraded_at`: ISO 8601 UTC timestamp of the write operation.

### 2. Write helpers — `src/agent_takt/onboarding/version.py` (new file)

```python
VERSION_FILE = ".takt/version.json"

def write_version_file(project_root: Path) -> Path:
    """Write .takt/version.json with the current installed takt version."""
    ...

def read_version_file(project_root: Path) -> dict | None:
    """Return parsed .takt/version.json, or None if absent or unreadable."""
    ...

def check_version_drift(project_root: Path) -> str | None:
    """Return a warning string if the repo version is behind the installed version, else None."""
    ...
```

`write_version_file` always overwrites (idempotent). `check_version_drift` compares versions by splitting on `.` and comparing integer tuples — e.g. `(0, 1, 10) > (0, 1, 9)` — so that patch ordering is correct without adding the `packaging` library as a dependency. Pre-release suffixes (e.g. `0.1.10a1`) are handled by stripping non-numeric suffixes from the last component before comparison; an exact string match on the raw version string is used as a tie-breaker. If the version file is missing entirely, return a warning prompting the operator to run `takt upgrade`.

### 3. Call `write_version_file` from `takt init` and `takt upgrade`

In `src/agent_takt/onboarding/scaffold.py`, call `write_version_file(project_root)` at the end of `scaffold_project()`, after step 8 (assets manifest). Add the path to `stage_paths` in `commit_scaffold()` so it is committed to git.

In `src/agent_takt/cli/commands/init.py`, in `command_upgrade`, call `write_version_file(project_root)` immediately before the existing `commit_scaffold(root, console)` call at the end of the function (~line 267). The file will be included in that commit automatically. In dry-run mode, skip the write (consistent with how other file writes are guarded by `if not dry_run`).

### 4. Version drift warning in `takt summary`

In `src/agent_takt/cli/commands/misc.py`, in the `command_summary` function, call `check_version_drift(project_root)` and print a warning line if it returns a non-None string. The warning should be visually distinct (yellow, prefixed with `⚠`):

```
⚠  Repo takt version: 0.1.27 — installed: 0.1.38. Run 'takt upgrade' to update.
⚠  No .takt/version.json found. Run 'takt upgrade' to record the current version.
```

The warning is printed before the summary counts so it is not missed.

## Files to Modify

| File | Change |
|---|---|
| `src/agent_takt/onboarding/version.py` | **New file** — `write_version_file`, `read_version_file`, `check_version_drift` |
| `src/agent_takt/onboarding/scaffold.py` | Call `write_version_file` at end of `scaffold_project()`; add path to `stage_paths` in `commit_scaffold()` |
| `src/agent_takt/cli/commands/init.py` | Call `write_version_file` in `command_upgrade` before `commit_scaffold`; skip in dry-run |
| `src/agent_takt/cli/commands/misc.py` | Call `check_version_drift` in `command_summary`; print warning if non-None |

## Acceptance Criteria

- Running `takt init` in a fresh repo creates `.takt/version.json` containing the installed takt version and a UTC timestamp.
- Running `takt upgrade` overwrites `.takt/version.json` with the current installed version and a new timestamp.
- `.takt/version.json` is committed to git as part of the `takt init` scaffold commit.
- `takt summary` prints no warning when `.takt/version.json` exists and matches the installed version.
- `takt summary` prints a yellow `⚠` warning when the repo version is older than the installed version, naming both versions and suggesting `takt upgrade`.
- `takt summary` prints a yellow `⚠` warning when `.takt/version.json` is absent, suggesting `takt upgrade`.
- Version comparison handles pre-release and patch versions correctly (e.g. `0.1.9 < 0.1.10`).
- All existing `takt init`, `takt upgrade`, and `takt summary` tests pass; new tests cover write, read, drift detection (match, older, missing).

## Pending Decisions

- None.
