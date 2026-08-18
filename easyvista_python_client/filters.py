"""Safe builders for EasyVista ``search`` expressions.

EasyVista's search grammar has three traps a caller cannot see, all verified
against a live instance:

1. An expression it cannot parse is **silently ignored** and every record is
   returned — a filter that fails yields the whole table, not an error.
2. ``,`` is a live combinator (OR within one field, AND across fields), so an
   unescaped value that closes its quote can append conditions and silently
   widen the result set.
3. A comparison operator does not exist. A change window is an *interval in the
   value position* — ``FIELD:(a;b)`` — and its bound is UNQUOTED, so
   ``ev_since_filter``/``ev_between_filter`` validate the bound's shape rather
   than escaping it.

These builders exist so none of them can happen. Filters return ``None`` for blank
input so callers compose without conditionals::

    search = ev_equals_filter("DEPARTMENT_CODE", code)
    if search is not None:
        client.search_departments(search=search)

``field`` is expected to be a trusted, developer-supplied constant (e.g.
``"DEPARTMENT_CODE"``) and is not validated; ``value`` is the untrusted input
these builders check.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime

from .timestamps import format_ev_datetime, parse_ev_datetime

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


# An interval bound is rendered UNQUOTED inside `(...)`, so the quote-based
# defence the other builders rely on does not apply here: a ';' would append a
# second bound and a ')' would close the interval early. Validating the shape is
# therefore the guard, not escaping. Deliberately strict — it accepts only the
# renderings measured live: a date, a second-precision ISO timestamp, or the
# full offset-bearing literal the API returns.
#
# This is a SHAPE gate only, not a validity gate: `[0-9]` (not `\d`, which is
# Unicode-aware) keeps non-ASCII digits out, and `fullmatch` anchors both ends
# unconditionally rather than relying on a trailing `$` — which would also
# match just before a newline — so the guard does not silently depend on the
# `.strip()` above having already removed one. Calendar/time validity (e.g.
# ``9999-99-99``, ``25:61:61``) is not this regex's job; :func:`_interval_bound`
# checks that separately via :func:`~easyvista_python_client.parse_ev_datetime`.
_TIMESTAMP_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}"  # YYYY-MM-DD
    r"(?:[T ][0-9]{2}:[0-9]{2}:[0-9]{2}"  # optional T HH:MM:SS
    r"(?:\.[0-9]{1,6})?"  # optional fractional seconds
    r"(?:Z|[+-][0-9]{2}:[0-9]{2})?)?"  # optional offset
)

# A datetime carrying NO ``Z`` and no ``+-HH:MM``. The wire accepts these, and
# reads them in another zone -- measured live 2026-08-18, the same wall-clock
# text with and without its offset enumerated 13 rows and 11 rows against one
# instance, the offset-less form moving the bound *later* and skipping records
# with no error. A bare date deliberately does NOT match: it has day
# granularity and no time to misplace, and round 1 measured it honoured.
_OFFSETLESS_TIME_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?"
)


def _interval_bound(value: str | datetime | None) -> str:
    """Render one interval bound, or ``""`` for an open end.

    Raises ``ValueError`` for anything that is not a timestamp, because the
    bound is interpolated unquoted (see :data:`_TIMESTAMP_RE`). The regex is a
    shape gate; :func:`~easyvista_python_client.parse_ev_datetime` is the
    validity gate behind it, so a well-shaped but impossible timestamp (e.g.
    ``9999-99-99`` or ``25:61:61``) is also refused rather than reaching the
    wire, where a dropped condition returns the whole table rather than an
    error.

    A third gate refuses a **time without a UTC offset**, even though the wire
    accepts one. An offset-less literal is read in another zone, which moves the
    bound and skips records silently -- the one failure mode a watermark must
    never have. :func:`~easyvista_python_client.format_ev_datetime` already
    refuses a naive ``datetime`` on this reasoning; this keeps the string path
    consistent with it. A bare date stays legal.
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        return format_ev_datetime(value)
    text = str(value).strip()
    if not text:
        return ""
    if not _TIMESTAMP_RE.fullmatch(text) or parse_ev_datetime(text) is None:
        raise ValueError(
            f"{value!r} is not an EasyVista timestamp. An interval bound is "
            "interpolated unquoted, so only a date or an ISO-8601 timestamp is "
            "accepted; pass a datetime to be certain."
        )
    if _OFFSETLESS_TIME_RE.fullmatch(text):
        raise ValueError(
            f"{value!r} names a time with no UTC offset, which EasyVista reads "
            "in another zone: that silently moves the bound and skips records "
            "with no error at all. Append the offset (or 'Z'), or pass an aware "
            "datetime and let format_ev_datetime render it. A date alone is "
            "accepted -- it has no time to misplace."
        )
    return text


