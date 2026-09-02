"""Aggregated ticket context and an href-free Markdown renderer."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from ._fields import _text
from ._html import html_to_text
from .exceptions import EasyvistaError
from .models.action import Action
from .models.document import Document
from .models.request import Request
from .references import DEFAULT_LANGUAGE_ORDER, localized_label

#: Default rows of ``TicketContext.to_markdown``'s field table, as
#: ``(label, field_name)`` pairs. Extend rather than retype:
#: ``fields=[*DEFAULT_MARKDOWN_FIELDS, ("SLA", "SLA_ID")]``.
DEFAULT_MARKDOWN_FIELDS: tuple[tuple[str, str], ...] = (
    ("Status", "STATUS"),
    ("Department", "DEPARTMENT"),
    ("Location", "LOCATION"),
    ("Catalog", "CATALOG_REQUEST"),
    ("Created", "CREATION_DATE_UT"),
    ("Updated", "LAST_UPDATE"),
)


def _cell(value: str) -> str:
    """Make a value safe inside a Markdown table cell."""
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _degraded_entry(branch: str, exc: EasyvistaError) -> str:
    """Build a ``degraded`` entry: ``"<branch>:<http-status>"``.

    ``"?"`` stands in for an error carrying no status code, which the transport
    always sets but a hand-constructed exception need not.
    """
    status = getattr(exc, "status_code", None)
    return f"{branch}:{status}" if isinstance(status, int) else f"{branch}:?"


def _degraded_status(degraded: Iterable[str], branch: str) -> str | None:
    """The HTTP status recorded for ``branch``, or ``None`` if it is not degraded.

    ``rpartition``, not ``split``: a memo branch is itself named
    ``"memo:<field>"``, so only the LAST colon separates the status.
    """
    for entry in degraded:
        name, _, status = entry.rpartition(":")
        if name == branch:
            return status
    return None


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

    ``degraded`` records which sub-resource fetches were swallowed, as
    ``"<branch>:<http-status>"`` entries -- split with ``rsplit(":", 1)``,
    because a memo branch is itself named ``"memo:<field>"``. Branch names are
    ``actions``, ``documents`` and ``memo:<field>``. An empty set means nothing
    was swallowed; it does not mean everything was populated.
    """

    ticket: Request
    description: str | None
    comment: str | None
    actions: list[Action]
    documents: list[Document]
    memos: dict[str, str | None] = field(default_factory=dict)
    degraded: frozenset[str] = frozenset()

    def to_markdown(
        self,
        *,
        fields: Sequence[tuple[str, str]] | None = None,
        languages: Sequence[str] = DEFAULT_LANGUAGE_ORDER,
    ) -> str:
        """Render an href-free Markdown document for this ticket.

        ``fields`` is the field table, as ``(label, field_name)`` pairs; it
        defaults to :data:`DEFAULT_MARKDOWN_FIELDS`. Each field is resolved with
        ``Request.reference``, so a nested object yields its localized label, a
        bare id yields the id, and a timestamp column yields EasyVista's own
        rendering. A pair whose field resolves to nothing is dropped, so naming
        a column this instance does not return costs an absent row, not an
        error. Pass a list of pairs, never a flat list of names.

        A section recorded in ``degraded`` renders a one-line notice naming the
        HTTP status instead of being omitted, so an export cannot read as "this
        ticket has no attachments" when the attachment list was refused. Only
        the actions and documents sections do this: a memo that was refused and
        a memo that is genuinely empty both render as no block, and injecting a
        heading for the refused one would break the role-based rule below. It is
        recorded in ``degraded`` either way.

        Headings name the *role* a block plays, not the field it came from:
        when only one memo has text it is the body and is titled
        ``## Description`` whichever field carried it; when both defaults have
        text the distinction is real and each keeps its own heading. A memo
        requested through ``memo_fields`` is rendered on the same rule -- a
        single non-empty one becomes the body, several each get a heading
        derived from the field name asked for -- so a deployment whose body
        memo is neither ``description`` nor ``comment`` still exports one.

        ``languages`` orders the language columns tried when resolving every
        human label -- the table's Status/Department/Location/Catalog values and
        each action's heading (default:
        :data:`~easyvista_python_client.DEFAULT_LANGUAGE_ORDER`). It changes the
        *content* only: the structural headings (``## Description``,
        ``## Actions``, ``## Attachments``, the ``| Field | Value |`` table) are
        fixed English and are part of this method's output contract, so a RAG
        chunker splitting on ``##`` headings behaves the same against every
        deployment.
        """
        data = self.ticket.model_dump(by_alias=True)
        rfc = self.ticket.rfc_number or "(unknown)"
        title = _text(data.get("TITLE"))
        lines: list[str] = [f"# Ticket {rfc}" + (f" — {title}" if title else ""), ""]

        rows: list[tuple[str, str]] = []
        # One extraction for every row, where the two date rows used to take a
        # separate `_text(data.get(...))` path. Equivalent, not a behaviour
        # change: `resolve_reference` renders a datetime through
        # `format_ev_datetime`, which is byte-identical to what `_text`
        # produced for these columns, naive-datetime fallback included. It is a
        # strict superset for anything else -- an int-valued column now renders
        # instead of yielding "".
        for label, column in DEFAULT_MARKDOWN_FIELDS if fields is None else fields:
            value = self.ticket.reference(column, languages=languages).display
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
                # The nested ACTION_TYPE's own NAME_<lang> columns first, then
                # the record's ACTION_LABEL_<lang> columns, then a literal. Both
                # rungs honour `languages`, and both reject a fully bracketed
                # untranslated echo -- reading one named column would return the
                # placeholder on any instance whose primary language is not that
                # column's.
                nested_type = adata.get("ACTION_TYPE")
                type_label = localized_label(
                    nested_type if isinstance(nested_type, dict) else {},
                    "NAME",
                    languages=languages,
                )
                heading_label = (
                    type_label
                    or localized_label(adata, "ACTION_LABEL", languages=languages)
                    or "Action"
                )
                author = _text(adata.get("DONE_BY"))
                heading = heading_label + (f" — {author}" if author else "")
                lines.append(f"### {heading}")
                # One body per action, DESCRIPTION first. This mirrors what the
                # UI does with the single text field it renders per action,
                # headed literally "comment or description": DESCRIPTION when
                # non-empty, COMMENT only when DESCRIPTION is empty (measured
                # in the UI 2026-09-01 on one instance, Service Manager 2025.3
                # -- one instance, one date, may not generalise). The COMMENT
                # arm is NOT legacy compatibility: it renders exactly the
                # actions a reader does see, and deleting it would drop their
                # bodies. ``_resolve_action_body`` resolves that memo under the
                # same condition, which is what makes this branch reachable.
                body = html_to_text(
                    action.description if isinstance(action.description, str) else None
                ) or html_to_text(
                    action.comment if isinstance(action.comment, str) else None
                )
                if body:
                    lines.extend(["", body])
                lines.append("")
        elif (
            actions_status := _degraded_status(self.degraded, "actions")
        ) is not None:
            lines.extend(
                ["## Actions", "", f"_Not available (HTTP {actions_status})._", ""]
            )

        if self.documents:
            lines.extend(["## Attachments", ""])
            for doc in self.documents:
                name = doc.filename or doc.name
                if name:
                    lines.append(f"- {name}")
            lines.append("")
        elif (
            documents_status := _degraded_status(self.degraded, "documents")
        ) is not None:
            lines.extend(
                [
                    "## Attachments",
                    "",
                    f"_Not available (HTTP {documents_status})._",
                    "",
                ]
            )

        return "\n".join(lines).rstrip() + "\n"
