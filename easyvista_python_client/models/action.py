"""Models for EasyVista actions (≈ ticket followups)."""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from ..references import localized_label
from .common import (
    EasyvistaModel,
    EasyvistaWriteModel,
    OptionalDateTime,
    OptionalDecimal,
    OptionalInt,
    _shipped_keys,
)


class Action(EasyvistaModel):
    """An action recorded against a ticket.

    Two shapes reach this model. ``list_actions`` returns a slim collection
    record; ``get_action`` returns a much fuller item-level one whose
    ``DESCRIPTION`` and ``COMMENT`` are Memo href objects. The note text a
    caller supplied as ``PostAction.description`` comes back through
    ``DESCRIPTION`` — **not** ``COMMENT``, and not on the list endpoint at all
    (verified live). ``extra="allow"`` preserves everything else.

    Item-level reads additionally carry timestamps (``CREATION_DATE_UT``,
    ``LAST_UPDATE``), the author (``DONE_BY_ID`` plus a nested ``DONE_BY``
    employee object) and workflow context (``STAGE_ID``, ``WORKFLOW_ID``) —
    verified live 2026-08-17. Their availability on the LIST endpoint is not
    uniform: ``CREATION_DATE_UT``, ``LAST_UPDATE``, ``GROUP_ID``, ``STAGE_ID``,
    ``WORKFLOW_ID`` and ``PARENT_ACTION_ID`` are genuinely absent from the
    default list projection; ``DONE_BY_ID`` and ``ACTION_NUMBER`` are already
    present there as top-level scalars; ``ACTION_TYPE_ID`` and ``REQUEST_ID``
    are present on a list row too, but only *nested* (inside ``ACTION_TYPE`` /
    ``REQUEST``) — since the declared fields alias the top-level key,
    ``action_type_id``/``request_id`` read ``None`` off a default list row
    even though the API did return the data. Pass ``fields=`` to
    ``list_actions`` to get these top-level for a whole PAGE of actions in one
    request instead of an item fetch per action — ``list_actions`` returns one
    page and does not paginate, so it is a page's worth, not a ticket's.

    **Effort columns: ``""`` and ``"0"`` are different answers.** ``elapsed_time``
    (minutes), ``time_cost``, ``contractual_cost``, ``start_date_ut`` and
    ``end_date_ut`` are declared as of 0.3.0, having previously reached callers
    only as untyped ``extra="allow"`` strings. When the API **returns** the
    column, ``""`` means it does not apply to this record and ``"0"`` /
    ``"0,00"`` means it applies and is zero (tier 4, measured 2026-09-02 over
    1500 rows on two instances -- so it may not generalise). This model preserves
    that distinction deliberately -- ``None`` for ``""``, ``0`` /
    ``Decimal("0.00")`` for the zeroes -- because collapsing the two destroys the
    only signal saying whether a record tracks effort at all. The two cost columns
    arrive with a French decimal comma (``'99,00'``) and parse to an exact
    :class:`~decimal.Decimal`. Either decimal separator is accepted; a grouping
    separator and three-or-more fraction digits are **refused** rather than
    guessed at, because ``'1.234,56'`` and ``'1,234.56'`` are the same amount
    under opposite conventions. Magnitude is not a trigger -- ``'1000,00'``
    parses. The parser is ``models/common.py::_parse_ev_decimal``, named as a
    path rather than cross-referenced because it is private and carries no
    rendered API-reference page.

    .. warning::

       **``None`` is ambiguous, and the default list row is the trap.** None of
       these five columns rides the default ``list_actions`` projection, so on a
       default list row every one of them reads ``None`` -- meaning *not
       returned*, not *does not apply*. The two are indistinguishable on the
       model. Project them explicitly (``list_actions(rfc, fields=[...,
       "ELAPSED_TIME", "WORKFLOW_ID"])``) or read item-level with
       :meth:`~easyvista_python_client.EasyvistaClient.get_action` before reading
       any meaning into a ``None``. To tell the two apart from a raw response,
       check whether the key is present at all -- once validated, that is gone.

    What that signal does **not** settle is whether a row was created as a task
    or as an action -- nothing on the record does, and the effort-shape heuristic
    that looks like it should is measurably wrong in both directions. See
    :attr:`is_workflow_generated`.

    Naming: this model calls its two timestamps ``created_at``/``updated_at``
    where :class:`~easyvista_python_client.models.request.Request` and
    :class:`~easyvista_python_client.models.employee.Employee` mirror the wire
    and call the identical columns ``creation_date_ut``/``last_update``. The
    divergence is only in the Python surface; the aliases
    (``CREATION_DATE_UT``/``LAST_UPDATE``) are the same on all three. Code that
    spans record types should therefore reach for the wire name via
    :meth:`~easyvista_python_client.models.common.EasyvistaModel.classify_fields`
    or ``.reference()`` rather than a shared attribute name, because
    ``getattr(record, "last_update")`` raises ``AttributeError`` on an
    ``Action``.
    """

    action_id: OptionalInt = Field(default=None, alias="ACTION_ID")
    href: str | None = Field(default=None, alias="HREF")
    comment: str | dict[str, Any] | None = Field(default=None, alias="COMMENT")
    # Memo href object on the item-level GET; a plain string once resolved.
    description: str | dict[str, Any] | None = Field(default=None, alias="DESCRIPTION")
    # The live API returns ACTION_TYPE as a nested object (id/name/...), not a
    # bare string, so accept either (same polymorphism as Request.description).
    action_type: str | dict[str, Any] | None = Field(default=None, alias="ACTION_TYPE")
    # The action's human label, present on the default list row. On a
    # single-language instance the other language columns (``_EN``, ``_GE``,
    # ``_IT``, ``_PO``, ``_SP``, ``_L1``..``_L6``) echo this text wrapped in
    # brackets to mark it untranslated; ``localized_label`` skips those. A
    # bracketed *suffix* on distinct text is a different thing entirely and
    # does carry meaning -- see :class:`PostAction`.
    action_label_fr: str | None = Field(default=None, alias="ACTION_LABEL_FR")
    # --- item-level fields (EV-R1, verified live 2026-08-17) ------------------
    # All ten are present on ``GET actions/{id}``. On the LIST endpoint:
    # CREATION_DATE_UT, LAST_UPDATE, GROUP_ID, STAGE_ID, WORKFLOW_ID and
    # PARENT_ACTION_ID are genuinely ABSENT from the default projection (the
    # default list row carries only ACTION_ID, ACTION_LABEL_FR, ACTION_NUMBER,
    # DONE_BY_ID and EXPECTED_START_DATE_UT) -- use a ``fields=`` projection
    # (see ``list_actions(fields=...)``) or an item fetch to get them.
    # ACTION_TYPE_ID and REQUEST_ID are NOT list-absent -- the default list row
    # already returns them, nested inside ACTION_TYPE / REQUEST respectively --
    # but because these fields alias the top-level key, they still read
    # ``None`` off a default list row; a ``fields=`` projection or the item GET
    # returns them top-level instead.
    #
    # Named ``created_at``/``updated_at`` rather than mirroring the API's
    # ``CREATION_DATE_UT``/``LAST_UPDATE`` because these are the two timestamps
    # a caller reaches for; the aliases keep the wire names authoritative.
    created_at: OptionalDateTime = Field(default=None, alias="CREATION_DATE_UT")
    updated_at: OptionalDateTime = Field(default=None, alias="LAST_UPDATE")
    done_by_id: OptionalInt = Field(default=None, alias="DONE_BY_ID")
    action_type_id: OptionalInt = Field(default=None, alias="ACTION_TYPE_ID")
    group_id: OptionalInt = Field(default=None, alias="GROUP_ID")
    request_id: OptionalInt = Field(default=None, alias="REQUEST_ID")
    action_number: OptionalInt = Field(default=None, alias="ACTION_NUMBER")
    # Workflow context. A freshly created ticket auto-spawns ~12 actions from the
    # catalog's workflow -- on one live ticket, only ONE of the twelve was
    # human-authored; the rest were the workflow's own generated steps. Those
    # generated actions carry these fields, an EMPTY ``DONE_BY_ID``, and also a
    # ``STATUS_ID_ON_CREATE`` (deliberately not declared here) -- together how a
    # caller tells a generated step from a human note. Filter on
    # ``action_type_id`` — the comment-like type ids are per-deployment config.
    stage_id: OptionalInt = Field(default=None, alias="STAGE_ID")
    workflow_id: OptionalInt = Field(default=None, alias="WORKFLOW_ID")
    parent_action_id: OptionalInt = Field(default=None, alias="PARENT_ACTION_ID")
    # --- effort and cost (EV-TASKSHAPE, added 0.3.0) -------------------------
    # Until 0.3.0 these five reached callers only as untyped ``extra="allow"``
    # strings. **The "" sentinel and "0" are different answers** -- "" means the
    # column does not apply to this record, "0" that it applies and is zero --
    # and ``OptionalInt``/``OptionalDecimal`` preserve exactly that: ``None`` for
    # "", ``0`` for "0". Measured over 1500 live rows 2026-09-02, ELAPSED_TIME
    # was "" on 384 and "0" on 895; the costs were "" on 691 and "0,00" on 808.
    #
    # ``elapsed_time`` is in MINUTES, is never derived from the window, and is
    # stored verbatim even when it contradicts it -- but a zero-length window
    # (``start_date_ut == end_date_ut``) stores 0 whatever was sent.
    #
    # Named for the wire (``start_date_ut``/``end_date_ut``) to match
    # ``Request.end_date_ut``, rather than following this model's own
    # ``created_at``/``updated_at``, which the class docstring flags as a wart.
    # Both are the ACTION's effort window: unlike ``Request.end_date_ut``, which
    # is stamped at RESOLUTION, an action's ``END_DATE_UT`` is set when the
    # action itself is ended.
    elapsed_time: OptionalInt = Field(default=None, alias="ELAPSED_TIME")
    time_cost: OptionalDecimal = Field(default=None, alias="TIME_COST")
    contractual_cost: OptionalDecimal = Field(default=None, alias="CONTRACTUAL_COST")
    start_date_ut: OptionalDateTime = Field(default=None, alias="START_DATE_UT")
    end_date_ut: OptionalDateTime = Field(default=None, alias="END_DATE_UT")

    @model_validator(mode="after")
    def _derive_action_id_from_href(self) -> Action:
        """Populate ``action_id`` from ``href`` when the API omits it.

        Defensive, and deliberately narrow: it fires only when ``href``'s
        trailing segment is numeric. It does **not** fire for a create
        response — ``POST requests/{rfc}/actions`` returns an HREF naming the
        **parent request**, not the new action, so its tail is an RFC number
        and ``.isdigit()`` correctly declines rather than inventing an id
        (verified live). A created action's id is not recoverable from its
        create response at all; see :meth:`EasyvistaClient.create_action`.
        Reads that carry a real ``ACTION_ID`` are left untouched.
        """
        if self.action_id is None and isinstance(self.href, str) and self.href:
            tail = self.href.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]
            if tail.isdigit():
                self.action_id = int(tail)
        return self

    @property
    def label(self) -> str | None:
        """Best localized action label, whichever language column carries it.

        Reads the ``ACTION_LABEL_<lang>`` columns in
        :data:`~easyvista_python_client.DEFAULT_LANGUAGE_ORDER` and returns the
        first that is populated and not an untranslated ``[placeholder]``.
        Prefer this over ``action_label_fr``, which names one column: on a
        single-language instance the *other* language columns echo the primary
        text wrapped in brackets, so on an English deployment
        ``action_label_fr`` is ``"[Customer Comment]"`` -- not ``None`` -- and
        reading it directly yields the placeholder. A bracketed *suffix* on
        otherwise distinct text (``"Commentaire [Public]"``) is real content and
        is kept.

        A plain property, not a serialized field, so it never recurses through
        ``model_dump`` and never appears in ``classify_fields``. ``None`` when no
        ``ACTION_LABEL_*`` column is populated, and also in the pathological case
        where every one of them is a bracketed placeholder; a caller that must
        always render something supplies its own fallback, as
        :meth:`~easyvista_python_client.TicketContext.to_markdown` does with the
        literal ``"Action"``. For a different language order call
        :func:`~easyvista_python_client.localized_label` on
        ``model_dump(by_alias=True)`` directly.
        """
        return localized_label(self.model_dump(by_alias=True), "ACTION_LABEL")

    @property
    def is_workflow_generated(self) -> bool:
        """Whether the workflow engine owns this row, i.e. ``WORKFLOW_ID`` is set.

        A ticket's catalog workflow auto-spawns its own action rows -- about a
        dozen on a freshly created ticket -- and each carries a ``WORKFLOW_ID``
        naming the workflow instance. Rows created by a person or by an API
        caller do not. Measured 2026-09-02 over 1500 live action rows on one
        instance (tier 4, so it may not generalise): no row of the
        conversation-bearing types (94 ``Commentaire [Public]``, 95 ``Note
        Interne [Prive]``, 7 ``Appel``) carried one, and every row of the
        workflow step types (1, 20, 21, 23, 30, 32, 33, 50, 65, 82, 84) that
        the engine had produced did.

        .. warning::

           **This is not a task/action discriminator, and there is none.** A
           task (``create_task``) and an action (``create_action``) are the same
           record in the same table, told apart only by the state they are born
           in -- open versus already ended -- and **neither ``WORKFLOW_ID`` nor
           the effort columns recover which route created a row**. Measured
           2026-09-02, both directions of the tempting shape heuristic fail on
           one instance:

           * 173 of 1500 rows had a ``WORKFLOW_ID`` **and** an empty
             ``ELAPSED_TIME`` -- 126 of them the type-20 ``Analyse et
             resolution`` workflow step. So "workflow row => effort is 0" is
             false.
           * 39 of 49 type-94 ``Commentaire [Public]`` rows -- ordinary public
             comments -- carried a **non-empty** ``ELAPSED_TIME``, usually
             ``'1'``; one carried ``ELAPSED_TIME='12'``, ``TIME_COST='99,00'``
             and ``CONTRACTUAL_COST='129,00'``. So "effort set => not a
             comment" is false, and a filter built on it drops four public
             comments in five.

           What an effort column reports is whether *effort was recorded*, not
           what kind of record this is. Deciding which action types count as
           conversation is per-deployment policy: pin the ``action_type_id``
           allowlist your administrator confirms, and use this property only to
           exclude the workflow engine's own rows. See
           ``docs/vendor-api-reference.md`` for the measurements.

        A plain property, not a serialized field, so it never appears in
        ``model_dump`` or ``classify_fields``. ``False``, never ``None``, when
        ``WORKFLOW_ID`` is absent from the projection -- the default
        ``list_actions`` row omits it, so on a default list row this reads
        ``False`` for every action whether or not the engine owns it. Project
        ``WORKFLOW_ID`` explicitly (``list_actions(rfc,
        fields=[..., "WORKFLOW_ID"])``) or read item-level before trusting it.
        """
        return self.workflow_id is not None


