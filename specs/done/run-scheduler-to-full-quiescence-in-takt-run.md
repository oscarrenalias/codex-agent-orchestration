---
name: Run scheduler to full quiescence in takt run
id: spec-4176a29d
description: "Make `takt run` actually run to quiescence as documented, instead of executing a single cycle and exiting with ready beads still pending"
dependencies: null
priority: medium
complexity: low
status: done
tags:
- scheduler
- cli
- ux
scope:
  in: null
  out: null
feature_root_id: B-53425f62
---
# Run scheduler to full quiescence in takt run

## Objective

The `takt run` command is documented as "run all beads to quiescence" (CLAUDE.md Quick Reference, line 9: `uv run takt --runner claude run                   # run all beads to quiescence with Claude Code`). The implementation does not match the documentation: `command_run` in `src/agent_takt/cli/commands/run.py` calls `scheduler.run_once()` exactly once and returns. There is no outer loop.

This causes a real operator UX problem when a tester bead is blocked mid-cycle and a corrective developer bead is auto-spawned to fix it. The cycle proceeds:

1. Tester runs, blocks, gets added to `started_this_cycle` (`core.py:157, 183`).
2. Corrective is dispatched mid-cycle by the slot-fill loop (works correctly).
3. Corrective completes; `_reevaluate_blocked` (`core.py:167`) flips the tester from `blocked` back to `ready`.
4. Next slot-fill pass: the tester is `ready` but its ID is in `started_this_cycle`, so `_select_beads_for_dispatch` skips it.
5. The review depends on the tester, so it can't dispatch either.
6. `if not futures: break` (`core.py:187-188`) → cycle ends → CLI exits.

The operator must manually re-invoke `takt run` to drain the unblocked tester and the dependent review. This was observed end-to-end in the session that produced spec-1b99116b: scheduler exited with `final_state: 5 done, 2 ready`, requiring a second `takt run` invocation to complete the feature.

The fix is to wrap the existing single-cycle dispatch in an outer loop that re-invokes `run_once()` until a cycle dispatches no beads (true quiescence). The `started_this_cycle` set is per-cycle, so it resets between iterations and the unblocked tester is picked up cleanly on the next outer iteration.

## Problems to Fix

1. **`command_run` calls `run_once()` exactly once.** `src/agent_takt/cli/commands/run.py:119-124` invokes `scheduler.run_once(...)` a single time and returns. There is no loop; the function name "run" and the documented behaviour ("run all beads to quiescence") imply otherwise.

2. **Beads that are unblocked mid-cycle by a corrective cannot run in the same cycle.** The `started_this_cycle` guard in `core.py:157` correctly prevents some edge-case infinite loops but has the side effect that any bead which already ran (and possibly blocked) cannot be re-dispatched even after `_reevaluate_blocked` requeues it. This guard is per-cycle, so the simplest fix is to start a new cycle.

3. **Operator must manually re-invoke `takt run`.** Until the operator runs `takt run` again, the feature tree sits in a partially-completed state with no outward signal. In autonomous flows (CI, scheduled cron, agent-driven orchestration) this manifests as a stalled feature tree.

4. **Documentation overstates current behaviour.** `CLAUDE.md` line 9 needs to either match a fixed implementation or be corrected to reflect single-cycle behaviour. The right move is to fix the implementation.

## Changes

### 1. Wrap dispatch in a quiescence loop in `command_run`

Modify `src/agent_takt/cli/commands/run.py:119-135` so the call to `scheduler.run_once()` runs inside a `while True:` loop that exits when a cycle dispatches zero beads. Accumulator dicts (`started`, `completed`, `blocked`, `correctives_created`) and `deferred_count` already exist (lines 99-103) and are designed to be merged across calls — this change just feeds multiple results into them.

Pseudocode:

```python
try:
    cycle_index = 0
    while True:
        cycle_index += 1
        result = scheduler.run_once(
            max_workers=args.max_workers,
            feature_root_id=feature_root_id,
            reporter=reporter,
        )
        for bead_id in result.started:
            started[bead_id] = bead_id
        for bead_id in result.completed:
            completed[bead_id] = bead_id
        for bead_id in result.blocked:
            blocked[bead_id] = bead_id
        for bead_id in result.correctives_created:
            correctives_created[bead_id] = bead_id
        deferred_count += len(result.deferred)
        if not result.started:
            break  # quiescence: nothing dispatched this cycle
finally:
    reporter.stop()
```

The exit condition is `not result.started`. A cycle with `started=[]` means `_select_beads_for_dispatch` found nothing to run, which is the definition of quiescence. Beads in `result.deferred` (waiting on dependencies) and `result.blocked` (terminal blocks) are correctly excluded — they are not progressable in any subsequent cycle without external intervention, so looping further is pointless.

### 2. Add a safety cap

Add a `--max-cycles` CLI flag (default 50) to `command_run`'s argparse setup in `src/agent_takt/cli/parser.py`, and break out of the outer loop with a `console.warn(...)` when the cap is hit. Rationale: a buggy planner or runaway corrective loop should not spin forever; the cap is a release-valve, not a normal exit condition. Users running tightly-scoped feature trees will never hit it; users running large fleets can raise it.

