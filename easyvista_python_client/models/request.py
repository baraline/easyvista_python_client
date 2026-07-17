"""Models for the EasyVista ``requests`` resource (tickets).

``Request``'s declared fields are those verified present on live single-ticket
GETs (see its class docstring for exactly which, and which are deliberately
left undeclared); ``extra="allow"`` preserves everything else. ``PostRequest``
and ``RequestUpdate`` field sets follow the documented create/update bodies
(see their own docstrings).
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from .common import EasyvistaModel, EasyvistaWriteModel, OptionalInt


class Request(EasyvistaModel):
    """A ticket (incident/request) as returned by the API.

    The declared fields are those verified present on live single-ticket GETs.
    ``extra="allow"`` preserves everything else, including the deliberately
    undeclared ones:

    * ``*_PATH`` (``SD_CATALOG_PATH``, ``DEPARTMENT_PATH``) — verified live:
      returned and populated, but **silently ignored as search conditions** (a
      real value returns the whole table while its ``*_ID`` sibling filters).
      ``LOCATION_PATH`` is *presumed* to behave the same by family resemblance
      only — no sampled ticket carried both ``LOCATION_PATH`` and
      ``LOCATION_ID``, so it was never actually tested. Left undeclared so this
      model never invites filtering on any of them.
    * ``E_*`` — instance-specific custom fields; they belong in the custom
      bucket of :meth:`~EasyvistaModel.classify_fields`, not here.
    * ``AVAILABLE_FIELD_*`` — the API's spare slots.

    ``TITLE`` is empty on tickets created through the portal/catalog on some
    instances (the human summary lives in ``DESCRIPTION`` / the catalog path),
    so ``title`` is legitimately ``None`` for those; it is populated for tickets
    created through this client with ``PostRequest(title=...)``.
    """

    # identity
    rfc_number: str | None = Field(default=None, alias="RFC_NUMBER")
    request_id: OptionalInt = Field(default=None, alias="REQUEST_ID")
    href: str | None = Field(default=None, alias="HREF")

    # content
    title: str | None = Field(default=None, alias="TITLE")
    # The list view returns DESCRIPTION inline (a string); the single-ticket GET
    # expands it into an HREF reference object (``{"HREF": ".../description"}``).
    # Accept either so both read paths validate. Whether the resolved text is
    # HTML or plain text is still unverified (spec open item O4).
    description: str | dict[str, Any] | None = Field(default=None, alias="DESCRIPTION")
    external_reference: str | None = Field(default=None, alias="EXTERNAL_REFERENCE")

    # classification
    sd_catalog_id: OptionalInt = Field(default=None, alias="SD_CATALOG_ID")
    status_id: OptionalInt = Field(default=None, alias="STATUS_ID")
    urgency_id: OptionalInt = Field(default=None, alias="URGENCY_ID")
    impact_id: OptionalInt = Field(default=None, alias="IMPACT_ID")
    severity_id: OptionalInt = Field(default=None, alias="SEVERITY_ID")
    # Write-side ``PostRequest.origin`` reads back as REQUEST_ORIGIN_ID; ``ORIGIN``
    # itself is not returned (spec open item O-ORIGIN).
    request_origin_id: OptionalInt = Field(default=None, alias="REQUEST_ORIGIN_ID")

    # parties and place
    department_id: OptionalInt = Field(default=None, alias="DEPARTMENT_ID")
    location_id: OptionalInt = Field(default=None, alias="LOCATION_ID")
    requestor_id: OptionalInt = Field(default=None, alias="REQUESTOR_ID")
    recipient_id: OptionalInt = Field(default=None, alias="RECIPIENT_ID")
    owner_id: OptionalInt = Field(default=None, alias="OWNER_ID")

    # timestamps — verified *returned*; their accepted format is NOT verified
    # (both a string and an int probe return HTTP 590), so no datetime parsing
    # is claimed here. See spec open item O-590-DATE.
    submit_date_ut: str | None = Field(default=None, alias="SUBMIT_DATE_UT")
    last_update: str | None = Field(default=None, alias="LAST_UPDATE")

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

    ``catalog_code`` is the only verified way to name a catalog here. An earlier
    ``catalog_guid`` field was removed: it is absent from the documented create
    body, and it cannot be verified on a profile where ``GET /catalog-requests``
    returns 403 (no way to obtain a real catalog GUID).
    """

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
