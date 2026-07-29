"""Assertion helpers that never print live instance data (design principle P2).

Every instance-derived value in this suite passes through one of these three
helpers. That is what makes "no real instance data" structural rather than
remembered: writing ``assert employee.last_name == "..."`` means bypassing this
module, which a reviewer can see in the diff.

**What actually keeps live values out of failure text.** Every helper takes a
``label`` and builds a message naming only that label, so a caller cannot
interpolate the value by accident. That is the guarantee, and it holds
unconditionally.

Three further mechanisms matter, and they are independent -- none subsumes
another (all measured, not assumed):

1. **The message is the only thing the assert renders.** Each helper binds its
   result to a plain local before asserting (``ok = bool(value)``, then ``assert
   ok, ...``). pytest's assertion rewriter reports the operands of the
   expression it rewrote, so ``assert bool(value), ...`` would print ``where
   False = bool(<the live value>)``. The rewriter only instruments
   ``conftest.py``, files matching ``python_files``, and modules passed to
   ``register_assert_rewrite`` -- this module is none of those -- but keep the
   local-variable form anyway: it costs nothing and it is what makes these
   helpers safe to move into a rewritten module later. Do not register this
   module for rewriting.

2. **``__tracebackhide__`` drops this frame from the traceback.** Without it,
   pytest renders a long traceback entry *with the frame's arguments*, so
   ``assert_shape(ticket, Request, "...")`` printed ``value = <the whole live
   Request>`` above the message -- defeating the label entirely. Assertion
   rewriting has nothing to do with it; the leak is the traceback, not the
   assert. With the frame hidden, the failure is reported at the call site,
   which names a label and not a value.

3. **The conftest forces a short traceback for every item in this directory.**
   That is the layer this module cannot provide, because the leak is not in
   here: pytest prints the *test function's* arguments too, so a test taking a
   live fixture spills that fixture's repr on ANY failure -- an unexpected
   exception included -- however carefully its assertions are written. See
   ``_force_short_traceback`` in ``conftest.py``.

Identifiers (RFC numbers, ids) are fine to print. Names, e-mail addresses,
department and catalog labels, and Consigne text are not.
"""

from __future__ import annotations

from typing import Any

import pytest


def assert_populated(value: Any, label: str) -> None:
    """Assert ``value`` is truthy. The failure names ``label`` and nothing else."""
    __tracebackhide__ = True
    ok = bool(value)
    assert ok, f"{label} is empty"


def assert_shape(value: Any, expected: type | tuple[type, ...], label: str) -> None:
    """Assert ``value``'s type. The failure names ``label`` and the types only."""
    __tracebackhide__ = True
    ok = isinstance(value, expected)
    names = (
        expected.__name__
        if isinstance(expected, type)
        else "/".join(t.__name__ for t in expected)
    )
    assert ok, f"{label}: expected {names}, got {type(value).__name__}"


def require_field(record: Any, name: str) -> Any:
    """Return ``record``'s ``name`` field, or skip when this instance lacks it.

    ``record`` is a mapping or an ``EasyvistaModel``; ``name`` matches
    case-insensitively, mirroring the API's ALL_CAPS keys. A field that is
    absent -- or present but empty -- is a fact about the instance, not a defect
    in the client, so this skips rather than fails (design principle P1). The
    skip message carries the field name only, never its value.
    """
    __tracebackhide__ = True
    data = record if isinstance(record, dict) else record.model_dump(by_alias=True)
    upper = {k.upper(): v for k, v in data.items() if isinstance(k, str)}
    key = name.upper()
    if key not in upper:
        pytest.skip(f"this instance does not expose the field {name}")
    value = upper[key]
    if value is None or value == "":
        pytest.skip(f"the field {name} is present but empty on this instance")
    return value
