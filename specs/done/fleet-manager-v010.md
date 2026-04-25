---
name: Fleet Manager v0.1.0
id: spec-0ba9d2a3
description: "A sibling CLI (takt-fleet) to manage multiple takt projects from one place: register projects, fan out ad-hoc beads or trigger multi-project runs, aggregate status, and log each fleet run for later querying."
dependencies: null
priority: medium
complexity: medium
status: done
tags:
- fleet
- cli
- multi-project
scope:
  in: "New sibling package `agent_takt_fleet`, `takt-fleet` CLI, project registry, fan-out for dispatch (ad-hoc bead per project) and run (execute what's queued), snapshot + live aggregation, run log with query CLI."
  out: "Cross-project specs, cross-project bead dependencies, coordinated merges, remote/networked projects, web UI, persistent daemon, authentication."
feature_root_id: B-7a0391f9
---
# Fleet Manager v0.1.0

## Objective

Operators of takt are now running it across multiple projects. Doing routine cross-cutting work ("check dependencies for tech debt", "audit test coverage", "apply this spec to all Python services") means repeating the same CLI dance N times, one project at a time, with no unified view of what's happening or what happened. This spec introduces **`takt-fleet`**, a sibling CLI that treats N takt projects as a fleet: register them once, dispatch work to a named subset, watch the merged event stream, and keep a queryable log of every fleet run so operators can answer "what did I run across my projects last week, and how did each one turn out?"

The v0.1.0 scope is deliberately narrow and addresses two distinct operator use cases:

1. **Cross-project ad-hoc beads** — fan out a single one-shot instruction ("check dependencies for tech debt", "upgrade library X if present") to each target project as a new bead. This is the primary pain point.
2. **Multi-project executor** — trigger `takt run` across projects to work through whatever is already queued in each, regardless of origin. `takt-fleet` effectively becomes a parallel executor that drains the backlog across the fleet.

Cross-project **specs** are explicitly out of scope. Specs are usually shaped around one project's structure, and forcing the same spec onto multiple repos tends to produce awkward fits rather than useful fan-out. Stick to the two use cases above.

Everything else — coordination, cross-project bead dependencies, networked projects — is also out of scope. Build the minimum that removes the "do it N times" chore and produces an audit trail; revisit coordination features only after real usage reveals which ones are actually needed.

## Problems to Fix

1. **Repetitive cross-project chores.** Running the same instruction ("check dependencies for tech debt") across N projects requires N separate `cd`, `takt bead create`, `takt run`, `takt merge` cycles. Nothing in takt today accepts a list of projects.
2. **No unified view of fleet state.** Operators must run `takt summary` in each project manually to know where everything stands. There is no aggregated "fleet summary".
3. **No merged live stream.** When multiple `takt run` invocations are in flight across projects, the operator cannot watch a merged event stream — they must tail each project's log separately.
4. **No multi-project execution trigger.** Even when beads are already queued across projects, operators must invoke `takt run` per project by hand. There is no "work through everything pending across the fleet" action.
5. **No record of fleet operations.** After a fan-out completes, the results scroll by in the terminal and are lost. There is no persistent log of "which projects were targeted, what was dispatched, and what happened in each one."
6. **Unclear boundary if these features land inside `agent_takt`.** Stuffing fleet logic into the existing `takt` CLI muddies the mental model ("is takt repo-local or global?") and invites tight coupling between the orchestrator and the fleet layer. A sibling package enforces a clean CLI-level boundary.

## Changes

### New package: `src/agent_takt_fleet/`

A new Python package alongside `src/agent_takt/`, shipped from the same repo, installed via the same `pyproject.toml`, exposing a new console script `takt-fleet`.

**Architectural rule (project interaction contract):** `agent_takt_fleet` interacts with each registered project **exclusively through the `takt` CLI (subprocess) and by reading documented `.takt/` telemetry files** (e.g. `events.jsonl`, `takt ... --json` stdout). Fleet must **never**:

- Write to any file under a project's `.takt/` directory (including bead JSON, logs, telemetry, config).
- Invoke takt's domain logic (`agent_takt.storage`, `agent_takt.scheduler`, `agent_takt.runner`, `agent_takt.gitutils`, `agent_takt.planner`) against a project's filesystem path.
- Use any non-subprocess mechanism to mutate project state.

