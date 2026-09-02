from datetime import datetime, timedelta, timezone

import pytest

from easyvista_python_client import (
    escape_ev_value,
    ev_between_filter,
    ev_contains_filter,
    ev_equals_filter,
    ev_in_filter,
    ev_since_filter,
    ev_starts_with_filter,
    is_safe_ev_value,
)

_CET = timezone(timedelta(hours=1))


def test_equals_filter_quotes_the_value():
    assert ev_equals_filter("DEPARTMENT_CODE", "ACME") == 'DEPARTMENT_CODE:"ACME"'


def test_equals_filter_quotes_ints_too():
    # EasyVista quotes numerics: DEPARTMENT_ID:"60", not DEPARTMENT_ID:60.
    assert ev_equals_filter("DEPARTMENT_ID", 60) == 'DEPARTMENT_ID:"60"'


@pytest.mark.parametrize("value", [None, "", "   "])
def test_blank_returns_none_so_callers_can_compose(value):
    assert ev_equals_filter("F", value) is None


def test_in_filter_joins_same_field_with_comma():
    # ',' is OR within a single field - verified live in Task 1.
    expected = 'DEPARTMENT_CODE:"A",DEPARTMENT_CODE:"B"'
    assert ev_in_filter("DEPARTMENT_CODE", ["A", "B"]) == expected


def test_in_filter_skips_blank_values():
    assert ev_in_filter("F", ["A", "", None, "B"]) == 'F:"A",F:"B"'


def test_in_filter_returns_none_when_no_usable_values():
    assert ev_in_filter("F", []) is None
    assert ev_in_filter("F", ["", "  "]) is None


def test_escape_rejects_quote():
    with pytest.raises(ValueError, match="cannot be used in an EasyVista search"):
        escape_ev_value('22" monitor')


def test_escape_allows_comma_because_it_is_inert_inside_quotes():
    # Verified live: CODE:"A,B" matches nothing rather than combining.
    assert escape_ev_value("A,B") == "A,B"


def test_equals_filter_rejects_unsafe_value():
    with pytest.raises(ValueError):
        ev_equals_filter("DEPARTMENT_CODE", 'X"')


def test_is_safe_predicate_never_raises():
    assert is_safe_ev_value("ACME") is True
    assert is_safe_ev_value('X"') is False


def test_since_emits_the_open_ended_interval():
    """``FIELD:(a;)`` — the form measured live as a watermark lower bound.

    The bound is NORMALISED, not passed through. The literal below is the most
    natural way for a caller to satisfy the offset gate, and measured live
    2026-08-18 it is HTTP 590 exactly as written -- second precision with an
    offset is not a rendering the interval grammar accepts. So the builder
    re-renders it at millisecond precision, which is.
    """
    got = ev_since_filter("LAST_UPDATE", "2025-11-28T16:14:41+01:00")
    assert got == "LAST_UPDATE:(2025-11-28T16:14:41.000+01:00;)"


def test_since_normalises_a_space_separated_literal_to_the_T_form():
    """``str(aware_datetime)`` uses a space, which is HTTP 590 on the wire.

    Measured live 2026-08-18 (and again in round 1). Normalising is what makes
    the most obvious Python rendering of an aware datetime usable at all.
    """
    got = ev_since_filter("LAST_UPDATE", "2025-11-28 16:14:41.133+01:00")
    assert got == "LAST_UPDATE:(2025-11-28T16:14:41.133+01:00;)"


def test_since_accepts_a_lowercase_z_the_read_path_already_accepts():
    """``parse_ev_datetime`` accepts ``z``; the gate must not contradict it.

    Rejecting a value this package's own read path produces -- with a message
    reading "is not an EasyVista timestamp" -- would be actively misleading.
    """
    got = ev_since_filter("LAST_UPDATE", "2025-11-28T15:14:41.133z")
    assert got == "LAST_UPDATE:(2025-11-28T15:14:41.133+00:00;)"


def test_the_string_and_datetime_paths_emit_byte_identical_bounds():
    """The last asymmetry between the two input paths, closed by normalisation.

    Before this, the same instant emitted two different literals depending on
    whether the caller had already stringified it -- and only one of the two was
    a rendering the wire honours.
    """
    dt = datetime(2025, 11, 28, 16, 14, 41, 133000, tzinfo=_CET)
    assert ev_since_filter("LAST_UPDATE", dt) == ev_since_filter(
        "LAST_UPDATE", dt.isoformat()
    )


