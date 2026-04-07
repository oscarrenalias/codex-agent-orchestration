# Onboarding a New Project

This guide covers installing the agent-takt CLI and initialising a new project for agent-based development.

## Installation

The `takt` CLI is distributed as a standard Python package named `agent-takt`.

**Recommended — isolated tool install via uv:**

```bash
uv tool install agent-takt
```

This installs the `takt` CLI into an isolated environment managed by uv, keeping it separate from your project dependencies.

**Alternative — pip:**

```bash
pip install agent-takt
```

Both methods install the same `takt` entry point. Verify the install succeeded:

```bash
takt --help
```

## Prerequisites

Before running `takt init`, make sure the following are in place:

1. **Git repository** — the target directory must be a git repo (`git init` if needed).
2. **Agent runner CLI** — install the backend you plan to use:
   - Claude Code: `npm install -g @anthropic-ai/claude-code`
   - Codex: `npm install -g @openai/codex`

`takt init` checks that the chosen runner binary is on `PATH` and exits with an install hint if it is not found.

## Running `takt init`

From the root of your git repository:

```bash
takt init
```

This starts an interactive prompt session. Press **Enter** to accept the default shown in brackets, or type a value and press Enter.

### Prompts

| Prompt | Default | Notes |
|--------|---------|-------|
| Runner backend (claude/codex) | `claude` | Must be `claude` or `codex` |
| Max parallel workers | `1` | Integer ≥ 1; sets `--max-workers` in run commands |
| Project language/framework | `Python` | Free text, e.g. `TypeScript/Node.js`, `Go` |
| Test command | `pytest` | Used by the scheduler's test gate |
| Build/syntax check command | `python -m py_compile` | Run to validate syntax without full tests |

### Non-interactive mode

For scripting or CI environments, skip all prompts and use built-in defaults:

```bash
takt init --non-interactive
```

To replace any files that were already created by a previous init:

```bash
takt init --overwrite
```

## What `takt init` Creates

After a successful run the following structure is added to your repository:

```
.takt/
  config.yaml              # Generated from your prompt answers; edit to customise
  assets-manifest.json     # SHA-256 fingerprints of all installed bundled assets
  beads/                   # Bead JSON state (version-controlled)
  logs/                    # Event log (runtime, gitignored)
  worktrees/               # Feature worktrees (runtime, gitignored)
  telemetry/               # Telemetry artifacts (runtime, gitignored)
  agent-runs/              # Per-bead agent outputs (runtime, gitignored)

templates/
  agents/              # Guardrail templates: planner.md, developer.md, tester.md, …
                       # Placeholders ({{LANGUAGE}}, {{TEST_COMMAND}}, …) are
                       # substituted with your prompt answers during init.

.agents/
  skills/              # Skill catalog for Codex backend (core/, role/, capability/, task/)

.claude/
  skills/              # Skill catalog for Claude Code backend

docs/
  memory/
    conventions.md     # Project conventions read by agents at runtime
    known-issues.md    # Known issues and workarounds (language-specific hints added)

specs/
  HOWTO.md             # Guidance on writing effective specs
  done/                # Archive directory for completed specs
  drafts/              # Working directory for draft specs
```

### The Assets Manifest

`takt init` records a SHA-256 fingerprint of every bundled file it installs into `.takt/assets-manifest.json`. This manifest is the reference point that `takt upgrade` uses to determine what has changed between takt versions.

Each tracked entry records three fields:

| Field | Description |
|-------|-------------|
| `sha256` | SHA-256 of the file as installed |
| `source` | `"bundled"` (installed by takt) or `"user"` (added directly by you) |
| `user_owned` | `true` means the file will never be overwritten by `takt upgrade` |

**Guardrail templates** (`templates/agents/*.md`) are marked `user_owned: true` at install time because `takt init` substitutes project-specific placeholders into them. Their on-disk content always differs from the bundled source, so automatic upgrades would overwrite your customisations. You can customise them freely without risk of a future `takt upgrade` reverting your changes.

If the manifest already exists when you run `takt init` again (for example to add a new file), the manifest is left untouched and a notice is printed directing you to run `takt upgrade` instead.

`.gitignore` is updated automatically with entries for the runtime-only `.takt/` subdirectories. Specifically, `takt init` appends the following block (skipping any lines already present):

```
# takt
.takt/worktrees/
.takt/telemetry/
.takt/logs/
.takt/agent-runs/
```

If `.gitignore` does not exist it is created. If all four entries are already present no changes are made.

### Generated config.yaml

The `.takt/config.yaml` produced by `generate_config_yaml` reflects your prompt answers in the `common` block. The `codex` and `claude` blocks are written with standard defaults:

```yaml
# Orchestrator configuration — generated by `orchestrator init`.
# Edit this file to customise settings. Missing keys use built-in defaults.

common:
  default_runner: claude         # from "Runner backend" prompt
  test_command: pytest           # from "Test command" prompt
  # max_workers is a CLI flag: takt run --max-workers 1

codex:
  binary: codex
  skills_dir: .agents
  flags:
    - "--skip-git-repo-check"
    - "--full-auto"
    - "--color"
    - "never"

claude:
  binary: claude
  skills_dir: .claude
  flags:
    - "--dangerously-skip-permissions"
  timeout_seconds: 900
  model_default: claude-sonnet-4-6
```

Key points:
- `max_workers` is intentionally **not** a config file key — it is a CLI flag passed to `takt run --max-workers N`. The comment in the generated file serves as a reminder of the value you chose.
- Any key omitted from this file falls back to takt's built-in defaults at load time (see `config.py`).
- The `codex` and `claude` blocks are always written, regardless of which runner you selected; you can use either backend at any time by passing `--runner codex` or `--runner claude` to `takt run`.

