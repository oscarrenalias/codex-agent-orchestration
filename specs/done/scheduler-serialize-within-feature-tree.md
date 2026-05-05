---
name: "Scheduler: serialize within feature tree"
id: spec-1eb14a19
description: "Opt-in config flag forcing the scheduler to serialize mutating beads within the same feature tree (worktree), bypassing file-scope packing. Needed for toolchains that require exclusive worktree access (Swift/Xcode/SPM)."
dependencies: null
priority: medium
complexity: low
status: done
tags:
- scheduler
- config
- swift
- worktree
scope:
  in: "New `SchedulerConfig.serialize_within_feature_tree` boolean field (default false), conditional check in `_beads_conflict()`, scheduler unit test, docs update."
  out: "Per-feature or per-bead overrides, automatic detection of toolchain-locked projects, changes to file-scope conflict detection across feature trees."
feature_root_id: B-9472cbcc
---
# Scheduler: serialize within feature tree

## Objective

Today's scheduler models conflicts at the **file** level: two mutating beads in the same feature tree can run concurrently if their declared `expected_files` / `expected_globs` don't overlap. That model breaks down for toolchains where the worktree itself carries exclusive-access invariants — e.g. Swift Package Manager's `.build/` cache, Xcode `.xcodeproj` state, the iOS Simulator (a single device), or any tool that holds a directory-wide lock. A bead can carefully list every file it touches and still corrupt state because the underlying tool serializes at the workspace level, not the file level.

This spec adds a single opt-in config flag — `scheduler.serialize_within_feature_tree` — that forces the scheduler to treat any pair of mutating beads in the same feature tree as conflicting, regardless of their declared file scopes. Cross-worktree parallelism is unchanged; only within-worktree packing is disabled. Default is off, so non-Swift projects see no change.

## Problems to Fix

1. **Worktree-level invariants are invisible to file-scope conflict detection.** The current `_beads_conflict()` rule (`src/agent_takt/scheduler/core.py:421`) treats two same-feature-tree beads as conflict-free when both declare non-overlapping scopes. For Swift projects this can produce concurrent SPM builds, simultaneous Xcode index writes, or competing Simulator launches — corrupting state in ways the scheduler can't see.
2. **No way to opt out of within-worktree packing.** Operators with toolchain-locked stacks have no configuration knob today. The only workaround is to leave `expected_files` blank on every bead (so the worktree-lock fallback in `_find_conflict_reason()` kicks in), which sacrifices the operator's ability to use file scope for cross-worktree conflict detection at all.
3. **Discussion record.** This decision came out of a session-level conversation about Swift development; the design intent and tradeoffs need to live somewhere durable.

## Changes

### Config field

Add a new optional field to `SchedulerConfig` in `src/agent_takt/config.py`:

```python
@dataclass(frozen=True)
class SchedulerConfig:
    # ... existing fields ...
    serialize_within_feature_tree: bool = False
```

Loaded from the YAML at `common.scheduler.serialize_within_feature_tree`. Default `False` preserves today's behaviour for every existing project.

**Loader semantics — both paths must yield `False`:**

- Dataclass default: `serialize_within_feature_tree: bool = False`.
- YAML loader: when the key is absent (or the entire `scheduler` block is absent, or the entire `common` block is absent) the field resolves to `False`. No warning, no error — silent default. This is required so that upgrading takt against a config file written before this spec landed produces zero behavioural change.

A unit test in `tests/test_config.py` (or wherever existing config-load tests live) must assert this loader semantic explicitly: load a YAML with no `scheduler` block and confirm `config.scheduler.serialize_within_feature_tree is False`.

Example config opt-in:

```yaml
common:
  scheduler:
    serialize_within_feature_tree: true
```

### Scheduler conflict logic

In `src/agent_takt/scheduler/core.py:_beads_conflict()` (currently around line 421), add a short-circuit at the top of the same-feature-tree branch:

```python
def _beads_conflict(self, bead: Bead, active: Bead) -> bool:
    same_feature_tree = (
        self.storage.feature_root_id_for(bead) == self.storage.feature_root_id_for(active)
    )

    # Worktree-level serialization opt-in: any two mutating beads in the
    # same feature tree conflict, regardless of declared file scope.
    if (
        same_feature_tree
        and self.config.scheduler.serialize_within_feature_tree
        and bead.agent_type in MUTATING_AGENTS
        and active.agent_type in MUTATING_AGENTS
    ):
        return True

    # ... existing logic unchanged below ...
```

The new check fires only when:
- Both beads share a feature tree (same worktree), AND
- The flag is enabled, AND
- Both beads are mutating agents (`developer`, `tester`, `documentation`).

`MUTATING_AGENTS` is the existing constant defined in `src/agent_takt/models.py:18` as `{"developer", "tester", "documentation"}` and imported into `core.py` (already in scope — no new import needed).

It does **not** affect:
- Cross-feature-tree conflict detection (file-scope overlap across worktrees still works as today).
- Read-only agent types (`planner`, `review`, `recovery`) — those don't mutate code, so they don't need worktree exclusivity.
- The existing `has_scope()` worktree-lock fallback for beads with no declared scope (still in effect, redundant when the flag is on but harmless).

### Conflict-reason message

When the new rule fires, `_find_conflict_reason()` (around line 357) should report a distinct reason so operators can tell why a bead was deferred:

```python
if (
    same_feature_tree
    and self.config.scheduler.serialize_within_feature_tree
    and bead.agent_type in MUTATING_AGENTS
    and active.agent_type in MUTATING_AGENTS
):
    return f"worktree serialization enabled — waiting on in-progress {active.bead_id}"
```

