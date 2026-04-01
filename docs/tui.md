# Interactive TUI

Launch with `uv run orchestrator tui`. Requires `textual` (installed via `uv sync`).

```bash
uv run orchestrator tui
uv run orchestrator tui --feature-root B0030
uv run orchestrator tui --refresh-seconds 5
```

## Layout

Three panels:
- **Beads** (left): bead tree in feature-root order, with active filter label in the title
- **Details** (right): selected bead scope and handoff fields
- **Status** (bottom): current mode, latest action result, footer counts

## Keyboard Bindings

| Key | Action |
|-----|--------|
| `q` | Quit |
| `Tab` / `Shift+Tab` | Move focus between list and detail panels |
| `j` / `Down` | Move selection down (list) or scroll down (detail) |
| `k` / `Up` | Move selection up (list) or scroll up (detail) |
| `PageUp` / `PageDown` | Page through whichever panel has focus |
| `Home` / `End` | Jump to start or end of focused panel |
| `g` / `G` | Jump to first or last bead in list |
| `n` / `N` | Move active collapsible section in detail panel |
| `Enter` | Toggle active detail section, or confirm a pending merge |
| `f` / `Shift+F` | Cycle filters forward / backward |
| `a` | Toggle timed refresh on/off |
| `r` | Manual refresh (or choose `ready` in status update flow) |
| `s` | Run one scheduler cycle |
| `S` | Toggle continuous scheduler runs on timed refreshes |
| `t` | Start retry confirmation for selected blocked bead |
| `u` | Start status update flow for selected bead |
| `b` / `d` | Choose `blocked` / `done` in status update flow |
| `y` | Confirm pending retry, merge, or status update |
| `c` | Cancel pending action |
| `m` | Start merge confirmation for selected done bead |
| `?` | Toggle help overlay |
| `Esc` | Close help overlay |

## Refresh and Scheduler Modes

The TUI starts in `manual refresh | scheduler=manual`. Mode is shown in the status panel footer.

- `a` — enables/disables timed refresh. Turning off also disables timed scheduler runs.
- `s` — one-shot scheduler pass (respects `--feature-root` scope if set).
- `S` — toggles continuous mode: each timed refresh runs a scheduler cycle instead of a read-only refresh.

## Filters

| Filter | Statuses shown |
|--------|---------------|
| `default` | `open`, `ready`, `in_progress`, `blocked`, `handed_off` |
| `actionable` | `open`, `ready` |
| `deferred` | `handed_off` |
| `done` | `done` |
| `all` | Every status |

When `--feature-root` is set, the root bead stays visible regardless of filter.

## Operator Actions

- **Retry** (`t` → `y`): requeues a blocked bead to `ready`.
- **Status update** (`u` → `r`/`b`/`d` → `y`): manually transitions a bead. Developer beads cannot be manually marked `done` — they must complete through the scheduler to trigger followup beads.
- **Merge** (`m` → `Enter`): merges a `done` bead's feature branch.

All actions require confirmation and report results in the status panel. Failed merges stay inside the TUI without closing the session.

## Mouse Behavior

- Clicking a bead row focuses the list and selects that bead.
- Clicking the detail panel focuses it without changing selection.
- Clicking a section header folds/unfolds that collapsible block.
- Mouse wheel follows the hovered panel: wheel over list moves selection, wheel over detail scrolls content.
