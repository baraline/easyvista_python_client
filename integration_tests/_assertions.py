"""Assertion helpers that never print live instance data (design principle P2).

Every instance-derived value in this suite passes through one of these three
helpers. That is what makes "no real instance data" structural rather than
remembered: writing ``assert employee.last_name == "..."`` means bypassing this
module, which a reviewer can see in the diff.

**Why each helper binds its result to a local before asserting.** pytest rewrites
assertions and reports the operands of the expression it rewrote, so
``assert bool(value), msg`` reports ``where False = bool(<the live value>)`` and
``assert isinstance(value, str), msg`` reports the value too. The message string
is not what protects anything -- binding the boolean to a plain local first is,
because a bare ``assert ok`` gives the rewriter nothing to expand. Do not
"simplify" these back into one-liners; ``test_assertions.py`` will fail if you do.

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
