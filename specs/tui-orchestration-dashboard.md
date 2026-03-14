# TUI Orchestration Dashboard

## Objective

Add a terminal UI for the orchestration system so an operator can load a spec, inspect bead state, monitor active agents, and follow the bead tree without leaving the terminal.

The TUI should provide a lightweight control and visibility layer on top of the existing repository-backed orchestrator.

## Why This Matters

The current CLI is functional, but it is optimized for individual commands rather than active orchestration.

That makes it harder to:

- load a new spec and immediately see the resulting bead graph
- understand which beads are pending, in progress, blocked, or done at a glance
- correlate active agents with the bead tree and current work
- monitor orchestration without repeatedly running separate CLI commands

A TUI is the next natural operator interface for a self-hosted orchestrator because it improves visibility without changing the core execution model.

## Scope

In scope:

- add a new TUI entrypoint for the orchestrator
- support keyboard shortcuts for loading a spec from the filesystem
- show pending, in-progress, blocked, and done beads
- show active agent status linked to the current bead view
- provide a tree-like bead view rooted at the epic or parent bead structure
- refresh from repository-backed state without requiring a background server

Out of scope:

- multi-user collaboration
- remote orchestration over the network
- editing bead contents inline in v1
- merge conflict resolution UI
- graphical UI outside the terminal

## Functional Requirements

### 1. New TUI Entry Point

The application should expose a dedicated TUI command.

Recommended command:

- `orchestrator tui`

The TUI should start in the current repository root and read state from:

- `.orchestrator/beads/`
- `.orchestrator/logs/events.jsonl`
- `.orchestrator/worktrees/`

### 2. Spec Loading Workflow

The TUI should support loading a spec through a keyboard shortcut.

Required behavior:

- provide a shortcut to open a file-picker style flow rooted in the repository
- allow folder navigation and spec file selection from the terminal
- after selection, invoke the existing planning workflow equivalent to `orchestrator plan <spec> --write`
- refresh the bead views after planning completes

The initial version does not need a fuzzy finder if a simple navigable file browser is easier to build and test.

### 3. Bead Status Panels

The TUI should show bead lists grouped by status.

Minimum required groupings:

- pending or ready beads
- in-progress beads
- blocked beads
- done beads

The UI may use either separate panels or a single filterable list, but the default layout should make pending and in-progress work immediately visible.

### 4. Tree View

The TUI should provide a tree-like bead view that reflects parent-child relationships.

Required behavior:

- show epics and child beads in hierarchy order
- show bead id, title, agent type, and status in the tree
- allow keyboard navigation through the tree
- selecting a bead in the tree should update the detail pane

This tree is the primary operator view and should remain synchronized with the status panels.

### 5. Bead Detail Pane

When a bead is selected, the TUI should show key bead details.

Minimum fields:

- bead id
- title
- agent type
- status
- dependencies
- block reason
- expected files / globs / touched files
- conflict risks
- latest handoff summary

The detail pane should be read-only in v1.

### 6. Active Agent View

The TUI should show which agents are currently active and which bead each one is working on.

This view should be connected to the selected bead when possible.

Minimum behavior:

- list active in-progress beads with lease owner
- show the active agent type
- indicate the linked bead id and title
- if the selected bead is active, highlight or otherwise make that relationship obvious

The implementation may derive this from in-progress bead state rather than introducing a new runtime agent registry.

### 7. Keyboard Shortcuts

The TUI should support a small, stable shortcut set.

Required shortcuts:

- one shortcut to load a spec from the filesystem
- one shortcut to refresh state
- one shortcut to switch focus between tree/list/detail panes
- one shortcut to trigger a single scheduler run equivalent to `orchestrator run --once`
- one shortcut to quit

Suggested defaults:

- `l` load spec
- `r` refresh
- `tab` cycle focus
- `s` scheduler run once
- `q` quit

Arrow keys or `j`/`k` may be used for navigation.

### 8. Refresh Model

The TUI should not require a daemon or socket service.

The dashboard should refresh by re-reading repository-backed state on demand and optionally on a short polling interval.

Recommended default:

- manual refresh always available
- lightweight auto-refresh every 2 seconds while the TUI is open

### 9. Error Handling

The TUI should degrade safely when operations fail.

Required behavior:

- show a visible error message if planning fails
- show a visible error message if scheduler run fails
- handle missing `.orchestrator/` directories by showing an empty-state message rather than crashing
- handle invalid spec path selection gracefully

## Non-Functional Requirements

- remain terminal-only and cross-platform within the current Python target
- reuse existing CLI or service-layer logic where practical instead of duplicating orchestration behavior
- keep the first version read-heavy and operationally simple
- avoid introducing a persistent background process

## Acceptance Criteria

The feature is complete when all of the following are true:

1. Running `orchestrator tui` opens a terminal UI for the current repository.
2. The TUI can load a spec via keyboard-driven file selection and write the resulting bead plan.
3. The operator can see pending, in-progress, blocked, and done beads.
4. The operator can navigate a tree-like bead hierarchy and inspect bead details.
5. The TUI shows active agent status connected to bead state.
6. The operator can trigger a single scheduler cycle from the TUI.
7. Tests cover state loading, tree shaping, shortcut actions, and failure handling for plan/run actions.

## Suggested Implementation Notes

- use a lightweight Python terminal UI library rather than building raw terminal control by hand
- keep the TUI as a thin layer over existing storage, planner, and scheduler services
- model the UI state separately from repository state so refreshes are simple and deterministic
- prefer a simple file-browser modal over a complex fuzzy finder in v1
- keep actions equivalent to existing CLI commands rather than inventing separate orchestration logic

## Example Scenario

Given a repository with existing bead state:

- the operator launches `orchestrator tui`
- the left pane shows the bead tree
- another pane shows pending and in-progress counts or lists
- the detail pane shows the selected bead’s status, scope, dependencies, and handoff summary

Given no current plan:

- the operator presses `l`
- navigates folders and selects `specs/specialized-agent-guardrails.md`
- the TUI writes the plan and refreshes to show the new epic and children

Given active worker execution:

- the operator presses `s` to run one scheduler cycle
- the in-progress pane updates
- the selected bead detail reflects the current agent and status

## Deliverables

- new `orchestrator tui` command
- terminal UI with bead tree, status views, active agent view, and bead detail pane
- keyboard-driven spec loading and scheduler-run actions
- refreshable state reading from existing repository-backed storage
- automated tests for TUI state and action behavior
