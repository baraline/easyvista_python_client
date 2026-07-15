"""Models for the EasyVista ``assets`` resource.

Field sets are the documented/common AM_ASSET fields; ``extra="allow"`` on the
read model preserves any others. Exact field names pending live validation.
"""

from __future__ import annotations

from pydantic import Field

from .common import EasyvistaModel, EasyvistaWriteModel


class Asset(EasyvistaModel):
    """An asset as returned by the API."""

    asset_id: int | None = Field(default=None, alias="ASSET_ID")
    asset_tag: str | None = Field(default=None, alias="ASSET_TAG")
    serial_number: str | None = Field(default=None, alias="SERIAL_NUMBER")
    status_id: int | None = Field(default=None, alias="STATUS_ID")
    href: str | None = Field(default=None, alias="HREF")


class PostAsset(EasyvistaWriteModel):
    """Payload for creating an asset.

    ``catalog_id`` is required by EasyVista (identifies the equipment model).
    ``custom_fields`` are serialized with an ``e_`` prefix (see EasyvistaWriteModel).
    """

    catalog_id: int
    asset_tag: str | None = None
    serial_number: str | None = None
    status_id: int | None = None
    comment_asset: str | None = None
    installation_date: str | None = None
