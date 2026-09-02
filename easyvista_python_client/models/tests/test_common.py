from datetime import datetime, timedelta, timezone

import pydantic
import pytest

from easyvista_python_client import FieldClassification
from easyvista_python_client.models.common import (
    EasyvistaModel,
    EasyvistaWriteModel,
    OptionalDateTime,
    OptionalInt,
    _empty_str_to_none,
)
from easyvista_python_client.models.request import PostRequest, Request


def test_classify_fields_declared_alias_is_official_custom_is_custom():
    # RFC_NUMBER is a declared alias on Request; E_CUSTOM_REF is not.
    ticket = Request.model_validate(
        {
            "RFC_NUMBER": "I1",
            "E_CUSTOM_REF": "42",
            "AVAILABLE_FIELD_1": "x",
            "DESCRIPTION": {"HREF": "https://h/requests/I1/description"},
        }
    )
    fc = ticket.classify_fields()
    assert isinstance(fc, FieldClassification)
    assert fc.custom == {"E_CUSTOM_REF": "42"}
    assert fc.available == {"AVAILABLE_FIELD_1": "x"}
    assert fc.links == {"DESCRIPTION": "https://h/requests/I1/description"}
    assert "RFC_NUMBER" in fc.official


def test_write_model_custom_bool_field_round_trips():
    class _W(EasyvistaWriteModel):
        pass

    body = _W(custom_fields={"is_vip": True, "already_prefixed": False}).to_api()
    # custom fields are e_-prefixed (unless already prefixed) and keep JSON bools.
    assert body["e_is_vip"] is True
    assert body["e_already_prefixed"] is False


def test_empty_str_to_none_coercion_directly():
    # The API's "" sentinel (and pure whitespace) become None; a real int and a
    # non-empty string both pass through unchanged.
    assert _empty_str_to_none("") is None
    assert _empty_str_to_none("  ") is None
    assert _empty_str_to_none("42") == "42"
    assert _empty_str_to_none(42) == 42


def test_optional_int_field_coerces_empty_and_whitespace_to_none():
    class _M(EasyvistaModel):
        n: OptionalInt = None

    assert _M.model_validate({"n": ""}).n is None
    assert _M.model_validate({"n": "  "}).n is None
    assert _M.model_validate({"n": "42"}).n == 42
    assert _M.model_validate({"n": 42}).n == 42


class _Sample(EasyvistaModel):
    pass


def test_base_model_keeps_unknown_fields():
    model = _Sample.model_validate({"RFC_NUMBER": "I123", "e_custom1": "x"})
    dumped = model.model_dump(by_alias=True)
    assert dumped["RFC_NUMBER"] == "I123"
    assert dumped["e_custom1"] == "x"


class _Probe(EasyvistaModel):
    when: OptionalDateTime = None


def test_parses_the_live_easyvista_format():
    got = _Probe.model_validate({"when": "2026-08-17T15:40:41.610+02:00"}).when
    assert got == datetime(
        2026, 8, 17, 15, 40, 41, 610000, tzinfo=timezone(timedelta(hours=2))
    )


def test_the_empty_string_sentinel_becomes_none():
    """EasyVista returns "" for every unset date — not null. Measured live."""
    assert _Probe.model_validate({"when": ""}).when is None
    assert _Probe.model_validate({"when": "   "}).when is None


def test_a_missing_key_is_none():
    assert _Probe.model_validate({}).when is None


def test_an_explicit_none_is_none_not_an_error():
    """A JSON ``null`` is an ordinary absence on a ``datetime | None`` column.

    Regression guard. When the validator was tightened so a malformed value
    raises instead of becoming a bogus epoch instant, it began raising on
    ``None`` too -- so a wire payload carrying ``"LAST_UPDATE": null``, or a
    caller passing the field's own default explicitly, failed validation. The
    tightening is about *junk*; an absence is not junk, and this column's own
    type says ``None`` is legal.
    """
    assert _Probe.model_validate({"when": None}).when is None
    assert _Probe(when=None).when is None


