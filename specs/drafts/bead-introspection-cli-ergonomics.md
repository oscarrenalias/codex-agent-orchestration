---
name: Bead introspection CLI ergonomics
id: spec-df49daa7
description: "Add CLI surface for bead introspection patterns agents currently hand-roll with inline Python — formatted execution_history view, field projection on show, and status/agent filters on list. Eliminates the dominant source of python3 -c '...' scripts in agent transcripts."
dependencies: null
priority: medium
complexity: low
status: draft
tags:
- cli
- dx
- agents
scope:
  in: "New `takt bead history` subcommand; `--field PATH` projection flag on `takt bead show`; `--status` and `--agent` filters on `takt bead list`."
  out: "TUI changes, multi-bead `show` (deferred), bead mutation commands, telemetry/metrics commands, anything outside the `takt bead` subcommand group."
feature_root_id: null
---
# Bead introspection CLI ergonomics

## Objective

Agents working in takt projects routinely write inline Python (`cat .takt/beads/<id>.json | python3 -c "..."`) to extract specific fields from bead state — most commonly the formatted `execution_history`, the `handoff_summary`, or the `block_reason`. These scripts are repetitive, error-prone (easy to break with quoting issues — observed in real agent transcripts), and leak implementation details (the on-disk JSON schema) into agent reasoning that should be using a stable CLI surface.

This spec adds four small, surgical CLI features that absorb the common patterns into first-class commands. The change is additive (no existing behaviour modified) and unblocks two improvements at once: less repeated inline-script churn in agent transcripts (saving tokens, reducing failure modes), and a more stable consumption contract — `takt bead show --field` is a documented projection, where `cat ... | python -c '...'` is operator-internal scaffolding.

## Problems to Fix

1. **No formatted view of `execution_history`.** Agents and operators want a chronological log of a bead's lifecycle (`created → ready → in_progress → completed/failed → ...`). Today the only way is `takt bead show <id>` (full JSON dump) followed by inline parsing. Real example from a recent agent transcript:
   ```python
   cat .takt/beads/B-74f58f45.json | python3 -c "
       import json, sys
       d = json.load(sys.stdin)
       for e in d.get('execution_history', []):
           ts = e.get('timestamp','')[:19]
           ev = e.get('event','')
           summary = e.get('summary','')[:120]
           print(f'  [{ts}] {ev}: {summary}')
   "
   ```
   This pattern repeats across many sessions and frequently breaks under shell quoting.
2. **No field projection on `bead show`.** `takt bead show <id>` is all-or-nothing: full JSON or nothing. Agents wanting just `block_reason`, `handoff_summary.completed`, `status`, or `execution_history[-1].event` reach for inline JSON parsing every time.
3. **`bead list` filters are limited to `--label`.** Common queries like "what's in progress right now?" or "list all blocked tester beads in this feature tree" require fetching the full list and filtering with inline Python. Two filter dimensions are missing: status and agent type.

## Changes

### New subcommand: `takt bead history <id>`

Formatted execution_history view. Default output is a one-line-per-entry table; flags control filtering and format.

```
takt bead history <id> [--limit N] [--event EVENT ...] [--json] [--plain]
```

- **Default output** (TTY or `--plain`):
  ```
  [2026-05-05T07:40:01] created            Bead created
  [2026-05-05T08:02:51] skills_loaded      Loaded 6 skill(s) for isolated execution
  [2026-05-05T08:02:51] started            Worker started
  [2026-05-05T08:02:52] guardrails_applied Applied guardrails from .takt/agent-runs/...
  [2026-05-05T08:17:53] failed             Worker execution failed: Agent timed out after 900 seconds
  [2026-05-05T08:17:56] retried            Requeued blocked bead after transient infrastructure/auth error
  ```
  Timestamp truncated to seconds (ISO-8601, no fractional part). Event column padded to a fixed width within the rendered output. Summary column truncated to fit the terminal width when rendering to a TTY; full text always retained when `--plain`.
- **`--limit N`** — show only the last N entries. Default: all.
- **`--event EVENT`** — filter to entries whose `event` field matches. Repeatable; OR semantics across multiple values. Example: `takt bead history B-... --event failed --event retried`.
- **`--json`** — emit the raw `execution_history` array as JSON (one line per entry would be `--json --jsonl`, but JSONL is out of scope for v1; use a single JSON array).
- **`--plain`** — pipe-friendly output: identical to default but never truncates the summary column. Mutually exclusive with `--json`.

Resolution of `<id>` reuses `RepositoryStorage.resolve_bead_id(prefix)` so partial IDs work (`takt bead history B-74f5` resolves like other commands).

### New flag on `takt bead show`: `--field PATH`

Project a single field from the bead JSON, jq-like dotted path with array index support.

```
takt bead show <id> --field <PATH>
```

- **Path syntax**: dotted path with bracket-style array indexing, including negative indices.
  - `--field status`
  - `--field block_reason`
  - `--field handoff_summary.completed`
  - `--field handoff_summary.verdict`
  - `--field execution_history[-1].event`
  - `--field expected_files[0]`
