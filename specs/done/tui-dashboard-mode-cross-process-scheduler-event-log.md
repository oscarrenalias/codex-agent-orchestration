---
name: "TUI dashboard mode: cross-process scheduler event log"
id: spec-cb04e3ba
description: Make the TUI a pure monitoring dashboard driven by events.jsonl; remove its scheduling capabilities; enrich CLI event payloads for full observability.
dependencies: null
priority: medium
complexity: medium
status: done
tags:
- tui
- scheduler
- observability
scope:
  in: "Enriching events.jsonl payloads, writing scheduler events from CliSchedulerReporter, TUI log panel tailing events.jsonl, removing TUI scheduling capabilities, always-on refresh, bead status icons"
  out: "Real-time streaming via sockets or named pipes, changes to bead storage format, changes to scheduler execution logic, TuiSchedulerReporter event-log writes"
feature_root_id: null
---
# TUI dashboard mode: cross-process scheduler event log

## Objective

The TUI currently has a dual role: it can both run the scheduler itself and display its output. This conflation makes it a poor monitoring tool — when `takt run` executes in a separate terminal, the TUI log panel stays completely silent because it only sees events from cycles it started itself. The fix is to make the TUI a **pure dashboard**: remove its scheduling capabilities entirely, enrich `events.jsonl` with full context payloads written by `CliSchedulerReporter`, and have the TUI tail that file to populate the log panel. Scheduling is always the CLI's job; the TUI observes, surfaces state, and lets the operator intervene (retry, status update, merge) — but never starts a cycle.

## Problems to Fix

1. **Log panel is blind to CLI runs.** `CliSchedulerReporter` writes only to console spinners. When `takt run` is running in another terminal, the TUI log panel receives zero updates.
2. **`events.jsonl` payloads are too thin.** The file currently only captures `bead_completed` (with `bead_id` and `agent_type`) and `bead_deleted`. Contextual strings — agent handoff summaries, worktree paths, deferral reasons, error text — are printed to stdout and then discarded.
3. **Some scheduler lifecycle events are not recorded at all.** `bead_started`, `bead_blocked`, `bead_failed`, `bead_deferred`, `worktree_ready`, and `lease_expired` are never written to `events.jsonl`.
4. **The TUI has scheduling capabilities that conflict with its dashboard role.** The `s`/`S` keybindings trigger scheduler cycles inside the TUI process, and a timed auto-scheduler can fire concurrently with an external `takt run`. These create race conditions and muddy the separation of concerns.
5. **Auto-refresh is opt-in, which makes no sense for a dashboard.** The `a` keybinding toggles timed refresh on/off. Since the TUI's only job is to reflect current state, there is no scenario where a operator would want the display to stop updating. The toggle was meaningful when `a` also controlled scheduler cycles; with scheduling removed it is vestigial and adds confusion.
6. **Bead status is not scannable at a glance.** The bead tree shows titles but no visual status indicator. In an "All" view with many beads, the operator cannot quickly identify which are blocked, in-progress, or done without reading each row carefully.

## Changes

### 1. Remove TUI scheduling capabilities

- Remove the `s` / `S` keybindings and their `action_scheduler_once` / `action_scheduler_toggle` handlers from `tui/app.py`.
- Remove `run_scheduler_cycle()` from `tui/actions.py`.
- Remove the timed auto-scheduler logic from `TuiRuntimeState` (the periodic `run_scheduler_cycle` timer).
- Remove `TuiSchedulerReporter` from `tui/reporter.py` — it is no longer needed. The log panel is now driven entirely by `events.jsonl` tailing.
- Update the TUI help overlay and any keybinding documentation to reflect the removed actions.

The TUI retains all other operator actions: retry, status update, merge, bead detail view.

### 2. Always-on refresh

- Remove the `a` keybinding and `action_toggle_timed_refresh` / `toggle_timed_refresh()` from `tui/app.py` and `tui/actions.py`.
- Remove the `timed_refresh_enabled: bool` field from `TuiRuntimeState`.
- Change `_on_interval_tick` to call `state.refresh()` unconditionally — no guard on `timed_refresh_enabled`.
- The `r` keybinding for manual refresh is retained (useful when the operator wants an immediate update rather than waiting for the next tick).
- Update the status bar and help overlay to remove references to the auto-refresh toggle.