Code sharing within the repo is otherwise unconstrained. Fleet may freely import utilities, helpers, formatters, and dataclass models from `agent_takt` (e.g. `agent_takt.console`, `agent_takt.models`). The boundary is about what fleet **does to projects**, not what it **imports**.

**Enforcement (`tests/fleet/test_boundaries.py`):**

1. **Write-path centralisation** — the only modules in `src/agent_takt_fleet/` permitted to perform filesystem writes (`open(..., 'w'|'a'|'x'|...)`, `Path.write_text()`, `Path.write_bytes()`, `shutil` writes, `yaml.safe_dump` to a file, `json.dump` to a file) are `registry.py` and `runlog.py`. Any such call elsewhere in the package fails the test. Implementation: AST scan of all `.py` files under `src/agent_takt_fleet/`.
2. **Fleet-owned write targets** — the writes performed by `registry.py` and `runlog.py` target only fleet-owned paths (the registry file under `$XDG_CONFIG_HOME/agent-takt/` and run log files under `$XDG_DATA_HOME/agent-takt/fleet/runs/`). Unit-tested directly in `test_registry.py` and `test_runlog.py`; the boundary test documents the invariant as a comment, without re-enforcing it here.
3. **Forbidden domain-logic imports** — no file under `src/agent_takt_fleet/` imports from `agent_takt.storage`, `agent_takt.scheduler`, `agent_takt.runner`, `agent_takt.gitutils`, `agent_takt.planner`, or `agent_takt.cli.*`. AST scan.
4. **Project-path usage is confined to `adapter.py`** — only `adapter.py` (where `TaktAdapter` lives) may accept or operate on a registered project's path. Other modules that touch a project path must do so via `TaktAdapter`. AST scan for `subprocess.*` calls with `cwd=` outside `adapter.py`.

### `pyproject.toml` — new console script

```toml
[project.scripts]
takt = "agent_takt.cli:main"
takt-fleet = "agent_takt_fleet.cli:main"
```

### Package layout

```
src/agent_takt_fleet/
  __init__.py
  cli/
    __init__.py       # main() entry point, dispatch
    parser.py         # argparse construction
    commands/
      __init__.py
      register.py     # register, unregister, list
      dispatch.py     # takt-fleet dispatch
      run.py          # takt-fleet run
      summary.py      # takt-fleet summary
      watch.py        # takt-fleet watch
      runs.py         # takt-fleet runs {list,show}
  registry.py         # YAML registry I/O, tag/path filtering
  adapter.py          # TaktAdapter: subprocess wrapper around `uv run takt ...`
  executor.py         # concurrent fan-out (ThreadPoolExecutor)
  tailer.py           # events.jsonl tailing + merge
  runlog.py           # fleet run log: write, read, list, query
  formatters.py       # table + event-stream rendering helpers
  models.py           # dataclasses: Project, ProjectResult, FleetRun, RunInputs
  paths.py            # resolve $XDG_CONFIG_HOME, $XDG_DATA_HOME with fallbacks
tests/fleet/
  test_registry.py
  test_adapter.py
  test_executor.py
  test_tailer.py
  test_runlog.py
  test_formatters.py
  test_cli_register.py
  test_cli_dispatch.py
  test_cli_run.py
  test_cli_summary.py
  test_cli_watch.py
  test_cli_runs.py
  test_boundaries.py  # asserts no forbidden imports from agent_takt internals
```

### CLI surface

All commands accept `--tag TAG` (repeatable, AND semantics) and `--project NAME` (repeatable) filters. Filters combine: the target set is projects matching ANY of the listed `--project` names AND ALL of the listed `--tag` values.

#### Registry management

```
takt-fleet register <path> [--name NAME] [--tag TAG ...]
takt-fleet unregister <path-or-name>
takt-fleet list [--tag TAG ...] [--plain]
```

- `register` — canonicalises `path` to absolute, ensures it exists, ensures `.takt/` subdir exists (warns if not), writes to the registry. `--name` defaults to the basename of the path. Refuses to register a duplicate path.
- `unregister` — removes by name or path.
- `list` — prints registered projects with columns: `name`, `path`, `tags`, `health`. `--plain` for a pipe-friendly table.

**Health values** (computed fresh on each invocation, short-circuit in the order listed):

