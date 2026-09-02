"""A read model for endpoints this package does not model."""

from __future__ import annotations

from .common import EasyvistaModel


class GenericRecord(EasyvistaModel):
    """One record from an endpoint this package does not model.

    Declares **no fields**. :class:`EasyvistaModel`
    already sets ``extra="allow"``, so every column the instance sends is kept
    verbatim and reachable by its API name through ``model_dump(by_alias=True)``,
    ``reference()`` and ``classify_fields()``.

    Declaring nothing is the point. A reference table's response schema in an
    instance's OpenAPI is tier 3 -- example-derived, illustrative only -- and
    the verified instance's ``GET /status`` schema is visibly wrong: it
    describes an SLA-shaped object (``DELAY``, ``SLA_ID``, ``NAME_*``,
    ``WORKING_HOURS_ID``) with no ``records`` envelope and no status id at all.
    A column list written from those schemas would be a guess frozen into this
    package's public API, and a different guess on the next deployment. So the
    columns stay data.

    One consequence to know: because nothing is declared, ``classify_fields()``
    sees an empty ``declared`` set, so every ``E_``-prefixed column lands in the
    ``custom`` bucket -- including an official one such as ``E_MAIL``. That is
    the right trade for a model that knows nothing about its table.
    """