### 3. Enrich `events.jsonl` event payloads

Extend `CliSchedulerReporter` to call `storage.record_event(event_type, payload)` on each callback, in addition to the existing console output. `CliSchedulerReporter.__init__` must accept `storage: RepositoryStorage`.

New and updated event types written by `CliSchedulerReporter` and `command_run`:

| `event_type` | Payload fields |
|---|---|
| `bead_started` | `bead_id`, `agent_type`, `title` |
| `bead_completed` | `bead_id`, `agent_type`, `summary`, `created_bead_ids: list[str]` |
| `bead_blocked` | `bead_id`, `agent_type`, `summary` |
| `bead_failed` | `bead_id`, `agent_type`, `summary` |
| `bead_deferred` | `bead_id`, `agent_type`, `reason` |
| `worktree_ready` | `bead_id`, `branch_name`, `worktree_path` |
| `lease_expired` | `bead_id` |
| `scheduler_cycle_started` | `max_workers`, `feature_root_id` (nullable), `pid` |
| `scheduler_cycle_completed` | `started_count`, `completed_count`, `blocked_count`, `deferred_count`, `pid` |

All new fields are optional so old log consumers aren't broken.

The `SchedulerReporter` protocol in `scheduler/reporter.py` already defines all required callback methods — no new method signatures are needed. The mapping from existing callbacks to new event types is:

| `SchedulerReporter` method | `record_event` call to add |
|---|---|
| `bead_started(bead)` | `bead_started` with `bead_id`, `agent_type`, `title` |
| `worktree_ready(bead, branch_name, worktree_path)` | `worktree_ready` with `bead_id`, `branch_name`, `worktree_path` |
| `bead_completed(bead, summary, created)` | `bead_completed` with `bead_id`, `agent_type`, `summary`, `created_bead_ids` |
| `bead_blocked(bead, summary)` | `bead_blocked` with `bead_id`, `agent_type`, `summary` |
| `bead_failed(bead, summary)` | `bead_failed` with `bead_id`, `agent_type`, `summary` |
| `bead_deferred(bead, reason)` | `bead_deferred` with `bead_id`, `agent_type`, `reason` |
| `lease_expired(bead_id)` | `lease_expired` with `bead_id` |

`CliSchedulerReporter` in `cli/commands/run.py` implements this protocol. Each method body gains one `self.storage.record_event(event_type, payload)` call alongside its existing console output. `CliSchedulerReporter.__init__` gains a `storage: RepositoryStorage` parameter. `scheduler_cycle_started` and `scheduler_cycle_completed` are emitted directly in `command_run` before and after the scheduler loop, not via reporter callbacks.

Also remove the duplicate direct `record_event("bead_completed", ...)` calls in `scheduler/finalize.py` (lines 183, 294–297, 377–380) — these are now handled by the reporter.

### 4. TUI tails `events.jsonl` for the log panel

Add `_tail_event_log()` to `TuiRuntimeState`:
- Track `_event_log_offset: int` (byte offset into `events.jsonl`, initialised to current file size on TUI start so only new events are shown by default).
- On each `refresh()` call, open `events.jsonl`, seek to `_event_log_offset`, read new lines, advance offset.
- Convert each new JSON line to a human-readable log string using a `_format_event(record) -> str | None` helper (returns `None` for unknown or suppressed event types, which are silently skipped).
- Feed the formatted strings to the log panel via `self._app._append_log_line(line)` — this method is defined in `tui/app.py:654` and is unaffected by the removal of `TuiSchedulerReporter` (its only callers are in `tui/reporter.py`, which is deleted; the method itself stays).

The TUI refresh interval is 3 seconds (configurable via `--refresh-seconds`, default 3). `_tail_event_log()` is called on every `refresh()` tick — no change to the interval is required to satisfy the ≤ 3 s acceptance criterion.

`_format_event` must handle all event types explicitly. The full mapping:

All format strings follow the same field ordering: timestamp, then `bead_id`, then event-specific context. `agent_type` appears inline where it adds meaning but always after `bead_id`. Each visible event is rendered with Rich colour markup applied to the entire line.

