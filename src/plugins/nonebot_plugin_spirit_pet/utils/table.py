"""Build GitHub-flavoured markdown tables that survive the message layer.

The QQ renderer escapes markdown metacharacters on every body line, `|` included,
so a table written by hand would be sent as `\\| 列1 \\|` and never render. Cell
text is escaped here instead — pipes and newlines, the two things that would break
the row — and the renderer passes rows through untouched (see
`adapters/messaging.escape` callers). Keep table content game-generated; do not
feed raw user text into a header.
"""

PIPE = "|"


def _cell(value: object) -> str:
    """One cell: no newlines, no bare pipes, no empty field."""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    # A literal pipe would split the row; escape it rather than drop it.
    text = text.replace("|", "\\|")
    return text or " "


def header(*names: object) -> tuple[str, ...]:
    """Header row plus separator row for `names` columns."""
    cells = [_cell(name) for name in names]
    return (
        PIPE + " " + " | ".join(cells) + " " + PIPE,
        PIPE + " " + " | ".join("---" for _ in cells) + " " + PIPE,
    )


def row(*values: object) -> str:
    return PIPE + " " + " | ".join(_cell(value) for value in values) + " " + PIPE


def table(headers, rows) -> tuple[str, ...]:
    """A complete table: header, separator, then one line per row.

    Rows shorter or longer than the header are padded or truncated so the table
    never has a ragged column count.
    """
    names = list(headers)
    if not names:
        return ()
    width = len(names)
    lines = list(header(*names))
    for values in rows:
        cells = list(values)[:width]
        cells += [""] * (width - len(cells))
        lines.append(row(*cells))
    return tuple(lines)


__all__ = ["PIPE", "header", "row", "table"]
