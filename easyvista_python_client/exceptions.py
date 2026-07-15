"""Exception hierarchy for the EasyVista client."""

from __future__ import annotations


class EasyvistaError(Exception):
    """Base class for all EasyVista client errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        ev_code: str | None = None,
        ev_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.ev_code = ev_code
        self.ev_message = ev_message


class EasyvistaAuthError(EasyvistaError):
    """401 / 403 — authentication or authorization failed."""


class EasyvistaNotFound(EasyvistaError):
    """404 — resource not found."""


class EasyvistaValidationError(EasyvistaError):
    """400 — request rejected as invalid by EasyVista."""


class EasyvistaRateLimitError(EasyvistaError):
    """429 — rate limited."""


class EasyvistaServerError(EasyvistaError):
    """5xx — EasyVista server error."""


class EasyvistaConnectionError(EasyvistaError):
    """Transport-level failure (timeout, connection refused, etc.)."""
