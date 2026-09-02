"""Shared Pydantic base models for EasyVista resources."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationInfo,
    model_validator,
)

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


# An optional sign, digits, then at most one separator and one or two fraction
# digits. Deliberately refuses a grouping separator -- see the validator.
_EV_DECIMAL = re.compile(r"^[+-]?\d+(?:[.,]\d{1,2})?$")


def _parse_ev_decimal(value: Any) -> Any:
    """Parse EasyVista's locale-formatted money column into an exact ``Decimal``.

    The instance renders a currency column with its own decimal separator: on
    the verified deployment ``TIME_COST`` and ``CONTRACTUAL_COST`` come back as
    ``'0,00'`` / ``'99,00'`` — a **comma** — which is why this exists rather
    than the column being a plain ``float``. Both separators are accepted, so a
    dot-configured deployment needs no setting; the separator is a deployment's
    locale, not an EasyVista constant.

    ``""`` maps to ``None`` and that is load-bearing: ``""`` means the column
    does **not apply** to this record, while ``'0,00'`` means it applies and is
    zero. Collapsing the two — to ``0`` or to ``None`` — destroys the only
    signal that says whether a record tracks cost at all. See
    :class:`~easyvista_python_client.models.action.Action` for what that signal
    is worth and what it does **not** prove.

    **Two shapes raise rather than being guessed at**, both of them formats this
    parser has never seen live:

    * **A grouping separator.** ``'1.234,56'`` and ``'1,234.56'`` are the same
      amount under opposite conventions, and ``'9,999'`` is either ``9.999`` or
      ``9999`` with nothing in the value to say which.
    * **Three or more fraction digits.** ``'1,234'`` is refused for the same
      reason — it is indistinguishable from a comma-grouped ``1234`` — which
      also means a genuinely 3-decimal currency is refused here.

    Note what is **not** a trigger: magnitude. ``'1000,00'`` parses fine, because
    it carries no grouping separator. An earlier revision of this docstring said
    "an amount above 999 is the case to watch", which was wrong — what matters is
    the *format*, not the size.

    Every amount observed live carried exactly two fraction digits and no
    grouping (1500 rows, 2026-09-02: ``'0,00'``, ``'99,00'``, ``'129,00'``).
    Refusing is the same trade :func:`_empty_str_to_none_datetime` makes — a
    wrong number is worse than a loud failure — and it carries the same cost:
    ``resources/descriptor.py`` validates a page in a list comprehension, so one
    unparseable amount fails the whole ``list_actions`` call rather than that
    row. See ``O-COSTGROUP`` in ``docs/vendor-api-reference.md``.

    ``Decimal``, not ``float``, because these are money: ``Decimal('0.10') +
    Decimal('0.20') == Decimal('0.30')`` and the float equivalent does not.
    A non-string value (an ``int``, ``float`` or ``Decimal`` handed in
    directly) passes through to pydantic's own ``Decimal`` validator untouched.
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if not _EV_DECIMAL.match(text):
            raise ValueError(
                f"{value!r} is not an EasyVista amount. Expected digits with at "
                "most one decimal separator ('.' or ',') and ONE OR TWO "
                "fraction digits, e.g. '0,00' or '99.00'. Refused, rather than "
                "guessed at: a grouping separator (because '1.234,56' and "
                "'1,234.56' are the same amount under opposite conventions), and "
                "three or more fraction digits (because '1,234' is "
                "indistinguishable from a comma-grouped 1234). Magnitude is not "
                "a trigger -- '1000,00' parses. If this instance really formats "
                "amounts this way, that is a finding worth recording -- report "
                "the value."
            )
        return Decimal(text.replace(",", "."))
    return value


OptionalDecimal = Annotated[Decimal | None, BeforeValidator(_parse_ev_decimal)]
"""An exact ``Decimal | None`` for an EasyVista currency column.

Accepts either decimal separator and maps the ``""`` sentinel to ``None``,
which is **not** the same answer as ``Decimal('0.00')`` — see
:func:`_parse_ev_decimal`.
"""


