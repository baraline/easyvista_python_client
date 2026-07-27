import pytest

from easyvista_python_client.exceptions import (
    EasyvistaAuthError,
    EasyvistaConnectionError,
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
    ],
)
def test_subclasses_are_easyvista_errors(cls):
    assert issubclass(cls, EasyvistaError)
