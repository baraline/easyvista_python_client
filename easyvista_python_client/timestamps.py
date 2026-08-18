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


def parse_ev_datetime(value: Any) -> datetime | None:
    """Parse an EasyVista timestamp to a timezone-aware ``datetime``, or ``None``.

    Accepts a ``datetime`` (returned as-is; a naive one is treated as UTC) or an
    ISO-8601 string. Normalizes for Python 3.10's stricter ``fromisoformat``:
    maps a trailing ``Z`` to ``+00:00`` and pads/truncates fractional seconds to
    6 digits — EasyVista sends 3, which 3.10 rejects outright. Unparseable input
    returns ``None`` rather than raising, so a single malformed column never
    fails a whole record.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
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
