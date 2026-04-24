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
