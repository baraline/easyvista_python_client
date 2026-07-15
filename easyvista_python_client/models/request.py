"""Models for the EasyVista ``requests`` resource (tickets).

Field sets are the documented/common SD_REQUEST fields; ``extra="allow"`` on the
read model preserves any others. Revisit exact fields against a live instance
(spec open item O1).
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from .common import EasyvistaModel, EasyvistaWriteModel


class Request(EasyvistaModel):
    """A ticket (incident/request) as returned by the API."""

    rfc_number: str | None = Field(default=None, alias="RFC_NUMBER")
    href: str | None = Field(default=None, alias="HREF")
    status_id: int | None = Field(default=None, alias="STATUS_ID")
    catalog_guid: str | None = Field(default=None, alias="CATALOG_GUID")
    # The list view returns DESCRIPTION inline (a string); the single-ticket GET
    # expands it into an HREF reference object (``{"HREF": ".../description"}``).
    # Accept either so both read paths validate (spec open items O1/O4).
    description: str | dict[str, Any] | None = Field(default=None, alias="DESCRIPTION")

    @model_validator(mode="after")
    def _derive_rfc_from_href(self) -> Request:
        """Populate ``rfc_number`` from ``href`` when the API omits it.

        ``POST /requests`` (create) returns an HREF-only body
        ``{"HREF": ".../requests/<id>"}`` with no ``RFC_NUMBER``; the trailing
        path segment of that HREF *is* the ticket's RFC (verified live), so
        callers can use ``ticket.rfc_number`` immediately after a create. Reads,
        which already carry ``RFC_NUMBER``, are left untouched.
        """
        if not self.rfc_number and isinstance(self.href, str) and self.href:
            tail = self.href.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]
            if tail:
                self.rfc_number = tail
        return self


class PostRequest(EasyvistaWriteModel):
    """Payload for creating a ticket.

    Field set matches the documented create body (``docs/API_Info.md``),
    verified against a live instance: a ticket needs at minimum ``catalog_code``
    plus ``title`` (and typically ``origin`` / ``department_id``). The exact
    mandatory fields are configured **per catalog on the EasyVista side**, so the
    client cannot know them statically; a missing one is rejected server-side and
    surfaces as :class:`EasyvistaValidationError` (HTTP 590, code 2013), not a
    retried server error. ``custom_fields`` values are serialized with an ``e_``
    prefix unless they already start with ``e_`` (see :class:`EasyvistaWriteModel`).
    """

    catalog_guid: str | None = None
    catalog_code: str | None = None
    title: str | None = None
    description: str | None = None
    origin: int | None = None
    department_id: int | None = None
    urgency_id: int | None = None
    impact_id: int | None = None
    severity_id: int | None = None
    recipient_id: int | None = None
    recipient_mail: str | None = None
    external_reference: str | None = None


class RequestUpdate(EasyvistaWriteModel):
    """Payload for updating a ticket via PUT."""

    status_id: int | None = None
    description: str | None = None