def _parse_with_context_formats(value: Any, info: ValidationInfo) -> datetime | None:
    """Try the caller's own timestamp formats, if it supplied any.

    Opt-in and empty by default: with no context this returns ``None``
    immediately and the guard below raises exactly as it always has. The
    patterns are :meth:`datetime.datetime.strptime` format strings, so nothing
    is ever guessed -- a value matching none of them still raises. A pattern
    that parses to a naive datetime is stamped UTC, the same assumption
    :func:`~easyvista_python_client.parse_ev_datetime` documents for an
    offset-less literal on the read path.
    """
    context = info.context
    if not isinstance(context, dict) or not isinstance(value, str):
        return None
    for pattern in context.get("datetime_input_formats") or ():
        try:
            parsed = datetime.strptime(value.strip(), pattern)
        except (TypeError, ValueError):
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _empty_str_to_none_datetime(value: Any, info: ValidationInfo) -> Any:
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

    **The cost of raising is a whole record, and on a search a whole PAGE.**
    ``resources/descriptor.py`` validates a page in a list comprehension, so one
    unparseable timestamp on one row fails the entire ``search_tickets`` call,
    not just that row. That is the deliberate trade -- a wrong instant is worse
    than a loud failure -- but it is the reason for the escape hatch below.

    A deployment whose timestamps are genuinely a different format can name that
    format instead of forking: pass
    ``EasyvistaConfig(datetime_input_formats=("%d/%m/%Y %H:%M:%S",))`` and every
    read through the client validates under it. The native ISO-8601 form is
    tried first, so a listed pattern can never change how a real EasyVista stamp
    parses, and an unlisted format still raises here.
    """
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    parsed = parse_ev_datetime(value)
    if parsed is None:
        parsed = _parse_with_context_formats(value, info)
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

    @model_validator(mode="before")
    @classmethod
    def _point_unknown_keys_at_extra_payload(cls, data: Any) -> Any:
        """Name the unknown keys, and the supported way past them.

        ``extra="forbid"`` catches a caller typo, which is what it is for, but
        its own message ("Extra inputs are not permitted") never mentions
        ``extra_payload`` -- the model's documented route for a field it
        declines to declare. Someone who has just read that a field was
        excluded has no way to learn from the error that there is a way
        through.

        The message stops short of promising the write will work. On this
        package an exclusion is usually a *measured misbehaviour*, not a gap in
        the documentation: ``RequestUpdate.status_id`` returned HTTP 200,
        applied its companion field and dropped the status in silence.
        ``extra_payload`` gets the field onto the wire; it cannot make the
        server store it.
        """
        if not isinstance(data, dict):
            return data
        unknown = sorted(str(key) for key in data if key not in cls.model_fields)
        if not unknown:
            return data
        raise ValueError(
            f"{cls.__name__} does not declare {', '.join(unknown)}. Check the "
            "spelling first. If the field is real on your deployment, send it "
            "as extra_payload={...}: it merges last and reaches the wire as "
            "written. Some fields are absent here because they were measured "
            "to misbehave, not merely because they are undocumented, so "
            "re-read afterwards -- a 200 is not a receipt on this API."
        )

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


def _shipped_keys(model: EasyvistaWriteModel) -> set[str]:
    """The case-folded keys of the body :meth:`EasyvistaWriteModel.to_api` will
    actually send.

    Derived from ``to_api()`` rather than from the declared attributes, so a
    required field supplied through ``extra_payload`` -- this package's
    documented route past a field the model declines to declare -- satisfies a
    guard instead of being refused for a body the API would have accepted.
    Deriving it here also means a guard cannot drift from ``to_api``'s
    case-insensitive merge rule, because it *is* that rule.

    A ``None`` value is dropped. ``to_api`` already drops ``None`` for declared
    fields; a ``None`` arriving through ``extra_payload`` is an absent value,
    not a supplied one.
    """
    return {
        str(key).casefold()
        for key, value in model.to_api().items()
        if value is not None
    }