class PostAction(EasyvistaWriteModel):
    """Payload for creating an action on a ticket.

    Field set follows the documented (and live-verified) create-action body:
    identify the action type via ``action_type_id`` (or ``action_type_name``) and
    the assigned group via ``group_id`` (or ``group_name``). Inherits
    ``custom_fields``/``to_api()`` from EasyvistaWriteModel.

    **An action stores two separate text fields**, ``description`` and
    ``comment``, each addressable afterwards as its own memo sub-resource
    (``GET actions/{id}/description`` and ``GET actions/{id}/comment``). Both
    persist when sent together on create -- verified live 2026-08-28 on one
    instance: a single create carrying both read back with exactly the text
    sent in each. The instance's own OpenAPI declares both on the create body
    and its example populates both (tier 2).

    **Independent in storage, not in visibility.** Measured in the UI
    2026-09-01 on one instance (Service Manager 2025.3 -- one instance, one
    date, so it may not generalise), the ticket history shows ONE text field
    per action, under a header reading literally "comment or description": it
    renders ``DESCRIPTION`` when that memo has text, and falls back to
    ``COMMENT`` only when it is empty. So **``description`` shadows
    ``comment``**. A create carrying both stores both, and the comment is
    readable through the API but never reaches a human -- no error, no dropped
    field, nothing to signal the loss. Put the text a person must read in
    ``description``; use ``comment`` only when you deliberately leave
    ``description`` empty, or when you mean it as API-only metadata.

    ``comment`` was previously absent from this model, on the reasoning that an
    action's text lives in ``DESCRIPTION`` while ``COMMENT`` "is empty" on the
    verified instance. That *reasoning* was wrong -- the column accepts writes
    and reads back. But the instinct behind the omission was half right: an
    action's **visible** text does live in ``DESCRIPTION``, because the UI
    reaches ``COMMENT`` only when the description memo is empty.

    **A comment is an action that has been ENDED.** This is the single most
    important thing to know before posting one, and it is why a newly created
    action looks wrong in the UI. An action is a unit of work: created open
    (a task still to do), then *ended* (work reported). Only an ended action
    renders in the ticket's history with its text visible -- an open one shows
    as a pending action row with no body. Verified live 2026-08-28: a type-95
    action created through this model stayed invisible as a message until it
    was ended, at which point its ``description`` appeared in the history.

    Ending sets ``START_DATE_UT``, ``END_DATE_UT``, ``ELAPSED_TIME`` and
    ``STATUS_ID_ON_TERMINATE``, and fills ``DONE_BY_ID`` with the person who
    ended it. None of those fields can be set through ``POST
    requests/{rfc}/actions``: sending them returns HTTP 200 and drops them
    silently.

    ``STATUS_ID_ON_TERMINATE`` records the status the **ticket** took when the
    action ended, which is what makes a workflow action's ending visible in the
    record: measured 2026-09-01/02 on one instance (one instance, two dates, so
    it may not generalise), a workflow action stored ``2`` (the status the
    ticket moved to) while a caller-created action on a ticket that did not
    move stored ``12`` (where it stayed). Those ids are this deployment's --
    status ids are per-instance and must never be hardcoded from another. It is
    empty on an action that is still open, so it reports what happened rather
    than predicting it.

    .. warning::

       **Retracted 2026-09-02.** This paragraph previously said ending
       **clears** ``GROUP_ID`` -- "the record moves from assigned-to-a-group to
       done-by-a-person". It does not. Re-read after ending, the group survived
       on both an ended workflow action (``GROUP_ID`` 57) and an ended
       caller-created one (``GROUP_ID`` 3, the value passed at create).

    Ending is ``PUT actions/{rfc_number}`` with the body wrapped in
    ``end_action`` (``doneby_mail``, ``start_date``, ``end_date``,
    ``elapsed_time``; omit ``action_id`` to end every open action at once), and
    dates in the instance's own ``DATE_FORMAT``. See
    https://docs.easyvista.com/docs/rest-api-finish-an-action-attached-to-an-incident-request.md
    **This package implements it as** ``EasyvistaClient.end_action`` -- read
    that method before calling it, because ending the ticket's own workflow
    action advances the workflow and moves the ticket's status.

    .. warning::

       **Retracted 2026-09-01.** This docstring previously said every
       documented form returned ``590 Action not found`` and read that as an
       instance- or profile-level restriction to raise with an administrator.
       That was wrong. The 590 is what the route answers when **no OPEN action
       matches** -- replaying it against an action that is already ended, for
       instance. Ending an open action succeeds.

    Measured 2026-09-01 on one instance (Service Manager 2025.3 -- one
    instance, one date, so it may not generalise):

    * ``end_date`` accepts ``dd/mm/yyyy hh:mm:ss`` and ``dd/mm/yyyy hh:mm`` and
      honours the time; a bare ``dd/mm/yyyy`` lands at midnight. **ISO 8601 is
      rejected** with ``590 "Invalid End Date"``.
    * ``elapsed_time`` is in **minutes**.
    * Send ``start_date`` explicitly. Left to derive it, the server returns a
      ``START_DATE_UT`` early by the instance's UTC offset -- confirmed with a
      DST control (120 minutes in September at +02:00, 60 in February at
      +01:00), so it tracks the offset rather than a fixed constant. An
      explicit ``start_date`` is stored faithfully.
    * The path segment is the **RFC number**, not an action id, despite the
      route living under ``/actions``: ``PUT actions/{action_id}`` answers 404
      even with the id also in the body.

    **Visibility is by action TYPE, and the labels say which is which.** There
    is no per-action visibility flag -- the item-level record was captured on
    2026-08-28 (88 columns) and holds no public/private boolean. The
    distinction lives in the action type. On the verified instance:
    type 94 is ``Commentaire [Public]`` / ``Customer Comment``, type 95 is
    ``Note Interne [Prive]`` / ``Internal Note``. Type ids are per-deployment
    and are not portable, but they are **discoverable**: ``GET action-types``
    is 403 on a standard profile, yet every action record carries its own
    ``ACTION_TYPE_ID`` alongside translated ``ACTION_LABEL_*`` columns, so one
    ``GET actions`` recovers the types in use.

    Two bracket conventions appear in ``ACTION_LABEL_*`` and they mean
    different things. A whole label wrapped in brackets that echoes another
    language (``EN='[Analyse et resolution]'``) is an *untranslated
    placeholder* and carries no meaning -- ``references.localized_label``
    already skips those. A bracketed *suffix* on distinct text, with genuine
    translations in the sibling columns (``FR='Commentaire [Public]'`` beside
    ``EN='Customer Comment'``), is a real visibility marker. An earlier
    revision of this package conflated the two and deleted the true finding.

    **Mandatory (tier 1):** ``action_type_id`` (or ``action_type_name`` /
    ``action_type_guid``), and one of ``group_id`` / ``group_name`` /
    ``group_mail``. A body missing either is refused here rather than drawing
    an HTTP 590 that names no field. Sent empty, this route answers 590 with
    nothing a caller can act on -- the same failure :class:`PostTask` has
    always guarded against, on the same vendor sentence.
    """

    # Types mirror PostTask exactly. They diverged for no recorded reason --
    # ``int | None`` here against ``int | str | None`` there -- which made a
    # non-numeric type or group id work through ``create_task`` and fail
    # through ``create_action``. The instance's own OpenAPI declares
    # ``action_type_id`` on this route as a *string* (tier 3, illustrative
    # only), which argues for accepting one, not for coercing to one: whichever
    # type is passed serializes unchanged.
    action_type_id: int | str | None = None
    action_type_name: str | None = None
    # Tier 1, 2023.4+ (docs/vendor-api-reference.md). Declared here and NOT on
    # PostTask -- see that class for why.
    action_type_guid: str | None = None
    group_id: int | str | None = None
    group_name: str | None = None
    # Tier 1, and the third way to name the group. PostTask has always had it;
    # this model's omission was an oversight, not a finding.
    group_mail: str | None = None
    # Tier 1, optional. An action of a child type hangs off its parent.
    parent_action_id: int | str | None = None
    description: str | None = None
    comment: str | None = None

    # Deliberately still undeclared, all tier 1 and all optional: contact_*,
    # done_by_*, creation_date_ut, expected_start_date_ut, expected_end_date_ut,
    # max_intervention_date_ut. Nothing in this package exercises any of them,
    # and extra_payload reaches them today. Declaring six fields nobody has sent
    # would put this model's word behind bodies it has never seen work.

    @model_validator(mode="after")
    def _require_a_type_and_a_group(self) -> PostAction:
        """Refuse a body the API would reject with an unattributable 590.

        Same rule and same tier-1 source as :class:`PostTask`'s guard. The
        check reads the body ``to_api()`` will actually send, so a field
        supplied through ``extra_payload`` satisfies it.
        """
        shipped = _shipped_keys(self)
        if not shipped & {"action_type_id", "action_type_name", "action_type_guid"}:
            raise ValueError(
                "an action needs an action type: pass action_type_id "
                "(preferred), action_type_name or action_type_guid. The type "
                "also carries the public/internal distinction -- read the ids "
                "off ACTION_LABEL_* on existing actions."
            )
        if not shipped & {"group_id", "group_name", "group_mail"}:
            raise ValueError(
                "an action needs an assigned group: pass group_id, group_name "
                "or group_mail. Tier 1 lists it as required; omitting it on "
                "the sibling tasks route drew HTTP 590 'Le groupe (Group_...) "
                "est invalide' (measured 2026-08-28)."
            )
        return self