def test_since_accepts_a_datetime_and_formats_the_offset_literal():
    dt = datetime(2025, 11, 28, 16, 14, 41, 133000, tzinfo=_CET)
    assert ev_since_filter("LAST_UPDATE", dt) == (
        "LAST_UPDATE:(2025-11-28T16:14:41.133+01:00;)"
    )


def test_between_emits_both_bounds():
    got = ev_between_filter("LAST_UPDATE", "2025-11-28", "2099-12-31")
    assert got == "LAST_UPDATE:(2025-11-28;2099-12-31)"


def test_blank_input_returns_none_so_callers_compose_without_conditionals():
    assert ev_since_filter("LAST_UPDATE", None) is None
    assert ev_since_filter("LAST_UPDATE", "") is None
    assert ev_between_filter("LAST_UPDATE", None, None) is None


def test_between_with_only_an_end_bound_is_open_on_the_left():
    assert ev_between_filter("LAST_UPDATE", None, "2099-12-31") == (
        "LAST_UPDATE:(;2099-12-31)"
    )


@pytest.mark.parametrize(
    "bad",
    [
        '2025-11-28";DEPARTMENT_ID:"9',  # quote breakout
        "2025-11-28;2099-12-31",  # a second bound smuggled in
        "2025-11-28)",  # closes the interval early
        "2025-11-28 or 1=1",
        "today",  # a real EV token, but not a timestamp
    ],
)
def test_interval_refuses_anything_that_is_not_a_timestamp(bad):
    """The interval value is UNQUOTED, so ';' and ')' would break out of it.

    ``ev_equals_filter`` can rely on quoting; this one cannot, so it validates
    the shape instead. Refuse rather than interpolate.
    """
    with pytest.raises(ValueError, match="timestamp"):
        ev_since_filter("LAST_UPDATE", bad)


@pytest.mark.parametrize(
    "bad",
    [
        "9999-99-99",  # no such month
        "2025-02-30",  # no such day (February)
        "2025-13-45T99:99:99",  # no such month/day/time at all
        "2025-11-28T25:61:61",  # out-of-range time components
        "٢٠٢٥-١١-٢٨",  # non-ASCII digits  # noqa: RUF001
    ],
)
def test_interval_refuses_a_well_shaped_but_impossible_timestamp(bad):
    """The regex is a shape gate only; a calendar-invalid value must still be
    refused, because a dropped condition returns the whole table rather than
    an error (this is what makes a typo'd watermark dangerous).
    """
    with pytest.raises(ValueError, match="timestamp"):
        ev_since_filter("LAST_UPDATE", bad)


@pytest.mark.parametrize(
    ("literal", "emitted"),
    [
        # A date alone is legal AND is passed through unchanged: day
        # granularity, no time to misplace, and measured live as honoured
        # (round 1: 4107 rows against a 4316-row table). Re-rendering it would
        # invent a midnight instant in some zone.
        ("2025-11-28", "2025-11-28"),
        # Already the one honoured time rendering: normalisation is a no-op.
        ("2025-11-28T16:14:41.133+01:00", "2025-11-28T16:14:41.133+01:00"),
        # Microseconds are truncated to EasyVista's own millisecond precision.
        ("2025-11-28T16:14:41.133456Z", "2025-11-28T16:14:41.133+00:00"),
    ],
)
def test_interval_accepts_every_rendering_measured_live(literal, emitted):
    """The guard's acceptance side: a regression here fails CLOSED on real
    watermarks, which no rejection test would catch.

    Accepted is not the same as emitted verbatim -- every admitted *time* is
    re-rendered into the one form measured live as honoured. See
    ``test_since_emits_the_open_ended_interval``.

    The offset-less *time* renderings that round 1 measured as accepted by the
    API moved to ``test_interval_refuses_a_time_without_an_offset``: the wire
    takes them, but it reads them in another zone. See that test.
    """
    assert ev_since_filter("LAST_UPDATE", literal) == f"LAST_UPDATE:({emitted};)"


