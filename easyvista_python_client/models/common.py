"""Shared Pydantic base models for EasyVista resources."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from ..field_model import FieldClassification, classify
from ..references import DEFAULT_LANGUAGE_ORDER, Reference, resolve_reference
from ..timestamps import parse_ev_datetime


def _empty_str_to_none(value: Any) -> Any:
    """Coerce the API's empty-string sentinel for an absent scalar to ``None``.

    EasyVista returns ``""`` for numeric columns that carry no value (e.g.
    ``MANAGER_ID`` / ``FUNCTION_ID`` on the single-record directory GETs); without
    this an ``int`` field would fail validation. Any non-empty or non-string value
    passes through untouched.
    """
    if isinstance(value, str) and not value.strip():
        return None
    return value


OptionalInt = Annotated[int | None, BeforeValidator(_empty_str_to_none)]
"""An ``int | None`` field that treats the API's ``""`` sentinel as ``None``."""


def _empty_str_to_none_datetime(value: Any) -> Any:
    """Coerce EasyVista's ``""`` sentinel for an absent date to ``None``.

    Distinct from :func:`_empty_str_to_none`: a *malformed* timestamp must still
    raise, so this maps only the two documented absences -- ``None`` (a JSON
    ``null``, and the field's own default) and EasyVista's ``""`` sentinel. Every
    other value -- including a ``datetime`` handed in directly, not just a string --
    routes through :func:`~easyvista_python_client.timestamps.parse_ev_datetime`,
    which normalizes a naive ``datetime`` to UTC and returns ``None`` for
    anything it cannot parse.

    When it returns ``None`` this raises ``ValueError``, which pydantic wraps
    into a ``ValidationError`` naming the field. It deliberately does **not**
    fall through to pydantic's own datetime parser, which is far more permissive
    than EasyVista's format and would invent a plausible-but-wrong instant
    instead of reporting the mismatch: ``"20260817"`` (ISO-basic, no separators)
    becomes ``1970-08-23T12:00:17Z``, 56 years off, and ``1755434441610`` --
    what an epoch-millis format change would look like -- becomes a wholly
    credible ``2025-08-17T12:40:41.610Z``. Absorbing the one format change this
    guard exists to surface is the opposite of the intended behaviour, so junk
    raises here instead.
    """
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    parsed = parse_ev_datetime(value)
    if parsed is None:
        raise ValueError(
            f"{value!r} is not an EasyVista timestamp. EasyVista sends ISO 8601 "
            "with an explicit UTC offset (or '' for an unset date); anything "
            "else is reported rather than guessed at, because pydantic's own "
            "parser would turn a numeric or ISO-basic value into a plausible "
            "but wrong instant and hide the format change."
        )
    return parsed


OptionalDateTime = Annotated[
    datetime | None, BeforeValidator(_empty_str_to_none_datetime)
]
"""An aware ``datetime | None`` for an EasyVista timestamp column.

EasyVista returns ISO 8601 with an explicit UTC offset and millisecond
precision (``2026-08-17T15:40:41.610+02:00``), and ``""`` for an unset date —
verified live 2026-08-17. Python 3.10's ``fromisoformat`` rejects the 3-digit
fraction outright, which is why this goes through
:func:`~easyvista_python_client.parse_ev_datetime` rather than letting pydantic
parse the string itself. A naive ``datetime`` passed in directly (not just a
wire string) is normalized to aware UTC the same way, so the ``| None`` aside,
this type's value is always timezone-aware, never naive.
"""


class EasyvistaModel(BaseModel):
    """Base for read models.

    Tolerates the API's ``ALL_CAPS`` field names (via aliases on subclasses) and
    preserves unknown / custom ``e_*`` fields so they round-trip unchanged.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    def reference(
        self, name: str, *, languages: Sequence[str] = DEFAULT_LANGUAGE_ORDER
    ) -> Reference:
        """Resolve a reference attribute (``STATUS``, ``URGENCY``, custom ``e_*``…)
        to a normalized :class:`~easyvista_python_client.references.Reference`.

        ``languages`` orders the language columns tried for the human label
        (default: :data:`~easyvista_python_client.DEFAULT_LANGUAGE_ORDER`).
        """
        return resolve_reference(
            self.model_dump(by_alias=True), name, languages=languages
        )

    def classify_fields(self) -> FieldClassification:
        """Partition this record's fields into official / custom (``e_*``) /
        available / link buckets.

        See :class:`~easyvista_python_client.field_model.FieldClassification`.
        """
        declared = {
            (f.alias or name).upper() for name, f in type(self).model_fields.items()
        }
        return classify(self.model_dump(by_alias=True), declared)


class EasyvistaWriteModel(BaseModel):
    """Base for write payloads (create/update).

    Rejects unknown fields (``extra="forbid"``) to catch caller typos, and
    serializes ``custom_fields`` with an ``e_`` prefix (unless already
    prefixed). ``extra_payload`` is an un-prefixed passthrough for anything the
    model does not declare -- see :meth:`to_api`.
    """

    model_config = ConfigDict(extra="forbid")

    custom_fields: dict[str, Any] = Field(default_factory=dict)
    extra_payload: dict[str, Any] = Field(default_factory=dict)

    def to_api(self) -> dict[str, Any]:
        """Return the API body: known fields (``None`` dropped), ``e_``-prefixed
        custom fields, then ``extra_payload`` verbatim.

        Booleans may be sent as native JSON ``true``/``false`` (EasyVista also
        accepts ``0``/``1`` and the strings ``"true"``/``"false"``).

        ``extra_payload`` is merged **last and wins**, over a declared field and
        over ``custom_fields`` alike. It is the supported route for a field this
        model declines to declare -- every such exclusion rests on behaviour
        measured against a single instance, and a deployment where that field
        behaves differently needs a way through that is not a fork. Because it
        bypasses the model it also bypasses the model's validation: whatever is
        put here reaches the wire as written.

        **The merge is case-insensitive.** The vendor documents the ticket
        create body's field names as case-insensitive (tier 1 --
        ``docs/vendor-api-reference.md``); the other write bodies are assumed
        to match it, which is the safe assumption in either direction here. An
        ``extra_payload`` key that matches a declared field's key or a
        ``custom_fields``-produced key when case is ignored *replaces* it: the
        model's entry is dropped, and ``extra_payload``'s own spelling and
        value are what ship. Without
        that, ``PostRequest(urgency_id=8, extra_payload={"URGENCY_ID": "4"})``
        would put **both** on the wire with conflicting values and leave which
        one the server honours undefined -- and the ``ALL_CAPS`` spelling is
        the one callers reach for, since it mirrors the read side. This is a
        merge rule only; a collision is never an error.
        """
        data = self.model_dump(
            exclude_none=True, exclude={"custom_fields", "extra_payload"}
        )
        for key, value in self.custom_fields.items():
            api_key = key if key.startswith("e_") else f"e_{key}"
            data[api_key] = value
        if self.extra_payload:
            overridden = {str(key).casefold() for key in self.extra_payload}
            data = {
                key: value
                for key, value in data.items()
                if key.casefold() not in overridden
            }
            data.update(self.extra_payload)
        return data
