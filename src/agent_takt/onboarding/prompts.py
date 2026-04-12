"""Interactive prompt collection helpers for the ``takt init`` command.

This module is intentionally isolated from asset-installation and config-generation
concerns.  It owns only the interactive question flow and the ``InitAnswers``
data structure that flows downstream into config and template generation.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import IO

# Canonical stack catalog used by the interactive init prompt and non-interactive defaults.
# Each entry is (display_name, test_command, build_check_command).
# "Other" is always last and signals a free-text fallback.
STACKS: list[tuple[str, str, str]] = [
    ("Python",        "pytest",          "python -m py_compile"),
    ("Node.js",       "npm test",        "npm run build"),
    ("TypeScript",    "npm test",        "tsc --noEmit"),
    ("Go",            "go test ./...",   "go build ./..."),
    ("Rust",          "cargo test",      "cargo build"),
    ("Java (Maven)",  "mvn test",        "mvn compile -q"),
    ("Other",         "",                ""),
]


@dataclass
class InitAnswers:
    """Collected answers from the ``orchestrator init`` interactive prompts."""

    runner: str               # 'claude' or 'codex'
    max_workers: int          # >= 1
    language: str             # free text, e.g. "Python", "TypeScript/Node.js"
    test_command: str         # e.g. "pytest", "npm test"
    build_check_command: str  # e.g. "tsc --noEmit", "uv run python -m py_compile"


def _prompt(
    prompt_text: str,
    default: str,
    *,
    stream_in: IO[str] | None = None,
    stream_out: IO[str] | None = None,
) -> str:
    """Emit a prompt and read one line of input.

    Returns *default* when the user enters an empty line.
    """
    out = stream_out or sys.stdout
    inp = stream_in or sys.stdin
    display = f"{prompt_text} [{default}]: " if default else f"{prompt_text}: "
    out.write(display)
    out.flush()
    line = inp.readline()
    value = line.rstrip("\n").strip()
    return value if value else default


def _select_from_list(
    prompt_text: str,
    options: list[str],
    default_index: int = 0,
    *,
    stream_in: IO[str] | None = None,
    stream_out: IO[str] | None = None,
) -> int:
    """Present a numbered menu and return the 0-based index of the chosen option.

    Prints each option prefixed with its 1-based number, then reads a single
    line. An empty line accepts the default. Non-integer input or an
    out-of-range number prints an error and re-prompts rather than raising.

    Args:
        prompt_text: Label printed above the numbered list.
        options: Display strings for each choice.
        default_index: 0-based index of the default selection.
        stream_in: Input stream (defaults to ``sys.stdin``).
        stream_out: Output stream (defaults to ``sys.stdout``).

    Returns:
        The 0-based index of the selected option.
    """
    out = stream_out or sys.stdout
    inp = stream_in or sys.stdin

    out.write(f"{prompt_text}:\n")
    for i, option in enumerate(options):
        out.write(f"  {i + 1}. {option}\n")
    out.flush()

    default_display = default_index + 1
    while True:
        out.write(f"Enter number [{default_display}]: ")
        out.flush()
        line = inp.readline()
        value = line.rstrip("\n").strip()
        if not value:
            return default_index
        try:
            choice = int(value)
        except ValueError:
            out.write(f"  '{value}' is not a valid number. Enter a number between 1 and {len(options)}.\n")
            out.flush()
            continue
        if 1 <= choice <= len(options):
            return choice - 1
        out.write(f"  {choice} is out of range. Enter a number between 1 and {len(options)}.\n")
        out.flush()


def collect_init_answers(
    *,
    stream_in: IO[str] | None = None,
    stream_out: IO[str] | None = None,
) -> InitAnswers:
    """Run the interactive question flow and return collected answers.

    Prompts for runner backend, max workers, and project stack using numbered
    menus, then derives test/build defaults from the selected stack.  Choosing
    ``Other`` falls back to free-text prompts for language, test command, and
    build-check command.

    Args:
        stream_in: Input stream (defaults to ``sys.stdin``).
        stream_out: Output stream (defaults to ``sys.stdout``).

    Returns:
        An :class:`InitAnswers` instance populated from user input.
    """
    out = stream_out or sys.stdout
    inp = stream_in or sys.stdin

    out.write("Press Enter to accept the default shown in [brackets].\n\n")
    out.flush()

    # --- Runner backend ---
    runner_options = ["claude", "codex"]
    runner_idx = _select_from_list(
        "Runner backend",
        runner_options,
        default_index=0,
        stream_in=inp,
        stream_out=out,
    )
    runner = runner_options[runner_idx]

    # --- Max workers ---
    while True:
        raw_workers = _prompt(
            "Max parallel workers",
            "1",
            stream_in=inp,
            stream_out=out,
        )
        try:
            max_workers = int(raw_workers)
            if max_workers >= 1:
                break
            out.write("  Max workers must be at least 1.\n")
            out.flush()
        except ValueError:
            out.write(f"  '{raw_workers}' is not a valid integer.\n")
            out.flush()

    # --- Project stack ---
    stack_names = [s[0] for s in STACKS]
    stack_idx = _select_from_list(
        "Project stack",
        stack_names,
        default_index=0,
        stream_in=inp,
        stream_out=out,
    )
    selected_stack = STACKS[stack_idx]
    is_other = selected_stack[0] == "Other"

    if is_other:
        # Free-text fallback for custom stacks
        language = _prompt(
            "Project language/framework (e.g. Python, TypeScript/Node.js, Go)",
            "Python",
            stream_in=inp,
            stream_out=out,
        )
        test_command = _prompt(
            "Test command (e.g. pytest, npm test, go test ./...)",
            "",
            stream_in=inp,
            stream_out=out,
        )
        build_check_command = _prompt(
            "Build/syntax check command (e.g. tsc --noEmit, go build ./...)",
            "",
            stream_in=inp,
            stream_out=out,
        )
    else:
        # Predefined stack: language is the display name; commands default from catalog
        language = selected_stack[0]
        test_command = _prompt(
            "Test command",
            selected_stack[1],
            stream_in=inp,
            stream_out=out,
        )
        build_check_command = _prompt(
            "Build/syntax check command",
            selected_stack[2],
            stream_in=inp,
            stream_out=out,
        )

    out.write("\n")
    out.flush()

    return InitAnswers(
        runner=runner,
        max_workers=max_workers,
        language=language,
        test_command=test_command,
        build_check_command=build_check_command,
    )
