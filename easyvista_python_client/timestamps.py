"""EasyVista's timestamp format, in one place.

Established against a live instance on 2026-08-17: every returned timestamp is
**ISO 8601 with an explicit UTC offset** and millisecond precision, e.g.
``2026-08-17T15:40:41.610+02:00``. Verified by arithmetic, not inspection — a
write bracketed by our own UTC clock at ``13:40:40.411Z``/``13:40:40.869Z``
produced ``15:40:41.610+02:00``, which *is* ``13:40:41.610Z``.

Two consequences worth stating, because both have bitten callers:

* The ``_UT`` suffix does **not** mean UTC-normalized. ``CREATION_DATE_UT`` and
  ``SUBMIT_DATE_UT`` carry the same local offset as ``LAST_UPDATE``. Treat it as
  a naming convention, not a zone promise.
* An **unset** date is the empty string, not ``null``. A parser that only guards
  ``None`` raises on real data.

One deliberate asymmetry, stated here because it looks like an inconsistency
otherwise. On the **read** path :func:`parse_ev_datetime` assumes UTC for a
literal that carries no offset, because an extractor must never fail a record
over one column. On the **write/query** path
:func:`easyvista_python_client.filters._interval_bound` *refuses* the identical
shape, because a mis-zoned interval bound silently moves the window and skips
records — the one failure a watermark must not have, and there a ``ValueError``
costs the caller nothing but a corrected input. So a naive stamp read back from
an instance becomes a confidently offset-bearing ``datetime``: if a deployment
ever returns offset-less timestamps, that guess is laundered past the filter
guard, and the assumption -- not the guard -- is what to revisit.

This module is a leaf: it imports nothing from the package, so both ``models/``
and ``filters.py`` can use it without a cycle.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

_FRACTION_RE = re.compile(r"\.(\d+)")


#: EasyVista sends the extended calendar date; the ISO basic forms that 3.11+
#: also accepts are not its format on any interpreter. See parse_ev_datetime.
_EXTENDED_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_ev_datetime(value: Any) -> datetime | None:
    """Parse an EasyVista timestamp to a timezone-aware ``datetime``, or ``None``.

    Accepts a ``datetime`` (returned as-is; a naive one is treated as UTC) or an
    ISO-8601 string. Normalizes for Python 3.10's stricter ``fromisoformat``:
    maps a trailing ``Z`` to ``+00:00`` and pads/truncates fractional seconds to
    6 digits — EasyVista sends 3, which 3.10 rejects outright. Unparseable input
    returns ``None`` rather than raising, so a single malformed column never
    fails a whole record.

    **A value must start with an extended ISO date** (``YYYY-MM-DD``) or it is
    refused, on every interpreter. From 3.11 ``fromisoformat`` also accepts the
    ISO *basic* forms — ``"20260817"``, ``"20260817T154041.610"``, week dates
    like ``"2026W331"`` — which 3.10 rejects, so without this rule the same wire
    value parsed to an instant on four of the five supported Pythons and raised
    on the fifth. CI found it precisely that way: 3.10 green, 3.11 and 3.12 red.

    The rule is stated positively because the reject-list version of it was
    wrong: "digits only" catches ``"20260817"`` and misses both a basic
    date-time (it has a ``.``) and a week date (it has a ``W``). EasyVista's
    format always carries separators, so none of these is one of its timestamps
    on any interpreter, and accepting one would let a genuine format change
    through as a plausible instant. A deployment that really sends such a form
    names it through ``EasyvistaConfig(datetime_input_formats=("%Y%m%d",))``,
    which is tried after this returns ``None``.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    # Require the extended (separator-bearing) calendar date ISO 8601 mandates
    # for EasyVista's own format. Stated positively on purpose: enumerating the
    # basic forms to reject misses them -- week dates ("2026W331") and basic
    # date-times ("20260817T154041.610") are not digit-only, and 3.11+ parses
    # both. See the docstring for why this cannot be left to fromisoformat.
    if not _EXTENDED_DATE_RE.match(text):
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    match = _FRACTION_RE.search(text)
    if match:
        frac6 = (match.group(1) + "000000")[:6]
        text = text[: match.start()] + "." + frac6 + text[match.end() :]
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def format_ev_datetime(value: datetime) -> str:
    """Render ``value`` as the literal EasyVista's search grammar accepts.

    Millisecond precision with an explicit offset — byte-identical to what the
    API itself returns, and verified live as an accepted interval bound
    (``LAST_UPDATE:(2025-11-28T16:14:41.133+01:00;…)`` was honoured).

    Raises ``ValueError`` for a naive datetime. ``ValueError``, not an
    ``Easyvista*`` error, because nothing reached the API: this is a local input
    fault, the same reasoning as :func:`~easyvista_python_client.escape_ev_value`.
    Refusing beats guessing a zone — a naive instant does not name a moment, and
    silently assuming UTC would shift every bound by the server's offset.
    """
    if value.tzinfo is None:
        raise ValueError(
            "an EasyVista timestamp must be timezone-aware; a naive datetime "
            "does not name a unique instant and would silently shift the bound"
        )
    return value.isoformat(timespec="milliseconds")


__all__ = ["format_ev_datetime", "parse_ev_datetime"]
