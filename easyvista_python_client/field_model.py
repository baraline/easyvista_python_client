"""Generic, config-free classification of EasyVista record fields.

Partitions any record's fields into official / custom (``e_``) / available
(``available_field_x``) / link (href-only sub-resource) buckets, using the API's
documented conventions. The model's own declared field aliases are the only
"registry": a declared field is always official, so official ``E_``-columns like
``E_MAIL`` are never mistaken for custom.

Leaf module: stdlib only, no model/client imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_AVAILABLE = re.compile(r"AVAILABLE_FIELD_\d+$")


@dataclass(frozen=True)
class FieldClassification:
    """A record's fields split into four buckets (each field in exactly one)."""

    official: dict[str, Any]
    custom: dict[str, Any]
    available: dict[str, Any]
    links: dict[str, str]


def classify(
    record: dict[str, Any], declared: set[str] | None = None
) -> FieldClassification:
    """Partition ``record`` (a by-alias model dump). ``declared`` is the set of
    the model's official field aliases, upper-cased; declared fields never count
    as custom. Never raises; a non-dict yields empty buckets."""
    declared = declared or set()
    official: dict[str, Any] = {}
    custom: dict[str, Any] = {}
    available: dict[str, Any] = {}
    links: dict[str, str] = {}
    if isinstance(record, dict):
        for key, value in record.items():
            if not isinstance(key, str):
                continue
            upper = key.upper()
            if upper == "HREF":
                continue
            if isinstance(value, dict) and set(value.keys()) == {"HREF"}:
                links[key] = value["HREF"]
            elif _AVAILABLE.match(upper):
                available[key] = value
            elif upper.startswith("E_") and upper not in declared:
                custom[key] = value
            else:
                official[key] = value
    return FieldClassification(
        official=official, custom=custom, available=available, links=links
    )


def parse_memo(data: Any, field: str) -> str | None:
    """The text of a Memo sub-resource response ``{"<FIELD>": "<text>", "HREF": …}``.

    Matches ``field`` case-insensitively and returns its string value (``""`` for
    an empty Memo). Returns ``None`` for a missing/non-string field or non-dict.
    """
    if not isinstance(data, dict):
        return None
    target = field.upper()
    for key, value in data.items():
        if isinstance(key, str) and key.upper() == target and isinstance(value, str):
            return value
    return None
