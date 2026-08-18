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
# therefore the guard, not escaping.
#
# This regex is the ADMISSION gate — which strings a caller may hand in — and it
# is deliberately WIDER than the set the wire honours, because
# :func:`_interval_bound` re-renders every admitted time through
# :func:`~easyvista_python_client.format_ev_datetime` before emitting it.
# Measured live 2026-08-18, a *time* bound is honoured only at millisecond
# precision with an explicit offset (or ``Z``); second precision with an offset
# (``2025-11-28T16:14:41+01:00``), minute precision, and a space instead of
# ``T`` are all HTTP 590. A bare date is honoured as written. Admitting the
# wider set and normalising is what lets a caller pass a stored watermark string
# at all instead of having to pre-render it in exactly one shape.
#
# This is a SHAPE gate only, not a validity gate: `[0-9]` (not `\d`, which is
# Unicode-aware) keeps non-ASCII digits out, and `fullmatch` anchors both ends
# unconditionally rather than relying on a trailing `$` — which would also
# match just before a newline — so the guard does not silently depend on the
# `.strip()` above having already removed one. Calendar/time validity (e.g.
# ``9999-99-99``, ``25:61:61``) is not this regex's job; :func:`_interval_bound`
# checks that separately via :func:`~easyvista_python_client.parse_ev_datetime`.
# ``z`` is accepted lowercase because ``parse_ev_datetime`` accepts it on the
# read path; refusing it here would reject a value this package itself produced.
_TIMESTAMP_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}"  # YYYY-MM-DD
    r"(?:[T ][0-9]{2}:[0-9]{2}:[0-9]{2}"  # optional T HH:MM:SS
    r"(?:\.[0-9]{1,6})?"  # optional fractional seconds
    r"(?:[Zz]|[+-][0-9]{2}:[0-9]{2})?)?"  # optional offset
)

# A bare calendar date, which is passed through UNCHANGED rather than
# normalised: it has day granularity, the API honours it as written, and
# re-rendering it would invent a midnight instant in some zone.
_DATE_ONLY_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

# A datetime carrying NO ``Z`` and no ``+-HH:MM``. The wire accepts these, and
# reads them in another zone -- measured live 2026-08-18, the same wall-clock
# text with and without its offset enumerated 13 rows and 11 rows against one
# instance, the offset-less form moving the bound *later* and skipping records
# with no error. A bare date deliberately does NOT match: it has day
# granularity and no time to misplace, and round 1 measured it honoured.
_OFFSETLESS_TIME_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?"
)


def _render_interval_bound(moment: datetime) -> str:
    """Render one time bound in the single form measured live as honoured.

    :func:`~easyvista_python_client.format_ev_datetime` emits millisecond
    precision with an explicit offset, which is the ONLY time rendering the
    interval grammar accepts: second precision with an offset, minute precision
    and a space separator instead of ``T`` are each HTTP 590 (measured live
    2026-08-18).

    The rendering is re-checked against :data:`_TIMESTAMP_RE` rather than
    trusted, because a zone whose UTC offset is not a whole number of minutes --
    every pre-1900 ``zoneinfo`` entry has one, e.g. ``Asia/Kolkata`` at
    ``+05:53:20`` -- renders as ``+05:53:20``, which the string path refuses and
    which the wire has no reason to honour either. Without this check the
    datetime path could emit a bound the string path would reject, which is the
    asymmetry this function exists to remove.
    """
    rendered = format_ev_datetime(moment)
    if not _TIMESTAMP_RE.fullmatch(rendered):
        raise ValueError(
            f"{moment!r} renders as {rendered!r}, which EasyVista's interval "
            "grammar cannot express: its UTC offset is not a whole number of "
            "minutes (historical zoneinfo zones carry such offsets). Convert "
            "the datetime to UTC, or to a zone with a whole-minute offset."
        )
    return rendered


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

    Past those gates an admitted **time** is NORMALISED rather than passed
    through: it is re-rendered by :func:`_render_interval_bound`, so the string
    and datetime paths emit byte-identical bounds and both emit the one
    rendering measured live as honoured. This is not cosmetic --
    ``"2025-11-28T16:14:41+01:00"``, the most natural way to comply with the
    offset gate, is HTTP 590 on the wire as written and becomes
    ``2025-11-28T16:14:41.000+01:00`` here. Sub-millisecond precision is
    truncated to milliseconds, EasyVista's own precision. A bare **date** is
    passed through unchanged (see :data:`_DATE_ONLY_RE`).
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        return _render_interval_bound(value)
    text = str(value).strip()
    if not text:
        return ""
    parsed = parse_ev_datetime(text) if _TIMESTAMP_RE.fullmatch(text) else None
    if parsed is None:
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
    if _DATE_ONLY_RE.fullmatch(text):
        return text
    return _render_interval_bound(parsed)


