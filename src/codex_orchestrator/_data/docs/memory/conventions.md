# Agent Conventions Memory

This file captures implicit patterns that emerged organically from working in this codebase.
It is **not** operator-maintained — it grows from agent experience across beads and features.

**Distinct from CLAUDE.md**: CLAUDE.md contains operator-defined rules and architecture reference.
This file contains conventions that agents discovered in practice and that future agents would benefit
from knowing upfront — things not obvious from reading the code alone.

**Append-only**: Never rewrite or delete existing entries. Add new dated entries at the bottom.

---

## Conventions

## 2026-04-02 — Always prefix commands with uv run

All orchestrator commands must be prefixed with `uv run` — invoking `orchestrator` or `python` directly without `uv run` will fail or use the wrong environment.

## 2026-04-02 — Bead ID formats coexist

Bead IDs use UUID format (`B-{8 hex chars}`); old sequential IDs (`B0001`) still coexist in storage and both formats are valid — do not assume one format.

## 2026-04-02 — Use unittest not pytest

Tests use `unittest`, not pytest — run a specific module with `uv run python -m unittest tests.<module> -v` rather than `uv run python -m unittest discover` to avoid timeout.

## 2026-04-02 — Config changes take effect immediately

The scheduler reads config at invocation time, not at startup — config changes in `.orchestrator/config.yaml` take effect on the next bead without restarting the scheduler.

## 2026-04-05 — Bundled assets: project-local takes precedence over package defaults

`codex_orchestrator._assets` exposes stable `Path` helpers (`packaged_templates_dir`, `packaged_agents_skills_dir`, `packaged_claude_skills_dir`, `packaged_docs_memory_dir`, `packaged_default_config`) that resolve to the `_data/` directory shipped inside the installed package.

Runtime lookup order (most specific wins):
- **Skills**: `.agents/skills/<id>/` inside the project repo; falls back to `packaged_agents_skills_dir()/<id>` when absent.
- **Templates**: `<root>/templates/agents/<type>.md` when a project root is supplied to `load_guardrail_template`; falls back to `packaged_templates_dir()/<type>.md` when `root=None`.
- **Default config**: `packaged_default_config()` is the last-resort fallback if `.orchestrator/config.yaml` is missing.

This means the orchestrator works out-of-the-box after `pip install` / `uv tool install` without a source checkout.
