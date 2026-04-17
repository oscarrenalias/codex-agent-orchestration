---
name: "TUI AI panel: embedded interactive Claude session"
id: spec-5e785402
description: "Add a dedicated TUI panel that embeds an interactive Claude Code session via PTY, enabling stateful multi-turn AI-assisted monitoring and intervention without leaving the TUI."
dependencies: spec-cb04e3ba
priority: medium
complexity: large
status: draft
tags:
- tui
- ai
- pty
- observability
scope:
  in: "New AI panel in TUI, PTY management, Claude Code subprocess lifecycle"
  out: "Changes to scheduler, bead storage, events.jsonl, other TUI panels"
feature_root_id: null
---
# TUI AI panel: embedded interactive Claude session

## Objective

Once the TUI becomes a pure dashboard (spec-cb04e3ba), the missing piece is the ability to monitor and intervene without leaving the TUI. Today this requires switching to a separate terminal, starting a Claude Code session, and context-switching back and forth. The goal is a dedicated AI panel in the TUI that hosts a persistent, stateful `claude` (or `codex`) session via PTY — the same kind of interactive, multi-turn conversation used to monitor plan execution, diagnose blocked beads, trigger retries, and guide the pipeline to completion, all from within the TUI.

## Problems to Fix

1. **No in-TUI intervention surface.** When a bead is blocked or a merge conflict arises, the operator must leave the TUI to start a Claude Code session in a separate terminal, losing dashboard visibility while intervening.
2. **Context switching is costly.** Switching between TUI and terminal breaks the monitoring flow, especially when watching a long-running pipeline and needing to issue occasional corrections.
3. **The preferred runner is already configured** (`config.default_runner`), but there is no way to start an interactive session with it from within the TUI.

## Open Questions (must be resolved before planning)

- **Which runner to embed?** Always `claude` (Claude Code CLI), or respect `config.default_runner`? If Codex is the default runner, does an interactive Codex session make sense in the same panel?
- **How does the embedded session access the repo?** Should it run in the project root (main worktree), so it can read bead state and issue `takt` commands directly? Or should it be scoped to a specific worktree?
- **ANSI rendering strategy.** Strip ANSI codes and display plain text in a `RichLog`, or attempt to render Rich markup from the output? Stripping is simpler; rendering preserves formatting.
- **Session lifecycle.** One persistent session for the TUI lifetime, or allow restarting? What happens to the session if the underlying `claude` process exits unexpectedly?
- **Input model.** Single-line text input (Enter to send), or a multi-line input area (Ctrl+Enter to send)? Multi-line is more natural for longer prompts.
- **Panel layout.** Fixed panel alongside the bead tree and event log, or a toggleable overlay? If fixed, which panels does it displace or resize?
- **Security / scope.** The embedded session has full access to the shell and repo. Is that acceptable, or should tool use be restricted?

## Proposed Approach (sketch — subject to revision)

### PTY management

- Allocate a PTY pair (`os.openpty()`).
- Fork `claude` (interactive, no `-p` flag) with the slave end as its controlling terminal, cwd set to project root.
- A background thread drains the PTY master into a queue, stripping ANSI escape sequences.
- The main Textual worker posts each line to the AI output log via `call_from_thread`.
- On panel resize, send `SIGWINCH` to the subprocess and update the PTY window size via `fcntl.ioctl(TIOCSWINSZ)`.

### TUI panel

- New `#ai-panel` widget: `RichLog` for output (scrollable) + single-line `Input` at the bottom.
- Enter submits the input line to the PTY master as `text + "\n"`.
- A toggle keybinding (e.g. `A`) shows/hides the panel.
- Panel border shows runner name and session status (active / restarting / exited).

### Session lifecycle

- Session starts lazily on first `A` keypress (not at TUI startup).
- If the process exits unexpectedly, border shows `[session ended — press A to restart]`.
- Restarting clears the output log and spawns a fresh subprocess.

## Files to Modify (preliminary)

| File | Change |
|---|---|
| `src/agent_takt/tui/app.py` | Add `#ai-panel`, toggle keybinding, layout changes |
| `src/agent_takt/tui/state.py` | PTY lifecycle management, reader thread, resize handling |
| `src/agent_takt/tui/actions.py` | `start_ai_session()`, `stop_ai_session()`, `send_ai_input()` |

## Acceptance Criteria (preliminary)

- Opening the TUI and pressing `A` starts a `claude` interactive session in the AI panel.
- Text typed in the input field and submitted with Enter is sent to the session and a response appears in the output log.
- The session is stateful — a follow-up message retains context from the previous exchange.
- The session can issue `takt` commands (e.g. `takt bead show`, `takt retry`) and the output appears in the panel.
- Resizing the TUI panel sends the correct window size to the subprocess.
- If the `claude` process exits, the panel shows a restart prompt; pressing `A` again starts a fresh session.
- The AI panel can be hidden and re-shown without terminating the session.
- All existing TUI tests pass.

## Pending Decisions

- Which runner to embed, and how to select it (config vs. hardcoded `claude`)?
- ANSI rendering strategy (strip vs. render)?
- Single-line vs. multi-line input?
- Panel layout — fixed or toggleable overlay?
- Session scope — project root or per-worktree?
