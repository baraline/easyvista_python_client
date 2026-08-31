"""Builders for the ticket ``documents`` sub-resource.

Documents are uploaded as base64 inside a JSON body, so no special multipart
transport handling is needed. The list endpoint shape is a best guess pending
live validation (spec open item O5).
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Any

from .._transport import RequestSpec
from ..config import (
    DEFAULT_DOCUMENT_DELETE_PATH_STYLE,
    DOCUMENT_DELETE_PATH_STYLES,
    DocumentDeletePathStyle,
)
from ..models.document import Document
from ..pagination import extract_records


def _document_records(data: Any) -> list[dict[str, Any]]:
    """Find the list of document dicts in a document response.

    The live list wraps items under a capital-D ``Documents`` key (measured
    2026-08-17 on one instance; may not generalise), which the generic
    ``extract_records`` also now matches. This stays a separate helper for a
    different reason: it checks a ``documents`` key *before* ``records``, the
    priority the live list shape was verified against, and ``extract_records``
    keeps ``records`` first. Both the list parser and the create parser go
    through it, so one response shape has one reading.
    """
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() == "documents" and isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
    return extract_records(data)


def _first_document(
    context: dict[str, Any] | None = None,
) -> Callable[[Any], Document]:
    """Build the single-document parser, binding the validation context.

    A factory rather than a bare function so ``context`` is fixed at build time
    and the returned parser keeps the ``Callable[[Any], Document]`` shape every
    other builder returns. ``Document`` declares no timestamp column today, so
    the context reaches nothing -- it is threaded anyway because "every builder
    that returns a parser takes a context" is a rule with no exception for a
    future field addition to forget.

    Goes through :func:`_document_records`, not ``extract_records``: the create
    and list responses are the same resource on the same instance, and reading
    them by two different rules is how a capital-D ``Documents`` echo produced
    an all-``None`` ``Document`` built from the wrapper.
    """

    def parse(data: Any) -> Document:
        records = _document_records(data)
        return Document.model_validate(
            records[0] if records else data, context=context
        )

    return parse


def _all_documents(
    context: dict[str, Any] | None = None,
) -> Callable[[Any], list[Document]]:
    """Build the document-list parser, binding the validation context.

    A factory for the same reason as :func:`_first_document`.
    """

    def parse(data: Any) -> list[Document]:
        return [
            Document.model_validate(r, context=context)
            for r in _document_records(data)
        ]

    return parse


def build_add_document(
    rfc_number: str,
    *,
    filename: str,
    content: bytes,
    context: dict[str, Any] | None = None,
) -> tuple[RequestSpec, Callable[[Any], Document]]:
    filedata = base64.b64encode(content).decode("ascii")
    spec = RequestSpec(
        "POST",
        f"requests/{rfc_number}/documents",
        json={"documents": [{"filename": filename, "filedata": filedata}]},
    )
    return spec, _first_document(context)


def build_list_documents(
    rfc_number: str,
    *,
    context: dict[str, Any] | None = None,
) -> tuple[RequestSpec, Callable[[Any], list[Document]]]:
    return (
        RequestSpec("GET", f"requests/{rfc_number}/documents"),
        _all_documents(context),
    )


def build_delete_document(
    rfc_number: str | None,
    document_id: str | int,
    *,
    path_style: DocumentDeletePathStyle = DEFAULT_DOCUMENT_DELETE_PATH_STYLE,
) -> RequestSpec:
    """Delete one attachment, by either of the two routes that exist for it.

    The instance OpenAPI document read 2026-08-27 declares DELETE on **both**
    ``requests/{RFC_NUMBER}/documents/{id}`` and ``documents/{id}``, marking
    only the latter ``deprecated``. So the HTTP 403 measured against the
    top-level form on the verified instance (2026-08-17, one instance, may not
    generalise) was a profile denial, not a missing route -- this API answers
    403 for an unknown path as well as for a denied one, so the status code
    alone never said which.

    ``path_style="nested"`` (the default, and the form verified live 2026-08-17:
    the document count went 5 -> 4 and the target was absent from a re-listing)
    needs both identifiers non-blank. ``path_style="top_level"`` addresses the
    document by id alone and ignores ``rfc_number`` entirely, which may be
    ``None``. ``document_id`` must be non-blank either way: a blank one
    addresses the collection rather than an item, which is a very different
    request to send by accident.
    """
    if path_style not in DOCUMENT_DELETE_PATH_STYLES:
        raise ValueError(
            "path_style must be one of "
            f"{DOCUMENT_DELETE_PATH_STYLES!r}, got {path_style!r}"
        )
    doc = str(document_id).strip()
    if not doc:
        raise ValueError("document_id is required to delete a document")
    if path_style == "top_level":
        return RequestSpec("DELETE", f"documents/{doc}")
    rfc = str(rfc_number or "").strip()
    if not rfc:
        raise ValueError(
            "rfc_number is required to delete a document with the 'nested' "
            "path style; pass path_style='top_level' to address the document "
            "by its id alone"
        )
    return RequestSpec("DELETE", f"requests/{rfc}/documents/{doc}")


def download_href(document: Document | str) -> str:
    """The URL to fetch a document's bytes.

    Accepts a :class:`Document` or a raw href/path. Prefers ``DDL_HREF`` (the
    direct-download URL) and falls back to ``HREF``. Lives here, not on either
    client, so the sync and async ``download_document`` share one definition of
    which field carries the URL -- the same reason every other request/response
    decision lives in this package.
    """
    href = (
        document
        if isinstance(document, str)
        else (document.download_href or document.href)
    )
    if not href:
        raise ValueError(
            "document has no download URL (neither DDL_HREF nor HREF is set)"
        )
    return href
