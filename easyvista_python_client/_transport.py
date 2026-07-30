"""Shared request description for the EasyVista client.

``RequestSpec`` is all this module holds, and it stays here permanently. It is
a frozen dataclass with no I/O and 18 importers outside the client -- six
resource builders in ``resources/`` and twelve probe scripts -- so it sits at
the package root while the executors that consume it live in the generated
trees. A shared resource builder must not import from a tree, and a probe
script has no business reaching into ``_async/`` for a pure value type.

Everything else EasyVista-specific about talking to the API -- URL building,
auth headers, error mapping, the executor -- lives in
``_async/_transport.py`` and its generated ``_sync/`` twin.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RequestSpec:
    """A resource-relative HTTP request, independent of sync/async execution."""

    method: str
    path: str
    params: dict[str, Any] | None = None
    json: dict[str, Any] | None = None
