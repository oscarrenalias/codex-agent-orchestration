---
name: Rename project to agent-takt
id: spec-1797b8d3
description: Rename the package, module, and CLI from codex-agent-orchestration/codex_orchestrator/orchestrator to agent-takt/agent_takt/takt
dependencies:
priority: medium
complexity: medium
status: draft
tags:
- refactoring
- rename
scope:
  in: pyproject.toml, src/codex_orchestrator/, tests/, CLAUDE.md, README.md, docs/, apm.yml, skills/spec-management/SKILL.md, templates/agents/
  out: bead JSON files, git history
feature_root_id:
---

# Rename Project to agent-takt

## Objective

The project is no longer Codex-specific — it supports Claude Code and Codex interchangeably. The name `codex-agent-orchestration` is misleading. This spec renames the project to `agent-takt` throughout: PyPI package name, Python module name, and CLI command.

---

## Problems to Fix

1. **Package name is misleading** — `codex-agent-orchestration` implies Codex-only; the project is backend-agnostic.
2. **Module name is stale** — `codex_orchestrator` appears in every import across 15 test files and all source modules.
3. **CLI command is generic** — `orchestrator` is undifferentiated; `takt` is brand-aligned and shorter.
4. **Project description is inaccurate** — pyproject.toml says "Codex-based multi-agent orchestration MVP".

---

## Changes

### Naming Decisions

| Item | Current | New |
|---|---|---|
| PyPI package name | `codex-agent-orchestration` | `agent-takt` |
| Python module (directory) | `src/codex_orchestrator/` | `src/agent_takt/` |
| Python import prefix | `from codex_orchestrator.` | `from agent_takt.` |
| CLI command | `orchestrator` | `takt` |
| Environment variable | `ORCHESTRATOR_RUNNER` | `AGENT_TAKT_RUNNER` |
| Runtime state dir | `.orchestrator/` | `.takt/` |
| Config file | `.orchestrator/config.yaml` | `.takt/config.yaml` |

### 1. `src/` directory rename

Rename `src/codex_orchestrator/` to `src/agent_takt/`. This is a directory rename — all file contents remain identical except for the import changes below.

Delete the stale egg-info: `src/codex_agent_orchestration.egg-info/` (regenerated on next build).

### 2. Runtime state directory rename

The hardcoded `.orchestrator` directory name appears in `storage.py`, `config.py`, `gitutils.py`, `cli.py`, and `scheduler.py` (anywhere that constructs paths like `root / ".orchestrator"`). Replace all occurrences with `.takt`.

This affects:
- `RepositoryStorage` root path construction
- `load_config(root)` — looks for `root / ".orchestrator" / "config.yaml"`
- `gitutils.py` — worktree paths under `.orchestrator/worktrees/`
- `cli.py` — any hardcoded `.orchestrator` path references
- Any log/telemetry path constants

The existing `.orchestrator/` directory in this repo must be **migrated** as part of this bead:
```bash
mv .orchestrator .takt
```
Then create a symlink so the current session's worktrees (which still reference `.orchestrator/`) don't break mid-migration:
```bash
ln -s .takt .orchestrator
```
The symlink can be removed once all active worktrees are cleaned up.

### 3. `pyproject.toml`

```toml
[project]
name = "agent-takt"
description = "Multi-agent orchestration for AI-assisted software development"

[project.scripts]
takt = "agent_takt.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
agent_takt = [
    "_data/templates/agents/*.md",
    "_data/docs/memory/*.md",
    "_data/default_config.yaml",
    "_data/agents_skills/**/*",
    "_data/claude_skills/**/*",
]
```

### 4. Internal imports within `src/agent_takt/`

Every `from codex_orchestrator.` or `import codex_orchestrator` inside the source modules must be updated to `from agent_takt.` / `import agent_takt`.

Files affected (all files in `src/codex_orchestrator/` that cross-import):
`cli.py`, `runner.py`, `prompts.py`, `skills.py`, `scheduler.py`, `storage.py`, `planner.py`, `tui.py`, `onboarding.py`, `gitutils.py`, `graph.py`, `_assets.py`

### 5. Environment variable fallback in `runner.py`

```python
# AGENT_TAKT_RUNNER takes priority; ORCHESTRATOR_RUNNER kept as legacy fallback
backend_name = (
    runner_backend
    or os.environ.get("AGENT_TAKT_RUNNER")
    or os.environ.get("ORCHESTRATOR_RUNNER")  # legacy fallback
    or config.default_runner
)
```

### 6. Test files (15 files under `tests/`)

Replace all `from codex_orchestrator.` with `from agent_takt.` and all `import codex_orchestrator` with `import agent_takt`.

Files:
`tests/test_onboarding.py`, `tests/test_config.py`, `tests/test_cli_init.py`, `tests/test_assets.py`, `tests/test_orchestrator.py`, `tests/test_model_override.py`, `tests/test_config_wiring_phase3.py`, `tests/test_bead_telemetry.py`, `tests/test_merge_safety.py`, `tests/test_telemetry_merge.py`, `tests/test_runner_timeout.py`, `tests/test_model_selection.py`, `tests/test_tui.py`, `tests/test_config_wiring.py`, `tests/test_console.py`