If `--max-cycles` is omitted, default to 50. If set to 0 or a negative value, treat as unbounded (let the loop run until natural quiescence).

### 3. Emit per-cycle progress markers

When the outer loop iterates more than once, emit a console line at the start of each iteration so the operator sees progress:

```
Scheduler
• Starting scheduler loop with max_workers=4, feature_root=B-622deef1
• Cycle 1
  ...
• Cycle 2
  ...
```

Cycle 1's marker can be elided for backward-compatible output when only one cycle runs (preserves the current single-cycle UX for simple cases).

### 4. Update `scheduler_cycle_started` / `scheduler_cycle_completed` events

The existing `scheduler_cycle_started` and `scheduler_cycle_completed` storage events (`run.py:114-118` and `137-143`) are emitted once per CLI invocation. Move them inside the loop so each cycle gets its own pair, and add a `cycle_index` field to both. This preserves telemetry granularity — operators looking at the event log can see each cycle's outcome individually instead of an aggregated total.

The CLI's final `Cycle summary` and `Final state` lines (run.py:156-164) should remain a single end-of-run report (not per-cycle) — they already aggregate across multiple `run_once` results via the dicts.

### 5. Add tests

Add tests to `tests/test_cli_run.py` (the file already exists; append):

- **`test_run_loops_until_quiescence`**: Set up a fake `Scheduler` whose `run_once` returns three `SchedulerResult` objects in sequence — first with `started=["B-1"]`, second with `started=["B-2"]`, third with `started=[]`. Invoke `command_run`. Assert `run_once` was called exactly 3 times and the final summary contains both bead IDs.
- **`test_run_stops_when_no_beads_started`**: `run_once` returns `started=[]` immediately. Assert it was called exactly once.
- **`test_run_respects_max_cycles_cap`**: `run_once` always returns `started=["B-N"]`. With `--max-cycles 5`, assert `run_once` was called exactly 5 times and a warning was emitted.
- **`test_run_quiescence_with_deferred_only_exits`**: `run_once` returns `started=[]`, `deferred=["B-X"]` (a bead waiting on an unsatisfied dependency). Assert the loop exits — beads that defer indefinitely on dependencies should not loop forever.

Mocking `Scheduler.run_once` directly is cleanest for these CLI-level tests; the `_FakeRunner` patterns in `tests/helpers.py` are only needed if a real scheduler is desired.

### 6. Update CLAUDE.md and docs

The Quick Reference comment at line 9 of CLAUDE.md is already correct ("run all beads to quiescence") — leave it unchanged. Add a brief note under a new "Run command" subsection (or extend "Multi-Worker CLI Output") describing:

- `takt run` loops until the scheduler finds nothing to dispatch.
- `--max-cycles N` caps iterations (default 50; `0` = unbounded).
- Beads stuck on unsatisfied dependencies (`deferred`) cause the loop to exit, not spin — they require operator intervention or upstream completion.

## Files to Modify

| File | Change |
|---|---|
| `src/agent_takt/cli/commands/run.py` | Wrap `run_once` call in a while-loop terminated by `not result.started`; emit per-cycle markers; move telemetry events inside loop with `cycle_index` |
| `src/agent_takt/cli/parser.py` | Add `--max-cycles` flag (default 50) to the `run` subparser |
| `tests/test_cli_run.py` | Add four tests covering quiescence, immediate exit, cap, and deferred-only exit |
| `CLAUDE.md` | Add a brief subsection documenting the loop behaviour and `--max-cycles` flag |

No changes to `src/agent_takt/scheduler/core.py`. The `started_this_cycle` guard remains intact — its purpose (preventing same-cycle re-dispatch) is preserved, and the outer loop sidesteps the practical issue by starting a fresh cycle where the set is empty.

## Acceptance Criteria

- `takt run` repeatedly calls `Scheduler.run_once()` until a cycle returns `result.started == []`, then exits with success.
- A feature tree where a tester blocks mid-cycle, a corrective is created and completes, and the tester re-runs successfully — completes in a single `takt run` invocation (no manual re-invocation required).
- `--max-cycles N` caps the loop at N iterations and emits a warning if hit. Default is 50; `--max-cycles 0` is unbounded.
- Each cycle emits its own `scheduler_cycle_started` and `scheduler_cycle_completed` events with a `cycle_index` field.
- The end-of-run JSON summary block (`run.py:166-174`) remains a single aggregated report (unchanged shape) — keys still cover the full invocation.
- The four new tests in `tests/test_cli_run.py` pass; the full suite remains green.
- CLAUDE.md documents the new behaviour and `--max-cycles` flag.

## Pending Decisions

- **Default value for `--max-cycles`.** 50 is a reasonable safety cap for typical feature trees (which complete in 1-3 cycles). Larger fleets or `takt-fleet` orchestration may want a higher default. Open to setting it to 100 or making it configurable via `OrchestratorConfig.scheduler` instead. Resolution: starting with 50 as a CLI flag default; can promote to config if operators hit the cap routinely.
- **Should `result.deferred` count toward "progress"?** No — deferred beads are waiting on unsatisfied dependencies that won't change without external work landing. Treating deferred-only cycles as quiescence is correct and prevents infinite loops on stuck feature trees.