def ev_since_filter(field: str, start: str | datetime | None) -> str | None:
    """Build an open-ended lower bound: ``FIELD:(start;)``.

    This is the change-window filter. EasyVista has **no** comparison operator —
    ``>=``, ``>``, ``BETWEEN``, ``[a TO b]`` and ``a..b`` are all silently
    dropped, which returns the whole table (256 live trials, zero honoured).
    A range is instead an *interval in the value position*, and the open-ended
    form is exactly a watermark::

        search = ev_since_filter("LAST_UPDATE", watermark)
        if search is not None:
            seen = set()
            for ticket in client.iter_tickets(
                search=search, sort="LAST_UPDATE DESC"
            ):
                if ticket.rfc_number in seen:
                    continue
                seen.add(ticket.rfc_number)
                ...

    **The sort is load-bearing, and its DIRECTION decides whether a dropped row
    ever comes back.** ``iter_tickets`` walks the result set by offset, and the
    rows this filter selects are by construction the rows that are changing, so
    a row touched between page N and page N+1 moves *within the very set being
    paged*. Either direction can drop a row from the current sweep; what differs
    is where the dropped row's own timestamp ends up relative to the watermark
    this sweep will record:

    * **Descending** (``LAST_UPDATE DESC``) — the re-touched row jumps to the
      *head*, behind the read cursor, so this sweep misses it. But its
      ``LAST_UPDATE`` is now *above* the watermark, so the next sweep selects it
      again: the miss is **deferred and self-healing**.
    * **Ascending** (bare ``LAST_UPDATE``, or ``LAST_UPDATE ASC``) — the
      re-touched row moves to the tail, and every row between its old place and
      the tail shifts one position head-ward. The row that crosses the cursor is
      therefore one whose own stamp did **not** change; it falls *below* the new
      watermark, so no later sweep selects it either. The miss is **permanent**.

    So sweep **descending** and de-duplicate by ``rfc_number`` as above. Both
    directions are honoured tokens (measured live); the direction is chosen for
    this reason, not for availability. An earlier docstring in this package
    recommended ascending, on the reasoning that it turns a permanent miss into a
    duplicate — that was wrong: the row an ascending sweep drops is not the
    re-touched one.

    Descending is the safe direction, not a guarantee: ``iter_tickets`` owns its
    offset. A caller who cannot tolerate even a deferred miss should page
    :meth:`~easyvista_python_client.EasyvistaClient.search_tickets` directly
    with **keyset** pagination: sort ascending and, after each page, advance the
    *window* — ``ev_since_filter(field, max(stamps on the page))`` read again at
    ``offset=0`` — instead of incrementing an offset. With no offset there is no
    cursor for a row to shift past. ``iter_tickets`` cannot express this.

    The lower bound is **INCLUSIVE** and milliseconds are honoured (verified
    live on three independent boundaries), so a watermark taken as
    ``max(t.last_update)`` re-reads that boundary record on the next sweep —
    another duplicate the same de-duplication absorbs.

    ``start`` may be a ``datetime`` (the preferred input) or a timestamp
    string; a string naming a time is re-rendered to the one form the wire
    honours (see :func:`_interval_bound`). Blank or ``None`` returns ``None``,
    matching the other builders so callers compose without conditionals.
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


# Every character that is a metacharacter to `~`, measured live 2026-08-18
# against one instance:
#   *  %  multi-character wildcards, interchangeable
#   _     SINGLE-character wildcard -- replacing one character of an RFC that
#         matched 1 row turned it into 9
#   [     opens a character class -- `[0-9]` in the same position also gave 9,
#         and `[<realchar>x]` gave 1, so the class is genuinely evaluated
# There is no escape: `\_` returned 0 rows, i.e. the backslash is compared
# literally. So these builders refuse rather than silently changing which
# records match -- and `_` is not exotic in EasyVista, it is pervasive in asset
# tags, catalog codes and `e_*` column values.
_PATTERN_METACHARS = ("*", "%", "_", "[")


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
    if any(char in text for char in _PATTERN_METACHARS):
        raise ValueError(
            f"{value!r} contains a pattern metacharacter (one of * % _ [). "
            "These builders add the wildcards themselves; a metacharacter "
            "inside the value would change which records match rather than "
            "being compared literally, and EasyVista provides no escape for it "
            "-- a backslash is taken literally (verified live)."
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

    A value containing ``*``, ``%``, ``_`` or ``[`` raises ``ValueError``: all
    four are metacharacters to ``~`` (``_`` matches any single character, ``[``
    opens a character class), and no escape for them exists. Refusing beats
    silently matching records the caller did not ask for —
    ``ev_contains_filter("ASSET_TAG", "LAPTOP_01")`` would otherwise also match
    ``LAPTOP-01`` and ``LAPTOP001`` with HTTP 200 and no hint.
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
