from __future__ import annotations

import json

from ..models import Bead


LIST_PLAIN_COLUMNS: tuple[tuple[str, str], ...] = (
    ("BEAD_ID", "bead_id"),
    ("STATUS", "status"),
    ("AGENT", "agent_type"),
    ("TYPE", "bead_type"),
    ("PRIORITY", "priority"),
    ("TITLE", "title"),
    ("FEATURE_ROOT", "feature_root_id"),
    ("PARENT", "parent_id"),
)


def _plain_value(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, str):
        return value or "-"
    return str(value)


def _column_value(attribute: str, value: object) -> str:
    if attribute == "priority":
        return "" if value is None else str(value)
    return _plain_value(value)


def format_bead_list_plain(beads: list[Bead]) -> str:
    ordered = sorted(
        beads,
        key=lambda bead: (bead.execution_history[0].timestamp if bead.execution_history else "", bead.bead_id),
    )
    if not ordered:
        return "No beads found."

    rows = [
        [_column_value(attribute, getattr(bead, attribute, None)) for _, attribute in LIST_PLAIN_COLUMNS]
        for bead in ordered
    ]
    widths = [
        max(len(header), max((len(row[column_index]) for row in rows), default=0))
        for column_index, (header, _) in enumerate(LIST_PLAIN_COLUMNS)
    ]

    header_line = "  ".join(
        header.ljust(widths[column_index])
        for column_index, (header, _) in enumerate(LIST_PLAIN_COLUMNS)
    )
    row_lines = [
        "  ".join(
            value.ljust(widths[column_index])
            for column_index, value in enumerate(row)
        )
        for row in rows
    ]
    return "\n".join([header_line, *row_lines])


def format_bead_history_plain(
    entries: list[dict[str, object]],
    *,
    plain: bool = False,
    terminal_width: int | None = None,
) -> str:
    if not entries:
        return "No history."

    sorted_entries = sorted(entries, key=lambda e: str(e.get("timestamp", "")))

    def _truncate_ts(ts: object) -> str:
        s = str(ts) if ts is not None else ""
        # Strip fractional seconds: 2026-05-05T07:40:01.234567+00:00 → 2026-05-05T07:40:01
        dot = s.find(".")
        if dot != -1:
            s = s[:dot]
        # Strip timezone that follows the seconds (e.g. +00:00 appended with no dot)
        elif len(s) > 19:
            s = s[:19]
        return s

    event_col_width = max((len(str(e.get("event", ""))) for e in sorted_entries), default=0)

    lines = []
    for entry in sorted_entries:
        ts = _truncate_ts(entry.get("timestamp", ""))
        event = str(entry.get("event", "")).ljust(event_col_width)
        summary = str(entry.get("summary", ""))
        prefix = f"[{ts}] {event}  "
        if not plain and terminal_width is not None:
            available = terminal_width - len(prefix)
            if available > 0 and len(summary) > available:
                summary = summary[:available]
        lines.append(f"{prefix}{summary}")

    return "\n".join(lines)


def format_bead_field(value: object) -> str:
    if value is None or value == "":
        return ""
    # bool must be checked before int since bool is a subclass of int
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, (list, dict)):
        return json.dumps(value, indent=2)
    return str(value)


def format_claims_plain(claims: list[dict[str, object]]) -> str:
    if not claims:
        return "No active claims."

    lines: list[str] = []
    for claim in claims:
        lease_owner = "-"
        lease = claim.get("lease")
        if isinstance(lease, dict):
            lease_owner = _plain_value(lease.get("owner"))
        lines.append(
            f"{_plain_value(claim.get('bead_id'))} | "
            f"{_plain_value(claim.get('agent_type'))} | "
            f"feature={_plain_value(claim.get('feature_root_id'))} | "
            f"lease={lease_owner}"
        )
    return "\n".join(lines)


