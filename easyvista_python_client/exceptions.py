"""Exception hierarchy for the EasyVista client."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .workflow import WorkflowEffect


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


class EasyvistaContentError(EasyvistaError):
    """A rich-text value could not be converted between memo HTML and Markdown.

    Raised by
    :class:`~easyvista_python_client.content.EasyvistaContentConverter`, in
    either direction, when a parser fails for any reason other than the
    memo being nested too deeply -- or when the caller's stack is too short
    even to strip a memo's tags; the underlying fault is always attached as
    ``__cause__``. The converter is the optional ``content`` extra, but this
    class is part of the core package, so ``except EasyvistaContentError``
    works whether or not the extra is installed.

    It exists so that no failure of the content layer escapes the package's
    taxonomy. The conversion runs third-party parsers (``markdownify``
    inbound, ``markdown`` outbound), and a parser fault would otherwise reach
    the caller as a bare builtin that ``except EasyvistaError`` does not
    catch. HTML nested too deeply to convert is not an error at all: it is
    answered with the memo's text instead.

    No request is involved, so the converter raises it with a message alone
    and ``status_code``, ``ev_code``, ``ev_message`` and ``body`` stay
    ``None``. Mirrors ``glpi_python_client``'s ``GlpiContentError``.
    """


class EasyvistaWorkflowEffectRefused(ValueError):
    """A write that may change a ticket's workflow was refused before it was sent.

    Raised with no request made: by the transport, when a request names a
    :class:`~easyvista_python_client.WorkflowEffect` that the call did not
    allow through ``allow_workflow_effect=``; and by ``end_action``, when the
    action it was asked to end is a workflow step or cannot be shown not to be.

    **Deliberately not an** :class:`EasyvistaError`. Nothing was sent, so there
    is no status code and nothing transient: the same call can never succeed on
    a retry, and a caller that treats a status-code-less ``EasyvistaError`` as
    "try again later" would retry it for ever. It subclasses ``ValueError``
    because it refuses the arguments, as this package's other local refusals do.

    ``effects`` holds the refused effects; ``triggers`` the ``(what, effect)``
    pairs that named them -- a body key, a column, or a route.
    """

    def __init__(
        self,
        message: str,
        *,
        effects: frozenset[WorkflowEffect] = frozenset(),
        triggers: tuple[tuple[str, WorkflowEffect], ...] = (),
    ) -> None:
        super().__init__(message)
        self.effects = effects
        self.triggers = triggers
