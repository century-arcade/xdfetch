"""Plain TSV: no quoting, UTF-8, one header row."""

from __future__ import annotations

import io
from pathlib import Path


def parse(text: str) -> tuple[list[str], list[dict[str, str]]]:
    """Return (columns, rows). Blank lines and lines starting with # are skipped."""
    lines = text.splitlines()
    if not lines:
        return [], []
    columns = lines[0].rstrip("\r").split("\t")
    rows = []
    for line in lines[1:]:
        line = line.rstrip("\r")
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        fields = (fields + [""] * len(columns))[: len(columns)]
        rows.append(dict(zip(columns, fields, strict=True)))
    return columns, rows


def read(path: str | Path) -> tuple[list[str], list[dict[str, str]]]:
    return parse(Path(path).read_text(encoding="utf-8"))


def format_rows(columns: list[str], rows: list[dict[str, str]], header: bool = True) -> str:
    out = io.StringIO()
    if header:
        out.write("\t".join(columns) + "\n")
    for row in rows:
        out.write("\t".join(clean(str(row.get(c, ""))) for c in columns) + "\n")
    return out.getvalue()


def clean(value: str) -> str:
    """A field can't hold a tab or a newline."""
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")