- **Output rendering** by value type:

  | Value type | Rendered as | Example |
  |---|---|---|
  | `str` | bare value + newline, no surrounding quotes | `status` → `done\n` |
  | `int` / `float` | `str(value)` + newline | `retries` → `2\n` |
  | `bool` | lowercase `true` / `false` + newline (matches JSON convention) | `requires_followup` → `true\n` |
  | `null` (JSON null / Python `None`) | empty line (just `\n`) | `lease` on a non-leased bead → `\n` |
  | empty string `""` | empty line (just `\n`) | `block_reason` on a never-blocked bead → `\n` |
  | `list` / `dict` | pretty JSON (indent=2) + newline | `handoff_summary` → multi-line JSON |

- **Path resolution semantics**:
  - **Path doesn't exist** (e.g. `--field handoff_summary.fooBar` where `fooBar` is not a key): exit non-zero with stderr `field not found: handoff_summary.fooBar`. No stdout output. This masks bugs less than silent empty output.
  - **Path exists but value is null / empty string** (the bead simply hasn't set it yet — common for `block_reason`, `handoff_summary`, etc. on early-lifecycle beads): exit zero, output the empty-line per the table above. This is NOT an error — a never-blocked bead legitimately has `block_reason: null`.
  - **Array index out of range** (`expected_files[5]` on a 3-element list): treat as path-doesn't-exist, exit non-zero with stderr `field not found: expected_files[5] (length 3)`.
- **Combinable with `--json`** (existing flag, if present)? Out of scope: `--field` always returns the projected value; `--json` is for full-bead JSON output.

### New filter on `takt bead list`: `--status STATUS`

Repeatable, OR semantics within `--status` (a bead matches if its status is in the requested set), AND with other filters (`--label`).

```
takt bead list --status in_progress --plain
takt bead list --status ready --status blocked --label urgent --plain
```

Valid values: `open`, `ready`, `in_progress`, `done`, `blocked`, `handed_off`. Validation at parse time with a friendly error listing the allowed set.

### New filter on `takt bead list`: `--agent AGENT`

Repeatable, OR semantics within `--agent`, AND with other filters.

```
takt bead list --agent tester --status ready --plain
takt bead list --agent developer --agent recovery
```

Valid values: any of the agent types defined in the config (today `planner`, `developer`, `tester`, `documentation`, `review`, `recovery`). Validation: reuse the same agent-type registry the rest of the codebase uses, so adding a new agent type doesn't require updating the CLI.

### New filter on `takt bead list`: `--feature-root <id>`

Restrict the list to beads whose `feature_root_id` matches. Mirrors the existing `--feature-root` flag on `takt summary`. Single-valued (not repeatable); combines AND-wise with `--status`, `--agent`, `--label`.

```
takt bead list --feature-root B-9472cbcc --plain
takt bead list --feature-root B-9472cbcc --status ready --agent tester --plain
```

Resolution of the `<id>` reuses `RepositoryStorage.resolve_bead_id(prefix)` so partial IDs work.

## Files to Modify

| File | Change |
|---|---|
| `src/agent_takt/cli/parser.py` | Add `history` subcommand under `bead`; add `--field` flag on `show`; add `--status`, `--agent`, `--feature-root` flags on `list`. |
| `src/agent_takt/cli/commands/bead.py` | Implement `command_bead_history()` handler; extend `command_bead_show()` to support `--field`; extend `command_bead_list()` to apply `--status`, `--agent`, and `--feature-root` filters. |
| `src/agent_takt/cli/formatting.py` | Add `format_bead_history_plain(entries, *, plain=False, terminal_width=None)` and `format_bead_field(value)` helpers. Reuse `format_bead_list_plain` (extend its filtering rather than duplicate). |
| `tests/test_cli_bead.py` | Add tests for the four new surfaces (see Test Plan). |
| `CLAUDE.md` | Update the "Working with Beads" section to list the new commands as the canonical introspection paths; remove or de-emphasise references to inline JSON parsing if any. |

## Test Plan

In `tests/test_cli_bead.py`:

1. **`takt bead history` default output** — bead with 3 execution records → output has one line per record, format matches the spec example, sorted ascending by timestamp.
2. **`takt bead history --limit N`** — bead with 5 records, `--limit 2` → only the last 2.
3. **`takt bead history --event EVT`** (single) — bead with mixed events → only matching entries.
4. **`takt bead history --event A --event B`** (repeated) — OR semantics: matches entries with event A or B.
5. **`takt bead history --json`** — emits a JSON array equal to the bead's `execution_history`.
6. **`takt bead show --field PATH` scalar** — `--field status` returns the bead's status as a bare string with newline.
7. **`takt bead show --field PATH` nested object** — `--field handoff_summary.completed` returns the string value.
8. **`takt bead show --field PATH` array index** — `--field execution_history[-1].event` returns the last entry's event.
9. **`takt bead show --field` missing path** — exits non-zero with stderr `field not found: ...` and no stdout output.
10. **`takt bead show --field` object value** — `--field handoff_summary` (the whole object) emits pretty JSON.
11. **`takt bead list --status in_progress`** — matches only in-progress beads.
12. **`takt bead list --status ready --status blocked`** — OR within `--status`.
13. **`takt bead list --status invalid`** — exits non-zero with stderr listing valid statuses.
14. **`takt bead list --agent tester --status ready`** — AND across `--status` and `--agent`; combined with `--label` works.
15. **`takt bead list --agent invalid`** — exits non-zero with stderr listing valid agent types.
16. **`takt bead list --feature-root B-xxxx`** — returns only beads whose `feature_root_id` matches; combines AND-wise with `--status`, `--agent`, `--label`.
17. **`takt bead show --field` for a `null` value** — `--field lease` on a non-leased bead returns an empty line (`\n`), exits zero. Confirms null-vs-missing distinction.
18. **`takt bead show --field` for a `bool` value** — `--field handoff_summary.requires_followup` returns `true` or `false` (lowercase), exits zero.
19. **`takt bead show --field` for an `int` value** — `--field retries` on a bead with `retries=2` returns `2\n`, exits zero.
20. **`takt bead show --field` array out of range** — `--field expected_files[99]` on a 3-element list exits non-zero with stderr `field not found: expected_files[99] (length 3)`.
21. **Backwards-compat**: `takt bead list` with no filters returns the same JSON as before. `takt bead show <id>` with no `--field` returns the same JSON as before. `takt bead list --label X` (existing filter) still works.

## Acceptance Criteria

1. `uv run takt bead history <id>` exists and prints a chronological one-line-per-entry view of the bead's `execution_history` matching the format in the Changes section.
2. `--limit N`, `--event EVT` (repeatable), `--json`, and `--plain` flags on `bead history` work per the spec.
3. `uv run takt bead show <id> --field PATH` exists and supports dotted paths, array indexing including negative indices, and emits pretty JSON (indent=2) for non-scalar values.
4. `--field` rendering rules match the table in the Changes section: bare strings unquoted, `int`/`float` via `str()`, `bool` lowercased (`true`/`false`), `null` and empty string render as a single newline, lists/dicts as pretty JSON.
5. `--field` failure modes: path-not-found exits non-zero with stderr `field not found: <path>`; null/empty-string-but-valid-path exits zero with empty-line output (legitimate "field unset" case); array index out of range exits non-zero with stderr including the actual length.
6. `uv run takt bead list --status STATUS` is repeatable, validates against the allowed set, and combines AND-wise with other filters (`--label`, `--agent`, `--feature-root`).
7. `uv run takt bead list --agent AGENT` is repeatable, validates against the configured agent types, and combines AND-wise with other filters.
8. `uv run takt bead list --feature-root <id>` filters to beads in that feature tree, supports prefix resolution, and combines AND-wise with other filters.
9. All existing `takt bead list` and `takt bead show` invocations behave identically when none of the new flags are passed (backwards compatibility).
10. All new flags are documented in `--help` text for their respective subcommands.
11. `CLAUDE.md` "Working with Beads" section is updated to list the new commands and de-emphasise inline JSON parsing.
12. `uv run pytest tests/ -n auto -q` passes with the 21 new tests above plus no regressions.

## Pending Decisions

1. ~~**Path syntax for `--field`**~~ — **Resolved 2026-05-05**: Python-style without leading dot (`handoff_summary.completed`, NOT `.handoff_summary.completed`). Friendlier under shell quoting and consistent with takt's existing CLI conventions; the Changes section commits to this via examples already.
2. ~~**Negative array indices in `--field`**~~ — **Resolved 2026-05-05**: yes. `execution_history[-1].event` is the canonical "latest event" idiom and is shown as a documented example in the Changes section.
3. **`--field` output for non-scalars** — pretty JSON (indented) or compact JSON? Draft: pretty (indent=2) for human readability when piped to a pager; compact for `| jq` pipelines. Lean pretty since most consumers will be agents reading the output, not pipes; if compact is needed later, add `--field-format compact`.
4. **Multi-bead `show <id1> <id2> ...`** — useful for the cross-reference pattern but adds CLI complexity. Draft: out of scope for v1; revisit if the inline-loop pattern keeps appearing in transcripts after these four additions land.
5. ~~**`takt bead list --feature-root <id>` filter**~~ — **Resolved 2026-05-05**: included in this spec. `summary` already supports this filter; adding it to `list` closes a parallel inline-filter gap with negligible additional implementation cost. Spec body, Files to Modify, Test Plan (#16), and Acceptance Criterion #8 all reflect this.
6. **Curated `bead show --short`** — a one-screen summary view (status, agent, title, last event, block_reason, handoff verdict) for quick at-a-glance use. Draft: out of scope for v1; `--field` covers the targeted-projection cases, and `--short` is more design work (which fields to include?) than the four core additions.
