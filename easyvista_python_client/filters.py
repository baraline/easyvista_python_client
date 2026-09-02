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
from typing import Literal

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

# A time whose UTC offset carries SECONDS (``+05:53:20``), which
# :data:`_TIMESTAMP_RE` refuses. Matched separately only to DIAGNOSE it: the
# value is perfectly good ISO 8601 -- it is what ``isoformat()`` produces for
# any pre-1900 ``zoneinfo`` instant -- so the generic "not an EasyVista
# timestamp ... pass a datetime to be certain" message would be wrong twice
# over, since parsing it back to a datetime and passing that raises for the
# same underlying reason (see :func:`_render_interval_bound`).
_SUB_MINUTE_OFFSET_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?[+-][0-9]{2}:[0-9]{2}:[0-9]{2}"
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
    truncated to milliseconds, EasyVista's own precision -- truncated **down**,
    never rounded (``.133999`` becomes ``.133``). That direction is not
    symmetric between the two ends of an interval: on the **inclusive lower**
    bound it widens the window, so the worst case is re-reading a record, while
    on an **upper** bound it moves the bound up to 999 microseconds *earlier*
    and NARROWS the window, excluding anything stamped inside the truncated
    remainder. A caller who needs an exact upper bound should hand in a value
    already at millisecond precision. A bare **date** is passed through
    unchanged (see :data:`_DATE_ONLY_RE`).
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
        if _SUB_MINUTE_OFFSET_RE.fullmatch(text):
            raise ValueError(
                f"{value!r} carries a UTC offset that is not a whole number of "
                "minutes, which EasyVista's interval grammar cannot express -- "
                "the value itself is valid ISO 8601 (every pre-1900 zoneinfo "
                "zone renders like this). Convert it to UTC, or to a zone with "
                "a whole-minute offset. Parsing it back to a datetime and "
                "passing that does NOT help: the datetime path refuses the same "
                "offset for the same reason."
            )
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

    **A sweep that does not run to completion is a separate trap under this
    sort.** Because ``DESC`` yields the newest row first, the watermark reaches
    its *final* value on page 1. A sweep interrupted partway through, or capped
    with ``max_records``, still ends up holding the newest stamp — so advancing
    the watermark from it makes the next window's ``(newest;)`` bound
    permanently exclude every row the incomplete sweep never reached. Advance the
    watermark only after a sweep runs to completion.

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

    Both bounds are normalised exactly as :func:`ev_since_filter`'s is (see
    :func:`_interval_bound`): a bare date passes through, and a value naming a
    time is re-rendered at millisecond precision with an explicit offset. The
    sub-millisecond truncation that involves runs **downward**, which is the
    safe direction for the lower bound but not for the upper one —
    ``"...41.133999Z"`` as ``end`` becomes ``"...41.133Z"``, up to 999
    microseconds early. Pass an ``end`` already at millisecond precision when
    the exact instant matters. (EasyVista itself returns millisecond precision,
    so a bound read back from a record cannot fall inside that remainder. The
    *upper* bound's inclusivity is unmeasured — only the lower bound's was
    verified live.)
    """
    low, high = _interval_bound(start), _interval_bound(end)
    if not low and not high:
        return None
    return f"{field}:({low};{high})"


# The wildcard tokens this builder can APPEND. `*` is the one measured live
# 2026-08-17 on the verified instance; `%` reproduced its exact match count
# there (32 of 4317), and is the token a LIKE-backed deployment may use
# instead. Not exported: see `wildcard=` on the two public builders.
_WILDCARD_TOKENS = ("*", "%")

# Metacharacters of `~` ITSELF, evaluated whether or not this builder appends a
# wildcard. Measured live 2026-08-18 against one instance, and it may not
# generalise: the probes in integration_tests/test_live_change_window.py are
# raw `FIELD~"<stem>_"` and `FIELD~"<stem>[0-9]"` -- no wildcard added at all --
# and each widened a one-row exact match to nine, while `[<realchar>x]` still
# matched the one row, so the class is genuinely evaluated. There is no escape:
# a backslash before `_` returned 0 rows, i.e. it is compared literally. These
# stay refused at EVERY `wildcard=` setting, because the refusal was never about
# what this builder adds. `_` is not exotic in EasyVista -- it is pervasive in
# asset tags, catalog codes and `e_*` column values.
_OPERATOR_METACHARS = ("_", "[")

# Everything refused while a wildcard IS being appended: the operator's own
# metacharacters plus the wildcard tokens, a second one of which inside the
# value would compose with the appended one.
_PATTERN_METACHARS = _WILDCARD_TOKENS + _OPERATOR_METACHARS


def _wildcard_filter(
    field: str,
    value: str | None,
    pattern: str,
    wildcard: Literal["*", "%"] | None,
) -> str | None:
    """Shared body for the ``~`` pattern builders.

    ``pattern`` is a format string over ``{w}`` (the wildcard token, or ``""``
    when none is appended) and ``{v}`` (the escaped value).

    ``wildcard`` is validated before anything else, so an unsupported token is
    refused even on a call whose blank ``value`` would return ``None`` -- it is
    a fault in the caller's code, not in their data, and it must not depend on
    what happens to be in ``value`` that day.
    """
    if wildcard is not None and wildcard not in _WILDCARD_TOKENS:
        raise ValueError(
            f"wildcard={wildcard!r} is not a token these builders emit. Pass "
            "'*' (the default, and the token measured live on the verified "
            "instance), '%' (interchangeable with it there, and the token a "
            "LIKE-backed deployment may use instead), or None to append "
            "nothing -- the vendor's plain Contains reading of '~'. The token "
            "is interpolated outside the value escaping, so it comes from a "
            "closed set on purpose; for any other pattern, build the "
            "expression yourself and pass it as a raw search= string."
        )
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        # With a wildcard appended a blank value renders `FIELD~"**"`, which
        # matches every row -- the silent-widening failure these builders exist
        # to prevent. With none appended it renders `FIELD~""`, which asks
        # nothing. Both return None, so callers compose without conditionals
        # either way.
        return None
    if wildcard is None:
        if any(char in text for char in _OPERATOR_METACHARS):
            raise ValueError(
                f"{value!r} contains a pattern metacharacter (one of _ [). "
                "These are metacharacters of '~' ITSELF, not of the wildcard "
                "this builder appends, so wildcard=None does not make them "
                "literal: measured live 2026-08-18 against one instance (it "
                'may not generalise), FIELD~"<stem>_" with no wildcard '
                "appended widened a one-row exact match to nine, and [0-9] in "
                "the same position did the same. EasyVista provides no escape "
                "-- a backslash is compared literally. For an EXACT match use "
                "ev_equals_filter: ':' does not expand a wildcard. If your "
                "deployment compares '_' literally under '~' -- the vendor "
                "documents '~' as plain Contains and names no metacharacters "
                "-- pass the expression as a raw search= string."
            )
    elif any(char in text for char in _PATTERN_METACHARS):
        raise ValueError(
            f"{value!r} contains a pattern metacharacter (one of * % _ [). "
            "These builders add the wildcards themselves; a metacharacter "
            "inside the value would change which records match rather than "
            "being compared literally, and EasyVista provides no escape for it "
            "-- a backslash is taken literally (verified live). For an EXACT "
            "match on a value containing one, use ev_equals_filter: ':' does "
            "not expand a wildcard. To pattern-match around one, filter "
            "server-side on a wider condition and compare exactly in Python. "
            "To place '*' or '%' yourself, pass wildcard=None and put them in "
            "the value."
        )
    rendered = pattern.format(
        w="" if wildcard is None else wildcard, v=escape_ev_value(text)
    )
    return f'{field}~"{rendered}"'


def ev_contains_filter(
    field: str,
    value: str | None,
    *,
    wildcard: Literal["*", "%"] | None = "*",
) -> str | None:
    """Build a substring match: ``FIELD~"*value*"``.

    Two readings of ``~`` are on record, and this builder resolves them in
    favour of the measured one:

    * **Tier 1, vendor documentation** -- ``~`` is *Contains* (Oxygen 1.7+).
      The vendor's grammar table gives it one word, no example, and names
      neither a wildcard nor any metacharacter. On a deployment that behaves
      that way, ``FIELD~"value"`` is already the substring match.
    * **Tier 4, measured live 2026-08-17 against one instance, which may not
      generalise** -- ``~`` behaved as a *pattern* operator needing an explicit
      wildcard. ``RFC_NUMBER~"*260817*"`` matched 33 rows while a bare value
      matched only the one exact row, and ``RFC_NUMBER:"I26081*"`` matched 0,
      because ``:`` never expands a wildcard.

    ``wildcard`` chooses between them. It defaults to ``"*"`` -- the tier-4
    reading -- because that is the only behaviour anyone has measured. Pass
    ``wildcard="%"`` for a deployment whose wildcard is the LIKE one (``%``
    reproduced ``*``'s exact match count on the verified instance, so the two
    are interchangeable there), or ``wildcard=None`` to emit ``FIELD~"value"``
    with nothing appended, which is the vendor's plain Contains.

    **The two settings fail in opposite directions, and neither failure is
    visible in the response.** Appending a wildcard on a deployment that
    compares ``*`` literally returns zero rows with HTTP 200 and no hint;
    ``wildcard=None`` on a deployment like the verified one degenerates to an
    exact match. Confirm once which reading your deployment follows -- compare
    a filtered count against the unfiltered baseline -- rather than guessing
    per call.

    A value containing ``_`` or ``[`` raises ``ValueError`` **at every**
    ``wildcard`` setting, including ``None``: both are metacharacters of ``~``
    itself rather than of the wildcard this builder appends. Measured live
    2026-08-18 against one instance, and it may not generalise --
    ``FIELD~"<stem>_"``, with no wildcard appended at all, widened a one-row
    exact match to nine; ``[0-9]`` in the same position did the same; and there
    is no escape, a backslash before the character being compared literally.
    ``*`` and ``%`` are refused **only** while a wildcard is being appended,
    where a second one in the value would compose with it; with
    ``wildcard=None`` they pass through, which is how to hand-build a pattern
    through this builder.

    Refusing beats silently matching records the caller did not ask for --
    ``ev_contains_filter("ASSET_TAG", "LAPTOP_01")`` would otherwise also match
    ``LAPTOP-01`` and ``LAPTOP001`` with HTTP 200 and no hint. For an **exact**
    match on such a value use :func:`ev_equals_filter`, whose ``:`` does not
    expand a wildcard. Only pattern-matching *around* a literal metacharacter
    is impossible here: that needs a wider server-side condition plus an exact
    comparison in Python, or an expression built by hand and passed to the
    caller's own ``search=`` argument, which every search method accepts as a
    raw unvalidated string.
    """
    return _wildcard_filter(field, value, "{w}{v}{w}", wildcard)


def ev_starts_with_filter(
    field: str,
    value: str | None,
    *,
    wildcard: Literal["*", "%"] | None = "*",
) -> str | None:
    """Build a prefix match: ``FIELD~"value*"`` (verified live 2026-08-17: 32 rows).

    ``wildcard`` means what it means in :func:`ev_contains_filter`, including
    its default of ``"*"`` and the two readings of ``~`` documented there --
    the vendor's tier-1 *Contains*, and this package's tier-4 measurement of a
    pattern operator, taken 2026-08-17 against one instance and not necessarily
    general.

    **``wildcard=None`` does not express a prefix on either kind of
    deployment.** It emits ``FIELD~"value"``, which is an exact match on the
    verified instance and an *unanchored substring* match on a deployment that
    follows the vendor's reading. So on this builder ``None`` removes the
    anchor rather than swapping a token: use it only once you have confirmed
    which reading you are on, and expect a wider result set than the function
    name promises if that reading is the vendor's.

    Refuses ``_`` and ``[`` in ``value`` at every ``wildcard`` setting, and
    ``*``/``%`` while a wildcard is being appended, for the reasons and with
    the exits given in :func:`ev_contains_filter`.
    """
    return _wildcard_filter(field, value, "{v}{w}", wildcard)


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