def test_interval_refuses_a_sub_minute_utc_offset_on_either_path():
    """A whole-minute offset is not a given: historical zoneinfo zones break it.

    ``format_ev_datetime`` would render ``+05:53:20``, which no shape this
    grammar accepts can express -- and which the string path already refused.
    Validating the RENDERED bound is what keeps the datetime path from emitting
    something its own sibling path would reject.

    Both paths must give the SAME diagnosis, which is why the string half matches
    on "whole number of minutes" rather than merely on "timestamp". The generic
    message ("is not an EasyVista timestamp ... pass a datetime to be certain")
    would be wrong twice over here: the value IS a valid ISO-8601 timestamp -- it
    is what ``isoformat()`` returns for such a zone -- and following the advice
    raises on the datetime path for the same underlying reason.
    """
    odd = timezone(timedelta(hours=5, minutes=53, seconds=20))
    aware = datetime(2025, 11, 28, 16, 14, 41, tzinfo=odd)
    with pytest.raises(ValueError, match="whole number of minutes"):
        ev_since_filter("LAST_UPDATE", aware)
    with pytest.raises(ValueError, match="whole number of minutes"):
        ev_since_filter("LAST_UPDATE", aware.isoformat())
    # The fractional-second variant takes the same branch: `isoformat()` emits
    # microseconds whenever they are non-zero, so this is the shape a caller who
    # serialised `datetime.now(odd)` would actually hand back.
    with pytest.raises(ValueError, match="whole number of minutes"):
        ev_since_filter("LAST_UPDATE", aware.replace(microsecond=133999).isoformat())
    # A genuinely unparseable value must keep the generic message -- the new
    # branch must not swallow it.
    with pytest.raises(ValueError, match="is not an EasyVista timestamp"):
        ev_since_filter("LAST_UPDATE", "not-a-timestamp")


@pytest.mark.parametrize(
    "bad",
    [
        "2025-11-28T16:14:41",
        "2025-11-28 16:14:41",
        "2025-11-28T16:14:41.133",
        "2025-11-28T16:14:41.133456",
    ],
)
def test_interval_refuses_a_time_without_an_offset(bad):
    """An offset-less time SILENTLY SHIFTS the window, so refuse it locally.

    The API *accepts* these -- which is precisely the danger. Measured live
    2026-08-18 against one instance, the same wall-clock text with and without
    its offset enumerated 13 rows and 11 rows respectively; the offset-less form
    is read in another zone, moving the bound *later* and skipping records with
    no error of any kind. A watermark that silently skips is the worst outcome
    this grammar can produce.

    ``format_ev_datetime`` already refuses a naive ``datetime`` for exactly this
    reason, and its docstring says so. Accepting a naive *string* let the same
    hazard reach the wire by the other path, so both paths now refuse.
    """
    with pytest.raises(ValueError, match="offset"):
        ev_since_filter("LAST_UPDATE", bad)


def test_between_refuses_an_offsetless_time_on_either_bound():
    """Both bounds go through the same gate, so neither may be naive."""
    with pytest.raises(ValueError, match="offset"):
        ev_between_filter("LAST_UPDATE", "2025-11-28T16:14:41", "2025-12-01")
    with pytest.raises(ValueError, match="offset"):
        ev_between_filter("LAST_UPDATE", "2025-11-28", "2025-12-01T16:14:41")


def test_contains_wraps_the_value_in_wildcards_with_the_tilde_operator():
    """``~`` IS a pattern operator; it needs an explicit ``*`` (measured live)."""
    assert ev_contains_filter("ASSET_TAG", "LAPTOP") == 'ASSET_TAG~"*LAPTOP*"'


def test_starts_with_anchors_on_the_left_only():
    assert ev_starts_with_filter("RFC_NUMBER", "I26081") == 'RFC_NUMBER~"I26081*"'


def test_wildcard_builders_reject_a_double_quote():
    """Same reasoning as escape_ev_value: no escape for '"' exists."""
    with pytest.raises(ValueError):
        ev_contains_filter("ASSET_TAG", 'LAP"TOP')


