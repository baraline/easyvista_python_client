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
your instance. On `Request`, the ticket-workflow skill discovers ids like this
with `reference()`, because fields such as `STATUS_ID` are declared and
`reference()` can resolve a nested label around them. `Asset` is different:
it declares only five fields (`asset_id`, `asset_tag`, `serial_number`,
`status_id`, `href` — see Gotchas), none of them a catalog, so there is
nothing for `reference()` to resolve a catalog id against out of the box.
Print the raw fields on a real asset instead, and find whatever key this
instance uses:

```python
from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    page = client.search_assets(max_rows=5)
    for asset in page.records:
        print(asset.asset_id, asset.asset_tag, asset.serial_number)
        # Asset declares only five fields (see Gotchas); everything else the
        # instance returns -- including whatever key carries the catalog --
        # is preserved here and visible through classify_fields().
        print("raw fields:", sorted(asset.classify_fields().official))
```

Look through `raw fields` for whatever this instance calls the catalog (or
ask whoever administers catalogs on it) and read its id from there; that is
the value `catalog_id` needs.

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

## Gotchas

- `catalog_id` is required by EasyVista and is an `int`; `get_asset` takes a
  `str` id. The asymmetry is real.
- `ASSET_TAG` filters as **exact match** with `~` as well as `:` — there is
  no substring search for a partial tag
  (`integration_tests/test_live_search_syntax.py::test_tilde_on_asset_tag_is_exact_match`).
- The `Asset` model declares only `asset_id`, `asset_tag`, `serial_number`,
  `status_id` and `href`; everything else the instance returns is preserved
  by `extra="allow"` and reachable through `classify_fields()`. There is no
  declared catalog field, which is why the discovery block above prints raw
  keys instead of calling `reference()`.
- Asset field names beyond those five are pending live validation — that is
  the module's own framing, not just this skill's caution. Verify a column
  filters (baseline check, `easyvista-search-syntax`) before relying on it.
- There is no update or delete method for assets on this client.
- A profile restriction on asset creation surfaces as `EasyvistaAuthError`
  (403) — the same generic 401/403 mapping used everywhere on this client.
  No tracked test creates an asset live, so how commonly that restriction
  applies in practice is not something this repository has verified.
