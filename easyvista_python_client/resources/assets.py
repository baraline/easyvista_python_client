"""Builders for the ``assets`` resource.

Create/get/search ride the generic resource engine (:mod:`.descriptor`); the
returned ``(RequestSpec, parser)`` pairs are shared by the sync and async clients.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from .._transport import RequestSpec
from ..models.asset import Asset, PostAsset
from ..pagination import SearchResult
from .descriptor import ResourceDescriptor, build_create, build_get, build_search

ASSETS: ResourceDescriptor[Asset] = ResourceDescriptor(
    path="assets", envelope_key="assets", model=Asset
)


def build_create_asset(
    payload: PostAsset,
) -> tuple[RequestSpec, Callable[[Any], Asset]]:
    return build_create(ASSETS, payload)


def build_get_asset(asset_id: str) -> tuple[RequestSpec, Callable[[Any], Asset]]:
    return build_get(ASSETS, asset_id)


def build_search_assets(
    *,
    search: str | None = None,
    fields: Iterable[str] | str | None = None,
    sort: str | None = None,
    max_rows: int | None = None,
    offset: int | None = None,
) -> tuple[RequestSpec, Callable[[Any], SearchResult[Asset]]]:
    return build_search(
        ASSETS,
        search=search,
        fields=fields,
        sort=sort,
        max_rows=max_rows,
        offset=offset,
    )
