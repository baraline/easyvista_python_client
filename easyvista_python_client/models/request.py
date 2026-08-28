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

    Field set follows the vendor-documented create body (tier 1 --
    ``docs/vendor-api-reference.md``). **Send
    the whole documented set** -- ``catalog_code``, ``origin``, ``title``,
    ``description``, ``department_id``, ``urgency_id``, ``impact_id`` -- rather
    than a subset. An earlier version of this docstring claimed a ticket needs
    "at minimum ``catalog_code`` plus ``title``"; that is wrong, and the way it
    is wrong is expensive:

    * the full documented body creates successfully on every catalog tried;
    * the same body minus the four ids creates on some catalogs and is rejected
      on others -- measured on two catalogs of one instance with the *identical*
      remaining bytes, accepted by one and rejected by the other;
    * the rejection is HTTP 590 / code 2013 whose message is a **SQL parser
      error** (``=(1,35) expected token:( * + - . IDENTIFIER CASE NOT JOIN ...``)
      naming no field at all. It is easy to misread as a server-side defect. It
      is not: it is what an under-specified create body looks like here.

    Which fields a given catalog can do without is configured per catalog on the
    EasyVista side, so the client cannot know it statically -- which is exactly
    why sending the documented set is the only reliable shape.

    Ids may be sent as JSON numbers or as strings; both are accepted (measured
    side by side). The documented examples quote them; these fields are typed
    ``int`` here and serialize as numbers, which the API takes.

    ``origin`` and ``impact_id`` accept an ``int`` or a ``str`` and serialize
    whichever was passed. The two tiers disagree about their type and both are
    honoured rather than one being picked: the vendor documents them as strings
    (tier 1), while ints were measured accepted on one instance (tier 4).

    **A rejected create may still have created the ticket.** Measured: 12
    attempts returned 3 ``RFC_NUMBER``s and afterwards all 12 tickets existed --
    9 of 9 failures had written a row, with the ids they were missing left null.
    So a 590 here means *possibly created*, never *not created*: retrying
    duplicates, and the caller never learns the id. Reconcile by
    ``external_reference`` rather than trusting the error.

    The recipient, requestor, department and location families each offer
    several ways to name the same thing, and the vendor documents a priority
    order within each (id, then identification, then mail, then name). Tier 1
    for all of them: they are vendor-documented and are **not** verified live by
    this package's test suite, so a deployment may reject one the vendor lists.

    ``submit_date`` is a string whose accepted format follows the employee's
    location settings, so no ``datetime`` is accepted here -- this package has
    never established a write format for an EasyVista date (both a string and an
    int probe returned HTTP 590), which is why no write model carries one.

    ``workflow_start`` is a boolean and is sent even when ``False``: it is the
    documented way to create a ticket *without* starting its workflow, and
    dropping a deliberate ``False`` would silently do the opposite.

    ``custom_fields`` values are serialized with an ``e_``
    prefix unless they already start with ``e_`` (see :class:`EasyvistaWriteModel`).

    ``catalog_guid`` and ``catalog_code`` both name the ticket's subject, and one
    of them is required -- tier 1, and the vendor documents the **guid** as the
    preferred form. An earlier version of this model dropped ``catalog_guid``
    entirely on the grounds that it was "absent from the documented create
    body"; the document consulted was a customer handover note rather than the
    vendor specification, and the vendor documents it plainly. Note that
    ``GET /catalog-requests`` is 403 on a restricted profile, so an instance may
    give you no way to *read* a catalog GUID even though the create accepts one.

    ``description`` supplied at create time was **not** readable back through
    either Memo on the verified instance -- neither ``DESCRIPTION`` nor
    ``COMMENT``. To set body text you can read again, follow the create with
    ``update_ticket(rfc, RequestUpdate(description=...))``.
    """

    catalog_guid: str | None = None
    catalog_code: str | None = None
    title: str | None = None
    description: str | None = None
    origin: int | str | None = None
    department_id: int | None = None
    department_code: str | None = None
    location_id: int | str | None = None
    location_code: str | None = None
    urgency_id: int | None = None
    impact_id: int | str | None = None
    severity_id: int | None = None
    recipient_id: int | None = None
    recipient_mail: str | None = None
    recipient_name: str | None = None
    recipient_identification: str | None = None
    requestor_identification: str | None = None
    requestor_mail: str | None = None
    requestor_name: str | None = None
    parentrequest: str | None = None
    phone: str | None = None
    submit_date: str | None = None
    workflow_start: bool | None = None
    external_reference: str | None = None

    @model_validator(mode="after")
    def _require_a_catalog_identifier(self) -> PostRequest:
        """Refuse a create body with no subject.

        Tier 1: the vendor documents ``catalog_guid`` OR ``catalog_code`` as the
        only required part of a create body. Sent without either, the server
        answers HTTP 590 with a SQL parser error naming no field at all, which
        is easy to misread as a server defect -- so this is refused here, where
        the message can say what is missing.
        """
        if not self.catalog_guid and not self.catalog_code:
            raise ValueError(
                "a create body needs a subject: pass catalog_guid (preferred) "
                "or catalog_code"
            )
        return self


class RequestUpdate(EasyvistaWriteModel):
    """Payload for updating a ticket via PUT.

    The vendor documents only the create, comment and close bodies
    (``docs/vendor-api-reference.md``), so the update body is not
    vendor-documented. Every field here is one verified accepted against a
    live instance **by re-reading the ticket afterwards**, not by trusting
    HTTP 200 — that distinction matters on this API, where a write can return
    200 and change nothing.

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

    * ``status_id`` — there is **no flat status update on this API**. It was a
      field here until 2026-08-25 and it never worked: sent alone the PUT is
      rejected 590/2013, and sent beside any other field the PUT returns **200,
      applies the other field, and drops the status in silence** (measured:
      title updated, ``STATUS_ID`` unchanged). A write that reports success and
      stores nothing is worse than one that fails, so the field is gone and
      ``extra="forbid"`` now makes ``RequestUpdate(status_id=...)`` raise at
      construction instead.

      Set a status with :meth:`~easyvista_python_client.EasyvistaClient.set_status`,
      which sends the documented ``{"closed": {"status_GUID": ...}}`` body. That
      route reaches **every** status, not just terminal ones -- all six statuses
      tried landed on exactly the one requested. It is addressed by
      ``STATUS_GUID``, not by ``STATUS_ID``.
    * ``severity_id`` — ``SEVERITY_ID`` is rejected with HTTP 590 (code 2013).
    * ``urgency_id`` — ``URGENCY_ID`` raised HTTP 590 *and the value still
      changed*, so the API's behaviour is not one this model can express
      honestly. Set it with a raw request and re-read if you must. Note this is
      an **update**-path finding only: on the CREATE path ``urgency_id`` is part
      of the documented body and lands cleanly (see :class:`PostRequest`).
    * a priority field — EasyVista derives priority from urgency x impact rather
      than exposing a writable column.

    ``external_reference`` is capped at 50 characters: 50 is accepted and 51 is
    rejected server-side (bisected live). The cap is enforced here so the round
    trip is saved; over-length is rejected rather than truncated either way.
    """

    title: str | None = None
    description: str | None = None
    impact_id: int | None = None
    owner_id: int | None = None
    external_reference: str | None = Field(default=None, max_length=50)
