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
from ..models.document import Document
from ..pagination import extract_records


def _first_document(data: Any) -> Document:
    records = extract_records(data)
    return Document.model_validate(records[0] if records else data)


def _document_records(data: Any) -> list[dict[str, Any]]:
    """Find the list of document dicts in a list response.

    The live list wraps items under a capital-D ``Documents`` key (verified live),
    which the generic ``extract_records`` (lowercase ``documents``/``records``) does
    not match; check any case-insensitive ``documents`` key first, then fall back.
    """
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() == "documents" and isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
    return extract_records(data)


def _all_documents(data: Any) -> list[Document]:
    return [Document.model_validate(r) for r in _document_records(data)]


def build_add_document(
    rfc_number: str, *, filename: str, content: bytes
) -> tuple[RequestSpec, Callable[[Any], Document]]:
    filedata = base64.b64encode(content).decode("ascii")
    spec = RequestSpec(
        "POST",
        f"requests/{rfc_number}/documents",
        json={"documents": [{"filename": filename, "filedata": filedata}]},
    )
    return spec, _first_document


def build_list_documents(
    rfc_number: str,
) -> tuple[RequestSpec, Callable[[Any], list[Document]]]:
    return RequestSpec("GET", f"requests/{rfc_number}/documents"), _all_documents