### Automatic Git Commit

After all files are written, `takt init` stages the scaffolded paths and creates a single commit:

```
chore: takt init scaffold
```

The following paths are staged and committed:

| Path | Notes |
|------|-------|
| `templates/` | Guardrail templates |
| `.agents/skills/` | Codex skill catalog |
| `.claude/skills/` | Claude Code skill catalog |
| `docs/memory/` | Memory seed files |
| `specs/` | `HOWTO.md` + `.gitkeep` sentinels in `drafts/` and `done/` |
| `.takt/config.yaml` | Generated config |
| `.takt/beads/.gitkeep` | Sentinel so the empty beads directory is tracked |
| `.gitignore` | Updated with takt entries |

If nothing has changed (e.g. `--overwrite` was not passed and all files already existed), git will report nothing to commit and the commit step is skipped with a warning — this is expected and harmless.

## Keeping Assets Up to Date

When you update the `agent-takt` package, bundled skill files and other assets may have changed. Running `takt init` again is **not** the right way to pick up these changes — it skips files that already exist and would silently leave you on older versions.

Use `takt upgrade` instead:

```bash
takt upgrade
```

This reads `.takt/assets-manifest.json`, compares every tracked file against the current bundled catalog, and applies the appropriate action for each file.

### What `takt upgrade` Does

| Condition | Action | Output label |
|-----------|--------|--------------|
| File unchanged since install; bundle matches disk | Skip silently | `[up-to-date]` in dry-run only |
| File unchanged since install; bundle has a newer version | Overwrite with bundle | `[updated]` |
| File present in bundle but absent from manifest (new in this release) | Install | `[new]` |
| File tracked in manifest, still in bundle, but deleted from disk | Restore from bundle | `[restored]` |
| File tracked in manifest but **removed** from the current bundle | Rename to `.disabled` | `[disabled — removed from bundle]` |
| File on disk under a bundled prefix, not in manifest or bundle | Record in manifest as user-owned | `[tracked — user-owned]` |
| `user_owned: true` in manifest | Skip unconditionally | `[skipped — user-owned]` |
| Disk SHA differs from manifest SHA (you edited the file) | Skip | `[skipped — locally modified]` |

Files you have edited locally are never overwritten. If the bundle has a newer version of a file you have modified, it is skipped and listed at the end of the output so you can review the difference manually.

After a successful run, `upgraded_at` is written into the manifest.

### Dry-Run Mode

To preview what an upgrade would do without writing any files:

```bash
takt upgrade --dry-run
```

Dry-run prints the full action plan — including `[up-to-date]` entries that are silently skipped in normal mode — but makes no changes to disk and does not update the manifest.

### Config Key Merging

`takt upgrade` also performs a non-destructive merge of `.takt/config.yaml`. Any keys present in the bundled default config that are missing from your file are added with their default values. Keys you have already set are never overwritten. New keys are reported in a separate "Config additions" section at the end of the output.

### Removed Bundled Assets

When takt removes a file from the bundled catalog in a new release, `takt upgrade` renames the on-disk copy to `<filename>.disabled` rather than deleting it. This prevents silent data loss if you had customised the file. Review `.disabled` files after upgrading and delete them once you are satisfied the change is intentional.

### Asset Ownership

Use `takt asset mark-owned` to tell the upgrade command to permanently skip a file, even if the bundle has a newer version:

```bash
# Protect all skill files from automatic upgrades
takt asset mark-owned ".agents/skills/**"

# Protect a single guardrail template
takt asset mark-owned "templates/agents/developer.md"
```

Ownership is stored in `.takt/assets-manifest.json`. Once marked, the file receives the `[skipped — user-owned]` treatment on every future `takt upgrade` run.

To re-enable upgrade management for a file:

```bash
takt asset unmark-owned ".agents/skills/core/**"
```

Note: Files with `source: user` (files you added directly, not installed by takt) always remain user-owned and cannot be unmarked.

### Listing Asset Status

To see the current status of all tracked assets:

```bash
takt asset list
```

This prints a table with four columns:

| Column | Description |
|--------|-------------|
| `PATH` | Project-relative path |
| `STATUS` | Current upgrade status (up-to-date, update available, locally modified, etc.) |
| `SOURCE` | `bundled` (installed by takt) or `user` (added by you) |
| `OWNED` | `yes` if `user_owned: true`; `no` otherwise |

## Post-Init Project Ownership

After `takt init` copies assets into your repository, **those files belong to your project**. This means:

- **Templates** (`templates/agents/*.md`) — edit these to tune agent guardrails for your stack. Changes take effect on the next scheduler run. Templates are marked `user_owned: true` in the manifest and are never overwritten by `takt upgrade`.
- **Skills** (`.agents/skills/` and `.claude/skills/`) — add, remove, or modify skill definitions to control what tools agents are allowed to use. To protect a skill you have customised from being overwritten, run `takt asset mark-owned "<glob>"`.
- **Memory files** (`docs/memory/conventions.md`, `docs/memory/known-issues.md`) — keep these up to date as your project evolves. Agents read them at runtime for project-specific context. These files are not tracked in the manifest and are never touched by `takt upgrade`.
- **Config** (`.takt/config.yaml`) — adjust runner settings, timeouts, test commands, and parallel worker count here. `takt upgrade` will add missing keys from new releases but will not overwrite values you have set.

Running `takt init --overwrite` will re-copy bundled defaults on top of any local changes, so avoid that after you have customised your files. Use `takt upgrade` for routine asset updates after a package upgrade.

## Verifying the Setup

After init, confirm everything is in place:

```bash
takt summary
```

This should print bead counts (all zeros on a fresh project) without errors. You are ready to plan your first spec.
