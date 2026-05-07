---
name: Cross-feature-root file-scope conflict false positive
id: spec-1b99116b
description: Stop the scheduler from blocking beads in different feature roots when their expected_files overlap
dependencies: null
priority: medium
complexity: low
status: done
tags:
- scheduler
- bug
scope:
  in: null
  out: null
feature_root_id: B-622deef1
---
# Cross-feature-root file-scope conflict false positive

## Objective

The scheduler currently blocks two beads from running concurrently when their `expected_files`/`expected_globs` overlap, even when the beads belong to **different feature roots** and therefore execute in **different Git worktrees**. This is a false positive: beads in different worktrees physically cannot collide at runtime — they read and write distinct copies of the file on disk. Any "conflict" is a merge-time concern, which `takt merge` already handles via the merge-conflict bead flow.

The observed symptom: an operator running two scheduler invocations scoped to different feature roots (each via `--feature-root <id>`) saw one bead deferred with `file-scope conflict with in-progress <other-id>`, even though the two beads were in separate worktrees.

This spec fixes the conflict check so it only fires within the same feature tree, matching the behaviour already in place for the no-scope and serialize-within-feature-tree paths.

## Problems to Fix

1. **`_beads_conflict()` ignores `same_feature_tree` on the explicit-scope path.** In `src/agent_takt/scheduler/core.py:429-444`, the early branches at lines 431 and 438-443 all gate on `same_feature_tree`, but the final fall-through `return self._scopes_overlap(bead, active)` at line 444 does not. Two beads in different feature roots with overlapping `expected_files` are therefore declared in conflict and one is deferred unnecessarily.

2. **No test covers the cross-feature-root overlap case.** `tests/test_scheduler_core.py` has `test_serialize_on_cross_feature_tree_both_dispatched` (line 480) which verifies cross-tree dispatch when files do **not** overlap, and `test_same_feature_tree_non_overlapping_mutations_can_run_in_parallel` (line 175) which verifies in-tree dispatch when files do not overlap — but no test exercises "different feature roots, overlapping `expected_files`". This gap is what allowed the bug to slip in.

## Changes

### 1. Gate `_scopes_overlap()` on `same_feature_tree`

Modify `_beads_conflict()` in `src/agent_takt/scheduler/core.py` so the final return statement only declares a conflict when both beads share a feature tree. The change is one line:

```python
# Before (line 444):
return self._scopes_overlap(bead, active)

# After:
return same_feature_tree and self._scopes_overlap(bead, active)
```

`same_feature_tree` is already computed at the top of the function (line 430), so no additional storage lookups are needed.

The `_find_conflict_reason()` method at lines 358-377 does not need changes: it already produces a reasonable message ("file-scope conflict…") for the cases where `_beads_conflict()` returns `True`, and after the fix that path will only be reached for same-tree pairs.

### 2. Add a test for the cross-feature-root overlap case

Add a new test method to `tests/test_scheduler_core.py`, modelled on `test_serialize_on_cross_feature_tree_both_dispatched` (line 480):

```python
def test_cross_feature_tree_overlapping_files_both_dispatched(self) -> None:
    """Two beads in different feature roots with overlapping expected_files
    must both dispatch — they run in different worktrees so cannot collide."""
    bead1 = self.storage.create_bead(
        title="Tree A task", agent_type="developer", description="a",
        expected_files=["src/shared.py"],
    )
    bead2 = self.storage.create_bead(
        title="Tree B task", agent_type="developer", description="b",
        expected_files=["src/shared.py"],  # same path, different feature root
    )
    runner = _FakeRunnerWithDefault(
        results={
            bead1.bead_id: AgentRunResult(outcome="completed", summary="done", expected_files=bead1.expected_files),
            bead2.bead_id: AgentRunResult(outcome="completed", summary="done", expected_files=bead2.expected_files),
        }
    )
    scheduler = Scheduler(self.storage, runner, WorktreeManager(self.root, self.storage.worktrees_dir))
    result = scheduler.run_once(max_workers=2)
    self.assertIn(bead1.bead_id, result.started)
    self.assertIn(bead2.bead_id, result.started)
    self.assertNotIn(bead1.bead_id, result.deferred)
    self.assertNotIn(bead2.bead_id, result.deferred)
```

Each top-level `create_bead` call without a `parent_id` creates its own feature root, so `bead1` and `bead2` belong to different feature trees.

### 3. Verify existing tests still pass

The change tightens the conflict check (from "any overlap" to "same-tree overlap"), so it can only turn previously-deferred pairs into now-dispatched pairs. No existing test exercises a cross-tree overlap pair expecting deferral, but run the full scheduler suite to confirm.

## Files to Modify

| File | Change |
|---|---|
| `src/agent_takt/scheduler/core.py` | One-line change at line 444: gate `_scopes_overlap()` on `same_feature_tree` |
| `tests/test_scheduler_core.py` | Add `test_cross_feature_tree_overlapping_files_both_dispatched` near the existing `test_serialize_on_cross_feature_tree_both_dispatched` (around line 503) |

## Acceptance Criteria

- `_beads_conflict()` returns `False` for two mutating beads in different feature roots whose `expected_files` (or `expected_globs`) overlap, when `serialize_within_feature_tree=False` (the default).
- `_beads_conflict()` continues to return `True` for two mutating beads in the **same** feature root whose `expected_files` overlap (no regression on the in-tree path).
- A new test `test_cross_feature_tree_overlapping_files_both_dispatched` in `tests/test_scheduler_core.py` exercises the cross-tree overlap case and asserts both beads are in `result.started` and neither is in `result.deferred`.
- Existing tests continue to pass: `uv run pytest tests/ -n auto -q` is green.
- No change to `_find_conflict_reason()`, `_scopes_overlap()`, `_files_match_globs()`, or `_globs_overlap()` — only `_beads_conflict()`'s final return statement is modified.

## Pending Decisions

None. The fix is minimal, the bug is straightforward, and the same-feature-tree gating is consistent with the surrounding branches.
