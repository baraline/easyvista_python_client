"""Models for EasyVista actions (≈ ticket followups)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import EasyvistaModel, EasyvistaWriteModel


class Action(EasyvistaModel):
    """An action recorded against a ticket."""

    action_id: int | None = Field(default=None, alias="ACTION_ID")
    comment: str | None = Field(default=None, alias="COMMENT")
    # The live API returns ACTION_TYPE as a nested object (id/name/...), not a
    # bare string, so accept either (same polymorphism as Request.description).
    action_type: str | dict[str, Any] | None = Field(default=None, alias="ACTION_TYPE")


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
