# Codex Agent Orchestration MVP

This repository contains a local Python CLI for orchestrating specialized Codex workers against a Git-native task graph.

## Highlights

- Repository-backed bead storage under `.orchestrator/beads/`
- Deterministic scheduler with dependency resolution and worker leases
- Isolated Git worktrees per active bead
- Structured handoffs between developer, tester, documentation, and review agents
- Assisted planner command backed by Codex CLI

## Quick start

```bash
uv sync
orchestrator bead create --title "Implement feature X" --agent developer --description "Read spec and implement"
orchestrator run --once
```

## Development

```bash
uv run python -m unittest discover -s tests -v
uv build
```

## Layout

- `.orchestrator/beads/`: authoritative bead state
- `.orchestrator/logs/events.jsonl`: scheduler event log
- `.orchestrator/worktrees/`: per-bead Git worktrees
- `docs/memory/`: shared project memory
