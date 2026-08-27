"""Models for EasyVista actions (≈ ticket followups)."""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from .common import EasyvistaModel, EasyvistaWriteModel, OptionalDateTime, OptionalInt


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
    # brackets to mark it untranslated; ``localized_label`` skips those. The
    # brackets carry no other meaning.
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


class PostAction(EasyvistaWriteModel):
    """Payload for creating an action on a ticket.

    Field set follows the documented (and live-verified) create-action body:
    identify the action type via ``action_type_id`` (or ``action_type_name``) and
    the assigned group via ``group_id`` (or ``group_name``); ``description`` holds
    the note text. Inherits ``custom_fields``/``to_api()`` from EasyvistaWriteModel.

    An action carries no visibility flag, so a "private" note is simply a
    different ``action_type_id``. Which type ids a deployment treats as internal
    is not discoverable -- ``GET action-types`` is 403 on a standard profile --
    so ask the instance's administrator. Brackets in ``ACTION_LABEL_*`` mark an
    untranslated label, not a restricted one.
    """

    action_type_id: int | None = None
    action_type_name: str | None = None
    group_id: int | None = None
    group_name: str | None = None
    description: str | None = None


class ActionUpdate(EasyvistaWriteModel):
    """Payload for editing an existing action's note.

    ``PUT actions/{id}`` is live-verified (2026-08-17): writing the action's
    ``DESCRIPTION`` memo really changed it, confirmed by re-reading it rather
    than by trusting HTTP 200. The **nested**
    ``PUT requests/{rfc}/actions/{id}`` returns 403, as does
    ``DELETE actions/{id}`` — an action can be edited but not deleted.

    ``description`` is the note text. On the verified instance an action's text
    lives in the ``DESCRIPTION`` memo and ``COMMENT`` is empty, mirroring how
    ``PostAction.description`` round-trips; ``comment`` is offered for a
    deployment configured the other way round, and is **not** live-verified.
    """

    description: str | None = None
    comment: str | None = None