| `event_type` | Output | Colour | Visible in TUI |
|---|---|---|---|
| `bead_started` | `[HH:MM:SS] {bead_id} ({agent_type}) · "{title}" started` | dim white | yes |
| `bead_completed` | `[HH:MM:SS] {bead_id} completed — {summary}` | green | yes |
| `bead_blocked` | `[HH:MM:SS] {bead_id} blocked — {summary}` | red | yes |
| `bead_failed` | `[HH:MM:SS] {bead_id} failed — {summary}` | bold red | yes |
| `bead_deferred` | `[HH:MM:SS] {bead_id} deferred — {reason}` | yellow | yes |
| `worktree_ready` | `[HH:MM:SS] {bead_id} worktree {worktree_path} on {branch_name}` | dim white | yes |
| `lease_expired` | `[HH:MM:SS] {bead_id} lease expired` | yellow | yes |
| `bead_deleted` | `None` | — | no |
| `scheduler_cycle_started` | `None` | — | no |
| `scheduler_cycle_completed` | `None` | — | no |
| unknown / unrecognised | `None` | — | no |

`bead_blocked` and `bead_failed` are intentionally distinguished: blocked (red) means the agent gave up after retries and needs operator attention; failed (bold red) means an unexpected exception — higher urgency. `bead_deferred` and `lease_expired` use yellow as a soft warning — transient, not yet requiring intervention.

### 5. On-demand history loading

Track `_history_offset: int` alongside `_event_log_offset`. On TUI start both are initialised to the current EOF position.

Add `load_event_log_history(n_lines: int) -> int` to `TuiRuntimeState`:
- Reads backwards from `_history_offset` in fixed 8 KB chunks, accumulating complete lines until `n_lines` displayable (non-`None` from `_format_event`) lines have been collected or the start of the file is reached.
- Chunk boundaries may fall mid-line: carry any partial line (bytes before the first newline in a chunk) forward to be prepended to the next (earlier) chunk before splitting on newlines.
- Prepends the collected lines to the log panel (so they appear above existing content).
- Updates `_history_offset` to the byte position of the earliest line consumed.
- Returns the number of lines actually loaded (0 means no more history).

Expose this as a TUI action bound to `H` (shift-H): load 50 historical lines per press. When `_history_offset` reaches 0 and a further `H` press yields 0 lines, show a one-time dim message in the log panel: `── beginning of event log ──`.

### 6. Bead status icons in the tree panel

Add a `_status_icon(status: str) -> str` helper in `tui/tree.py` that maps each bead status to a single Unicode character. Prepend the icon to each bead row label when building tree rows in `build_tree_rows`.

| Status | Icon | Colour (Rich markup) |
|---|---|---|
| `open` | `○` | dim |
| `ready` | `◎` | blue |
| `in_progress` | `●` | yellow |
| `done` | `✓` | green |
| `blocked` | `✗` | red |
| `handed_off` | `→` | dim |

Icons are rendered using Rich colour markup so they remain distinguishable without relying on colour alone (the character shape itself carries the meaning). Because `build_tree_rows` is called on every `refresh()`, icons always reflect the latest status with no additional wiring.

## Known Limitations

**Agent intermediate output is not visible.** Both runners (`ClaudeCodeAgentRunner`, `CodexAgentRunner`) use `subprocess.run(..., capture_output=True)`, which captures the agent's raw output stream in memory and discards it after parsing the structured result. Tool calls, file reads, reasoning steps, and intermediate progress generated by the agent while a bead is running are not persisted anywhere and will not appear in the TUI log panel. The log panel shows only lifecycle milestones: `started`, `worktree_ready`, and `completed`/`blocked`/`failed` with the agent's final structured `summary`. The gap between `started` and the terminal event is silent in the log — the `●` status icon in the bead tree indicates the bead is running, but no finer-grained progress is surfaced. Making intermediate output visible would require the runner to stream or persist output incrementally (e.g. writing a live log to `.takt/agent-runs/<bead_id>/stdout.txt` during execution), which is out of scope for this spec.

## Files to Modify

