---
name: GitHub CI: trigger only on meaningful file changes
id: spec-7ce17d7a
description: Add paths filter to the CI workflow so pushes to specs/, .orchestrator/, and docs/ do not trigger builds
dependencies: spec-dd4b17af
priority: medium
complexity: low
status: draft
tags: []
scope:
  in:
  out:
feature_root_id:
---
# GitHub CI: Trigger Only on Meaningful File Changes

## Objective

Every commit to `main` currently triggers a CI build, a package publish, and a version bump — including commits that only touch specs, bead state, CLAUDE.md, or documentation. This wastes CI minutes and produces spurious releases. Adding a `paths` filter to the workflow trigger limits builds to commits that actually affect the package.

---

## Problems to Fix

1. **Spec and bead commits trigger unnecessary builds** — pushing a spec draft or a `.orchestrator/beads/*.json` update publishes a new package version with no code changes.
2. **Version number inflated by noise commits** — every `[orchestrator]` bead commit bumps the patch version, making version numbers meaningless as a signal of actual change.

---

## Changes

### `.github/workflows/ci.yml` — add `paths` filter to trigger

Update the `on.push` trigger to include a `paths` allowlist. The workflow only runs when files under these paths are modified:

```yaml
on:
  push:
    branches:
      - main
    paths:
      - 'src/**'
      - 'pyproject.toml'
      - 'templates/**'
      - '.agents/skills/**'
      - '.claude/skills/**'
```

**Rationale for each path:**
- `src/**` — package source code
- `pyproject.toml` — package metadata and dependencies
- `templates/**` — guardrail templates bundled as package data
- `.agents/skills/**` — Codex skill catalog bundled as package data
- `.claude/skills/**` — Claude Code skill catalog bundled as package data

Paths intentionally excluded from triggering:
- `specs/**` — spec files
- `.orchestrator/**` — bead state, config, logs
- `docs/**` — documentation
- `CLAUDE.md`, `README.md` — project documentation
- `tests/**` — test changes alone do not produce a new package artifact worth releasing

---

## Testing Notes

No automated tests required. This is a one-field change to a YAML workflow file. The review agent should verify the `paths` list is complete and correct. End-to-end validation: push a spec-only commit to main and confirm the workflow does not trigger.

---

## Files to Modify

| File | Change |
|---|---|
| `.github/workflows/ci.yml` | Add `paths` filter to `on.push` trigger |

---

## Acceptance Criteria

- A commit touching only `specs/` does not trigger the CI workflow
- A commit touching only `.orchestrator/` does not trigger the CI workflow
- A commit touching `src/` triggers the CI workflow
- A commit touching `pyproject.toml` triggers the CI workflow
- A commit touching `templates/agents/*.md` triggers the CI workflow
- A commit touching `.agents/skills/**` or `.claude/skills/**` triggers the CI workflow
