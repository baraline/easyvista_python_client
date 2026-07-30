"""Sequential concurrency primitives for the sync client.

Hand-written twin of the async ``_concurrency`` module -- see that module for
why these two files are the only ones not generated.

**This file is not produced by the codegen and must be edited alongside its
async twin.** ``unasync_build.py`` excludes it by name.
"""

from __future__ import annotations

from typing import Any


class Semaphore:
    """A no-op context manager standing in for :class:`asyncio.Semaphore`.

    The async surface bounds its fan-out width because every branch is in
    flight at once. Here the branches have already run, one after another, by
    the time the enclosing ``settle`` is entered -- concurrency is one, so
    there is nothing to bound. Accepting and ignoring the width keeps the
    call site identical on both surfaces.
    """

    def __init__(self, value: int) -> None:
        self.value = value

    def __enter__(self) -> Semaphore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


def settle(*values: Any) -> list[Any]:
    """Return ``values`` unchanged, preserving order.

    This looks like a no-op and is doing real work. On the async side the call
    reads ``await settle(self.a(), self.b())`` and runs the two concurrently.
    Stripping the ``await`` leaves ``settle(self.a(), self.b())``, where each
    argument has already been evaluated -- in order -- by the time this is
    entered. Collecting them is therefore the correct and complete
    synchronous meaning of the same expression, including its failure
    behaviour: a raise in an earlier argument prevents the later ones from
    being evaluated at all.
    """
    return list(values)


__all__ = ["Semaphore", "settle"]
