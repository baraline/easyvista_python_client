"""Aggregated ticket context and an href-free Markdown renderer."""

from __future__ import annotations

from dataclasses import dataclass

from ._fields import _label, _text
from ._html import html_to_text
from .models.action import Action
from .models.document import Document
from .models.request import Request


def _cell(value: str) -> str:
    """Make a value safe inside a Markdown table cell."""
    return value.replace("|", "\\|").replace("\n", " ").strip()


@dataclass
class TicketContext:
    """A ticket plus its resolved narrative content.

    Holds the *raw* resolved text (``description``/``comment`` may still be HTML);
    :meth:`to_markdown` does the plain-text reduction and formatting.
    """

    ticket: Request
    description: str | None
    comment: str | None
    actions: list[Action]
    documents: list[Document]

    def to_markdown(self) -> str:
        """Render an href-free Markdown document for this ticket."""
        data = self.ticket.model_dump(by_alias=True)
        rfc = self.ticket.rfc_number or "(unknown)"
        title = _text(data.get("TITLE"))
        lines: list[str] = [f"# Ticket {rfc}" + (f" — {title}" if title else ""), ""]

        rows: list[tuple[str, str]] = []
        for label, value in (
            ("Status", self.ticket.reference("STATUS").display),
            ("Department", self.ticket.reference("DEPARTMENT").display),
            ("Location", self.ticket.reference("LOCATION").display),
            ("Catalog", self.ticket.reference("CATALOG_REQUEST").display),
            ("Created", _text(data.get("CREATION_DATE_UT"))),
            ("Updated", _text(data.get("LAST_UPDATE"))),
        ):
            if value:
                rows.append((label, value))
        if rows:
            lines.append("| Field | Value |")
            lines.append("|-------|-------|")
            lines.extend(f"| {k} | {_cell(v)} |" for k, v in rows)
            lines.append("")

        # Headings name the ROLE a block plays in this ticket, decided from the
        # data in hand -- not the EasyVista field it came from.
        #
        # Which memo carries a ticket's body is a per-deployment fact. On the
        # verified instance DESCRIPTION is unused and the body arrives in
        # COMMENT (0/15 sampled tickets had a non-empty DESCRIPTION, 15/15 had a
        # COMMENT), and `RequestUpdate.description` writes COMMENT too -- so
        # this library's own tickets export that way on any instance. Titling
        # that block "Comment" mislabels the single most important part of the
        # document for an LLM, or for a RAG chunker splitting on "## ".
        #
        # But the opposite hard-coding is just as wrong: an instance that
        # populates DESCRIPTION properly uses COMMENT for a genuine follow-up
        # note, and fusing or relabelling the two would destroy a real
        # distinction. So neither universal is asserted. When only one memo has
        # text it IS the body, whichever it came from, and is titled
        # "Description"; when both do, the distinction is real and each keeps
        # its own heading. An instance where DESCRIPTION works renders exactly
        # as it did before.
        description = html_to_text(self.description)
        comment = html_to_text(self.comment)
        if description and comment:
            lines.extend(["## Description", "", description, ""])
            lines.extend(["## Comment", "", comment, ""])
        elif description or comment:
            lines.extend(["## Description", "", description or comment, ""])

        if self.actions:
            lines.extend(["## Actions", ""])
            for action in self.actions:
                adata = action.model_dump(by_alias=True)
                type_label = _label(adata.get("ACTION_TYPE"), ("NAME_EN", "NAME_FR"))
                type_label = (
                    type_label or _text(adata.get("ACTION_LABEL_FR")) or "Action"
                )
                author = _text(adata.get("DONE_BY"))
                heading = type_label + (f" — {author}" if author else "")
                lines.append(f"### {heading}")
                # DESCRIPTION carries the note text once get_ticket_context has
                # resolved it; COMMENT is a separate field that never does
                # (verified live). Fall back to it only for records that
                # predate resolution.
                body = html_to_text(
                    action.description if isinstance(action.description, str) else None
                ) or html_to_text(
                    action.comment if isinstance(action.comment, str) else None
                )
                if body:
                    lines.extend(["", body])
                lines.append("")

        if self.documents:
            lines.extend(["## Attachments", ""])
            for doc in self.documents:
                name = doc.filename or doc.name
                if name:
                    lines.append(f"- {name}")
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"
