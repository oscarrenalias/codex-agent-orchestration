---
name: Structured output recovery for no-structured-output bead failures
id: spec-0eaad5f9
description: "When an agent completes real work but emits prose instead of a JSON verdict, a recovery bead reads the prose and git diff to synthesise a valid handoff, unblocking the pipeline automatically."
dependencies: null
priority: medium
complexity: medium
status: planned
tags:
- scheduler
- recovery
- structured-output
scope:
  in: Recovery bead type for no-structured-output failures; scheduler integration to auto-create recovery beads; recovery agent prompt; tests
  out: Changes to the agent prompt to prevent prose output in the first place; changes to how verdicts are parsed
feature_root_id: null
---
# Structured output recovery for no-structured-output bead failures

## Objective

When an agent completes its real work but emits prose instead of a valid JSON verdict, the bead blocks with reason `"no structured output"`. Today the only recourse is a manual `takt retry`, which runs the agent again from scratch — wasting time and tokens re-doing work that was already done.

This spec adds an automatic recovery path: a lightweight recovery bead is created that is given the prose output and the git diff from the worktree. A recovery agent reads both, synthesises a valid JSON handoff summary, and feeds it back to the scheduler, which uses it to mark the original bead done and continue the pipeline.

## Problems to Fix

1. **Wasted re-execution**: `takt retry` re-runs the full agent, ignoring that the code changes are already committed in the worktree. The real work is already done; only the structured output is missing.
2. **Manual intervention required**: The operator must notice the `"no structured output"` block reason and manually issue a retry. This stalls the pipeline until someone is watching.
3. **Retry counts wasted**: Each `takt retry` for a "no structured output" failure consumes a corrective attempt slot, eventually triggering human escalation for a problem that was never a real failure.

## Changes

### New model field: `recovery_for`

Add an optional `recovery_for: str | None` field to `Bead` (in `models.py`). When set, this is the `bead_id` of the original bead whose prose output this recovery bead is resolving. This field is stored in the bead JSON.

### Scheduler: auto-create recovery bead on `no-structured-output` block

In `scheduler.py`, in the block-handling path (where `block_reason` is set), detect the specific case `block_reason.startswith("no structured output")` (or a new sentinel constant `BLOCK_REASON_NO_STRUCTURED_OUTPUT`). Instead of treating this as a corrective attempt, create a new `recovery` bead:

```python
recovery_bead = Bead(
    bead_id=f"{original_bead.bead_id}-recovery",
    title=f"Recover structured output for {original_bead.title}",
    agent_type="recovery",
    bead_type="recovery",
    feature_root_id=original_bead.feature_root_id,
    parent_id=original_bead.bead_id,
    recovery_for=original_bead.bead_id,
    spec=<recovery_prompt>,   # see prompt section below
    status="ready",
)
```

The recovery bead is created in the same feature worktree as the original bead (same `feature_root_id`). It does NOT consume a corrective attempt slot.

### Recovery agent prompt

The prompt passed to the recovery agent (via `spec` field or via `prompts.py`) must include:

1. **The prose output** — the full text that the original agent emitted (available in `block_reason` or in `.takt/agent-runs/{bead_id}/stdout.txt`).
2. **The git diff** — `git diff HEAD` from the feature worktree, showing what files the original agent changed.
3. **The bead title and description** — so the recovery agent understands what work was meant to be done.
4. **The JSON schema** — the exact `AGENT_OUTPUT_SCHEMA` the output must conform to, printed inline.
5. **Instruction** — the agent must emit ONLY a JSON object matching the schema, nothing else.

The recovery agent should NOT use any tools — it only reads the provided context and emits JSON.

### Recovery bead completion

When the recovery bead completes with a valid JSON verdict, the scheduler:

1. Reads the recovery bead's `handoff_summary`.
2. Writes it as the handoff summary for the original bead (`recovery_for`).
3. Marks the original bead `done` (or `handed_off` if appropriate).
4. Deletes or marks the recovery bead `done`.
5. Continues the pipeline (followup beads are created for the original bead as normal).

This logic lives in a new `_handle_recovery_completion(recovery_bead)` method in `Scheduler`.

### Agent type: `recovery`

Add `"recovery"` as a valid agent type in:
- `AGENT_OUTPUT_SCHEMA` enum (so the planner doesn't try to plan recovery beads, but the schema is consistent)
- `AGENT_SKILL_ALLOWLIST` in `skills.py` — recovery agents get only `core/base-orchestrator` (no role, capability, or task skills; they don't need tools)
- `templates/agents/recovery.md` — guardrail template. Should instruct the agent to emit ONLY the JSON object.

### Prompt construction (`prompts.py`)

Add `build_recovery_prompt(original_bead, prose_output, git_diff)` function that assembles the recovery agent prompt described above. Called by the scheduler when creating the recovery bead.

### No `takt retry` for `no-structured-output`

In the retry path (`cli.py` and/or `scheduler.py`), if the bead's `block_reason` indicates `no-structured-output` AND a recovery bead already exists (i.e. `bead_id-recovery` exists), skip creating a new corrective and inform the operator.

## Files to Modify

| File | Change |
|---|---|
| `src/agent_takt/models.py` | Add `recovery_for: str \| None = None` to `Bead` dataclass |
| `src/agent_takt/scheduler.py` | Detect `no-structured-output` block; create recovery bead; add `_handle_recovery_completion()` |
| `src/agent_takt/prompts.py` | Add `build_recovery_prompt(original_bead, prose_output, git_diff)` |
| `src/agent_takt/skills.py` | Add `"recovery"` to `AGENT_SKILL_ALLOWLIST` with minimal skill set |
| `src/agent_takt/runner.py` | Ensure `"recovery"` agent type is handled (no-tool mode or minimal tools) |
| `templates/agents/recovery.md` | New guardrail: emit only JSON, no prose, no tool calls |
| `tests/test_scheduler.py` | Tests for recovery bead creation and completion handling |

## Acceptance Criteria

- When a bead blocks with `block_reason` matching `"no structured output"`, the scheduler automatically creates a `{bead_id}-recovery` bead on the next cycle — without consuming a corrective attempt.
- The recovery bead's prompt includes the prose output, git diff, bead title, and the JSON schema.
- When the recovery bead produces valid JSON, the scheduler marks the original bead `done` with the synthesised handoff and continues the pipeline (followup beads are created).
- When the recovery bead itself fails, the original bead remains blocked and the operator is notified; no infinite recovery loop.
- `takt bead list --plain` shows recovery beads with `bead_type=recovery`.
- `takt retry <bead_id>` on a `no-structured-output` bead that already has a pending recovery bead prints a warning and does not create a duplicate.
- All existing tests pass. New tests cover: recovery bead creation, prompt content, completion handling, and the no-duplicate-recovery guard.

## Pending Decisions

- **Prose source**: The prose may be in `block_reason` (truncated) or in `.takt/agent-runs/{bead_id}/stdout.txt` (full). Prefer the full file if it exists; fall back to `block_reason`. Implementation should handle both.
- **Recovery agent runs in the same worktree**: Confirmed — it shares the feature worktree so the git diff is available directly.
- **What if the recovery agent also emits prose?**: Mark the recovery bead blocked (normal block path). Do NOT create a recovery-of-recovery. The original bead stays blocked; operator must intervene manually.
