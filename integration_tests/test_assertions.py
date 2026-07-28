"""Unit tests for the P2 assertion helpers. No credentials, no network.

Marked ``integration`` by this directory's collection hook (so CI deselects
them), but they run anywhere a plain ``pytest`` runs.
"""

from __future__ import annotations

import pytest

from integration_tests._assertions import (
    assert_populated,
    assert_shape,
    require_field,
)


class _Falsy:
    """A falsy value whose repr is a stand-in for live data.

    Used to prove the helpers keep the value out of the failure text: if a
    helper let pytest's assertion rewriter see the value, this repr would show
    up in the report.
    """

    def __init__(self, text: str) -> None:
        self.text = text

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return self.text


def test_assert_populated_accepts_a_truthy_value():
    assert_populated("EVCLI0123456789", "TITLE")


def test_assert_populated_message_names_only_the_label():
    with pytest.raises(AssertionError) as info:
        assert_populated("", "REQUESTOR")
    assert str(info.value) == "REQUESTOR is empty"


def test_assert_populated_never_reports_the_value():
    with pytest.raises(AssertionError) as info:
        assert_populated(_Falsy("A Real Person"), "REQUESTOR")
    assert "A Real Person" not in str(info.value)


def test_assert_shape_accepts_a_matching_type():
    assert_shape("text", str, "DESCRIPTION")
    assert_shape(3, (int, str), "SLA_ID")


def test_assert_shape_message_names_the_label_and_types_only():
    with pytest.raises(AssertionError) as info:
        assert_shape(_Falsy("someone@example.test"), int, "REQUESTOR_ID")
    message = str(info.value)
    assert "REQUESTOR_ID" in message
    assert "someone@example.test" not in message


def test_require_field_returns_the_value_case_insensitively():
    assert require_field({"TITLE": "EVCLI0123"}, "title") == "EVCLI0123"


def test_require_field_reads_an_easyvista_model():
    from easyvista_python_client import Request

    ticket = Request.model_validate({"RFC_NUMBER": "I1", "E_GTR_STATUS": "OK"})
    assert require_field(ticket, "E_GTR_STATUS") == "OK"


def test_require_field_skips_when_the_field_is_absent():
    with pytest.raises(pytest.skip.Exception) as info:
        require_field({"TITLE": "x"}, "E_GTR_STATUS")
    assert "E_GTR_STATUS" in str(info.value)


def test_require_field_skips_when_the_field_is_empty():
    with pytest.raises(pytest.skip.Exception) as info:
        require_field({"E_GTR_STATUS": ""}, "E_GTR_STATUS")
    assert "E_GTR_STATUS" in str(info.value)


def test_require_field_skip_message_is_exactly_the_field_name():
    # Pinned to the exact string: a future edit that helpfully appends the value
    # to the reason ("... is empty, got 'Jane Doe'") would leak it into every
    # test report, and this is what stops that landing unnoticed.
    with pytest.raises(pytest.skip.Exception) as info:
        require_field({"REQUESTOR_NAME": ""}, "REQUESTOR_NAME")
    assert str(info.value) == (
        "the field REQUESTOR_NAME is present but empty on this instance"
    )
