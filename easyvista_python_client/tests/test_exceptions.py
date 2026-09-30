import pytest

from easyvista_python_client.exceptions import (
    EasyvistaAuthError,
    EasyvistaConnectionError,
    EasyvistaContentError,
    EasyvistaError,
    EasyvistaNotFound,
    EasyvistaRateLimitError,
    EasyvistaServerError,
    EasyvistaValidationError,
)


def test_base_error_carries_context():
    err = EasyvistaError("boom", status_code=418, ev_code="E1", ev_message="teapot")
    assert err.status_code == 418
    assert err.ev_code == "E1"
    assert err.ev_message == "teapot"
    assert "boom" in str(err)


@pytest.mark.parametrize(
    "cls",
    [
        EasyvistaAuthError,
        EasyvistaNotFound,
        EasyvistaValidationError,
        EasyvistaRateLimitError,
        EasyvistaServerError,
        EasyvistaConnectionError,
        EasyvistaContentError,
    ],
)
def test_subclasses_are_easyvista_errors(cls):
    assert issubclass(cls, EasyvistaError)


def test_content_error_carries_no_http_context():
    """A conversion fault involves no request, so there is nothing to report.

    The converter raises it with a message alone; every HTTP attribute the
    base class defines stays ``None`` rather than borrowing a meaning.
    """
    err = EasyvistaContentError("could not convert")
    for attribute in ("status_code", "ev_code", "ev_message", "body"):
        assert getattr(err, attribute) is None, attribute
    assert str(err) == "could not convert"