| File | Change |
|---|---|
| `src/agent_takt/storage.py` | No signature change to `record_event`; payloads enriched by callers |
| `src/agent_takt/scheduler/finalize.py` | Remove direct `record_event("bead_completed", ...)` calls (now reporter's responsibility) |
| `src/agent_takt/cli/commands/run.py` | Pass `storage` to `CliSchedulerReporter`; emit `scheduler_cycle_started` / `scheduler_cycle_completed` |
| `src/agent_takt/cli/__init__.py` | Pass `storage` through to `CliSchedulerReporter` construction |
| `src/agent_takt/tui/reporter.py` | Remove `TuiSchedulerReporter` entirely |
| `src/agent_takt/tui/actions.py` | Remove `run_scheduler_cycle()`, timed auto-scheduler logic, and `toggle_timed_refresh()` |
| `src/agent_takt/tui/state.py` | Add `_event_log_offset`, `_history_offset`, `_tail_event_log()`, `_format_event()`, `load_event_log_history()`; call `_tail_event_log()` in `refresh()`; remove scheduler-running state; remove `timed_refresh_enabled` field |
| `src/agent_takt/tui/app.py` | Remove `s`/`S` and `a` keybindings and their actions; make `_on_interval_tick` unconditional; remove `TuiSchedulerReporter` usage; bind `H` to `load_event_log_history(50)`; update status bar and help overlay |
| `src/agent_takt/tui/tree.py` | Add `_status_icon(status)` helper; prepend icon to each bead row label in `build_tree_rows` |

## Acceptance Criteria

- When `takt run` is executing in a separate terminal, the TUI log panel shows `bead_started`, `bead_completed`, `bead_blocked`, and `bead_failed` entries within one refresh cycle (≤ 3 seconds at the default refresh interval; sooner if `--refresh-seconds` is lower).
- Worktree path and branch are visible in the log panel for each started bead, sourced from `events.jsonl`.
- Agent handoff summaries appear in `bead_completed` log entries in the TUI, sourced from `events.jsonl`.
- Old events already in `events.jsonl` before the TUI opens are not replayed into the log panel (offset initialised to current EOF).
- The TUI has no `s` / `S` keybindings and cannot trigger a scheduler cycle in any way.
- The timed auto-scheduler no longer fires inside the TUI process.
- `TuiSchedulerReporter` is deleted; no references to it remain.
- The `a` keybinding is removed; the bead tree refreshes automatically on every tick without any toggle.
- `timed_refresh_enabled` is removed from `TuiRuntimeState`; `_on_interval_tick` calls `refresh()` unconditionally.
- The `r` keybinding for immediate manual refresh is retained.
- Each bead row in the tree panel is prefixed with a status icon (`○` `◎` `●` `✓` `✗` `→`) coloured with Rich markup.
- Status icons update on every refresh cycle — a bead transitioning from `in_progress` to `done` shows `✓` within one refresh tick.
- Existing `bead_deleted` audit events in `events.jsonl` are unaffected.
- `scheduler_cycle_started` and `scheduler_cycle_completed` entries are present in `events.jsonl` after a `takt run` but never appear in the TUI log panel.
- Pressing `H` in the TUI log panel prepends up to 50 historical lines (formatted via `_format_event`) without loading the entire file into memory.
- Pressing `H` repeatedly loads progressively older history in 50-line pages.
- When the start of the file is reached, the panel shows `── beginning of event log ──` and further `H` presses are no-ops.
- All existing tests pass. New unit tests cover: `_format_event` for every event type in the mapping table above (visible events produce the correct format string; suppressed events return `None`); `_tail_event_log` advancing the offset correctly across multiple calls; `load_event_log_history` with multi-chunk backwards reads and partial-history files.

## Pending Decisions

- ~~Should `scheduler_cycle_started` / `scheduler_cycle_completed` events be displayed in the TUI log panel, or filtered out (too noisy for normal use)?~~ Resolved: write to `events.jsonl` for audit purposes, but `_format_event` returns `None` for both — never shown in the TUI.
- ~~Should the TUI offer a way to scroll back through historical events from before the current session (opt-in "load history" action), or is start-at-EOF always correct?~~ Resolved: lazy reverse-read via `H` keybinding, 50 lines per press, chunked 8 KB reads backwards — no full-file load.
- ~~Should the TUI be a pure dashboard or retain scheduling capabilities?~~ Resolved: pure dashboard. Scheduling is the CLI's responsibility. TUI scheduling capabilities (`s`/`S` keybindings, `run_scheduler_cycle`, timed auto-scheduler, `TuiSchedulerReporter`) are removed entirely.
- ~~Should auto-refresh be opt-in (toggle) or always-on?~~ Resolved: always-on. No scenario exists where a dashboard operator would want the display to stop updating. The `a` toggle is removed; refresh fires unconditionally on every interval tick.