def test_an_unparseable_timestamp_raises_rather_than_silently_becoming_none():
    """A malformed date is a real signal; swallowing it would hide a format change.

    Contrast the "" sentinel above, which is EasyVista's documented way of
    saying "unset" and is therefore not an error.
    """
    with pytest.raises(pydantic.ValidationError) as exc_info:
        _Probe.model_validate({"when": "not-a-date"})
    # _empty_str_to_none_datetime raises ValueError, which pydantic wraps into a
    # ValidationError naming the field -- confirm it actually does, not just
    # that *some* error was raised.
    assert exc_info.value.errors()[0]["loc"] == ("when",)


@pytest.mark.parametrize(
    "junk",
    [
        # ISO-basic, no separators. Pydantic's own parser reads this as epoch
        # seconds -> 1970-08-23T12:00:17Z, an instant 56 years off, SILENTLY.
        "20260817",
        # What an epoch-millis format change would look like on the wire.
        # Pydantic reads it as 2025-08-17T12:40:41.610Z -- entirely plausible,
        # which is exactly why absorbing it would defeat this guard.
        1755434441610,
        "1755434441610",
        # A plausible alternative "unset" sentinel; pydantic reads it as the
        # epoch rather than reporting that EasyVista's sentinel is "".
        0,
        "0",
    ],
)
def test_a_numeric_shaped_value_raises_instead_of_becoming_an_epoch_instant(junk):
    """The guard must not fall through to pydantic's much broader parser.

    Every value here is one pydantic accepts with a credible-looking result, so
    a fallthrough would turn the one signal this guard exists to raise -- a
    change in EasyVista's timestamp format -- into wrong data with no error.
    """
    with pytest.raises(pydantic.ValidationError) as exc_info:
        _Probe.model_validate({"when": junk})
    assert exc_info.value.errors()[0]["loc"] == ("when",)


def test_a_naive_datetime_input_comes_back_aware():
    """A datetime handed in directly (not a wire string) must still end up
    aware -- OptionalDateTime promises "An aware `datetime | None`" for every
    accepted input, not only for strings."""
    got = _Probe.model_validate({"when": datetime(2026, 1, 1, 9, 0, 0)}).when
    assert got == datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc)


# --- the caller's own timestamp formats, opt-in and empty by default ---------
#
# The raise-rather-than-guess default above stays exactly as it is; the tests in
# this block are about the escape hatch beside it, for a deployment whose
# timestamps are genuinely a different format. Nothing here softens the guard --
# an unlisted format still raises.


def test_no_context_behaves_exactly_as_before():
    """The default path is untouched: an explicit ``context=None`` still raises."""
    with pytest.raises(pydantic.ValidationError):
        _Probe.model_validate({"when": "20260817"}, context=None)


def test_an_unlisted_format_still_raises_under_a_context():
    """Naming a format is not a licence to guess at every other one."""
    with pytest.raises(pydantic.ValidationError) as exc_info:
        _Probe.model_validate(
            {"when": "not-a-date"},
            context={"datetime_input_formats": ["%d/%m/%Y"]},
        )
    assert exc_info.value.errors()[0]["loc"] == ("when",)


def test_a_named_format_is_accepted_and_stamped_utc():
    """A pattern yielding a naive datetime is read as UTC.

    The same assumption ``parse_ev_datetime`` already documents for an
    offset-less literal on the read path, so the two paths agree.
    """
    got = _Probe.model_validate(
        {"when": "17/08/2026 15:40:00"},
        context={"datetime_input_formats": ["%d/%m/%Y %H:%M:%S"]},
    ).when
    assert got == datetime(2026, 8, 17, 15, 40, 0, tzinfo=timezone.utc)


def test_a_context_format_never_shadows_the_native_iso_form():
    """Order is load-bearing: ``parse_ev_datetime`` runs FIRST.

    ``"%Y%m%d"`` would happily consume the leading ``20260817`` of an ISO
    stamp if strptime were tried first, silently discarding the time and the
    offset. Because the native form is tried first, adding a pattern can never
    change how a real EasyVista timestamp parses.
    """
    got = _Probe.model_validate(
        {"when": "2026-08-17T15:40:41.610+02:00"},
        context={"datetime_input_formats": ["%Y%m%d"]},
    ).when
    assert got == datetime(
        2026, 8, 17, 15, 40, 41, 610000, tzinfo=timezone(timedelta(hours=2))
    )


