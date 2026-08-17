---
name: easyvista-asset-workflow
description: "Create, fetch, search and iterate EasyVista assets with easyvista_python_client — create_asset, get_asset, search_assets and iter_assets with PostAsset and Asset. Use for equipment, hardware or CI records: registering a new asset, looking one up by tag, or listing a department's assets."
license: MIT
compatibility: "Requires Python 3.10+, easyvista-python-client, network access to an EasyVista Service Manager REST API, and a profile authorized for the assets resource."
metadata:
  package: easyvista-python-client
  version: "0.1.0"
---

> **Sync and async.** Examples use `EasyvistaClient`. For `AsyncEasyvistaClient`,
> use `async with`, `await` every call, and `async for` over the `iter_*`
> methods — the method names and arguments are identical. See
> `easyvista-client-setup`.

Assets are EasyVista's equipment records — the `assets` resource. Four
methods: `create_asset`, `get_asset`, `search_assets` and `iter_assets`; there
is no update or delete (see Gotchas). Filtering any `search=` argument follows
the grammar in `easyvista-search-syntax` — see that skill for the rules; they
are not repeated here.

## Discover the catalog id first

`PostAsset.catalog_id` is **required** and identifies the equipment model on
your instance. `reference()` resolves declared and undeclared fields equally
well: it works from `self.model_dump(by_alias=True)`, and `extra="allow"`
folds every raw API key -- named in the model or not -- into that dump. This
is exactly how `easyvista-ticket-workflow` resolves `reference("STATUS")` and
`reference("CATALOG_REQUEST")` on `Request`, neither of which is a field
`Request` declares either. The reason `reference()` does not help with the
catalog here is different: no tracked source confirms an AM_ASSET payload
carries any key resembling `CATALOG` or `CATALOG_ID` at all, declared or
not -- there is simply nothing known yet to point it at. Print the raw
fields (and the href-only `links` bucket, in case the catalog comes back as
a bare `{"HREF": ...}` sub-resource rather than an inline value) on a real
asset instead, and read the id straight off whichever key turns out to be
the catalog on your instance:

```python
from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    page = client.search_assets(max_rows=5)
    for asset in page.records:
        print(asset.asset_id, asset.asset_tag, asset.serial_number)
        # Asset declares only five fields (see Gotchas); everything else the
        # instance returns -- including whatever field carries the catalog --
        # is preserved here, keys and values both.
        buckets = asset.classify_fields()
        print("raw fields:", buckets.official)
        print("href-only fields:", buckets.links)
```

Look through `raw fields` (and `href-only fields`, if the catalog turns out
to be a link rather than an inline value) for whatever this instance calls
the catalog, and read its id straight off the printed value; that is what
`catalog_id` needs.

## Procedure

1. Discover `catalog_id` (above). Never hardcode one copied from another
   instance.
2. Build a `PostAsset(catalog_id=..., asset_tag=..., serial_number=...)`;
   instance-specific columns go in `custom_fields`.
3. Call `create_asset(asset)`.
4. Fetch one with `get_asset(asset_id)` — `asset_id` is a string here.
5. Search a page with `search_assets(search=..., max_rows=...)`; walk every
   match with `iter_assets(...)`.

## Examples

```python
from easyvista_python_client import EasyvistaClient, PostAsset

with EasyvistaClient.from_env() as client:
    asset = client.create_asset(
        PostAsset(
            catalog_id=1,
            asset_tag="LAPTOP-0001",
            serial_number="SN-0001",
            comment_asset="Issued to the service desk pool.",
        )
    )
    print(asset.asset_id, asset.asset_tag)
```

`catalog_id=1` above is a placeholder — use the id the discovery block
printed for your instance.

```python
from easyvista_python_client import EasyvistaClient, ev_equals_filter

with EasyvistaClient.from_env() as client:
    found = client.search_assets(
        search=ev_equals_filter("ASSET_TAG", "LAPTOP-0001"), max_rows=50
    )
    print(found.record_count, "of", found.total_record_count)
    for asset in found.records:
        print(asset.asset_id, asset.serial_number)
```

```python
from easyvista_python_client import EasyvistaClient, ev_equals_filter

with EasyvistaClient.from_env() as client:
    search = ev_equals_filter("DEPARTMENT_ID", 42)
    for asset in client.iter_assets(search=search, page_size=100, max_records=1000):
        print(asset.asset_id, asset.asset_tag)
```

```python
from easyvista_python_client import EasyvistaClient, ev_contains_filter

with EasyvistaClient.from_env() as client:
    # A bare '~' is exact match, just like ':' -- ev_contains_filter adds the
    # explicit wildcard a partial-tag search needs: ASSET_TAG~"*LAPTOP*"
    found = client.search_assets(search=ev_contains_filter("ASSET_TAG", "LAPTOP"))
    print(found.total_record_count)
```

## Gotchas

- `catalog_id` is required by EasyVista and is an `int`; `get_asset` takes a
  `str` id. The asymmetry is real.
- `ASSET_TAG~"LAPTOP"` (a bare value, no wildcard) is **exact match**,
  identical to `ASSET_TAG:"LAPTOP"` — `~` degenerates to equality without an
  explicit wildcard. For a partial-tag search use `ev_contains_filter` /
  `ev_starts_with_filter`, which add the wildcard for you:
  `ev_contains_filter("ASSET_TAG", "LAPTOP")` builds `ASSET_TAG~"*LAPTOP*"`
  (verified live
  `integration_tests/test_live_search_syntax.py::test_tilde_without_a_wildcard_is_exact_on_asset_tag`;
  see `easyvista-search-syntax` for the full grammar).
- The `Asset` model declares only `asset_id`, `asset_tag`, `serial_number`,
  `status_id` and `href`; everything else the instance returns is preserved
  by `extra="allow"` and reachable through `classify_fields()`. `reference()`
  resolves declared and undeclared fields equally well (see the discovery
  section above) -- the reason it is not used for the catalog is that no
  tracked source confirms an AM_ASSET payload carries a `CATALOG`-shaped key
  at all, not that the field is undeclared.
- Asset field names beyond those five are pending live validation — that is
  the module's own framing, not just this skill's caution. Verify a column
  filters (baseline check, `easyvista-search-syntax`) before relying on it.
- There is no update or delete method for assets on this client.
- A profile restriction on asset creation surfaces as `EasyvistaAuthError`
  (403) — the same generic 401/403 mapping used everywhere on this client.
  No tracked test creates an asset live, so how commonly that restriction
  applies in practice is not something this repository has verified.