class ActionUpdate(EasyvistaWriteModel):
    """Payload for editing an existing action's note.

    ``PUT actions/{id}`` is live-verified (2026-08-17): writing the action's
    ``DESCRIPTION`` memo really changed it, confirmed by re-reading it rather
    than by trusting HTTP 200. There is no **nested**
    ``requests/{rfc}/actions/{id}`` route at all, and no DELETE verb on the
    top-level one -- the instance OpenAPI document read 2026-08-27 declares
    only GET, PUT and PATCH there. So an action can be edited but not deleted,
    and the 403 an earlier note recorded against both is what this API answers
    for an absent route as well as a denied one.

    ``description`` and ``comment`` are the action's two stored text fields,
    the same pair :class:`PostAction` writes on create -- both were verified
    live on 2026-08-28 to persist and read back separately from a single
    create. Editing either targets that memo alone -- but **the two are not
    interchangeable to a reader**. Measured in the UI 2026-09-01 on one
    instance (Service Manager 2025.3 -- one instance, one date, may not
    generalise), the history renders ``DESCRIPTION`` and falls back to
    ``COMMENT`` only when the description memo is empty, so an
    ``ActionUpdate(comment=...)`` on an action that already has a description
    returns 200, re-reads cleanly, and changes nothing anyone sees.

    **Write ``description`` to change what a person reads.** The same
    measurement confirmed a ``description`` edit applied to an action that had
    already been **ended** renders in the history, which is how to correct or
    extend a resolution after the fact.

    Neither memo is private in the API's sense (see :class:`PostAction`:
    visibility is carried by the action type). An unrendered ``comment`` is
    invisible by accident, not by permission.
    """

    description: str | None = None
    comment: str | None = None