@pytest.mark.parametrize(
    "bad",
    [
        "LAP*TOP",
        "LAP%TOP",
        # `_` is a SINGLE-character wildcard under `~`, measured live: replacing
        # one character of an RFC that matched 1 row gave 9. Underscores are
        # pervasive in EasyVista codes, so this is the routine case, not the
        # exotic one -- `ASSET_TAG~"*LAPTOP_01*"` also matches `LAPTOP-01`.
        "LAP_TOP",
        "LAPTOP_01",
        # `[` opens a character class; `[0-9]` in the same position also gave 9.
        "LAP[0-9]TOP",
        # A backslash does NOT escape it (`\\_` returned 0 rows live), so an
        # escaped-looking value is refused too rather than silently mismatching.
        r"LAP\_TOP",
    ],
)
def test_wildcard_builders_reject_a_metacharacter_inside_the_value(bad):
    """A metacharacter in the middle silently changes what the caller asked for.

    ``ev_contains_filter("A*B")`` would match "A" then anything then "B" rather
    than the literal "A*B", so refuse instead of quietly widening the query.
    All four of ``* % _ [`` behave this way under ``~`` (measured live) and none
    of them can be escaped, so all four are refused on the identical rationale.
    """
    with pytest.raises(ValueError, match="metacharacter"):
        ev_contains_filter("ASSET_TAG", bad)
    with pytest.raises(ValueError, match="metacharacter"):
        ev_starts_with_filter("ASSET_TAG", bad)


@pytest.mark.parametrize("blank", [None, "", "   "])
@pytest.mark.parametrize("wildcard", ["*", "%", None])
def test_blank_wildcard_value_returns_none_not_a_match_everything_pattern(
    blank, wildcard
):
    """``FIELD~"**"`` would match every row — the exact silent-widening shape.

    ``None`` is included because the signature says ``str | None``: without the
    guard, ``str(None)`` would render ``FIELD~"*None*"``, a pattern that both
    widens silently and matches on a value no caller ever supplied.

    The ``wildcard`` axis pins that the blank guard sits *ahead* of the render
    on every setting. At ``wildcard=None`` the pattern would be ``FIELD~""``
    rather than ``FIELD~"**"`` — it asks nothing instead of asking everything,
    which is a different failure, but returning ``None`` uniformly is what lets
    callers compose without a per-setting conditional.
    """
    assert ev_contains_filter("ASSET_TAG", blank, wildcard=wildcard) is None
    assert ev_starts_with_filter("ASSET_TAG", blank, wildcard=wildcard) is None


# --- `wildcard=`: which reading of `~` this expression is built for ----------
#
# The vendor documents `~` as plain Contains (tier 1, no wildcard named); this
# package measured it live 2026-08-17 as a pattern operator needing an explicit
# one (tier 4, one instance). The default stays the measured reading, so every
# test above this line exercises the unchanged path.


def test_percent_wildcard_is_emitted_verbatim():
    """``%`` is the token a LIKE-backed deployment may use instead of ``*``."""
    assert (
        ev_contains_filter("ASSET_TAG", "LAPTOP", wildcard="%")
        == 'ASSET_TAG~"%LAPTOP%"'
    )
    assert (
        ev_starts_with_filter("RFC_NUMBER", "I26081", wildcard="%")
        == 'RFC_NUMBER~"I26081%"'
    )


def test_wildcard_none_appends_nothing():
    """``wildcard=None`` emits the bare value — the vendor's plain Contains.

    The equality between the two builders is the point, not an accident of the
    assertion style: with nothing appended there is no anchor left to
    distinguish a prefix from a substring, so ``ev_starts_with_filter`` stops
    expressing a prefix at all. That is why its docstring warns that ``None``
    removes the *anchor* rather than swapping a token.
    """
    contains = ev_contains_filter("ASSET_TAG", "LAPTOP", wildcard=None)
    starts_with = ev_starts_with_filter("ASSET_TAG", "LAPTOP", wildcard=None)
    assert contains == 'ASSET_TAG~"LAPTOP"'
    assert contains == starts_with