def ev_since_filter(field: str, start: str | datetime | None) -> str | None:
    """Build an open-ended lower bound: ``FIELD:(start;)``.

    This is the change-window filter. EasyVista has **no** comparison operator —
    ``>=``, ``>``, ``BETWEEN``, ``[a TO b]`` and ``a..b`` are all silently
    dropped, which returns the whole table (256 live trials, zero honoured).
    A range is instead an *interval in the value position*, and the open-ended
    form is exactly a watermark::

        search = ev_since_filter("LAST_UPDATE", watermark)
        if search is not None:
            for ticket in client.iter_tickets(search=search):
                ...

    ``start`` may be a ``datetime`` (the preferred input) or a timestamp
    string. Blank or ``None`` returns ``None``, matching the other builders so
    callers compose without conditionals.
    """
    bound = _interval_bound(start)
    if not bound:
        return None
    return f"{field}:({bound};)"


def ev_between_filter(
    field: str, start: str | datetime | None, end: str | datetime | None
) -> str | None:
    """Build a closed interval: ``FIELD:(start;end)``.

    Either bound may be omitted for a half-open interval. With both omitted the
    result is ``None`` rather than ``FIELD:(;)``, which would match everything.

    Note ``,`` is **not** the separator — ``FIELD:(a,b)`` raises HTTP 590 live.
    """
    low, high = _interval_bound(start), _interval_bound(end)
    if not low and not high:
        return None
    return f"{field}:({low};{high})"


def _wildcard_filter(field: str, value: str | None, pattern: str) -> str | None:
    """Shared body for the ``~`` pattern builders.

    ``pattern`` is a format string over ``{v}`` placing the wildcards.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        # A blank value would render `FIELD~"**"`, which matches every row —
        # the silent-widening failure these builders exist to prevent.
        return None
    if any(char in text for char in ("*", "%")):
        raise ValueError(
            f"{value!r} contains a wildcard character (* or %). These builders "
            "add the wildcards themselves; one inside the value would change "
            "which records match rather than being compared literally."
        )
    return f'{field}~"{pattern.format(v=escape_ev_value(text))}"'


def ev_contains_filter(field: str, value: str | None) -> str | None:
    """Build a substring match: ``FIELD~"*value*"``.

    ``~`` **is** a pattern operator, and it needs an explicit wildcard — verified
    live: ``RFC_NUMBER~"*260817*"`` matched 33 rows while
    ``RFC_NUMBER:"I26081*"`` matched 0, because ``:`` never expands wildcards.
    Without a wildcard, ``~`` degenerates to exact match, which is why this
    package previously documented it as "exact-match, not contains" — that
    conclusion held only for the inputs it was tested with.
    """
    return _wildcard_filter(field, value, "*{v}*")


def ev_starts_with_filter(field: str, value: str | None) -> str | None:
    """Build a prefix match: ``FIELD~"value*"`` (verified live: 32 rows)."""
    return _wildcard_filter(field, value, "{v}*")


__all__ = [
    "escape_ev_value",
    "ev_between_filter",
    "ev_contains_filter",
    "ev_equals_filter",
    "ev_in_filter",
    "ev_since_filter",
    "ev_starts_with_filter",
    "is_safe_ev_value",
]
