"""Shared Pydantic base models for EasyVista resources."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from ..field_model import FieldClassification, classify
from ..references import Reference, resolve_reference


def _empty_str_to_none(value: Any) -> Any:
    """Coerce the API's empty-string sentinel for an absent scalar to ``None``.

    EasyVista returns ``""`` for numeric columns that carry no value (e.g.
    ``MANAGER_ID`` / ``FUNCTION_ID`` on the single-record directory GETs); without
    this an ``int`` field would fail validation. Any non-empty or non-string value
    passes through untouched.
    """
    if isinstance(value, str) and not value.strip():
        return None
    return value


OptionalInt = Annotated[int | None, BeforeValidator(_empty_str_to_none)]
"""An ``int | None`` field that treats the API's ``""`` sentinel as ``None``."""


class EasyvistaModel(BaseModel):
    """Base for read models.

    Tolerates the API's ``ALL_CAPS`` field names (via aliases on subclasses) and
    preserves unknown / custom ``e_*`` fields so they round-trip unchanged.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    def reference(self, name: str) -> Reference:
        """Resolve a reference attribute (``STATUS``, ``URGENCY``, custom ``e_*``…)
        to a normalized :class:`~easyvista_python_client.references.Reference`."""
        return resolve_reference(self.model_dump(by_alias=True), name)

    def classify_fields(self) -> FieldClassification:
        """Partition this record's fields into official / custom (``e_*``) /
        available / link buckets.

        See :class:`~easyvista_python_client.field_model.FieldClassification`.
        """
        declared = {
            (f.alias or name).upper() for name, f in type(self).model_fields.items()
        }
        return classify(self.model_dump(by_alias=True), declared)


class EasyvistaWriteModel(BaseModel):
    """Base for write payloads (create/update).

    Rejects unknown fields (``extra="forbid"``) to catch caller typos, and
    serializes ``custom_fields`` with an ``e_`` prefix (unless already prefixed).
    """

    model_config = ConfigDict(extra="forbid")

    custom_fields: dict[str, Any] = Field(default_factory=dict)

    def to_api(self) -> dict[str, Any]:
        """Return the API body: known fields (``None`` dropped) plus ``e_``-prefixed
        custom fields.

        Booleans may be sent as native JSON ``true``/``false`` (EasyVista also
        accepts ``0``/``1`` and the strings ``"true"``/``"false"``).
        """
        data = self.model_dump(exclude_none=True, exclude={"custom_fields"})
        for key, value in self.custom_fields.items():
            api_key = key if key.startswith("e_") else f"e_{key}"
            data[api_key] = value
        return data
