"""Shared request description for the EasyVista client.

``RequestSpec`` is all this module holds, and it stays here permanently. It is
a frozen dataclass with no I/O, imported by every resource builder in
``resources/`` (actions, assets, departments, descriptor, documents,
employees, requests -- seven modules), so it sits at the package root while
the executors that consume it live in the generated trees. A shared resource
builder must not import from a tree, and a pure value type with no I/O has no
business living inside one either.

Everything else EasyVista-specific about talking to the API -- URL building,
auth headers, error mapping, the executor -- lives in
``_async/_transport.py`` and its generated ``_sync/`` twin.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from .config import reject_authorization
from .workflow import WorkflowEffect, as_effects


@dataclass(frozen=True)
class RequestSpec:
    """A resource-relative HTTP request, independent of sync/async execution.

    ``headers`` are merged OVER the transport's client-level ones for this
    request alone, and may not carry ``Authorization``: the credential is
    ``config.token`` or ``config.login`` / ``password``, and nothing else. They
    exist because the client-level ``Content-Type: application/json`` is wrong
    for a route that takes another body type, and a single request must be able
    to say so without disturbing the client.

    ``json`` is typed ``Any`` rather than ``dict``: some routes this package does
    not wrap take a bare list body, and ``httpx`` accepts anything
    JSON-serialisable.

    ``allow_workflow_effect`` is the set of workflow effects this request may
    carry -- see :mod:`easyvista_python_client.workflow`. The transport refuses
    a request that names any effect not in it, so a builder that sends a
    workflow command on purpose, or a client method passing the caller's
    opt-in through, widens it with :meth:`allowing`.
    """

    method: str
    path: str
    params: dict[str, Any] | None = None
    json: Any = None
    headers: Mapping[str, str] | None = None
    allow_workflow_effect: frozenset[WorkflowEffect] = frozenset()

    def __post_init__(self) -> None:
        if self.headers is not None:
            reject_authorization(self.headers, "RequestSpec.headers")
        # Normalised here, so a spec given one member or a list compares and
        # checks like one given a frozenset, and a bad value fails at
        # construction rather than at send time.
        object.__setattr__(
            self, "allow_workflow_effect", as_effects(self.allow_workflow_effect)
        )

    def allowing(self, allow: WorkflowEffect | Iterable[WorkflowEffect]) -> RequestSpec:
        """This spec, additionally allowing ``allow`` (a member or an iterable)."""
        return replace(
            self, allow_workflow_effect=self.allow_workflow_effect | as_effects(allow)
        )
