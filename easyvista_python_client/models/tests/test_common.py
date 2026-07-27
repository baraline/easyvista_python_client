from easyvista_python_client import FieldClassification
from easyvista_python_client.models.common import (
    EasyvistaModel,
    EasyvistaWriteModel,
    OptionalInt,
    _empty_str_to_none,
)
from easyvista_python_client.models.request import Request


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
