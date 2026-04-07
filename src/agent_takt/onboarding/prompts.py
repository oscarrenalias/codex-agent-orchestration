"""Interactive prompt collection helpers for the ``takt init`` command.

This module is intentionally isolated from asset-installation and config-generation
concerns.  It owns only the interactive question flow and the ``InitAnswers``
data structure that flows downstream into config and template generation.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import IO


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


def collect_init_answers(
    *,
    stream_in: IO[str] | None = None,
    stream_out: IO[str] | None = None,
) -> InitAnswers:
    """Run the interactive question flow and return collected answers.

    Prompts for runner backend, max workers, language/framework, test command,
    and build-check command, with sensible defaults and basic validation.

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
    while True:
        runner = _prompt(
            "Runner backend (claude/codex)",
            "claude",
            stream_in=inp,
            stream_out=out,
        )
        if runner in ("claude", "codex"):
            break
        out.write(f"  Invalid runner '{runner}'. Choose 'claude' or 'codex'.\n")
        out.flush()

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

    # --- Language / framework ---
    language = _prompt(
        "Project language/framework (e.g. Python, TypeScript/Node.js, Go)",
        "Python",
        stream_in=inp,
        stream_out=out,
    )

    # --- Test command ---
    test_command = _prompt(
        "Test command (e.g. pytest, npm test, go test ./...)",
        "pytest",
        stream_in=inp,
        stream_out=out,
    )

    # --- Build / syntax check command ---
    build_check_command = _prompt(
        "Build/syntax check command (e.g. tsc --noEmit, go build ./...)",
        "python -m py_compile",
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
