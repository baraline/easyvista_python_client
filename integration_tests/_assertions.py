"""Assertion helpers that never print live instance data (design principle P2).

Every instance-derived value in this suite passes through one of these three
helpers. That is what makes "no real instance data" structural rather than
remembered: writing ``assert employee.last_name == "..."`` means bypassing this
module, which a reviewer can see in the diff.

**What actually keeps live values out of failure text.** Every helper takes a
``label`` and builds a message naming only that label, so a caller cannot
interpolate the value by accident. That is the guarantee, and it holds
unconditionally.

Each helper additionally binds its result to a plain local before asserting
(``ok = bool(value)``, then ``assert ok, ...``). That is defence in depth, not
the active mechanism: pytest's assertion rewriter -- which reports the operands
of the expression it rewrote, and would print ``where False = bool(<the live
value>)`` -- only instruments ``conftest.py``, files matching ``python_files``,
and modules passed to ``register_assert_rewrite``. This module is none of
those, so its asserts are plain Python and only the message is ever rendered.
Keep the local-variable form anyway: it costs nothing and it is what makes
these helpers safe to move into a ``conftest.py`` or a test module later, both
of which ARE rewritten. Do not register this module for rewriting.

Identifiers (RFC numbers, ids) are fine to print. Names, e-mail addresses,
department and catalog labels, and Consigne text are not.
"""

from __future__ import annotations

from typing import Any

import pytest


def assert_populated(value: Any, label: str) -> None:
    """Assert ``value`` is truthy. The failure names ``label`` and nothing else."""
    ok = bool(value)
    assert ok, f"{label} is empty"


def assert_shape(value: Any, expected: type | tuple[type, ...], label: str) -> None:
    """Assert ``value``'s type. The failure names ``label`` and the types only."""
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
    data = record if isinstance(record, dict) else record.model_dump(by_alias=True)
    upper = {k.upper(): v for k, v in data.items() if isinstance(k, str)}
    key = name.upper()
    if key not in upper:
        pytest.skip(f"this instance does not expose the field {name}")
    value = upper[key]
    if value is None or value == "":
        pytest.skip(f"the field {name} is present but empty on this instance")
    return value