This must precede the existing checks in `_find_conflict_reason()` so the new reason wins when multiple rules would apply.

### Documentation

- **`CLAUDE.md`** — add a one-paragraph note in the "Configuration" section describing the new flag, when to enable it (Swift/Xcode/SPM and similar toolchain-locked stacks), and the trade (loses within-worktree packing).
- **`docs/multi-backend-agents.md`** (or wherever `SchedulerConfig` is documented) — add the field to the config reference table.

### Tests

In `tests/test_scheduler_core.py` (or the file that already covers `_beads_conflict()` / `_select_beads_for_dispatch()`):

1. **Flag off (default)**: two same-feature-tree mutating beads with non-overlapping `expected_files` are NOT in conflict — both get dispatched. Asserts current behaviour is preserved.
2. **Flag on**: same setup, same beads, but with `serialize_within_feature_tree=True` in config → second bead is deferred with the new conflict reason.
3. **Flag on, cross-feature-tree**: two beads in DIFFERENT feature trees with non-overlapping scopes → both dispatched (the flag does not affect cross-tree).
4. **Flag on, non-mutating bead pair**: e.g., a planner + a review in the same tree → no conflict (the flag only applies to mutating agents).
5. **Flag on, deferral reason**: assert the deferred bead's `block_reason` matches the new "worktree serialization enabled" string.

## Files to Modify

| File | Change |
|---|---|
| `src/agent_takt/config.py` | Add `serialize_within_feature_tree: bool = False` to `SchedulerConfig` dataclass and YAML load path. |
| `src/agent_takt/scheduler/core.py` | Add short-circuit in `_beads_conflict()` (around line 421) and matching reason string in `_find_conflict_reason()` (around line 357). |
| `tests/test_scheduler_core.py` | Add 5 new tests covering flag off, flag on, cross-tree, non-mutating pair, and deferral reason. |
| `CLAUDE.md` | One-paragraph note in Configuration section describing the flag and when to use it. |
| `docs/multi-backend-agents.md` | Add the flag to the SchedulerConfig reference table. |
| `src/agent_takt/onboarding/config.py` | If the YAML scaffolding emitted by `takt init` includes a `scheduler:` block, add a commented-out `# serialize_within_feature_tree: false` line so operators can discover the flag. If onboarding does not emit a `scheduler:` block today, no change is required. |

## Acceptance Criteria

1. `SchedulerConfig.serialize_within_feature_tree` exists, defaults to `False`, loads from `common.scheduler.serialize_within_feature_tree` in `.takt/config.yaml`.
2. Loading a config YAML where the key is absent — or the whole `scheduler` block is absent, or the whole `common` block is absent — resolves the field to `False` silently (no warning, no error). A unit test asserts this for at least the absent-key and absent-`scheduler`-block cases.
3. With the flag `False` (or unset), scheduler behaviour is **byte-identical** to today: same beads selected, same deferral reasons, same execution history events. Existing test suite passes unchanged.
4. With the flag `True`, two mutating beads in the same feature tree with non-overlapping `expected_files` → only one is selected per cycle; the other is deferred with reason `"worktree serialization enabled — waiting on in-progress <bead_id>"`.
5. With the flag `True`, two mutating beads in DIFFERENT feature trees → both selected (no cross-tree effect).
6. With the flag `True`, a non-mutating bead (planner/review/recovery) and a mutating bead in the same tree → no conflict from this rule (existing rules still apply).
7. New tests in `tests/test_scheduler_core.py` cover the five cases listed under "Tests" above.
8. `CLAUDE.md` and `docs/multi-backend-agents.md` document the flag.
9. `uv run pytest tests/ -n auto -q` passes with no regressions.

## Pending Decisions

1. ~~**Per-feature override?**~~ — **Resolved 2026-04-28**: out of scope for this spec. Project-level flag is sufficient for the Swift use case. If per-feature granularity is ever needed, add it as a separate spec rather than expanding this one.
2. ~~**Auto-detect Swift/Xcode projects and set the flag?**~~ — **Resolved 2026-04-28**: out of scope. Magic detection adds maintenance burden and surprises operators. Explicit opt-in is preferred.
3. ~~**Default value for new projects.**~~ — **Resolved 2026-04-28**: `False`. This applies both to the dataclass field default AND to the loader's behaviour when the YAML key is missing or the entire `scheduler` block is absent — both paths must resolve to `False` so existing projects see no change after upgrading. Explicit opt-in matches takt's "predictable rather than clever" philosophy.
4. ~~**Tester / documentation agent types covered by the rule.**~~ — **Resolved 2026-04-28**: yes. They are in `MUTATING_AGENTS`, so the new flag applies to them too. Intentional: a Swift project's tester running `swift test` competes for the same SPM lock as a developer running `swift build`. No special-case needed.

## Background — discussion summary (2026-04-28)

The need surfaced during a fleet-management session. The operator was reasoning about how takt assigns workers to multiple worktrees with `max_workers=N`, and observed that:

- The scheduler picks beads project-wide, not per-worktree.
- Beads in the same worktree compete for the worktree-level lock when they don't declare file scope.
- Beads with non-overlapping declared scopes can be packed into the same worktree.

For Swift development, that last property is dangerous: SPM, Xcode, and the iOS Simulator all hold workspace-level locks that aren't visible at the file level. The operator concluded — correctly — that takt's current model can't express "this worktree must serialize, even if file scopes look disjoint." This spec is the minimal change that adds that expressiveness without disturbing existing semantics.
