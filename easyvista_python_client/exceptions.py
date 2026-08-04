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
        body: bytes | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.ev_code = ev_code
        self.ev_message = ev_message
        # The raw response body, for a caller that hit one the transport does
        # not recognize (an nginx/WAF HTML page, a plain-text 5xx). The
        # transport deliberately stopped interpolating it into `message` (P2:
        # nothing redacts exception TEXT, so it would print wherever the
        # exception surfaces), which would otherwise make it unrecoverable.
        # NOT passed to `super().__init__`, so it never becomes part of
        # `.args` -- that is what keeps it out of `str()`/`repr()`.
        self.body = body


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
