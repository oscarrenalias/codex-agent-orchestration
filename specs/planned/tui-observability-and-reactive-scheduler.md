---
name: "Reactive Scheduler: Continuous Slot Fill and Deferral Logging"
id: spec-f4a943a4
description: Reactive continuous slot-fill scheduler and deferral reason logging — no TUI changes
dependencies: null
priority: null
complexity: null
status: planned
tags: []
scope:
  in: null
  out: null
feature_root_id: null
---
# Reactive Scheduler: Continuous Slot Fill and Deferral Logging

## Objective

The scheduler currently operates in batch mode: `run_once()` dispatches a snapshot of ready beads into a `ThreadPoolExecutor`, then waits for all of them to finish before returning. New beads that become ready mid-execution (correctives created, dependencies completing) are not picked up until the next call — which may be 10+ minutes away if long-running agents are active. This spec replaces the batch model with a continuous slot-fill model and adds structured deferral logging. Both changes benefit the CLI `run` command and the TUI equally — no TUI rendering changes are included here.

## Problems to Fix

### 1. Scheduler cycle blocks on running agents

`run_once()` dispatches a snapshot of ready beads, then blocks until all of them complete. New ready beads that appear mid-cycle (corrective created, dependency finished) wait until the next call. With long-running agents (tester, docs), this means idle worker slots for the full agent duration.

### 2. Deferred beads have no structured reason

When the scheduler defers a bead (file conflict, worktree in use, dependency not satisfied), the deferral reason is visible in the CLI output but is not passed through `SchedulerReporter` in a structured way. The TUI's scheduler log just shows a bare deferral count, not which bead was deferred or why.

### 3. Scheduler log noise from empty cycles

When the TUI auto-runs the scheduler on a tick interval, cycles that dispatch nothing still emit "Scheduler cycle starting…" log lines, creating noise without useful signal.

---

## Changes

### 1. Continuous slot-fill inside `run_once()`

**File: `src/agent_takt/scheduler/core.py`**

Replace the current pattern (dispatch snapshot → wait for all) with a fill loop:

```python
# Pseudocode — implementation may vary
with ThreadPoolExecutor(max_workers=max_workers) as pool:
    futures: dict[Future, Bead] = {}
    while True:
        # Fill free slots
        free_slots = max_workers - len(futures)
        if free_slots > 0:
            candidates = self._pick_ready_beads(exclude={b.bead_id for b in futures.values()})
            for bead in candidates[:free_slots]:
                futures[pool.submit(self._run_bead, bead)] = bead
        if not futures:
            break  # nothing running, nothing left to dispatch
        # Wait for at least one to finish
        done, _ = wait(futures, return_when=FIRST_COMPLETED)
        for f in done:
            bead = futures.pop(f)
            self._finalize(bead, f.result())
```

Key properties:
- Free slots are filled immediately when a worker completes, not at the next `run_once()` call
- `_pick_ready_beads()` re-evaluates the full ready set each iteration (picks up correctives, unblocked dependencies)
- The loop exits only when no workers are active and no ready beads remain
- `--once` semantics are preserved: `run_once()` still returns after one pass; the outer CLI loop calls it in a `while True` with a sleep — the reactive fill means that loop rarely needs to do more than one call per "burst"

**Note on `run_once()` vs `run_continuous()`**: the simplest approach is to modify `run_once()` in place so the existing CLI loop and TUI call sites work unchanged. A `run_continuous()` alternative may be introduced only if the existing call sites need to remain strictly single-pass.

### 2. Structured deferral reporting via `SchedulerReporter`

**File: `src/agent_takt/scheduler/reporter.py`**

Add a `bead_deferred(bead, reason)` method to `SchedulerReporter`:

```python
def bead_deferred(self, bead: Bead, reason: str) -> None:
    """Called when a ready bead is skipped this cycle with a specific reason."""
```

**File: `src/agent_takt/scheduler/core.py`**

Wherever a bead is deferred (conflict check, worktree check, dependency check), call `reporter.bead_deferred(bead, reason)` with a human-readable reason string, e.g.:
- `"file conflict with in-progress B-09ea66ab (src/agent_takt/tui/app.py)"`
- `"dependency B-a0302285 not done"`
- `"worktree in use"`

**File: `src/agent_takt/cli/commands/run.py`** (`CliSchedulerReporter`)

Implement `bead_deferred()` to emit a detail line when `--verbose` is set, and suppress it otherwise (deferral noise on every cycle is unhelpful by default).

**File: `src/agent_takt/tui/app.py`** (`TuiSchedulerReporter`)

Implement `bead_deferred()` to append a log line to the TUI scheduler panel:
```
[10:23:41] Deferred B-5441fde0: file conflict with in-progress B-09ea66ab
```

### 3. Suppress empty-cycle log noise

**File: `src/agent_takt/tui/app.py`** (`TuiSchedulerReporter`)

Only emit "Scheduler cycle starting…" (or equivalent) when the cycle actually dispatches or defers at least one bead. If nothing changed, log nothing.

---

## Files to Modify

| File | Change |
|---|---|
| `src/agent_takt/scheduler/core.py` | Replace batch dispatch with continuous slot-fill loop |
| `src/agent_takt/scheduler/reporter.py` | Add `bead_deferred(bead, reason)` to `SchedulerReporter` ABC |
| `src/agent_takt/cli/commands/run.py` | Implement `bead_deferred()` in `CliSchedulerReporter` |
| `src/agent_takt/tui/app.py` | Implement `bead_deferred()` in `TuiSchedulerReporter`; suppress empty-cycle noise |
| `tests/test_scheduler_core.py` | Tests for slot-fill-on-completion: verify new beads are picked up mid-cycle |
| `tests/test_scheduler_execution.py` | Tests for deferral reason strings |
| `tests/test_cli_run.py` | Tests for `bead_deferred` suppression in non-verbose mode |

---

## Acceptance Criteria

- When a worker slot frees up mid-cycle, the next ready bead is dispatched within the same `run_once()` call without waiting for the remaining running agents to finish
- New ready beads created mid-cycle (correctives, unblocked dependencies) are picked up in the same fill pass, not delayed to the next call
- `SchedulerReporter` has a `bead_deferred(bead, reason)` method; all existing reporter implementations provide it
- Every scheduler deferral calls `reporter.bead_deferred(bead, reason)` with a non-empty reason string
- CLI `run` (non-verbose): deferral events are not printed by default
- TUI scheduler log: deferred beads appear as `Deferred B-xxxxx: <reason>` log lines
- TUI scheduler log: no "cycle starting" noise when nothing was dispatched or deferred
- All existing scheduler and CLI tests pass

---

## Pending Decisions

### 1. `run_once()` in-place vs new `run_continuous()`
Modifying `run_once()` in place is simplest and keeps all call sites unchanged. A separate method would let callers choose. **Leans toward in-place — the batch behaviour was never intentionally exposed as an API contract.**

### 2. Deferral verbosity threshold for CLI
Log deferred beads only with `--verbose`, or always? Deferral on every cycle for the same bead would be noisy (e.g. a blocked bead deferred 20 times). **Leans toward suppressed by default, enabled with `--verbose`.**
