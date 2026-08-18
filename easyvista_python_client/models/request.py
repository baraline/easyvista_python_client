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

from .common import EasyvistaModel, EasyvistaWriteModel, OptionalDateTime, OptionalInt


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

    # timestamps — ISO 8601 with an EXPLICIT UTC OFFSET and millisecond
    # precision, verified live 2026-08-17 against our own UTC clock, so these
    # parse to aware datetimes. Their accepted WRITE format is still NOT
    # verified (both a string and an int probe return HTTP 590), which is why
    # no write model carries a datetime. An unset date is ``""``, handled by
    # OptionalDateTime. Note ``_UT`` does NOT mean UTC-normalized: those columns
    # carry the same local offset as LAST_UPDATE.
    #
    # These are the OFFICIAL time fields, portable across EasyVista
    # deployments. The instance-specific GTR/GTI family (``E_GTR_STATUS``,
    # ``E_GTI_UT``, ``E_DELAI_PEC``…) is deliberately NOT declared: it does not
    # exist on another deployment, so it belongs in the custom bucket of
    # :meth:`classify_fields`, reached by name at the call site.
    submit_date_ut: OptionalDateTime = Field(default=None, alias="SUBMIT_DATE_UT")
    creation_date_ut: OptionalDateTime = Field(default=None, alias="CREATION_DATE_UT")
    max_resolution_date_ut: OptionalDateTime = Field(
        default=None, alias="MAX_RESOLUTION_DATE_UT"
    )
    expected_date_ut: OptionalDateTime = Field(default=None, alias="EXPECTED_DATE_UT")
    end_date_ut: OptionalDateTime = Field(default=None, alias="END_DATE_UT")
    last_update: OptionalDateTime = Field(default=None, alias="LAST_UPDATE")
    sla_id: OptionalInt = Field(default=None, alias="SLA_ID")
    # Verified live (2026-07-28 Phase 0 probe, U6) as a string on every ticket
    # checked -- never an int -- so no int branch is declared here.
    time_used_to_solve_request: str | None = Field(
        default=None, alias="TIME_USED_TO_SOLVE_REQUEST"
    )

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

    ``description`` supplied at create time was **not** readable back through
    either Memo on the verified instance -- neither ``DESCRIPTION`` nor
    ``COMMENT``. To set body text you can read again, follow the create with
    ``update_ticket(rfc, RequestUpdate(description=...))``.
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
    """Payload for updating a ticket via PUT.

    ``docs/API_Info.md`` documents only the create, comment and close bodies, so
    the update body is not vendor-documented. Every field here is one verified
    accepted against a live instance **by re-reading the ticket afterwards**, not
    by trusting HTTP 200 — that distinction matters on this API, where a write
    can return 200 and change nothing.

    ``description`` writes the ticket's **COMMENT** Memo, not ``DESCRIPTION`` --
    verified live by reading the text back, and pinned by
    ``integration_tests/test_live_ticket_metadata.py``.

    EasyVista models ``COMMENT`` as the request's justification and
    ``DESCRIPTION`` as a separate Memo. Which one a deployment populates is a
    per-instance configuration choice, and it is **not** reliably detectable at
    runtime. A pooled 77-row sample of one instance across four different
    orderings found ``COMMENT`` populated on 57 rows, ``DESCRIPTION`` on 27,
    *both* on 24 and neither on 17 -- and the proportions flipped depending on
    which slice was sampled, so a majority vote over a sample answers whichever
    way the sort happened to fall (measured 2026-08-18). An earlier 15-ticket
    sample that found ``DESCRIPTION`` empty everywhere was not representative;
    do not rely on that being true of any instance. Treat the body memo as
    operator configuration, not as something to infer.

    Read ``COMMENT`` back with ``resolve_memo("requests/{rfc}/comment")``, or
    take ``TicketContext.comment``, which resolves it for you.

    **Deliberately absent** (verified 2026-08-17):

    * ``severity_id`` — ``SEVERITY_ID`` is rejected with HTTP 590 (code 2013).
    * ``urgency_id`` — ``URGENCY_ID`` raised HTTP 590 *and the value still
      changed*, so the API's behaviour is not one this model can express
      honestly. Set it with a raw request and re-read if you must.
    * a priority field — EasyVista derives priority from urgency x impact rather
      than exposing a writable column.

    ``external_reference`` is capped at 50 characters: 50 is accepted and 51 is
    rejected server-side (bisected live). The cap is enforced here so the round
    trip is saved; over-length is rejected rather than truncated either way.
    """

    status_id: int | None = None
    title: str | None = None
    description: str | None = None
    impact_id: int | None = None
    owner_id: int | None = None
    external_reference: str | None = Field(default=None, max_length=50)
