---
name: Codebase Refactoring
id: spec-ff6c7a5e
description: Split oversized source modules and their corresponding test files into smaller, focused units. No functional changes — purely structural.
dependencies:
priority: medium
complexity: medium
status: draft
tags: [refactoring, structure]
scope:
  in: tui.py, cli.py, scheduler.py, onboarding.py, test_orchestrator.py, test_tui.py, test_onboarding.py
  out: runner.py, storage.py, models.py, config.py — acceptable size as-is
feature_root_id:
---
# Codebase Refactoring

## Objective

Split oversized source modules and their corresponding test files into smaller, focused units with single clear responsibilities. No functional changes — all behaviour, public APIs, and test outcomes stay identical. Import paths that external callers use are preserved via `__init__.py` re-exports.

## Current State (line counts)

| File | Lines | Problem |
|---|---|---|
| `tui.py` | 2230 | State, rendering, tree-building, actions, and the Textual App class all in one file |
| `cli.py` | 1704 | Argument parsing, all command implementations, formatting helpers, and telemetry in one file |
| `scheduler.py` | 1203 | Core loop, execution, finalisation, followup/corrective logic, and reporter protocol in one file |
| `onboarding.py` | 1182 | Asset installation, upgrade evaluation, config generation, prompt collection, and scaffold in one file |
| `test_orchestrator.py` | 5048 | 257 test methods, 4 test classes, all scheduler/storage/bead behaviour tests |
| `test_tui.py` | 3837 | All TUI tests |
| `test_onboarding.py` | 1628 | All onboarding tests |

## Principles

- **No functional changes.** Tests pass without modification (or with only import path updates).
- **Extract, don't rewrite.** Move code as-is; avoid cleaning up or optimising during the move.
- **Preserve public API.** Existing `from agent_takt.scheduler import Scheduler` style imports continue to work via `__init__.py` re-exports.
- **Tests follow source.** Each new source module gets a corresponding test file. Tests are moved, not rewritten.
- **No circular imports.** New modules within a package must not import from each other in a cycle.

## Proposed Splits

### 1. `tui.py` → `tui/` package (2230 lines, highest priority)

| New module | Responsibility | Approx lines |
|---|---|---|
| `tui/__init__.py` | `run_tui()` entry point, re-exports | ~10 |
| `tui/app.py` | Textual `App` subclass, `compose()`, keybindings, event handlers | ~300 |
| `tui/state.py` | `TuiRuntimeState` — bead state, selection, filter mode, scroll offsets | ~350 |
| `tui/actions.py` | Operator action flows — merge, retry, status update, scheduler cycle | ~300 |
| `tui/render.py` | `render_tree_panel()`, `render_detail_panel()`, `format_detail_panel()`, `format_help_overlay()` | ~400 |
| `tui/tree.py` | `build_tree_rows()`, `TreeRow`, `collect_tree_rows()`, tree navigation helpers | ~250 |

`from agent_takt.tui import run_tui` continues to work unchanged.

**Test split** (`test_tui.py`, 3837 lines):

| New test file | Covers |
|---|---|
| `tests/test_tui_state.py` | `TuiRuntimeState` — selection, filtering, scroll |
| `tests/test_tui_actions.py` | Merge, retry, status update action flows |
| `tests/test_tui_render.py` | Panel rendering, detail formatting, help overlay |
| `tests/test_tui_tree.py` | Tree building, row collection, navigation |
| `tests/test_tui_app.py` | App composition, keybinding dispatch, event handling |

---

### 2. `cli.py` → `cli/` package (1704 lines, high priority)

| New module | Responsibility | Approx lines |
|---|---|---|
| `cli/__init__.py` | `main()` entry point, re-exports | ~20 |
| `cli/parser.py` | `build_parser()`, all `argparse` subparser definitions | ~200 |
| `cli/commands/bead.py` | `command_bead()` — create, show, list, delete, label, graph | ~250 |
| `cli/commands/run.py` | `command_run()`, `CliSchedulerReporter`, `SpinnerPool` wiring | ~150 |
| `cli/commands/merge.py` | `command_merge()`, `_emit_merge_conflict_bead()`, `_get_diff_context()` | ~180 |
| `cli/commands/telemetry.py` | `command_telemetry()`, `aggregate_telemetry()`, `_format_telemetry_table()` | ~250 |
| `cli/commands/init.py` | `command_init()`, `command_upgrade()` | ~270 |
| `cli/commands/misc.py` | `command_plan()`, `command_summary()`, `command_retry()`, `command_handoff()`, `command_tui()`, `command_asset()` | ~200 |
| `cli/formatting.py` | `format_bead_list_plain()`, `format_claims_plain()`, `_plain_value()`, bead formatting helpers | ~100 |
| `cli/services.py` | `make_services()`, `validate_operator_status_update()`, `apply_operator_status_update()` | ~60 |

`from agent_takt.cli import main` continues to work unchanged.

**Test split** (`test_cli_upgrade.py` already exists; `test_orchestrator.py` covers CLI commands):

| New test file | Covers |
|---|---|
| `tests/test_cli_bead.py` | `command_bead` — create, show, list, delete, label, graph |
| `tests/test_cli_run.py` | `command_run`, `CliSchedulerReporter` |
| `tests/test_cli_merge.py` | `command_merge`, conflict bead emission |
| `tests/test_cli_telemetry.py` | `command_telemetry`, `aggregate_telemetry` |

Existing `test_cli_upgrade.py`, `test_cli_init.py`, `test_cli_version.py` remain as-is.