### 7. `CLAUDE.md`

- Title: "Codex Agent Orchestration" → "agent-takt"
- All `uv run orchestrator` commands → `uv run takt`
- All `src/codex_orchestrator/` path references → `src/agent_takt/`
- Remove "Codex" branding from the multi-backend section description

### 8. `README.md`

- Project name/title
- All `uv run orchestrator` → `uv run takt`
- Any "Codex-based" or "Codex Agent" branding

### 9. `docs/` files

Update command examples and path references in:
- `docs/development.md` — `src/codex_orchestrator/` paths, `uv run orchestrator` commands
- `docs/onboarding.md` — `orchestrator init` → `takt init`
- `docs/tui.md` — `uv run orchestrator tui` → `uv run takt tui`
- `docs/multi-backend-agents.md` — `src/codex_orchestrator/runner.py`, `skills.py` path references
- `docs/scheduler-telemetry.md` — any `orchestrator` command examples

### 10. `apm.yml`

```yaml
name: agent-takt
description: APM project for agent-takt
```

### 11. `skills/spec-management/SKILL.md`

Replace all `uv run orchestrator` with `uv run takt` in command examples.

### 12. `.agents/skills/` and `.claude/skills/`

Search for any `uv run orchestrator` references in SKILL.md files and update to `uv run takt`.

---

## Files to Modify

| File/Path | Change |
|---|---|
| `src/codex_orchestrator/` | Rename directory to `src/agent_takt/` |
| `src/codex_agent_orchestration.egg-info/` | Delete (auto-regenerated) |
| `pyproject.toml` | name, description, entry point, package-data key |
| All `src/agent_takt/*.py` | Internal `codex_orchestrator` imports → `agent_takt`; `.orchestrator` path strings → `.takt` |
| `tests/*.py` (15 files) | All `codex_orchestrator` imports → `agent_takt`; any `.orchestrator` path strings → `.takt` |
| `CLAUDE.md` | Title, paths (`src/codex_orchestrator/` → `src/agent_takt/`, `.orchestrator/` → `.takt/`), all `orchestrator` CLI references |
| `README.md` | Title, branding, all `orchestrator` CLI references, `.orchestrator/` → `.takt/` |
| `docs/development.md` | Paths and command examples |
| `docs/onboarding.md` | Command examples, `.orchestrator/` → `.takt/` |
| `docs/tui.md` | Command examples |
| `docs/multi-backend-agents.md` | Path references |
| `docs/scheduler-telemetry.md` | `.orchestrator/telemetry/` → `.takt/telemetry/`, command examples |
| `apm.yml` | name, description |
| `skills/spec-management/SKILL.md` | `uv run orchestrator` → `uv run takt`; `.orchestrator/` → `.takt/` |
| `.agents/skills/**/*.md` | Any `uv run orchestrator` or `.orchestrator/` references |
| `.claude/skills/**/*.md` | Any `uv run orchestrator` or `.orchestrator/` references |

---

## What Does NOT Change

- `.takt/config.yaml` internal structure and keys
- Bead JSON file format and storage schema
- Git branch naming conventions (`feature/b-...`)
- All skill file logic and content (except `uv run orchestrator` and `.orchestrator/` command strings)
- GitHub repository name (out of scope — done separately by the developer via `gh repo rename`)

---

## Acceptance Criteria

- `uv run takt --help` works after install
- `uv run takt summary`, `uv run takt bead list --plain`, `uv run takt run --once` all work
- `from agent_takt.cli import main` imports successfully
- `uv run pytest tests/ -n auto -q` passes with zero import errors
- `pyproject.toml` has `name = "agent-takt"` and entry point `takt = "agent_takt.cli:main"`
- No remaining `codex_orchestrator` references in `src/`, `tests/`, or docs (verified by grep)
- No remaining `uv run orchestrator` in `CLAUDE.md`, `README.md`, or `docs/`
- No remaining `.orchestrator/` path references in source, tests, or docs
- `ORCHESTRATOR_RUNNER` env var still works as a silent fallback (backward compat)
- `AGENT_TAKT_RUNNER` env var takes priority over `ORCHESTRATOR_RUNNER`
- `src/codex_agent_orchestration.egg-info/` is deleted or absent
- `.takt/` directory exists and contains all runtime state (beads, logs, worktrees, etc.)
- A `.orchestrator → .takt` symlink exists in the repo root to ease the transition

---

## Pending Decisions

### 1. GitHub repository name
Renaming `oscarrenalias/codex-agent-orchestration` → `oscarrenalias/agent-takt` on GitHub is a manual step. Out of scope for this spec — do it after merge. GitHub will redirect the old URL automatically.

### 2. PyPI publication
The package is not yet on PyPI. When first published, it will register as `agent-takt`. No migration needed.
