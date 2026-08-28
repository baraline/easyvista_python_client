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