| Value | Condition |
|---|---|
| `missing` | The registered `path` does not exist on disk. |
| `no-takt` | `path` exists but `path/.takt/` does not, or `path/.takt/config.yaml` is absent. |
| `takt-error` | `uv run takt --version` with `cwd=path` exits non-zero or times out (5s). |
| `ok` | All of the above checks pass. |

`takt-version-mismatch` is **deferred** — v0.1.0 does not attempt to compare the project's takt version against any reference (since we decided each project uses its own `uv run takt`, mismatch isn't semantically useful). The column value set is exactly the four above.

#### Fan-out: dispatch

```
takt-fleet dispatch --title TITLE --description DESC --agent AGENT
                    [--tag TAG ...] [--project NAME ...]
                    [--label LABEL ...] [--max-parallel N]
```

Creates a single ad-hoc bead in each target project via `takt bead create`. This is the primary path for one-shot instructions like "check dependencies for tech debt" or "upgrade library X if present" — no spec file needed, one bead per project.

- `--agent` defaults to `developer`. Must be one of the allowed agent types (`developer`, `tester`, `documentation`, `review`).
- Default `--max-parallel` = `min(len(target_projects), 4)`.
- Records the created bead ID per project in the run log.
- Does **not** trigger execution. Operators run `takt-fleet run` separately to actually work the beads (or run `takt run` per project). This keeps dispatch (write) and execution (expensive) decoupled.

#### Fan-out: run

```
takt-fleet run [--tag TAG ...] [--project NAME ...]
               [--max-parallel N] [--runner codex|claude]
               [--project-max-workers N]
```

Works through whatever is already queued (`ready` / `in_progress`) in each target project — regardless of where those beads came from (dispatch, `takt plan`, manual creation, follow-ups). This is the "multi-project executor" use case.

- Spawns `uv run takt run` (with `--runner` and `--max-workers` forwarded) in each target project as a subprocess.
- Captures the final JSON block each `takt run` emits on stdout.
- Fleet's `--max-parallel` is how many project-level `takt run` calls run concurrently; `--project-max-workers` is forwarded to each one as `--max-workers`.
- Prints an aggregate report when all projects finish (or streams project-by-project as they complete, with a final summary).

#### Aggregation: summary

```
takt-fleet summary [--tag TAG ...] [--project NAME ...] [--json] [--plain]
```

For each target project, shells out `uv run takt summary --json` in parallel and prints a unified table:

```
PROJECT      DONE  READY  IN_PROGRESS  BLOCKED  HANDED_OFF  HEALTH
api-svc        42     3            2        0           0  ok
web-ui         17     0            0        1           0  ok
legacy-batch    -     -            -        -           -  no-takt
```

- `--json` — emit the aggregate as JSON for scripting.
- Errors per project (e.g. missing `.takt/`) are shown as `-` in columns and a health tag; the command always exits 0 if *any* project was queried.

#### Aggregation: watch

```
takt-fleet watch [--tag TAG ...] [--project NAME ...] [--since DURATION]
```

Tails `.takt/logs/events.jsonl` in each target project concurrently. Prints a merged stream, one line per event, prefixed with a project-coloured tag:

```
[api-svc     ] 14:02:31  bead_started       B-a1b2c3d4
[web-ui      ] 14:02:32  cycle_started
[api-svc     ] 14:02:45  bead_completed     B-a1b2c3d4  (verdict=approved)
```

- `--since DURATION` (e.g. `5m`, `1h`) — replay recent events before streaming new ones. Default: live only (start from EOF).
- Implementation: one polling thread per project (1s interval, `seek(0,2)` then read new lines); one stdout printer thread draining a merged `queue.Queue`.

**`--since` replay mechanics:** each event line in `events.jsonl` carries a top-level `timestamp` field (ISO-8601). On `--since`, the tailer:

1. Opens `events.jsonl` and scans from the start, streaming any line whose `timestamp` is within the requested window (cutoff = `now - DURATION`).
2. Once the scan reaches the end of file, continues in live mode from the current position.
3. If the file is shorter than the requested window (e.g. recently truncated or rotated by external means — takt does not rotate `events.jsonl` itself in v0.1.0, but the operator may), the tailer emits whatever it finds and logs a single warning per project: `watch: <project>: events.jsonl covers only N minutes, requested <DURATION>`. It does NOT attempt to read backup/rotated logs; v0.1.0 is best-effort on replay.
4. Events whose `timestamp` is unparseable are skipped with a debug-level log entry, not a hard failure.

