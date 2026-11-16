"""Linearize an EDGAR HTML document into plain text plus its tables, with offsets.

Returns Doc(text, tables) where each table knows the text offset it starts at, so a section
heading found in the text can be matched to the tables that follow it.
EDGAR tables are messy: values are split across cells ("6.3" | "x"), and spacer cells are everywhere.
`clean_row` normalizes that.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser


@dataclass
class Table:
    offset: int
    rows: list[list[str]] = field(default_factory=list)
    index: int = 0


@dataclass
class Doc:
    text: str
    tables: list[Table]


BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table"}


class _P(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.len = 0
        self.tables: list[Table] = []
        self.depth = 0
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.skip = 0

    def _emit(self, s: str):
        self.parts.append(s)
        self.len += len(s)

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "ix:header"):
            self.skip += 1
        elif tag == "table":
            self.depth += 1
            if self.depth == 1:
                self.tables.append(Table(self.len, [], len(self.tables)))
        elif tag == "tr" and self.depth == 1:
            self.row = []
        elif tag in ("td", "th") and self.depth == 1:
            self.cell = []
        if tag in BLOCK:
            if self.cell is not None:
                self.cell.append(" ")
            self._emit("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "ix:header"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("td", "th") and self.depth == 1 and self.cell is not None:
            if self.row is not None:
                self.row.append(_norm("".join(self.cell)))
            self.cell = None
            self._emit(" ")
        elif tag == "tr" and self.depth == 1 and self.row is not None:
            self.tables[-1].rows.append(self.row)
            self.row = None
        elif tag == "table":
            self.depth = max(0, self.depth - 1)
        if tag in BLOCK:
            self._emit("\n")

    def handle_data(self, data):
        if self.skip:
            return
        if self.cell is not None:
            self.cell.append(data)
        self._emit(data)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(s).replace("\xa0", " ")).strip()


def parse(html_text: str) -> Doc:
    p = _P()
    p.feed(html_text)
    p.close()
    text = "".join(p.parts)
    return Doc(text, p.tables)


_GLUE = {"x", "%", ")", "x)", "%)", "×"}


def clean_row(cells: list[str]) -> list[str]:
    """Drop spacer cells and glue split values: ['6.3', 'x'] -> ['6.3x'], ['$', '1,234'] -> ['$1,234']."""
    out: list[str] = []
    pending_prefix = ""
    for c in cells:
        c = c.strip()
        if not c:
            continue
        if c in ("$", "€", "£", "(", "$(") :
            pending_prefix += c
            continue
        if c in _GLUE and out:
            out[-1] += c
            continue
        out.append(pending_prefix + c)
        pending_prefix = ""
    return out
