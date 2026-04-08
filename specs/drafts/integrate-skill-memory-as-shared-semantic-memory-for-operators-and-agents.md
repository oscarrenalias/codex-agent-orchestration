---
name: Integrate skill-memory as shared semantic memory for operators and agents
id: spec-cbb95a79
description: "Replace append-only markdown memory with skill-memory (sqlite-vec), shared across operator and workers, with mandatory guardrail enforcement and takt ingest CLI"
dependencies: null
priority: medium
complexity: medium
status: draft
tags:
- memory
- search
- sqlite
- embeddings
- guardrails
- skill-memory
scope:
  in: "Worker memory skill (agents_skills/memory/, claude_skills/memory/); guardrail templates; takt memory ingest CLI; onboarding scaffold; venv/DB path stabilization"
  out: Operator personal cross-session memory (~/.claude/projects/.../memory/); agent output schema; scheduler/planner changes
feature_root_id: null
---
# Integrate skill-memory as shared semantic memory for operators and agents

## Objective

The current shared memory system stores institutional knowledge in two append-only markdown files (`docs/memory/known-issues.md`, `docs/memory/conventions.md`). Agents are instructed to read these files at bead start — but guardrails do not enforce this, memory usage is inconsistent, and there is no retrieval: agents receive all accumulated knowledge regardless of relevance.