---

### 3. `scheduler.py` → `scheduler/` package (1203 lines, medium priority)

| New module | Responsibility | Approx lines |
|---|---|---|
| `scheduler/__init__.py` | Re-exports `Scheduler`, `SchedulerReporter`, `SchedulerResult` | ~10 |
| `scheduler/core.py` | `Scheduler` class — `run_once()`, bead selection, conflict detection, lease management | ~300 |
| `scheduler/execution.py` | `_process()` — worktree setup, skill isolation, guardrail loading, agent invocation | ~250 |
| `scheduler/finalize.py` | `_finalize()` — state updates, followup/corrective creation, telemetry writes, git commits | ~300 |
| `scheduler/followups.py` | `_create_followup_beads()`, `_populate_shared_followup_touched_files()`, `_sync_followup_scope()` | ~200 |
| `scheduler/reporter.py` | `SchedulerReporter` protocol, `SchedulerResult` dataclass | ~50 |

`from agent_takt.scheduler import Scheduler` continues to work unchanged.

**Test split** (`test_orchestrator.py`, 5048 lines, 257 methods):

| New test file | Covers |
|---|---|
| `tests/test_scheduler_core.py` | `run_once()`, bead selection, conflict detection, lease management |
| `tests/test_scheduler_execution.py` | `_process()` — worktree setup, skill isolation, agent invocation |
| `tests/test_scheduler_finalize.py` | `_finalize()` — state transitions, telemetry, git commits |
| `tests/test_scheduler_followups.py` | Followup/corrective bead creation, scope population, scope sync |
| `tests/test_scheduler_beads.py` | `DeleteBeadTests`, `StructuredHandoffFieldsTests`, `BeadAutoCommitTests` (currently in `test_orchestrator.py`) |

`OrchestratorTests` base class moves to a shared `tests/helpers.py` or `tests/base.py` so all new test files can inherit `FakeRunner` and setup helpers without duplication.

---

### 4. `onboarding.py` → `onboarding/` package (1182 lines, medium priority)

| New module | Responsibility | Approx lines |
|---|---|---|
| `onboarding/__init__.py` | `scaffold_project()` entry point, re-exports | ~20 |
| `onboarding/assets.py` | `copy_asset_file()`, `copy_asset_dir()`, `install_templates()`, `install_agents_skills()`, `install_claude_skills()`, `install_default_config()` | ~200 |
| `onboarding/upgrade.py` | `evaluate_upgrade_actions()`, `_compute_bundled_catalog()`, `AssetDecision`, manifest read/write | ~300 |
| `onboarding/config.py` | `generate_config_yaml()`, `merge_config_keys()`, `substitute_template_placeholders()` | ~100 |
| `onboarding/prompts.py` | `collect_init_answers()`, `_prompt()`, `InitAnswers` | ~130 |
| `onboarding/scaffold.py` | `seed_memory_files()`, `update_gitignore()`, `create_specs_howto()`, `commit_scaffold()` | ~200 |

`from agent_takt.onboarding import scaffold_project` continues to work unchanged.

**Test split** (`test_onboarding.py`, 1628 lines):

| New test file | Covers |
|---|---|
| `tests/test_onboarding_assets.py` | Asset installation functions |
| `tests/test_onboarding_upgrade.py` | Upgrade evaluation, manifest, `AssetDecision` |
| `tests/test_onboarding_config.py` | Config generation, key merging, template substitution |
| `tests/test_onboarding_scaffold.py` | Memory seeding, gitignore, commit scaffold |

---

## Execution Order

1. `scheduler.py` first — clearest module boundaries, most test coverage to validate nothing breaks
2. `onboarding.py` second — self-contained, no dependencies on other large modules
3. `cli.py` third — depends on scheduler and other modules being stable
4. `tui.py` last — most complex, largest test file, highest risk

Each phase is its own feature root bead with developer → tester → reviewer pipeline.

## Files to Modify

| Action | Files |
|---|---|
| Replace with package | `src/agent_takt/tui.py` → `src/agent_takt/tui/` |
| Replace with package | `src/agent_takt/cli.py` → `src/agent_takt/cli/` |
| Replace with package | `src/agent_takt/scheduler.py` → `src/agent_takt/scheduler/` |
| Replace with package | `src/agent_takt/onboarding.py` → `src/agent_takt/onboarding/` |
| Split | `tests/test_orchestrator.py` → multiple `tests/test_scheduler_*.py` + `tests/test_cli_*.py` |
| Split | `tests/test_tui.py` → multiple `tests/test_tui_*.py` |
| Split | `tests/test_onboarding.py` → multiple `tests/test_onboarding_*.py` |
| New | `tests/helpers.py` — shared `FakeRunner`, `OrchestratorTests` base class |

## Acceptance Criteria

- All existing tests pass after each phase with no functional changes
- `from agent_takt.scheduler import Scheduler`, `from agent_takt.cli import main`, `from agent_takt.tui import run_tui`, `from agent_takt.onboarding import scaffold_project` all continue to work via `__init__.py` re-exports
- No module exceeds 500 lines after refactoring
- No test file exceeds 600 lines after refactoring
- No circular imports within any new package
- Each new module has a single identifiable responsibility
- `uv run pytest tests/ -n auto -q` passes in full after each phase

## Pending Decisions

- **`test_orchestrator.py` base class**: extract `OrchestratorTests` + `FakeRunner` to `tests/helpers.py` shared by all scheduler/CLI test files. Confirm this is the right approach before implementation.
