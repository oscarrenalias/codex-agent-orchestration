---
name: Bundle claude agents and sync skill-spec-management into onboarding
id: spec-1f179a4e
description: Add .claude/agents/ bundling to takt init/upgrade; sync skill-spec-management SKILL.md and add spec-reviewer.md as bundled agent
dependencies: null
priority: medium
complexity: small
status: done
tags:
- onboarding
- skill-spec-management
scope:
  in: "_assets.py, onboarding/assets.py, onboarding/scaffold.py, onboarding/upgrade.py, _data/claude_agents/"
  out: "skill content changes, runner or scheduler behaviour"
feature_root_id: null
---
# Bundle claude agents and sync skill-spec-management into onboarding

## Objective

The `takt init` onboarding process deploys `.claude/skills/` from `src/agent_takt/_data/claude_skills/`, but has no equivalent for `.claude/agents/`. The `spec-reviewer.md` agent steering file lives only in the working repo's `.claude/agents/` directory and is never propagated to new projects. Additionally, the bundled `skill-spec-management/SKILL.md` in `_data/claude_skills/` is out of sync with the working copy (missing the `--body-only` flag docs). This spec fixes both gaps.

## Problems to Fix

1. `.claude/agents/spec-reviewer.md` exists in the repo but has no bundle location (`src/agent_takt/_data/claude_agents/`) and is never installed by `takt init` or `takt upgrade`.
2. `src/agent_takt/_data/claude_skills/skill-spec-management/SKILL.md` is missing docs for the `--body-only` flag on the `show` command (added in a recent update to `.claude/skills/skill-spec-management/SKILL.md`).
3. No `packaged_claude_agents_dir()` helper exists in `_assets.py`.
4. No `install_claude_agents()` function exists in `onboarding/assets.py`.
5. `scaffold_project()` in `onboarding/scaffold.py` does not install `.claude/agents/` or stage it for the init commit.
6. `onboarding/upgrade.py` does not track `.claude/agents/` in the asset manifest or upgrade evaluation.

## Changes

### 1. Sync bundled SKILL.md

Copy the current content of `.claude/skills/skill-spec-management/SKILL.md` into `src/agent_takt/_data/claude_skills/skill-spec-management/SKILL.md`. The only diff is two lines in the `show` command documentation:

- Update the description line to include: `Use '--body-only' to print the body without frontmatter — always use this when passing a spec to the 'spec-reviewer' agent or any other agent that should not see frontmatter fields.`
- Add example: `python3 <spec-py> show --body-only spec-a3f19c2b`

### 2. Create bundled claude_agents directory and add spec-reviewer.md

Create `src/agent_takt/_data/claude_agents/` and copy `.claude/agents/spec-reviewer.md` into it.

### 3. Add `packaged_claude_agents_dir()` to `_assets.py`

```python
def packaged_claude_agents_dir() -> Path:
    """Path to the bundled ``.claude/agents/`` catalog."""
    return _data_path("claude_agents")
```

### 4. Add `install_claude_agents()` to `onboarding/assets.py`

Import `packaged_claude_agents_dir` from `_assets` and add:

```python
def install_claude_agents(project_root: Path, *, overwrite: bool = False) -> list[Path]:
    """Copy the bundled ``.claude/agents/`` agent steering files into *project_root*.

    Args:
        project_root: Root directory of the target project.
        overwrite: Overwrite existing agent files when ``True``.

    Returns:
        List of destination paths that were written.
    """
    src = packaged_claude_agents_dir()
    dest = project_root / ".claude" / "agents"
    return copy_asset_dir(src, dest, overwrite=overwrite)  # copy_asset_dir is an existing helper in this module
```

### 5. Update `scaffold_project()` in `onboarding/scaffold.py`

- Import `install_claude_agents` from `.assets`.
- After the `install_claude_skills` call in step 4, add:
  ```python
  written_claude_agents = install_claude_agents(project_root, overwrite=True)
  console.success("Installed .claude/agents/ agent steering files")
  ```
  Note: `overwrite=True` is hardcoded here (matching the pattern used for `install_claude_skills` and `install_agents_skills`), while `install_claude_agents()` defaults to `False`. This asymmetry is intentional — `scaffold_project()` always overwrites managed assets so re-running `takt init` propagates updated content; the `False` default lets upgrade callers control overwrite behaviour independently.
- Add `".claude/agents/"` to the `stage_paths` list in `commit_scaffold()`.

### 6. Update `onboarding/upgrade.py`

- Import `packaged_claude_agents_dir` from `.._assets`.
- Add `".claude/agents/"` to the tracked asset paths in `evaluate_upgrade_actions()` (alongside `.claude/skills/`).
- Add a catalog entry for `claude_agents` files in the manifest-building loop (pattern mirrors the existing `claude_skills` block).

## Files to Modify

| File | Change |
|---|---|
| `src/agent_takt/_data/claude_skills/skill-spec-management/SKILL.md` | Sync `show` command docs to include `--body-only` |
| `src/agent_takt/_data/claude_agents/spec-reviewer.md` | New file — copy from `.claude/agents/spec-reviewer.md` |
| `src/agent_takt/_assets.py` | Add `packaged_claude_agents_dir()` |
| `src/agent_takt/onboarding/assets.py` | Add `install_claude_agents()` |
| `src/agent_takt/onboarding/scaffold.py` | Call `install_claude_agents()` in `scaffold_project()`; add `.claude/agents/` to `stage_paths` in `commit_scaffold()` |
| `src/agent_takt/onboarding/upgrade.py` | Track `.claude/agents/` in manifest and upgrade evaluation |

## Acceptance Criteria

- `src/agent_takt/_data/claude_skills/skill-spec-management/SKILL.md` matches `.claude/skills/skill-spec-management/SKILL.md` exactly.
- `src/agent_takt/_data/claude_agents/spec-reviewer.md` exists and matches `.claude/agents/spec-reviewer.md`.
- `packaged_claude_agents_dir()` returns the correct path under `_data/claude_agents`.
- `install_claude_agents(project_root)` copies all files from `_data/claude_agents/` into `<project_root>/.claude/agents/`.
- Running `takt init` on a fresh directory creates `.claude/agents/spec-reviewer.md`.
- `.claude/agents/` is staged and included in the `chore: takt init scaffold` commit.
- `.claude/agents/` appears in the assets manifest written by `scaffold_project()`.
- `takt upgrade` (via `evaluate_upgrade_actions`) surfaces `.claude/agents/` files as upgradeable assets.
- All existing tests pass (`uv run pytest tests/ -n auto -q`).

## Pending Decisions

None.
