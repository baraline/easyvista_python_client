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
    document_id: str | None = Field(default=None, alias="DOCUMENT_ID")
    download_href: str | None = Field(default=None, alias="DDL_HREF")

    @model_validator(mode="after")
    def _fill_filename(self) -> Document:
        """Populate ``filename`` from ``DOCUMENT`` or ``NAME`` when unset."""
        if not self.filename:
            self.filename = self.document or self.name
        return self
