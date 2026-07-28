"""Models for EasyVista actions (≈ ticket followups)."""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from .common import EasyvistaModel, EasyvistaWriteModel, OptionalInt


class Action(EasyvistaModel):
    """An action recorded against a ticket.

    Two shapes reach this model. ``list_actions`` returns a slim collection
    record; ``get_action`` returns a much fuller item-level one whose
    ``DESCRIPTION`` and ``COMMENT`` are Memo href objects. The note text a
    caller supplied as ``PostAction.description`` comes back through
    ``DESCRIPTION`` — **not** ``COMMENT``, and not on the list endpoint at all
    (verified live). ``extra="allow"`` preserves everything else.
    """

    action_id: OptionalInt = Field(default=None, alias="ACTION_ID")
    href: str | None = Field(default=None, alias="HREF")
    comment: str | dict[str, Any] | None = Field(default=None, alias="COMMENT")
    # Memo href object on the item-level GET; a plain string once resolved.
    description: str | dict[str, Any] | None = Field(default=None, alias="DESCRIPTION")
    # The live API returns ACTION_TYPE as a nested object (id/name/...), not a
    # bare string, so accept either (same polymorphism as Request.description).
    action_type: str | dict[str, Any] | None = Field(default=None, alias="ACTION_TYPE")

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
    """

    action_type_id: int | None = None
    action_type_name: str | None = None
    group_id: int | None = None
    group_name: str | None = None
    description: str | None = None
