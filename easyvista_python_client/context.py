"""Aggregated ticket context and an href-free Markdown renderer."""

from __future__ import annotations

from dataclasses import dataclass, field

from ._fields import _label, _text
from ._html import html_to_text
from .models.action import Action
from .models.document import Document
from .models.request import Request


def _cell(value: str) -> str:
    """Make a value safe inside a Markdown table cell."""
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _memo_heading(name: str) -> str:
    """Title a memo block from the field name the caller asked for.

    Only the first letter of each word is touched, so an already-capitalized
    name (``COMMENT``) keeps its shape instead of being flattened to
    ``Comment`` the way :meth:`str.title` would.
    """
    words = name.replace("_", " ").replace("-", " ").split()
    return " ".join(word[:1].upper() + word[1:] for word in words) or name


@dataclass
class TicketContext:
    """A ticket plus its resolved narrative content.

    Holds the *raw* resolved text (``description``/``comment`` may still be HTML);
    :meth:`to_markdown` does the plain-text reduction and formatting.

    ``description`` and ``comment`` are the two memos EasyVista populates by
    default. ``memos`` carries every memo that was actually resolved, keyed by
    the field name requested -- the API models the memo name as a path segment
    (``GET /requests/{rfc}/{memo}``) (tier 2 -- ``docs/vendor-api-reference.md``:
    declared in the instance's OpenAPI ``paths``), so a deployment may carry
    others.
    """

    ticket: Request
    description: str | None
    comment: str | None
    actions: list[Action]
    documents: list[Document]
    memos: dict[str, str | None] = field(default_factory=dict)

    def to_markdown(self) -> str:
        """Render an href-free Markdown document for this ticket.

        Headings name the *role* a block plays, not the field it came from:
        when only one memo has text it is the body and is titled
        ``## Description`` whichever field carried it; when both defaults have
        text the distinction is real and each keeps its own heading. A memo
        requested through ``memo_fields`` is rendered on the same rule -- a
        single non-empty one becomes the body, several each get a heading
        derived from the field name asked for -- so a deployment whose body
        memo is neither ``description`` nor ``comment`` still exports one.
        """
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
        # Which memo carries a ticket's body is a per-deployment fact, and it
        # is not reliably detectable at runtime. Tier 4 -- measured on one
        # instance, 2026-08-18, and it may not generalise: a pooled 77-row
        # sample across four different orderings found COMMENT populated on 57
        # rows, DESCRIPTION on 27, both on 24 and neither on 17, with the
        # proportions flipping depending on the slice sampled. (An earlier
        # 15-ticket sample that found DESCRIPTION empty everywhere was not
        # representative; `models/request.py` treats the 77-row figure as the
        # authoritative one.) What is fixed is this library's own writes:
        # `RequestUpdate.description` writes COMMENT, so tickets this library
        # has written export that way. Titling that block "Comment" mislabels
        # the single most important part of the document for an LLM, or for a
        # RAG chunker splitting on "## ".
        #
        # But the opposite hard-coding is just as wrong: an instance that
        # populates DESCRIPTION properly uses COMMENT for a genuine follow-up
        # note, and fusing or relabelling the two would destroy a real
        # distinction. So neither universal is asserted. When only one memo has
        # text it IS the body, whichever it came from, and is titled
        # "Description"; when both do, the distinction is real and each keeps
        # its own heading. An instance where DESCRIPTION works renders exactly
        # as it did before.
        #
        # And when NEITHER default memo has text, the same rule runs over
        # `memos`. `get_ticket_context(rfc, memo_fields=("solution",))` is the
        # whole point of that parameter -- a deployment whose body memo is
        # neither default -- and rendering only the two defaults would drop
        # that body from the export with no heading and no warning. Fetch is
        # parameterised, so render is too.
        description = html_to_text(self.description)
        comment = html_to_text(self.comment)
        if description and comment:
            lines.extend(["## Description", "", description, ""])
            lines.extend(["## Comment", "", comment, ""])
        elif description or comment:
            lines.extend(["## Description", "", description or comment, ""])
        else:
            resolved = [
                (memo_name, memo_text)
                for memo_name, raw in self.memos.items()
                if (memo_text := html_to_text(raw))
            ]
            if len(resolved) == 1:
                lines.extend(["## Description", "", resolved[0][1], ""])
            else:
                for memo_name, memo_text in resolved:
                    lines.extend(
                        [f"## {_memo_heading(memo_name)}", "", memo_text, ""]
                    )

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