This spec replaces the current skill with the external [`skill-memory`](https://github.com/oscarrenalias/skill-memory) package, a self-contained SQLite+sqlite-vec semantic search system using local ONNX embeddings. Both worker agents and the operator (Claude Code) share a single project-level memory database. A new `takt memory ingest` CLI command migrates existing content and allows future bulk ingestion. Agent guardrail templates are updated to make memory access mandatory, not advisory.

## Problems to Fix

1. **Memory usage is advisory, not enforced.** The current SKILL.md says "read both files before touching any code" but guardrail templates contain no corresponding enforcement. Agents regularly skip memory.
2. **No retrieval quality.** Agents read both files in full. As content grows this wastes context budget on irrelevant entries.
3. **Operator and worker memories are disconnected.** The operator (Claude Code) has a separate personal memory under `~/.claude/projects/`. Worker agents share `docs/memory/`. There is no mechanism for the operator's institutional knowledge (things learned across sessions) to be accessible to workers, or vice versa.
4. **No migration path for existing content.** `known-issues.md` and `conventions.md` contain accumulated knowledge that would be lost when switching to the new system.
5. **Venv bootstrapping would be repeated per bead.** `skill-memory` bootstraps a Python venv on first run. Skills are *copied* into each isolated execution root (`.takt/agent-runs/{bead_id}/`), so without intervention every bead would trigger a fresh venv creation — slow and wasteful.
6. **DB path would be per-bead without stabilization.** Unless the DB path is pinned to the project workspace, each bead's memory writes would be isolated and invisible to other agents.

## Changes

### 1. Bundle `skill-memory` into the skill catalog

Copy from the `skill-memory` repository into the bundled skill data:

- `src/agent_takt/_data/agents_skills/memory/memory.py` — the full `skill-memory` CLI script
- `src/agent_takt/_data/agents_skills/memory/SKILL.md` — updated skill instructions (see §3)
- `src/agent_takt/_data/claude_skills/memory/memory.py` — same script
- `src/agent_takt/_data/claude_skills/memory/SKILL.md` — operator-specific instructions (see §3)

The `memory.py` script is self-contained and bootstraps its own venv on first invocation. No changes to `pyproject.toml` or takt's dependency tree are required.

### 2. Stabilize venv and DB paths

Two runtime problems must be solved for skills running inside isolated execution roots:

**Venv path**: `memory.py` creates `.venv/` adjacent to the script. Since skills are copied into each bead's execution root, this would trigger a fresh install per bead. Instead:

- `takt init` runs `memory.py init` once against the project's shared skill installation (`.agents/skills/memory/` or `.claude/skills/memory/`) to pre-build the venv.
- When skills are copied into an execution root (`prepare_isolated_execution_root` in `skills.py`), the pre-built venv is copied alongside the skill. This is a one-time cost at project init, not per bead.
- If the venv is absent from the source skill directory at copy time, `prepare_isolated_execution_root` should call `memory.py init` first to build it before copying.

**DB path**: The memory DB must be shared across all beads and the operator. Set `AGENT_MEMORY_DB` to an absolute path at the workspace root (`{workspace_root}/docs/memory/memory.db`) when launching agents. The workspace is available as a symlink at `exec_root/repo`; the absolute path resolves correctly.

The env var injection point is `runner.py` where the subprocess is launched — add `AGENT_MEMORY_DB` to the subprocess environment using the resolved workspace root path.

### 3. Update memory skill instructions (`SKILL.md`)

**Worker skill** (`agents_skills/memory/SKILL.md`) — replaces the current file-append instructions:

```markdown
# memory

Shared semantic memory stores institutional knowledge accumulated across all beads. Use it to avoid re-learning what the team already knows, and to record findings that future agents should have.

## At Bead Start (mandatory)

Before reading any code or planning your approach, search for relevant context:

    python3 memory/memory.py search "<brief description of your current task>"

Read the top results. Apply relevant entries; ignore entries that don't apply. This is mandatory — do not skip it.

## When to Write a Memory Entry

Write a new entry when you discover something that is:
- Project-wide and reusable (not bead-specific)
- Something that would have changed your approach if you had known it upfront
- Not already covered in CLAUDE.md or your guardrail template

    python3 memory/memory.py add --type convention "Always use X when doing Y"
    python3 memory/memory.py add --type known-issue "Z behaves unexpectedly because W"

Valid types: `convention`, `known-issue`, `decision`, `warning`.

Do NOT write entries for: bead-specific details, ephemeral state, or anything already in CLAUDE.md.

## Access Control

| Agent type    | Read | Write |
|---------------|------|-------|
| Planner       | yes  | `convention` only |
| Developer     | yes  | all types |
| Tester        | yes  | all types |
| Documentation | yes  | no — read-only |
| Review        | yes  | no — read-only |
```

**Operator skill** (`claude_skills/memory/SKILL.md`) — for Claude Code (the operator):

```markdown
# memory

Shared semantic memory stores institutional knowledge accumulated by all agents across all bead runs. The operator has full read/write access including the ability to correct or supersede stale entries.

## On-demand retrieval

Search when starting work on a feature or before making architectural decisions:

    python3 memory/memory.py search "<topic>" --limit 5

## Writing entries

Record non-obvious decisions, architectural choices, and environment quirks that future sessions would benefit from:

    python3 memory/memory.py add --type decision "We chose X over Y because Z"
    python3 memory/memory.py add --type convention "The pattern in this project is..."

## Bulk ingestion

To ingest a file or set of files into memory:

    uv run takt memory ingest <path>   # .md, .txt, .json, or .csv
```

### 4. Update guardrail templates

Add a mandatory memory section to the guardrail templates that will be auto-loaded as `CLAUDE.md` for Claude Code agents.

**`templates/agents/developer.md`** — add after the "Allowed actions" block:

```markdown
## Memory (mandatory)

Before starting: search shared memory for relevant context.

    python3 memory/memory.py search "<summary of your assigned task>"

Apply relevant results. At the end of your bead, if you discovered something reusable (a pitfall, a pattern, a non-obvious behaviour), write it to memory:

    python3 memory/memory.py add --type <type> "<content>"

Valid types: `convention`, `known-issue`, `decision`, `warning`. Do not skip the opening search.
```

Apply the same enforcement block (with role-appropriate write access) to:
- `templates/agents/tester.md` — full write access
- `templates/agents/planner.md` — write `convention` only
- `templates/agents/documentation.md` — search only, no write
- `templates/agents/review.md` — search only, no write

`recovery.md` and `merge-conflict.md` — no memory section needed (operational agents, not knowledge workers).

### 5. Add `takt memory ingest` CLI subcommand

New subcommand added to `src/agent_takt/cli/commands/misc.py` (or a new `memory.py` command module):

```
takt memory ingest <path>          # ingest a file or directory
takt memory ingest --migrate       # migrate docs/memory/known-issues.md and docs/memory/conventions.md
takt memory search "<query>"       # delegate to memory.py search (convenience wrapper)
takt memory rebuild                # rebuild DB from all ingested source files
```

`ingest` delegates to `memory.py ingest` with the `AGENT_MEMORY_DB` env var set to the project-level DB path. It does not re-implement ingestion logic.

`--migrate` is a one-shot convenience flag that:
1. Calls `takt memory ingest docs/memory/known-issues.md`
2. Calls `takt memory ingest docs/memory/conventions.md`
3. Prints a summary of migrated entries
4. Does NOT delete the source files (operator can do that manually after verification)

### 6. Update `scaffold_project()` in `onboarding.py`

After installing skills (`install_agents_skills()` / `install_claude_skills()`), call:

```python
memory_py = project_root / ".agents" / "skills" / "memory" / "memory.py"
subprocess.run([sys.executable, str(memory_py), "init"], check=True, env={
    **os.environ,
    "AGENT_MEMORY_DB": str(project_root / "docs" / "memory" / "memory.db"),
})
```

This bootstraps the venv and creates the DB at init time, so agents never trigger a cold-start venv build.

Add `docs/memory/memory.db` to the `.gitignore` template bundled in `src/agent_takt/_data/`.

## Files to Modify

| File | Change |
|---|---|
| `src/agent_takt/_data/agents_skills/memory/memory.py` | New — copy from skill-memory repo |
| `src/agent_takt/_data/agents_skills/memory/SKILL.md` | Replace with updated worker instructions |
| `src/agent_takt/_data/claude_skills/memory/memory.py` | New — same script |
| `src/agent_takt/_data/claude_skills/memory/SKILL.md` | Replace with operator instructions |
| `templates/agents/developer.md` | Add mandatory memory section |
| `templates/agents/tester.md` | Add mandatory memory section |
| `templates/agents/planner.md` | Add mandatory memory section (convention writes only) |
| `templates/agents/documentation.md` | Add mandatory memory section (read-only) |
| `templates/agents/review.md` | Add mandatory memory section (read-only) |
| `src/agent_takt/skills.py` | Copy pre-built venv with skill during `prepare_isolated_execution_root` |
| `src/agent_takt/runner.py` | Inject `AGENT_MEMORY_DB` env var pointing to workspace-level DB |
| `src/agent_takt/onboarding.py` | Call `memory.py init` post-install to pre-build venv |
| `src/agent_takt/cli/commands/misc.py` | Add `takt memory` subcommand (ingest, search, rebuild) |
| `src/agent_takt/cli/parser.py` | Register `memory` subcommand in argument parser |
| `src/agent_takt/_data/default_config.yaml` | No change needed — memory is path-based, not config-driven |
| `.gitignore` (bundled template) | Add `docs/memory/memory.db` |

## Acceptance Criteria

- `takt init` on a new project: installs `memory.py` into `.agents/skills/memory/` and `.claude/skills/memory/`, bootstraps the venv, creates `docs/memory/memory.db` with WAL mode, adds `docs/memory/memory.db` to `.gitignore`.
- Worker agents running inside isolated execution roots can call `python3 memory/memory.py search "..."` and `python3 memory/memory.py add ...` without triggering a venv bootstrap (venv pre-copied from skill catalog).
- All writes from parallel agents land in the same `docs/memory/memory.db` without corruption (WAL mode, ≥4 parallel workers tested).
- `takt memory ingest --migrate` ingests all entries from `docs/memory/known-issues.md` and `docs/memory/conventions.md`. Running it twice does not produce duplicate entries.
- `takt memory search "merge conflict"` returns the top-N most semantically relevant entries, including migrated content.
- Guardrail templates for developer, tester, planner, documentation, and review agents include explicit memory search (mandatory at bead start) and memory write (mandatory at bead end for write-capable agents) instructions.
- The operator skill (`claude_skills/memory/SKILL.md`) contains distinct instructions from the worker skill reflecting full write access and on-demand (not mandatory-at-start) retrieval.
- `docs/memory/memory.db` is listed in `.gitignore` and not tracked by git.
- All existing tests pass. New tests cover: venv copy path, `AGENT_MEMORY_DB` injection, `takt memory ingest` round-trip, concurrent writes.

## Pending Decisions

- **Which version of `memory.py` to bundle**: Pin to a specific commit/tag of `skill-memory` at implementation time. The implementer should fetch from `https://github.com/oscarrenalias/skill-memory` at the latest tag and note the pinned commit in a comment at the top of the bundled file.
- **`takt memory` subcommand location**: Added to `misc.py` or a new `memory.py` command module. Implementer's choice based on file size.
- **Venv copy strategy**: Copying a pre-built venv by path works on the same OS/arch, but venvs are not portable across machines or Python versions. Alternative: copy `memory.py` only and accept the one-time bootstrap cost per bead on first run (fast if venv already exists locally via pip cache). If the copy approach is brittle in practice, fall back to re-bootstrapping — the important guarantee is that the DB is shared, not that the venv is pre-built. Implementer should pick the simpler approach.
