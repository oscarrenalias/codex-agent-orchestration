"""Version tracking helpers for ``.takt/version.json``.

Written by ``takt init`` and ``takt upgrade`` to record the installed takt
version; read by ``takt summary`` to detect and warn about version drift.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from importlib.metadata import version as _pkg_version
from pathlib import Path

logger = logging.getLogger(__name__)

VERSION_FILE = ".takt/version.json"


def write_version_file(project_root: Path) -> Path:
    """Write ``.takt/version.json`` with the current installed takt version.

    Always overwrites any existing file (idempotent).

    Returns:
        The path to the written file.
    """
    data = {
        "takt_version": _pkg_version("agent-takt"),
        "last_upgraded_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    dest = project_root / VERSION_FILE
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return dest


def read_version_file(project_root: Path) -> dict | None:
    """Return the parsed ``.takt/version.json``, or ``None`` if absent or unreadable."""
    path = project_root / VERSION_FILE
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read %s", path)
        return None


def _parse_version(ver: str) -> tuple[tuple[int, ...], str]:
    """Return ``(int_tuple, raw)`` for *ver*.

    The last component has any non-numeric suffix stripped before conversion
    so that ``0.1.10a1`` sorts as ``(0, 1, 10)`` rather than raising.  The
    raw string is kept for exact-match tie-breaking.
    """
    parts = ver.split(".")
    ints: list[int] = []
    for i, part in enumerate(parts):
        if i == len(parts) - 1:
            # Strip trailing non-numeric suffix from the last component.
            m = re.match(r"^(\d+)", part)
            ints.append(int(m.group(1)) if m else 0)
        else:
            try:
                ints.append(int(part))
            except ValueError:
                ints.append(0)
    return tuple(ints), ver


def check_version_drift(project_root: Path) -> str | None:
    """Return a warning string when the repo version lags the installed version.

    Returns ``None`` when versions match or the repo is ahead.  Returns a
    warning string in two cases:

    * The version file is missing — prompt the operator to run ``takt upgrade``.
    * The repo version is older than the installed version — name both versions
      and suggest ``takt upgrade``.
    """
    data = read_version_file(project_root)
    if data is None:
        return "No .takt/version.json found. Run 'takt upgrade' to record the current version."

    repo_raw: str = data.get("takt_version", "")
    if not repo_raw:
        return "No .takt/version.json found. Run 'takt upgrade' to record the current version."

    installed_raw = _pkg_version("agent-takt")

    repo_tuple, _ = _parse_version(repo_raw)
    installed_tuple, _ = _parse_version(installed_raw)

    if installed_tuple > repo_tuple or (
        installed_tuple == repo_tuple and installed_raw != repo_raw
    ):
        return (
            f"Repo takt version: {repo_raw} — installed: {installed_raw}."
            " Run 'takt upgrade' to update."
        )
    return None
