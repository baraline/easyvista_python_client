"""Model for documents attached to an EasyVista ticket."""

from __future__ import annotations

from pydantic import Field, model_validator

from .common import EasyvistaModel


class Document(EasyvistaModel):
    """A document attached to a ticket (or the HREF returned after upload).

    The live ``GET requests/{rfc}/documents`` list exposes each attachment as
    ``DOCUMENT`` (filename), ``DOCUMENT_ID`` and ``DDL_HREF`` (the direct-download
    URL) — verified against a live instance. ``filename`` falls back to
    ``DOCUMENT`` (then ``NAME``) so it is populated on both the list shape and any
    ``FILE_NAME``-style shape; ``download_href`` is the URL to fetch the bytes.
    """

    href: str | None = Field(default=None, alias="HREF")
    filename: str | None = Field(default=None, alias="FILE_NAME")
    name: str | None = Field(default=None, alias="NAME")
    document: str | None = Field(default=None, alias="DOCUMENT")
    # Tier 4 and non-coercing, for the same reason as
    # ``Request.time_used_to_solve_request``: this column's type was observed on
    # one instance, never vendor-documented. Declared ``str`` alone, an instance
    # returning a JSON number for DOCUMENT_ID failed the record -- and because
    # the list parser validates a whole page in one comprehension, every
    # attachment on the ticket with it.
    document_id: str | int | None = Field(
        default=None, alias="DOCUMENT_ID", union_mode="left_to_right"
    )
    download_href: str | None = Field(default=None, alias="DDL_HREF")

    @model_validator(mode="after")
    def _fill_filename(self) -> Document:
        """Populate ``filename`` from ``DOCUMENT`` or ``NAME`` when unset."""
        if not self.filename:
            self.filename = self.document or self.name
        return self
