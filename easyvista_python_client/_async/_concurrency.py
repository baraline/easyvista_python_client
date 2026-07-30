"""Asyncio concurrency primitives for the async client.

This module and its sync twin are the only files maintained by hand on both
sides of the codegen. Everything else in the sync tree is generated from the
async one by :mod:`unasync`, which strips ``async``/``await`` and substitutes
whole NAME tokens. That works for syntax; it cannot work here, because
``asyncio.gather`` and ``asyncio.Semaphore`` are **dotted** names. unasync
matches single NAME tokens only, and a dotted substitution key is accepted
*silently and never fires* -- so a generated twin would call
``asyncio.gather`` from synchronous code and break at runtime.

Keeping both twins tiny is deliberate: hand-maintained duplication is a
liability, so it is confined to the smallest possible surface.

**Ordering is load-bearing and unenforced.** The sync twin's ``settle``
returns already-evaluated arguments, so a fan-out's sync meaning is "evaluate
these expressions left to right". That reproduces the sequential client only
because each fan-out's arguments are written in the order the sequential code
used. A future fan-out written out of order will generate sync code that
issues requests in an order nobody intended, and no test will catch it.
"""

from __future__ import annotations

import asyncio
from typing import Any

#: Bounded-concurrency primitive for the async surface.
#:
#: An :class:`asyncio.Semaphore`, and the sync twin is a no-op context
#: manager. Neither substitutes for the other. Note that instances must be
#: built **per call**, never stored on a client or at module level: an
#: ``asyncio.Semaphore`` binds to the first event loop that *contends* it --
#: an uncontended acquire never touches the loop at all -- so a stored one
#: passes every low-traffic test and then raises ``RuntimeError: bound to a
#: different event loop`` the first time a second loop contends it, i.e. in
#: production under load (measured on 3.10).
Semaphore = asyncio.Semaphore


async def settle(*awaitables: Any) -> list[Any]:
    """Run ``awaitables`` concurrently; return results in **source** order.

    ``return_exceptions=True`` is load-bearing twice over, and removing it is
    the tempting "simplification" this docstring exists to prevent.

    First, orphans. A bare ``asyncio.gather`` propagates the first exception
    while its siblings keep running -- it does not cancel them (measured).
    Those orphaned requests outlive the call and can still be in flight when
    ``__aexit__`` closes the client, which surfaces as a bare ``RuntimeError``
    inside a task nobody awaits. Settling every awaitable first means no
    request outlives the method that issued it.

    Second, *which* exception wins. Collecting the results and re-raising the
    first failure in source order reproduces the exception the sequential
    code would have raised. A bare gather instead raises whichever failed
    soonest on the clock, so the error a caller sees would depend on server
    timing.

    The cost, accepted deliberately: on a failing bundle every sibling still
    runs to completion, so an error path can issue more requests than a
    sequential version would. They are bounded by the fan-out width and they
    are all reads.

    The sync twin takes already-computed values and returns them. That is not
    a stub: once unasync strips the ``await`` from a call site, each argument
    expression evaluates eagerly where it is written, which *is* sequential
    execution. The same call shape means "concurrently" here and "one after
    the other" there, with no change to the calling code.
    """
    results = await asyncio.gather(*awaitables, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result
    return list(results)


__all__ = ["Semaphore", "settle"]
