"""Reduce HTML (EasyVista rich-text fields) to plain text, stdlib only."""

from __future__ import annotations

import re
from html.parser import HTMLParser

_BLOCK_TAGS = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)  # entities -> unicode in handle_data
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag == "br":
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(value: str | None) -> str:
    """Strip HTML tags and unescape entities; plain text passes through; None -> ''."""
    if value is None:
        return ""
    parser = _TextExtractor()
    parser.feed(value)
    text = parser.text()
    # Trim trailing spaces on each line, then collapse 3+ newlines to a blank line.
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
