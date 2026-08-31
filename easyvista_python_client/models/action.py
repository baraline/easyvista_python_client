"""Models for EasyVista actions (≈ ticket followups)."""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from ..references import localized_label
from .common import (
    EasyvistaModel,
    EasyvistaWriteModel,
    OptionalDateTime,
    OptionalInt,
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


class PostAction(EasyvistaWriteModel):
    """Payload for creating an action on a ticket.

    Field set follows the documented (and live-verified) create-action body:
    identify the action type via ``action_type_id`` (or ``action_type_name``) and
    the assigned group via ``group_id`` (or ``group_name``). Inherits
    ``custom_fields``/``to_api()`` from EasyvistaWriteModel.

    **An action carries two independent text channels**, ``description`` and
    ``comment``, each addressable afterwards as its own memo sub-resource
    (``GET actions/{id}/description`` and ``GET actions/{id}/comment``). Both
    persist when sent together on create -- verified live 2026-08-28 on one
    instance: a single create carrying both read back with exactly the text
    sent in each. The instance's own OpenAPI declares both on the create body
    and its example populates both (tier 2).

    ``comment`` was previously absent from this model, on the reasoning that an
    action's text lives in ``DESCRIPTION`` while ``COMMENT`` "is empty" on the
    verified instance. That inference was wrong: ``COMMENT`` was empty because
    nothing had ever written to it, not because the column is unused.

    **A comment is an action that has been ENDED.** This is the single most
    important thing to know before posting one, and it is why a newly created
    action looks wrong in the UI. An action is a unit of work: created open
    (a task still to do), then *ended* (work reported). Only an ended action
    renders in the ticket's history with its text visible -- an open one shows
    as a pending action row with no body. Verified live 2026-08-28: a type-95
    action created through this model stayed invisible as a message until it
    was ended, at which point its ``description`` appeared in the history.

    Ending sets ``START_DATE_UT``, ``END_DATE_UT``, ``ELAPSED_TIME`` and
    ``STATUS_ID_ON_TERMINATE``, fills ``DONE_BY_ID`` with the person who ended
    it, and **clears** ``GROUP_ID`` -- the record moves from "assigned to a
    group" to "done by a person". None of those fields can be set through
    ``POST requests/{rfc}/actions``: sending them returns HTTP 200 and drops
    them silently.

    The vendor documents ending as ``PUT actions/{rfc_number}`` with the body
    wrapped in ``end_action`` (``doneby_mail``, ``start_date``, ``end_date``,
    ``elapsed_time``; omit ``action_id`` to end every open action at once), and
    dates in the instance's own ``DATE_FORMAT`` -- ``dd/mm/yyyy`` on the
    verified instance, **not** ISO 8601. See
    https://docs.easyvista.com/docs/rest-api-finish-an-action-attached-to-an-incident-request.md
    **This package does not implement it, and it could not be made to work on
    the verified instance**: every documented form returned
    ``590 Action not found``, including for a user who could end the same
    action through the UI, which points at an instance- or profile-level
    restriction rather than a payload error. Treat ending as an open problem
    to raise with the deployment's administrator.

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
    """

    action_type_id: int | None = None
    action_type_name: str | None = None
    group_id: int | None = None
    group_name: str | None = None
    description: str | None = None
    comment: str | None = None


class ActionUpdate(EasyvistaWriteModel):
    """Payload for editing an existing action's note.

    ``PUT actions/{id}`` is live-verified (2026-08-17): writing the action's
    ``DESCRIPTION`` memo really changed it, confirmed by re-reading it rather
    than by trusting HTTP 200. The **nested**
    ``PUT requests/{rfc}/actions/{id}`` returns 403, as does
    ``DELETE actions/{id}`` — an action can be edited but not deleted.

    ``description`` and ``comment`` are the action's two independent text
    channels, the same pair :class:`PostAction` writes on create -- both were
    verified live on 2026-08-28 to persist and read back separately from a
    single create. Editing either here targets that memo alone; neither is
    inherently private (see :class:`PostAction` for why the API enforces no
    visibility distinction).
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
    in the UI           a pending row, body NOT shown     a history entry WITH its text
    needs ending after  yes                               no
    ==================  ================================  ========================

    So an action models work someone still has to do, and only becomes a
    readable history entry once it is ended. A task is created already ended,
    which is why one call is enough to post a comment. Verified live
    2026-08-28: two tasks (types 94 and 95) came back with ``END_DATE_UT`` and
    ``STATUS_ID_ON_TERMINATE`` already set, attributed to the API account.
    Vendor documentation:
    https://docs.easyvista.com/docs/rest-api-create-a-task-for-an-incident-request.md

    Prefer this over :class:`PostAction` unless you genuinely mean "someone
    must still do this" -- ending an action afterwards needs
    ``PUT actions/{rfc_number}``, which returned ``590 Action not found`` for
    every documented form on the verified instance.

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
        """Refuse a body the API would reject with an unattributable 590."""
        if self.action_type_id is None and self.action_type_name is None:
            raise ValueError(
                "a task needs an action type: pass action_type_id (preferred) or "
                "action_type_name. The type also carries the public/internal "
                "distinction -- read the ids off ACTION_LABEL_* on existing actions."
            )
        no_group = (
            self.group_id is None
            and self.group_name is None
            and self.group_mail is None
        )
        if no_group:
            raise ValueError(
                "a task needs an assigned group: pass group_id, group_name or "
                "group_mail. Omitting it draws HTTP 590 'Le groupe (Group_...) "
                "est invalide' (measured 2026-08-28)."
            )
        return self
