---
name: Eliminate chore commit destruction of main bead state
id: spec-d1a1398c
description: "Stop generating the chore commit at worktree creation; replace its purpose via pathspec-aware staging in commit_all. Eliminates the data-loss path that has wiped main's bead state on every takt merge in this repo today (4 recovery commits in this session alone)."
dependencies: null
priority: high
complexity: medium
status: done
tags:
- scheduler
- gitutils
- merge
- safety-net
- regression
scope:
  in: "Removing the chore commit generation in `_protect_worktree_bead_state`; converting `commit_all` to exclusion-aware staging via `git add :(exclude).takt/beads/**`; reconsidering the DU-conflict auto-resolution that silently destroys main's bead state; regression tests covering the cookbook-app empirical behavior; migration plan for repos with chore commits already in feature branch history."
  out: "Removing the bead state tracking opt-in (`!.takt/beads/**` in `.gitignore` for self-hosting takt projects); changes to how main's bead state is committed by the scheduler; the `--field` / `bead history` CLI surface (already shipped, unrelated)."
feature_root_id: B-a469cc74
---
# Eliminate chore commit destruction of main bead state

## Objective

Every `takt merge` in this repository today silently wipes main's `.takt/beads/` directory of all 1300+ tracked bead state files, requiring a manual `git checkout <pre-merge> -- .takt/beads/` recovery commit on each merge. This has happened **four times in this session alone** (recovery commits `18e074ca`, `3b70eada`, `7b131236`, `2ee649b9`). The bug is structural: the safety-net's `chore: untrack bead state from feature branch [skip ci]` commit, generated at worktree creation by `WorktreeManager._protect_worktree_bead_state()`, contains `git rm --cached` deletions of every bead state file that was tracked on main when the feature branch was created. When the feature branch is merged back to main, those deletes propagate cleanly (no conflict, because main typically hasn't modified those exact files since branching) and main loses the bead state.

This spec removes the chore commit at its source and replaces its defensive purpose (preventing worker `git add -A` calls from including bead state files) with explicit pathspec exclusion in `commit_all`. The result: feature branches no longer carry destructive deletes in their history; merges back to main become benign for `.takt/beads/`; the manual recovery dance is eliminated.

**Important operational caveat — this spec's own merge.** The feature branch that lands this fix will itself be created by the current (broken) worktree-creation flow, so its history will contain ONE last destructive chore commit. The merge that ships this fix will therefore trigger one final round of the data-loss-then-recovery dance. After that, no future feature branches generate the chore commit, and the recovery dance becomes obsolete. Plan accordingly: do this merge with eyes open, perform the recovery as documented, and never again.

## Background — what we learned today

Several mistaken corrections happened during this session before the root cause became clear. Capturing them so future readers don't repeat them:

1. **Initial mis-diagnosis**: I claimed the data loss was caused by today's commit `93933349` adding a post-preflight `_protect_worktree_bead_state(worktree_path)` call inside `merge_main_into_branch`. I reverted that call (commit `7e7b9332`) and declared victory. The revert was *valuable* — that secondary chore commit was real and destructive — but it was not the *primary* cause. The primary chore commit (generated at worktree creation, lines 285/292 of `gitutils.py`) was always destructive and predates this session.

2. **The cookbook-app comparison**: cookbook-app at `/Users/oscar.renalias/Projects/cookbook-app` runs takt 0.1.42 from PyPI, tracks 248 bead files, has feature branches with the same chore commits, and *does not* lose bead state on `takt merge`. Diffing v0.1.42 against current main shows: v0.1.42 has none of the auto-resolution machinery added today (`_save_and_remove_bead_files`, `_resolve_bead_state_conflicts`, `_du_conflicted_files`, `_merge_with_bead_state_fallback`). v0.1.42's `merge_main_into_branch` is a single `git merge --no-ff main` subprocess call.

3. **Why cookbook-app survives**: between worktree creation and final merge, cookbook-app's main accumulates few `[bead] B-foo: <state>` commits. The chore commit's `git rm` deletes target the same files main has been modifying, so during the final merge:
   - **In v0.1.42**: deletes-vs-modifies become merge conflicts. The merge fails loudly. Operator sees a merge-conflict bead, intervenes manually. No data loss because the merge doesn't complete.
   - **In current main**: the auto-resolver `_resolve_bead_state_conflicts` silently calls `git rm` on the conflicted files (consistent with the safety-net policy "feature branches don't track bead state"). The merge completes silently. Main loses the files.

   Today's `_du_conflicted_files` fix (`ac2b1542`) made things *worse* by ensuring this auto-resolution succeeds even when the conflict shape is "deleted by us, modified by them" — which would otherwise have crashed with `error: path '...' does not have our version`.

4. **The clean-delete case**: if main hasn't modified a chore-commit-deleted file since branching, the final merge applies the delete *cleanly* (no conflict at all). Neither v0.1.42 nor current main intercepts this — both versions silently lose the file. cookbook-app dodges this because the scope of overlap is small (few main commits, mostly adds of new beads, rarely modifying older ones). codex-agent-orchestration has continuous bead state mutation on main, so almost every chore-commit-deleted file overlaps with main's history.

5. **The CLI ergonomics merge data loss (`81e29913`) and the steering bead merge data loss (`ef08536f`)** were both this same mechanism — the chore commit's deletes propagating silently or via auto-resolution.

## Problems to Fix

1. **Worktree creation's `_protect_worktree_bead_state` produces a destructive commit on the feature branch.** The `git rm --cached` removes whatever bead state files were tracked at branch time; that deletion is recorded in the chore commit; the chore commit is on the feature branch's history forever. When merged back to main, those deletes propagate.

2. **`commit_all` uses `git add -A`.** The chore commit was added defensively to "untrack" bead state so that subsequent `git add -A` calls in `commit_all` wouldn't re-stage them. Without the chore commit, `git add -A` would include bead state files in worker commits — which is the original problem the safety net was solving.

3. **Today's `_resolve_bead_state_conflicts` + DU handling silently masks the propagation.** Conflicts that would have failed loudly in v0.1.42 are auto-resolved with `git rm`, completing the data loss without any operator-visible signal. This makes the underlying bug *harder* to notice, not easier.

4. **No regression test catches this end-to-end.** The current test suite has unit tests for individual mechanisms but no integration test that exercises "feature branched off main with N tracked beads → worktree creation chore commit runs → main accumulates `[bead]` commits → final merge → assert main still has all N beads."

## Changes

### Primary change — remove the chore commit, switch `commit_all` to exclusion-aware staging

Two coordinated changes in `src/agent_takt/gitutils.py`:

#### Change 1 — `_protect_worktree_bead_state` no longer commits a chore

Currently (around lines 113-145 of `gitutils.py`), this function:
1. Writes `info/exclude` with bead state patterns (legitimate — keeps untracked bead files invisible to git status).
2. Checks if any bead state files are tracked.
3. If yes: runs `git rm --cached -r --ignore-unmatch .takt/beads/` and `git commit -m "chore: untrack bead state..."`.

The new behavior: keep step 1, drop steps 2-3 entirely. The function becomes purely informational:

```python
def _protect_worktree_bead_state(self, worktree_path: Path) -> None:
    """Configure the worktree's info/exclude so untracked bead state
    files are invisible to git status. Does NOT remove any tracked bead
    state files — that responsibility moves to commit_all, which uses
    pathspec exclusion when staging worker changes.
    """
    _write_worktree_exclude(self.root, worktree_path)
```

Bead state files inherited from main remain tracked in the feature branch's index; they just don't get re-staged or modified by worker commits (see Change 2).

#### Change 2 — `commit_all` uses pathspec exclusion instead of `git add -A`

Currently `commit_all` (around lines 308-355) runs `git add -A` then `git commit`. Replace with explicit pathspec exclusion of bead state during the add step:

```python
add_proc = subprocess.run(
    ["git", "add", "--", ":/", ":(exclude).takt/beads/**", ":(exclude).takt/beads/"],
    cwd=worktree_path,
    text=True,
    capture_output=True,
    check=False,
)
```

The `:/` pathspec means "everything under repo root"; the `:(exclude).takt/beads/**` and `:(exclude).takt/beads/` (both forms — git's pathspec exclude can be finicky about trailing slashes vs. globs depending on git version) prevent any bead state files from being staged. Keep the existing `git status --porcelain` check before staging (returns `None` if nothing to commit) and the existing post-stage `git commit -m <message>` invocation.

Net effect: worker commits never include bead state file changes, even though those files are still tracked in the feature branch's index from inheritance. No need to untrack them via a chore commit.

**On main-side additions and modifications.** While the feature branch is in flight, main may add new bead state files (e.g. `B-6.json` for a newly created bead) and modify existing ones (e.g. `B-2.json` going from `ready` to `in_progress` to `done`). Those changes are **not** affected by `commit_all`'s pathspec exclusion — exclusion only governs the FEATURE-side staging. When `merge_main_into_branch` runs the preflight, main's additions and modifications come into the feature branch's index cleanly (the feature-side index doesn't have conflicting changes for those paths because workers never staged them). When `merge_branch` runs the final merge, the feature branch's tip already incorporates main's recent bead state via the preflight, so the final merge is a no-op for `.takt/beads/`. This is exactly the behavior we want and is the structural reason this fix works end to end.

### Secondary change — revert today's `_du_conflicted_files` and re-direct `_resolve_bead_state_conflicts`

Today's DU handling (commit `ac2b1542`, the `_du_conflicted_files` helper added to `gitutils.py:105-129`) silently destroys main's data when DU conflicts arise during `merge_branch` (cwd = main). The auto-resolution direction is wrong on the main side: it calls `git rm` on files the safety-net policy says feature shouldn't track, but on main those files ARE the source of truth.

Two coordinated changes to `gitutils.py`:

1. **Revert `_du_conflicted_files`**. Remove the helper function entirely (`gitutils.py:105-129` from commit `ac2b1542`). With the chore commit gone (Change 1), the DU conflict pattern this helper was built for becomes vanishingly rare; when it does fire, its current behavior is destructive in the wrong direction. Restoring `_resolve_bead_state_conflicts` to its pre-`ac2b1542` form (uniform `git checkout --ours` + `git add` for all bead conflicts) is sufficient and safer.

2. **Add a `direction` parameter to `_resolve_bead_state_conflicts`** (currently around `gitutils.py:199-216`). New signature:

   ```python
   def _resolve_bead_state_conflicts(
       self, cwd: Path, *, direction: Literal["main", "feature"]
   ) -> bool:
   ```

   Both call sites pass the appropriate value:

   - `_merge_with_bead_state_fallback` invoked from `merge_branch` (cwd = main, around `gitutils.py:295-306`): pass `direction="main"`. Resolution policy: `git checkout --theirs` (keep the feature-side version, which after the fix in Change 1 will be main's version anyway because feature-side commits don't touch bead state).
   - `_merge_with_bead_state_fallback` invoked from `merge_main_into_branch` (cwd = feature worktree, around `gitutils.py:385-414`): pass `direction="feature"`. Resolution policy: `git checkout --ours` (current behavior — keep feature's snapshot, which is the worktree's untracked-via-info/exclude state).

The net effect: on main, the resolver never destroys data; on the feature worktree, behavior is unchanged.

### Tests

Add an end-to-end integration test in `tests/test_merge_safety.py`:

```python
def test_takt_merge_preserves_main_bead_state_through_full_cycle(self) -> None:
    """End-to-end reproducer: main has many tracked bead files; feature
    branch is created; main accumulates `[bead]`-style commits modifying
    SOME of those files and adding new ones; takt merge runs preflight
    + final merge; assert main retains all original files plus the new
    ones, with the latest content for each.
    """
    # 1. Set up: 5 tracked bead files on main (.takt/beads/B-1..B-5.json)
    # 2. Create a feature worktree (triggers _protect_worktree_bead_state)
    # 3. On feature: change a Swift file (anything outside .takt/beads/)
    # 4. Worker commit via commit_all
    # 5. On main: modify B-2.json (simulating a `[bead] B-2: in_progress` commit)
    # 6. On main: create B-6.json (simulating a new bead)
    # 7. takt merge of feature into main:
    #    a. preflight: merge_main_into_branch
    #    b. final: merge_branch
    # 8. Assert: main's .takt/beads/ contains B-1, B-2 (with main's modification),
    #    B-3, B-4, B-5 (unchanged), and B-6 (new).
```

This test would fail on current main (data loss), pass after the spec lands. It's the missing safety net that should catch any future regression of this kind.

Also add a focused unit test for `commit_all` asserting bead state files are never staged even when present and modified.

## Files to Modify

| File | Change |
|---|---|
| `src/agent_takt/gitutils.py` | Strip the rm-cached + commit logic from `_protect_worktree_bead_state` (lines ~113-145); convert `commit_all`'s `git add -A` to pathspec-exclusion form (lines ~308-355); revisit `_resolve_bead_state_conflicts` direction logic. |
| `tests/test_merge_safety.py` | Add end-to-end `test_takt_merge_preserves_main_bead_state_through_full_cycle`. Update existing tests in `BeadStateMergeFallbackIntegrationTests` whose assertions depended on chore-commit-driven untracking. |
| `tests/test_gitutils_worktree_exclude.py` | Update `MergeMainIntoBranchSaveRestoreTests` and any other tests that depend on the destructive post-creation behavior. The save/restore tests should still pass (orthogonal). |
| `tests/test_scheduler_beads.py` | Add a test asserting bead state files are never staged by worker commits even when modified on disk. |
| CLAUDE.md | Update the "Bead state exclusion" subsection in "Conventions" — bead state isolation now comes from `info/exclude` + `commit_all`'s pathspec exclusion, not a chore commit. |

## Acceptance Criteria

1. After this spec is implemented, creating a feature worktree does NOT produce a `chore: untrack bead state from feature branch [skip ci]` commit on the feature branch. Verified by inspecting `git log feature/b-* -- .takt/beads/` immediately after worktree creation.
2. Worker commits made via `commit_all` do NOT include any path under `.takt/beads/`, even when bead state files are modified on disk in the worktree. Verified by a unit test that modifies `.takt/beads/B-foo.json` in a worktree, runs `commit_all`, and inspects the resulting commit's `git show --stat`.
3. End-to-end test (described under Tests) passes: takt merge of a feature into main preserves all of main's pre-merge `.takt/beads/` files, regardless of how many `[bead]` commits main accumulated during the feature run.
4. After this spec lands, no future merge of a feature branch (one created AFTER the spec lands, so without a chore commit in its history) produces a `recovery: restore bead state files lost in X merge` commit in `git log main`. Falsifiable from `git log main --grep="recovery: restore bead state"` returning no entries past the spec's own merge SHA.
5. `_resolve_bead_state_conflicts` accepts a `direction` parameter; DU conflicts during `merge_branch` (cwd = main, `direction="main"`) resolve via `git checkout --theirs` and never invoke `git rm`. Verified by a unit test that constructs a DU conflict on main and asserts the file's bytes survive the resolution.
6. `_du_conflicted_files` is removed from `gitutils.py`. Verified by `grep -n "_du_conflicted_files" src/agent_takt/gitutils.py` returning no results.
7. `uv run pytest tests/ -n auto -q` passes with the updated test suite.
8. CLAUDE.md "Bead state exclusion" subsection accurately describes the new mechanism (`info/exclude` + pathspec exclusion in `commit_all`, no chore commit).
9. No code path in `gitutils.py` produces a chore commit. `grep -n "untrack bead state" src/agent_takt/gitutils.py` returns no results after the spec is implemented.

## Pending Decisions

1. ~~**What to do with feature branches that ALREADY have a chore commit?**~~ — **Resolved 2026-05-06**: option (a) — drain in-flight features via `takt merge` before this spec lands, eat one final round of recovery commits per merge. Small population, one-time cost, no operator tooling needed.

2. ~~**Should `_resolve_bead_state_conflicts` and `_du_conflicted_files` be reverted?**~~ — **Resolved 2026-05-06**: keep `_resolve_bead_state_conflicts` (with the new `direction` parameter), REVERT `_du_conflicted_files`. Codified in Changes / Secondary change and Acceptance Criteria #5 and #6.

3. ~~**Should `info/exclude` continue to be written?**~~ — **Resolved 2026-05-06**: keep. With `commit_all` handling staging via pathspec exclusion, `info/exclude`'s only role is hiding untracked bead files from `git status` for operator ergonomics — real benefit, single file write, no failure mode. `_protect_worktree_bead_state` retains its `_write_worktree_exclude` call (just drops the rm-cached + commit logic per Change 1).

4. ~~**Pathspec exclusion form.**~~ — **Resolved 2026-05-06**: pass BOTH `:(exclude).takt/beads/**` and `:(exclude).takt/beads/` to be defensive against git version differences. Codified in Changes / Change 2. Acceptance criterion #2 (worker commits never include `.takt/beads/` paths) provides the test-level verification.

5. ~~**Backward compatibility with existing merge-conflict beads.**~~ — **Resolved 2026-05-06**: leave them alone. Implementation does not touch them; they'll resolve naturally once feature branches stop generating chore commits. If a stuck merge-conflict bead exists at landing time, the operator marks it `done` manually via `takt bead update --status done`.

6. ~~**Self-hosting test exposure.**~~ — **Resolved 2026-05-06**: accept one final recovery dance for this spec's own merge. Operationally simplest, and after this merge it never happens again. Promoted to a paragraph at the end of Objective so the operator sees it before starting implementation.

## References

- `src/agent_takt/gitutils.py` — primary file
- v0.1.42 baseline: `git show v0.1.42:src/agent_takt/gitutils.py` for the working pre-regression behavior
- Today's session recovery commits: `18e074ca`, `3b70eada`, `7b131236`, `2ee649b9`
- Today's introducing commits: `93933349` (save/restore + post-merge protect), `ac2b1542` (DU handling), `7e7b9332` (partial revert of post-merge protect)
- cookbook-app at `/Users/oscar.renalias/Projects/cookbook-app` — empirical reference for the working v0.1.42 behavior
- CLAUDE.md "Bead state exclusion" subsection — describes the current (broken) safety net