# --- an unknown key names itself, and names extra_payload -------------------


def test_an_unknown_field_names_itself_and_extra_payload():
    """``extra="forbid"``'s own message never mentions the way through.

    Someone who has just read that a field was excluded from a model has no way
    to learn from "Extra inputs are not permitted" that ``extra_payload``
    exists. The message must also stop short of promising the write works: on
    this API an exclusion is usually a measured misbehaviour, and a 200 is not
    a receipt.
    """
    with pytest.raises(pydantic.ValidationError) as exc_info:
        PostRequest(catalog_code="X", ctalog_guid="typo")
    message = str(exc_info.value)
    assert "ctalog_guid" in message
    assert "extra_payload" in message
    assert "a 200 is not a receipt on this API." in message


def test_a_known_field_is_not_intercepted():
    """The validator returns the input untouched when nothing is unknown."""
    assert PostRequest(catalog_code="X", title="t").to_api()["title"] == "t"


def test_a_non_mapping_input_falls_through():
    """A non-mapping must reach pydantic's own error, not this validator's."""
    with pytest.raises(pydantic.ValidationError) as exc_info:
        PostRequest.model_validate("nonsense")
    assert "extra_payload" not in str(exc_info.value)


def test_extra_payload_serializes_verbatim_without_prefix() -> None:
    """extra_payload keys reach the wire exactly as written."""
    payload = PostRequest(catalog_code="X", extra_payload={"URGENCY_ID": "4"})
    body = payload.to_api()
    assert body["URGENCY_ID"] == "4"
    assert "e_URGENCY_ID" not in body


def test_extra_payload_overrides_a_declared_field() -> None:
    """A caller reaching past the model wins; losing silently would be worse."""
    payload = PostRequest(catalog_code="X", title="declared",
                          extra_payload={"title": "override"})
    assert payload.to_api()["title"] == "override"


def test_extra_payload_overrides_custom_fields() -> None:
    payload = PostRequest(
        catalog_code="X",
        custom_fields={"thing": "from_custom"},
        extra_payload={"e_thing": "from_extra"},
    )
    assert payload.to_api()["e_thing"] == "from_extra"


def test_extra_payload_defaults_empty_and_adds_nothing() -> None:
    assert "extra_payload" not in PostRequest(catalog_code="X").to_api()


def test_extra_payload_overrides_a_declared_field_across_case() -> None:
    """An ALL_CAPS override must REPLACE the declared lower-case field.

    EasyVista's field names are case-insensitive, so an exact-key merge put
    both spellings on the wire with conflicting values and left the winner to
    the server. The ALL_CAPS spelling is the likely one, not a corner case:
    it mirrors the read side's ``ALL_CAPS`` convention, which is where callers
    copy names from.
    """
    body = PostRequest(
        catalog_code="X", urgency_id=8, extra_payload={"URGENCY_ID": "4"}
    ).to_api()
    assert body["URGENCY_ID"] == "4"
    assert "urgency_id" not in body


def test_extra_payload_overrides_custom_fields_across_case() -> None:
    """The same rule covers a ``custom_fields``-produced key."""
    body = PostRequest(
        catalog_code="X",
        custom_fields={"thing": "from_custom"},
        extra_payload={"E_THING": "from_extra"},
    ).to_api()
    assert body["E_THING"] == "from_extra"
    assert "e_thing" not in body


def test_a_case_insensitive_collision_never_raises() -> None:
    """The rule is a merge, not a validation: a collision is not an error."""
    payload = PostRequest(
        catalog_code="X", title="declared", extra_payload={"TITLE": "override"}
    )
    body = payload.to_api()
    assert body["TITLE"] == "override"
    assert body["catalog_code"] == "X"
