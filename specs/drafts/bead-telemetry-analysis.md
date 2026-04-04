---
name: Bead Telemetry Analysis
id: s-a0f0124
description: Code editing capability for implementation-focused tasks.
dependencies:
priority:  medium
complexity: medium
status: draft
scope:
  in: 
  out: tui
feature_root_id:
tags: cli, telemetry
---

# Bead Telemetry Analysis

## Objective

Provide a reusable, queryable telemetry subcommand built into the orchestrator CLI. Currently, analysing bead performance requires either reading raw JSON files from `.orchestrator/beads/` and `.orchestrator/telemetry/` directly, or writing one-off Python snippets. A first-class `orchestrator telemetry` command with a companion Claude Code skill allows both humans and the assistant to quickly answer questions like "which agent type is slowest?", "what's our retry rate this week?", and "which features have the most blocked beads?"

---

## Problems to Fix

1. **No reusable telemetry tool** — bead performance data is only accessible by reading raw `.json` files. Every analysis requires writing throwaway code.
2. **No structured skill for the assistant** — the assistant cannot reliably access telemetry metrics without re-deriving the access pattern each time.
3. **No aggregation across agent types or features** — there is no supported way to get counts, timing stats, or retry rates across a filtered subset of beads.

---

## Changes

### 1. CLI subcommand: `orchestrator telemetry`

A new `command_telemetry()` function in `src/codex_orchestrator/cli.py`, wired alongside the existing `summary`, `bead`, `run`, etc. commands.

**CLI interface:**

```bash
uv run orchestrator telemetry [OPTIONS]

Options:
  --days N            Include beads created in the last N days (default: 7)
  --feature-root ID   Limit to beads under this feature root (prefix match supported)
  --agent-type TYPE   Limit to a specific agent type (developer, tester, review, etc.)
  --status STATUS     Limit to beads in this status (done, blocked, in_progress, etc.)
  --json              Output raw JSON instead of formatted table
```

**Output sections (default mode):**

```
=== Bead Telemetry Report (last 7 days) ===

Summary
-------
Total beads:        142
  done:             118
  blocked:           12
  in_progress:        6
  ready:              4
  open:               2

By Agent Type
-------------
agent_type    count  done  blocked  avg_turns  avg_wall_s  p95_wall_s  retry_rate
developer        52    44        5       4.2        287.3       612.0       0.10
tester           29    25        3       2.1        391.5       720.0       0.10
review           28    26        2       6.1         74.2       180.0       0.07
documentation    28    26        2       2.3         61.0       150.0       0.07
planner           5     5        0       3.0         45.0        90.0       0.00

Retry / Block Rates
-------------------
Corrective beads created:   14  (out of 142)
Merge-conflict beads:        3
Timeout blocks:              4  (beads blocked with "timed out" reason)
Transient blocks:            8

Feature Roots
-------------
feature_root_id   title (truncated)             beads  done  blocked
B-af576483        Safe merge with rebase...         32    32        0
B-0513c78c        Bead graph diagram...             18    15        2
...
```

**Data sources:**

- Bead metadata: `RepositoryStorage.load_all_beads()` (uses existing storage API)
- Wall-clock time: derived from `execution_history` entries (first `started` to last `completed` timestamp per bead)
- Turn count: `result.turns` from `AgentRunResult` in the bead's last execution history entry
- Token usage: `result.usage` dict if present in `AgentRunResult`
- Retry detection: beads whose `bead_id` ends with `-corrective` or `-merge-conflict`

**Implementation notes:**

- `command_telemetry()` receives the same `args` + `storage: RepositoryStorage` + `console: ConsoleReporter` signature as other command functions in `cli.py`
- Wall-clock: `history[-1].completed_at - history[0].started_at` (skip entries where `completed_at` is None)
- p95 is computed over the filtered bead set using `statistics.quantiles` or a simple sort
- `--feature-root` prefix resolution uses `RepositoryStorage.resolve_bead_id(prefix)` — same as other commands
- Wire the subparser in the existing `build_parser()` / dispatch block in `cli.py`, following the pattern used by `summary` and `bead`

### 2. Skill: `.claude/skills/bead-telemetry/SKILL.md`

A Claude Code skill that explains how to run the command and interpret its output.

**Contents:**

- When to use this skill (asked about agent performance, retry rates, slow beads, feature progress)
- How to run `orchestrator telemetry` with common flag combinations
- How to interpret each output section
- Limitations (only covers beads still present in storage; deleted beads are excluded)

### 3. Tests: `tests/test_bead_telemetry.py`

Unit tests covering:

- `--days` filter correctly excludes old beads
- `--agent-type` filter returns only matching beads
- `--feature-root` filter with prefix match
- Wall-clock calculation from `execution_history`
- Corrective bead detection (bead ID suffix `-corrective`, `-merge-conflict`)
- `--json` flag produces valid JSON with expected keys
- Empty result set (no beads match filter) prints graceful "No beads found" message

---

## Files to Modify

| File | Change |
|---|---|
| `src/codex_orchestrator/cli.py` | Add `command_telemetry()` function; wire subparser and dispatch |
| `.claude/skills/bead-telemetry/SKILL.md` | New file — Claude Code skill |
| `tests/test_bead_telemetry.py` | New file — unit tests for the telemetry command |

---

## Acceptance Criteria

- `uv run orchestrator telemetry` runs without error on the current repo and prints a formatted report
- `--days`, `--agent-type`, `--feature-root`, `--status` flags each correctly filter the bead set
- `--json` outputs valid JSON parseable with `json.loads()`
- Wall-clock times are accurate (validated against at least one known bead)
- Corrective and merge-conflict beads are identified correctly by ID suffix
- All tests in `tests/test_bead_telemetry.py` pass
- `orchestrator --help` lists `telemetry` as a subcommand
- The skill file is present at `.claude/skills/bead-telemetry/SKILL.md` and accurately describes the command

---

## Pending Decisions

### 1. Token usage availability
Token usage is only present in `AgentRunResult` if the runner captures it. Claude Code runner may or may not populate `result.usage`. Should the command skip token columns when data is absent, or always show them with `N/A`? **Recommendation: show columns, display `N/A` when data is missing — keeps the output schema stable.**

### 2. Feature root title truncation
Feature root titles can be long. Should the "Feature Roots" table truncate at 40 chars or be omitted entirely in favour of `--feature-root` flag for drill-down? **Recommendation: truncate at 40 chars with `…` suffix; always show full ID.**