### Registry

#### Storage location

- `$XDG_CONFIG_HOME/agent-takt/fleet.yaml` (fallback: `~/.config/agent-takt/fleet.yaml`).

#### Schema — `fleet.yaml`

```yaml
version: 1
projects:
  - name: api-svc
    path: /Users/you/Projects/api-svc
    tags: [python, backend]
  - name: web-ui
    path: /Users/you/Projects/web-ui
    tags: [typescript, frontend]
```

- `version: 1` — integer schema version. Required. Bumped on any incompatible shape change (e.g. renaming a field, adding per-project settings that older code can't ignore).
- `projects` — list of project records. Each has `name` (unique within the file), `path` (absolute, canonicalised), `tags` (list of strings; defaults to empty).

**Load behaviour:**

- Missing file — treated as an empty registry (`version: 1`, `projects: []`). No error.
- `version` absent — loader rejects the file with a clear error pointing the operator at `takt-fleet` version compatibility. Do not silently assume v1. Hand-edited pre-versioning drafts must add `version: 1` manually.
- `version` newer than the current code understands — loader rejects with a "registry written by a newer takt-fleet; upgrade" error.
- `version` older than current and unsupported — loader rejects; v0.1.0 only knows about `version: 1` so this is not yet reachable.

**Write behaviour:** `registry.py` always writes `version: 1` and the full `projects` list. Atomic write (temp file + rename). No partial updates.

**Forward-compatibility philosophy:** bumping `version` is a deliberate act tied to a schema change. Purely additive fields on existing records (e.g. a future optional `environment` key on a project) do NOT require a version bump — old code ignores unknown keys. A bump is reserved for removals, renames, or semantic changes.

### Fleet run log

#### Storage location

- Run logs: `$XDG_DATA_HOME/agent-takt/fleet/runs/<run_id>.json` (fallback: `~/.local/share/agent-takt/fleet/runs/<run_id>.json`). One JSON file per run.
- Run ID format: `FR-<8 hex chars>` (prefix is "Fleet Run"; distinct from takt's `B-` bead prefix so they never collide visually).

#### Schema — `<run_id>.json`

```json
{
  "version": 1,
  "run_id": "FR-a1b2c3d4",
  "command": "dispatch|run",
  "started_at": "2026-04-24T14:02:00+00:00",
  "finished_at": "2026-04-24T14:05:12+00:00",
  "inputs": {
    "bead": {"title": "...", "description": "...", "agent_type": "developer", "labels": ["..."]},
    "tag_filter": ["python"],
    "project_filter": [],
    "max_parallel": 4,
    "runner": "claude",
    "project_max_workers": null
  },
  "projects": [
    {
      "name": "api-svc",
      "path": "/Users/.../api-svc",
      "status": "success|error|skipped",
      "started_at": "2026-04-24T14:02:00+00:00",
      "finished_at": "2026-04-24T14:04:50+00:00",
      "error": null,
      "outputs": {
        "created_beads": ["B-abcd1234"],
        "run_summary": {"started": [...], "completed": [...], "blocked": [...], "final_state": {...}}
      }
    }
  ],
  "aggregate": {
    "total": 3,
    "succeeded": 2,
    "failed": 1,
    "skipped": 0
  }
}
```

`inputs.bead` is non-null for `command == "dispatch"` and null for `command == "run"`.

`outputs.created_beads` is populated by `dispatch` (one entry per project); `outputs.run_summary` is populated by `run`. The other is `null`.

**Write protocol:** the run log file lives at its final path (`<run_id>.json` under the runs directory) for the entire lifetime of the fleet run. It is created when the fleet run starts (with `finished_at: null` and `projects: []`) and is rewritten **atomically** (write to a sibling temp file, then `os.replace()` onto the final name) on every meaningful state change:

1. When the run starts — initial record.
2. Each time a project completes (success, error, or skipped) — append the `ProjectResult` to `projects[]`, bump `aggregate` counts.
3. On final aggregation — set `finished_at` to the current timestamp.
4. On crash (Ctrl-C, adapter exception) — set `crashed: true` and `finished_at` to the current timestamp before exiting.

`finished_at` is the authoritative terminal marker for consumers. `runs show` treats `finished_at == null` as "still in progress" and enters tail mode; any non-null value means the record is final (even if `crashed: true`). Readers must tolerate concurrent reads during tail mode — `os.replace()` is atomic on POSIX so a reader always sees a complete JSON document, never a partial write.

**Versioning:** every run log record carries a top-level `version: 1` integer. Same load/write rules as the registry — missing `version` is rejected, unknown higher versions are rejected, `runlog.py` always writes `version: 1`. `runs list` and `runs show` silently skip files with unrecognised versions and log a warning (don't let one bad file break the listing).

#### Query CLI

```
takt-fleet runs list [--limit N] [--since DURATION] [--status success|error|partial|in_progress] [--command dispatch|run] [--plain]
takt-fleet runs show <run-id> [--json]
```

- `runs list` — table with columns: `run_id`, `started_at`, `command`, `projects` (count), `succeeded`, `failed`, `duration`. Most recent first. Default `--limit` = 20.
- `runs show <run-id>` — single command for both live and completed runs. Auto-detects state by reading the run log file: if `finished_at == null`, tails the in-progress record, printing project completions as they happen and exiting cleanly when `finished_at` is written; otherwise prints the detailed breakdown (inputs, per-project status table, errors inline, terminal-friendly visualisation with green/red/yellow status glyphs). `--json` always dumps the raw record as-is (no tailing). Scoped to one fleet run — distinct from `watch`, which is a live stream of takt events across all registered projects regardless of run.
- Prefix resolution: `<run-id>` accepts unambiguous prefixes (e.g. `FR-a1b2` if unique), mirroring `takt`'s bead prefix resolution.

#### Visualisation for `runs show` (completed run)

Output layout for a completed run (rich-style table, plain-text fallback when not a TTY):

```
Fleet Run FR-a1b2c3d4
  Command:    dispatch
  Started:    2026-04-24 14:02:00
  Duration:   3m 12s
  Inputs:
    bead:     title="Check deps for tech debt", agent=developer
    filters:  tags=[python]
  Projects:
    ✓ api-svc         success   B-abcd1234  (2m 50s)
    ✓ worker-pool     success   B-ef567890  (1m 42s)
    ✗ legacy-batch    error                 (0m 03s)  takt binary not found on PATH
  Aggregate: 2 succeeded, 1 failed, 0 skipped (total 3)
```

For an in-progress run, `runs show` tails the record — printing a header, then one line per project as each one transitions to a terminal state, and a final aggregate line when `finished_at` is written:

```
Fleet Run FR-a1b2c3d4  (in progress)
  Command:    run
  Started:    2026-04-24 14:02:00
  Projects:   3 total, 0 complete

  ✓ api-svc         success   (2m 50s)
  ✓ worker-pool     success   (1m 42s)
  ✗ legacy-batch    error     (0m 03s)  takt binary not found on PATH

  Aggregate: 2 succeeded, 1 failed, 0 skipped (total 3)  — finished in 3m 12s
```

Implementation: poll the run log file (1s interval), diff against last-seen `projects[]`, print new terminal-state entries. Exit cleanly when `finished_at != null`.

### Models (`models.py`)

```python
@dataclass(frozen=True)
class Project:
    name: str
    path: Path
    tags: tuple[str, ...]

@dataclass(frozen=True)
class RunInputs:
    bead: dict | None          # {title, description, agent_type, labels} — set for dispatch, None for run
    tag_filter: tuple[str, ...]
    project_filter: tuple[str, ...]
    max_parallel: int
    runner: str | None
    project_max_workers: int | None

@dataclass
class ProjectResult:
    name: str
    path: Path
    status: str                # "success" | "error" | "skipped"
    started_at: datetime
    finished_at: datetime | None
    error: str | None
    outputs: dict              # {created_beads: [...] | None, run_summary: {...} | None}

@dataclass
class FleetRun:
    run_id: str                # "FR-<8hex>"
    command: str               # "dispatch" | "run"
    started_at: datetime
    finished_at: datetime | None
    inputs: RunInputs
    projects: list[ProjectResult]
    crashed: bool = False

    @property
    def aggregate(self) -> dict: ...
```

### Adapter (`adapter.py`)

```python
class TaktAdapter:
    def __init__(self, project_path: Path, timeout: int | None = None): ...

    def summary(self) -> dict: ...
    def create_bead(self, title: str, description: str,
                    agent_type: str, labels: list[str]) -> str: ...
    def run(self, runner: str | None, max_workers: int | None) -> dict: ...
    def version(self) -> str: ...
```

Each method shells out via `subprocess.run(["uv", "run", "takt", ...], cwd=self.project_path, capture_output=True, text=True, timeout=self.timeout)`, parses JSON from stdout, and raises `AdapterError` on non-zero exit or malformed JSON. The error carries stdout/stderr for run log recording.

### Concurrency

`executor.fan_out(projects, fn, max_parallel)` uses `concurrent.futures.ThreadPoolExecutor`. Each fanned-out call is a subprocess, so threads just multiplex I/O. Exceptions per project are captured (not re-raised) and surfaced in the aggregated `ProjectResult`. Ctrl-C propagates as `KeyboardInterrupt` and terminates in-flight subprocesses.

## Files to Modify

| File | Change |
|---|---|
| `pyproject.toml` | Add `takt-fleet = "agent_takt_fleet.cli:main"` to `[project.scripts]`. |
| `src/agent_takt_fleet/` | New package — full contents per layout above. |
| `src/agent_takt_fleet/cli/__init__.py` | `main()` entry point; argparse dispatch for `register`, `unregister`, `list`, `dispatch`, `run`, `summary`, `watch`, `runs`. |
| `src/agent_takt_fleet/cli/parser.py` | Argparse construction with shared `--tag`, `--project` filters and per-command flags. |
| `src/agent_takt_fleet/cli/commands/*.py` | One module per command group. |
| `src/agent_takt_fleet/registry.py` | YAML I/O for `fleet.yaml` (schema version 1); `load_registry()`, `save_registry()`, `filter(projects, tags, names)`; rejects missing or unknown-version files with clear errors. |
| `src/agent_takt_fleet/adapter.py` | `TaktAdapter` subprocess wrapper. |
| `src/agent_takt_fleet/executor.py` | `fan_out()` ThreadPoolExecutor helper. |
| `src/agent_takt_fleet/tailer.py` | Per-project `events.jsonl` tailing; merged queue. |
| `src/agent_takt_fleet/runlog.py` | Write/read/list/query fleet run records. |
| `src/agent_takt_fleet/formatters.py` | Table + event-stream rendering. |
| `src/agent_takt_fleet/models.py` | Dataclasses per above. |
| `src/agent_takt_fleet/paths.py` | XDG path resolution with fallbacks. |
| `tests/fleet/` | New test package mirroring `src/agent_takt_fleet/`. |
| `tests/fleet/test_boundaries.py` | Enforce the project interaction contract via AST scans (see "Architectural rule" above): writes only from `registry.py` / `runlog.py`; no imports from `agent_takt.storage`/`scheduler`/`runner`/`gitutils`/`planner`/`cli.*`; `subprocess` calls with `cwd=` only inside `adapter.py`. |
| `CLAUDE.md` | Add a "Fleet Manager" section (short) pointing to the spec and listing the top-level commands. |
| `docs/fleet.md` | New user-facing doc: registry setup, command reference, run log format. |

## Acceptance Criteria

1. `uv run takt-fleet register <path> --tag python` adds the project to `fleet.yaml`; `uv run takt-fleet list` shows it; `uv run takt-fleet unregister <path>` removes it.
2. `uv run takt-fleet list` computes and reports `health` correctly for each registered project, per the table in the Registry section: `missing` when the path is absent, `no-takt` when `.takt/` is absent, `takt-error` when `uv run takt --version` fails, `ok` otherwise.
3. `uv run takt-fleet summary` prints a table showing counts for every registered project; projects with missing `.takt/` are shown with a `no-takt` health tag but do not abort the command.
4. `uv run takt-fleet dispatch --title "Check deps" --description "..." --agent developer --tag python` creates one bead in each matching project; bead IDs recorded in the run log. Does not trigger execution.
5. `uv run takt-fleet run --tag python` invokes `takt run` in each matching project concurrently (capped by `--max-parallel`); final JSON summaries captured per project; aggregate printed at the end.
6. `uv run takt-fleet watch --tag python` prints a merged live stream of `events.jsonl` lines from all matching projects, prefixed with a project tag; Ctrl-C exits cleanly.
7. `uv run takt-fleet runs list` shows the 20 most recent fleet runs; filters by `--status`, `--command`, `--since` work as specified.
8. `uv run takt-fleet runs show <run-id>` auto-detects run state: for a completed run it prints the detailed per-project table with success/error glyphs and error messages inline; for an in-progress run it tails the record live, printing project completions as they happen, and exits cleanly when the run finishes. `--json` always dumps the raw record as-is without tailing.
9. `tests/fleet/test_boundaries.py` passes and covers the four checks listed in the "Architectural rule" section: (a) filesystem writes are confined to `registry.py` and `runlog.py`; (b) write targets are fleet-owned paths only; (c) no imports from `agent_takt.storage` / `scheduler` / `runner` / `gitutils` / `planner` / `cli.*`; (d) `subprocess` calls with `cwd=` only appear in `adapter.py`.
10. A crash (Ctrl-C, adapter exception) during a fleet run still produces a run log file with `crashed: true` and the projects that completed before the crash recorded.
11. All new tests pass under `uv run pytest tests/ -n auto -q` with no regressions to existing `agent_takt` tests.
12. `takt-fleet --help` and every subcommand's `--help` text is present and accurate.
13. `takt-fleet` does not accept any command that distributes or applies a spec across projects — spec fan-out is explicitly out of scope for v0.1.0.

## Pending Decisions

1. ~~**Should `takt-fleet plan` copy the spec file into each project, or pass an absolute path?**~~ — **Resolved 2026-04-24**: `takt-fleet plan` removed from v0.1.0. Cross-project specs are out of scope; the two supported fan-out modes are `dispatch` (ad-hoc bead per project) and `run` (execute what's queued).
2. ~~**Should fleet use the project's `uv run takt` (project's pinned version) or its own?**~~ — **Resolved 2026-04-24**: use the project's. `TaktAdapter` invokes `uv run takt ...` with `cwd=project_path`, which resolves the project's own `uv` environment and its pinned takt version. Lets different projects pin different takt versions independently of `takt-fleet`'s own install.
3. ~~**`runs tail` behaviour for completed runs.**~~ — **Resolved 2026-04-24**: `runs tail` removed; `runs show` is the single command for both live and completed runs. It auto-detects state by checking `finished_at` and either tails the in-progress record or prints the completed breakdown. Simpler CLI, one command to learn. `--json` always dumps as-is without tailing.
4. ~~**Shared code between `agent_takt` and `agent_takt_fleet`.**~~ — **Resolved 2026-04-24**: code sharing is unconstrained. The boundary is reframed as a *project interaction contract*, not an import restriction. Fleet may freely import utilities, helpers, formatters, and dataclass models from `agent_takt`. What fleet may NOT do: touch project state outside the `takt` CLI + documented `.takt/` reads. Specifically forbidden: writing to any project's `.takt/`, importing `agent_takt.storage`/`scheduler`/`runner`/`gitutils`/`planner`/`cli.*`, using `subprocess` with `cwd=<project>` outside `adapter.py`. Enforced by `tests/fleet/test_boundaries.py` (AST scans).
5. ~~**Registry schema evolution.**~~ — **Resolved 2026-04-24**: include a `version: 1` integer field in both `fleet.yaml` and every run log record from day one. Good hygiene — avoids a painful retrofit later. Missing `version` is rejected with a clear upgrade-path error; higher-than-known versions are rejected; additive field changes don't require a bump. Load/write rules documented in the "Registry" and "Fleet run log" schema sections.
6. ~~**Timeouts for `takt-fleet run`.**~~ — **Resolved 2026-04-24**: no timeout in v0.1.0. `takt run` can legitimately run for hours; the operator has Ctrl-C as the escape hatch. Revisit in v0.2 if runaway or stuck subprocesses become a real problem — a `--timeout DURATION` flag can be added without breaking the run log schema.
7. ~~**Run log retention.**~~ — **Resolved 2026-04-24**: no automatic pruning. Run log records are small (a few KB each) and the operator is expected to keep them as long as needed for audit/history. Add `takt-fleet runs prune --older-than DURATION` in v0.2 only if the directory actually grows unmanageable.
8. ~~**Should `takt-fleet dispatch` offer a `--run` convenience flag to chain into `run` immediately?**~~ — **Resolved 2026-04-24**: keep `dispatch` and `run` as separate commands, no chained `--run` flag. Rationale: queueing multiple beads across projects one after another (potentially with different filters/tags) before triggering execution as a single batch is a legitimate workflow. Fold them only if real usage shows the two-step dance is always painful.
