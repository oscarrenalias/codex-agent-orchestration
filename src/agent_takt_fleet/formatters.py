from __future__ import annotations

from typing import Any, Sequence


def _col_widths(headers: list[str], rows: list[list[str]]) -> list[int]:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(cell))
    return widths


def format_table(
    headers: list[str],
    rows: list[list[str]],
    plain: bool = False,
) -> str:
    """Render a table with fixed-width columns.

    In plain mode, output is tab-separated (header + rows) without a separator
    line — suitable for piping to awk/cut.
    """
    if not rows and not headers:
        return ""

    widths = _col_widths(headers, rows)
    sep = "  "

    def fmt_row_padded(cells: list[str]) -> str:
        return sep.join(c.ljust(widths[i]) for i, c in enumerate(cells))

    lines: list[str] = []
    if plain:
        lines.append("\t".join(headers))
        for row in rows:
            lines.append("\t".join(row))
    else:
        lines.append(fmt_row_padded(headers))
        lines.append(sep.join("-" * w for w in widths))
        for row in rows:
            lines.append(fmt_row_padded(row))

    return "\n".join(lines)


def format_project_list(
    projects: Sequence,
    health_map: dict[str, str],
    plain: bool = False,
) -> str:
    """Render the `takt-fleet list` table.

    `projects` is a sequence of `Project` instances.
    `health_map` maps project name → health string.
    """
    headers = ["NAME", "PATH", "TAGS", "HEALTH"]
    rows = [
        [
            p.name,
            str(p.path),
            ",".join(p.tags) if p.tags else "",
            health_map.get(p.name, "unknown"),
        ]
        for p in projects
    ]
    return format_table(headers, rows, plain=plain)


def format_fleet_summary(
    rows: list[dict[str, Any]],
    plain: bool = False,
) -> str:
    """Render the `takt-fleet summary` table.

    Each dict in rows must have:
      name: str
      health: str
      counts: dict | None  — keys: open, ready, in_progress, blocked, done, handed_off

    Rows with counts=None are rendered with "-" placeholders.
    """
    headers = ["PROJECT", "DONE", "READY", "IN_PROGRESS", "BLOCKED", "HANDED_OFF", "HEALTH"]
    table_rows: list[list[str]] = []
    for row in rows:
        counts = row.get("counts")
        health = row.get("health", "error")
        if counts is None:
            table_rows.append([row["name"], "-", "-", "-", "-", "-", health])
        else:
            table_rows.append([
                row["name"],
                str(counts.get("done", 0)),
                str(counts.get("ready", 0)),
                str(counts.get("in_progress", 0)),
                str(counts.get("blocked", 0)),
                str(counts.get("handed_off", 0)),
                health,
            ])
    return format_table(headers, table_rows, plain=plain)
