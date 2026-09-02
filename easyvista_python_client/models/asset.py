"""Models for the EasyVista ``assets`` resource.

Field sets are the documented/common AM_ASSET fields; ``extra="allow"`` on the
read model preserves any others.
"""

from __future__ import annotations

from pydantic import Field

from .common import EasyvistaModel, EasyvistaWriteModel, OptionalInt


class Asset(EasyvistaModel):
    """An asset as returned by the API.

    The two id columns use :data:`OptionalInt`, not a bare ``int | None``:
    EasyVista returns ``""`` for a numeric column that carries no value, and a
    CMDB row with an unset ``STATUS_ID`` is ordinary data, not corruption.
    Typed ``int`` alone such a row failed the whole record -- and because a
    search validates a page in one comprehension, the whole page with it.
    """

    asset_id: OptionalInt = Field(default=None, alias="ASSET_ID")
    asset_tag: str | None = Field(default=None, alias="ASSET_TAG")
    serial_number: str | None = Field(default=None, alias="SERIAL_NUMBER")
    status_id: OptionalInt = Field(default=None, alias="STATUS_ID")
    href: str | None = Field(default=None, alias="HREF")


class PostAsset(EasyvistaWriteModel):
    """Payload for creating an asset.

    ``catalog_id`` identifies the equipment model and is required.

    ``catalog_id`` and ``status_id`` are ``int | str`` with
    ``union_mode="left_to_right"``: a numeric string is coerced to the number
    the instance's own create example shows (tier 3, illustrative only --
    ``{"assets": [{"catalog_id": 2666, ..., "status_id": 1}]}``), while a
    non-numeric value passes through as written rather than being refused by a
    type this package cannot vendor-document. ``custom_fields`` are serialized
    with an ``e_`` prefix (see :class:`EasyvistaWriteModel`).
    """

    catalog_id: int | str = Field(union_mode="left_to_right")
    asset_tag: str | None = None
    serial_number: str | None = None
    status_id: int | str | None = Field(default=None, union_mode="left_to_right")
    comment_asset: str | None = None
    installation_date: str | None = None
