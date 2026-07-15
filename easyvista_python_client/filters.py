"""Safe builders for EasyVista ``search`` expressions.

EasyVista's search grammar has two traps a caller cannot see, both verified
against a live instance:

1. An expression it cannot parse is **silently ignored** and every record is
   returned — a filter that fails yields the whole table, not an error.
2. ``,`` is a live combinator (OR within one field, AND across fields), so an
   unescaped value that closes its quote can append conditions and silently
   widen the result set.

These builders exist so neither can happen. Filters return ``None`` for blank
input so callers compose without conditionals::

    search = ev_equals_filter("DEPARTMENT_CODE", code)
    if search is not None:
        client.search_departments(search=search)

``field`` is expected to be a trusted, developer-supplied constant (e.g.
``"DEPARTMENT_CODE"``) and is not validated; ``value`` is the untrusted input
these builders check.
"""

from __future__ import annotations

from collections.abc import Iterable

# A double quote terminates the quoted value, letting a caller reach the ','
# combinator; no escape for it is known (verified live). ',' itself is NOT
# rejected: inside quotes it is inert, so without a '"' it cannot combine.
_UNSAFE_CHARS = ('"',)


def is_safe_ev_value(value: str) -> bool:
    """Whether ``value`` can be rendered inside an EasyVista search expression."""
    return not any(char in value for char in _UNSAFE_CHARS)


def escape_ev_value(value: str) -> str:
    """Render ``value`` for use inside a quoted EasyVista search value.

    Raises ``ValueError`` if it cannot be rendered safely. ``ValueError`` — not
    ``EasyvistaValidationError`` — because nothing reached the API: this is a
    local input fault, not a server rejection.
    """
    if not is_safe_ev_value(value):
        raise ValueError(
            f"{value!r} cannot be used in an EasyVista search: the double-quote "
            "character terminates a quoted value and EasyVista provides no escape "
            "for it."
        )
    return value


def ev_equals_filter(field: str, value: str | int | None) -> str | None:
    """Build an exact-match filter: ``FIELD:"value"``."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return f'{field}:"{escape_ev_value(text)}"'


def ev_in_filter(field: str, values: Iterable[str | int | None]) -> str | None:
    """Build a "field is one of these" filter: ``FIELD:"a",FIELD:"b"``.

    ``,`` is OR when every condition names the same field (verified live).
    Blank values are skipped; no usable value returns ``None``.
    """
    parts = [f for f in (ev_equals_filter(field, v) for v in values) if f]
    if not parts:
        return None
    return ",".join(parts)


__all__ = [
    "escape_ev_value",
    "ev_equals_filter",
    "ev_in_filter",
    "is_safe_ev_value",
]
