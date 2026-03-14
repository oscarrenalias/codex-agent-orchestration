# TUI Operator Actions

## Objective

Extend the orchestration TUI with operator actions so a human can manage bead flow directly from the dashboard without dropping back to the CLI for common interventions.

The goal is to make the TUI operationally useful once the dashboard exists, while keeping the first action set narrow and aligned with existing orchestrator commands.

## Why This Matters

A read-only dashboard improves visibility, but an operator still has to leave the interface to do routine work such as:

- retrying blocked beads
- creating handoffs
- merging finished work
- updating bead status after inspection

That split weakens the TUI as a control surface. A small set of in-TUI actions makes the dashboard viable for real orchestration without turning it into a full editor.

## Scope

In scope:

- trigger retry for a selected bead from the TUI
- trigger merge for a selected completed bead from the TUI
- create a handoff bead from the selected bead in the TUI
- update a selected bead’s status from the TUI using constrained actions
- show confirmation and error states for those actions

Out of scope:

- free-form editing of arbitrary bead fields
- inline editing of acceptance criteria or descriptions
- bulk multi-select actions
- destructive Git operations beyond the existing merge command
- full workflow automation design beyond existing CLI semantics

## Functional Requirements

### 1. Action Model

The TUI should expose operator actions for the currently selected bead.

Actions should call the existing orchestration service or command behavior rather than reimplementing orchestration logic separately.

The initial action set should include:

- retry bead
- merge bead branch
- create handoff
- mark status using constrained valid transitions

### 2. Retry Action

When a blocked bead is selected, the operator should be able to retry it from the TUI.

Required behavior:

- invoke behavior equivalent to `orchestrator retry <bead_id>`
- clear the block reason and lease as the existing retry flow does
- refresh the dashboard after the action completes
- show success or error feedback in the UI

### 3. Merge Action

When a bead with a mergeable branch is selected, the operator should be able to merge it from the TUI.

Required behavior:

- invoke behavior equivalent to `orchestrator merge <bead_id>`
- only enable the action when the selected bead has a branch name
- show confirmation before merge
- refresh the dashboard after the merge attempt
- show visible success or failure feedback

### 4. Handoff Action

The operator should be able to create a handoff bead from the selected bead.

Required behavior:

- prompt for the target agent type
- prompt for a short summary
- invoke behavior equivalent to `orchestrator handoff <bead_id> --to <agent> --summary <text>`
- refresh the dashboard after creation

Supported handoff targets in v1 should match the built-in agent types already supported by the orchestrator, excluding `scheduler`.

### 5. Status Update Action

The TUI should support constrained status updates for the selected bead.

Required behavior:

- provide a small action menu of valid statuses for manual intervention
- update bead state through the same storage or command-layer behavior as the CLI
- refresh the dashboard after update

The initial version should support only simple intervention statuses already used by the system, such as:

- `ready`
- `blocked`
- `done`

The UI should avoid exposing invalid or confusing transitions when possible.

### 6. Keyboard Shortcuts

The TUI should provide dedicated shortcuts for operator actions.

Suggested defaults:

- `a` open action menu for selected bead
- `t` create handoff for selected bead
- `y` retry selected bead
- `m` merge selected bead
- `u` update selected bead status

Actions that are not valid for the selected bead should be disabled or should show a clear explanation.

### 7. Confirmation and Safety

Potentially consequential actions should require confirmation.

Required confirmations:

- merge
- status update to `done`
- handoff creation

Retry may be single-step if the selected bead is already blocked and the action is low risk.

### 8. UI Feedback

The TUI should have a visible place for action results.

Minimum behavior:

- show transient success and error messages
- keep the last action result visible long enough to read
- include the bead id and action name in failure messages

## Non-Functional Requirements

- keep the action model thin and consistent with existing CLI behavior
- avoid duplicating orchestration state transition logic in the UI
- do not require a background service
- keep operator actions keyboard-first

## Acceptance Criteria

The feature is complete when all of the following are true:

1. The TUI can retry a blocked bead.
2. The TUI can merge a bead branch when merge is applicable.
3. The TUI can create a handoff bead from the selected bead.
4. The TUI can perform constrained status updates for a selected bead.
5. Action availability responds to the selected bead’s current state.
6. The TUI shows clear success and failure feedback for each operator action.
7. Tests cover action dispatch, confirmation behavior, invalid-action handling, and dashboard refresh after mutation.

## Suggested Implementation Notes

- keep the TUI action layer mapped closely to existing CLI command functions or shared service methods
- prefer adding reusable service helpers if the current command functions are too CLI-shaped
- keep prompts and confirmations modal and simple
- avoid inline free-form editing beyond short handoff summary input in v1

## Example Scenario

Given a blocked bead selected in the tree:

- the operator presses `y`
- the bead is retried
- the status updates to `ready`
- the UI refreshes and shows a success message

Given a completed implementation bead with a branch:

- the operator presses `m`
- confirms merge
- the merge runs
- the result is shown in the UI

Given a bead that should move to documentation:

- the operator presses `t`
- selects `documentation`
- enters a short handoff summary
- the new handoff bead appears in the tree after refresh

## Deliverables

- TUI action menu and keyboard shortcuts
- retry, merge, handoff, and constrained status-update actions
- confirmation and feedback UI
- shared action wiring that reuses existing orchestrator behavior
- automated tests covering TUI operator action flows