class PostTask(EasyvistaWriteModel):
    """Payload for creating a **task** on a ticket -- an action that arrives ended.

    **This is the model to use for a comment.** A task and an action are the
    same underlying record; they differ in the state they are born in:

    ==================  ================================  ========================
    ..                  ``POST requests/{rfc}/actions``   ``POST requests/{rfc}/tasks``
    ==================  ================================  ========================
    body shape          wrapped in ``action``             flat at the root
    resulting state     **open** -- work still to do      **ended** -- work reported
    in the UI           a pending row, body NOT shown     shows its ``description``
    needs ending after  yes                               no
    ==================  ================================  ========================

    So an action models work someone still has to do, and only becomes a
    readable history entry once it is ended. A task is created already ended,
    which is why one call is enough to post a comment. Verified live
    2026-08-28: two tasks (types 94 and 95) came back with ``END_DATE_UT`` and
    ``STATUS_ID_ON_TERMINATE`` already set, attributed to the API account.
    Vendor documentation:
    https://docs.easyvista.com/docs/rest-api-create-a-task-for-an-incident-request.md

    **Put the comment text in ``description``.** ``comment`` is a second memo
    on the same record, and the UI renders only one: ``description``, falling
    back to ``comment`` when the description memo is empty (measured in the UI
    2026-09-01 on one instance -- one instance, one date, may not generalise).
    A task sending both therefore shows only the description, and a note split
    across the two loses half of itself with no error.

    Prefer this over :class:`PostAction` unless you genuinely mean "someone
    must still do this". An action is born open, so its text does not render
    until it is ended; ending is a second call
    (``EasyvistaClient.end_action``, which also advances the workflow when the
    action is a workflow step), and a task skips it entirely.

    **Public vs internal is the action type**, not a flag on the body. On the
    verified instance type 94 is ``Commentaire [Public]`` / ``Customer
    Comment`` and type 95 is ``Note Interne [Prive]`` / ``Internal Note``.
    Those ids are per-deployment; recover yours from the labels on existing
    actions (see :class:`PostAction`). Unlike an action of type 95, a task
    needs no ``parent_action_id``.

    Mandatory (tier 1): ``action_type_id`` **or** ``action_type_name``, and one
    of ``group_id`` / ``group_name`` / ``group_mail``. A body missing either is
    refused locally rather than drawing an HTTP 590 that names no field.
    """

    action_type_id: int | str | None = None
    action_type_name: str | None = None
    group_id: int | str | None = None
    group_name: str | None = None
    group_mail: str | None = None
    description: str | None = None
    comment: str | None = None
    # The vendor example spells this ``Elapsed_Time``; JSON object names are
    # case-insensitive on this API (tier 1), so the snake_case spelling ships
    # and no alias is needed -- which also keeps ``to_api()``'s plain
    # ``model_dump()`` correct. Left unset, EasyVista computes it.
    elapsed_time: int | str | None = None
    time_cost: int | str | None = None
    contractual_cost: int | str | None = None
    creation_date_ut: str | None = None
    start_date_ut: str | None = None
    end_date_ut: str | None = None

    @model_validator(mode="after")
    def _require_a_type_and_a_group(self) -> PostTask:
        """Refuse a body the API would reject with an unattributable 590.

        Reads the body ``to_api()`` will send, not the declared attributes, so
        a field passed through ``extra_payload`` satisfies it.
        ``action_type_guid`` counts even though this model does not declare it:
        nothing in the repository documents the task body's field list against
        tier 1 (see O-TASKDOC in ``docs/vendor-api-reference.md``), so the
        guard accepts the key without the model asserting the field exists on
        this route.
        """
        shipped = _shipped_keys(self)
        if not shipped & {"action_type_id", "action_type_name", "action_type_guid"}:
            raise ValueError(
                "a task needs an action type: pass action_type_id (preferred) or "
                "action_type_name, on the model or through extra_payload. The "
                "type also carries the public/internal distinction -- read the "
                "ids off ACTION_LABEL_* on existing actions."
            )
        if not shipped & {"group_id", "group_name", "group_mail"}:
            raise ValueError(
                "a task needs an assigned group: pass group_id, group_name or "
                "group_mail. Omitting it draws HTTP 590 'Le groupe (Group_...) "
                "est invalide' (measured 2026-08-28)."
            )
        return self