@pytest.mark.parametrize(
    "bad", ["LAP_TOP", "LAPTOP_01", "LAP[0-9]TOP", r"LAP\_TOP"]
)
def test_wildcard_none_still_refuses_the_operators_own_metacharacters(bad):
    """``_`` and ``[`` belong to ``~`` itself, not to the appended wildcard.

    This is the item's central decision, and it is settled by this repo's own
    live probe rather than by inference:
    ``integration_tests/test_live_change_window.py:659-660`` builds
    ``RFC_NUMBER~"{stem}_"`` and ``RFC_NUMBER~"{stem}[0-9]"`` as raw ``search=``
    strings with **no builder-added wildcard**, and each widened a one-row exact
    match to nine. So the tempting premise — that with nothing appended a
    metacharacter is merely a character — holds for ``*``/``%`` and is false
    for these two. Relaxing them under ``wildcard=None`` would trade a loud,
    local ``ValueError`` for the silent widening these builders exist to
    prevent, on the only deployment anyone has measured.

    ``LAP\\_TOP`` is refused for the ``_`` it contains, not for the backslash:
    a backslash is compared literally under ``~`` (``<stem>\\_`` matched
    nothing live), so it escapes nothing.
    """
    with pytest.raises(ValueError, match="metacharacter"):
        ev_contains_filter("ASSET_TAG", bad, wildcard=None)
    with pytest.raises(ValueError, match="metacharacter"):
        ev_starts_with_filter("ASSET_TAG", bad, wildcard=None)


def test_wildcard_none_admits_a_caller_placed_wildcard():
    """With nothing appended, ``*``/``%`` in the value are the caller's own.

    This is the supported way to hand-build a pattern through these builders:
    the value still goes through ``escape_ev_value``, so the ``"`` defence
    holds, but the wildcard placement becomes the caller's.
    """
    assert (
        ev_contains_filter("ASSET_TAG", "*LAPTOP*", wildcard=None)
        == 'ASSET_TAG~"*LAPTOP*"'
    )
    assert (
        ev_contains_filter("ASSET_TAG", "%LAPTOP%", wildcard=None)
        == 'ASSET_TAG~"%LAPTOP%"'
    )
    # The complement: while a wildcard IS being appended, BOTH tokens are
    # refused, not merely the one being appended -- either would compose with
    # it.
    with pytest.raises(ValueError, match="metacharacter"):
        ev_contains_filter("ASSET_TAG", "LAP*TOP", wildcard="%")
    with pytest.raises(ValueError, match="metacharacter"):
        ev_contains_filter("ASSET_TAG", "LAP%TOP", wildcard="*")


@pytest.mark.parametrize("token", ["?", "**", "", '"'])
def test_an_unsupported_wildcard_token_is_refused(token):
    """The token bypasses ``escape_ev_value``, so its domain must be closed.

    ``'"'`` is the load-bearing case: the token is interpolated as part of
    ``pattern``, outside the value escaping, so without this check it would
    terminate the quoted value and reach the ``,`` combinator — reopening the
    exact hole ``escape_ev_value`` exists to shut.
    """
    with pytest.raises(ValueError, match="wildcard="):
        ev_contains_filter("ASSET_TAG", "LAPTOP", wildcard=token)
    with pytest.raises(ValueError, match="wildcard="):
        ev_starts_with_filter("ASSET_TAG", "LAPTOP", wildcard=token)


@pytest.mark.parametrize("blank", [None, "  "])
def test_an_unsupported_wildcard_token_is_refused_even_for_a_blank_value(blank):
    """A bad token is a fault in the caller's code, not in their data.

    Validating it after the blank-value early return would make the same wrong
    call succeed or raise depending on what happened to be in ``value`` that
    day, which is the worst shape a programming error can take.
    """
    with pytest.raises(ValueError, match="wildcard="):
        ev_contains_filter("ASSET_TAG", blank, wildcard="?")
    with pytest.raises(ValueError, match="wildcard="):
        ev_starts_with_filter("ASSET_TAG", blank, wildcard="?")


def test_a_double_quote_is_still_refused_with_no_wildcard():
    """``escape_ev_value`` runs on every path, including ``wildcard=None``."""
    with pytest.raises(ValueError):
        ev_contains_filter("ASSET_TAG", 'LAP"TOP', wildcard=None)
    with pytest.raises(ValueError):
        ev_starts_with_filter("ASSET_TAG", 'LAP"TOP', wildcard=None)
