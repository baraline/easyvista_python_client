---
name: easyvista-instance-discovery
description: "Discover what one EasyVista deployment actually exposes with easyvista_python_client — get_api_spec reads the instance's own OpenAPI, list_reference_table reads any list route into column-free records, discover resolves one reference name to the ids/labels/codes/GUIDs in use, and describe_instance profiles the lot into an InstanceProfile. Use before hardcoding any id, when a ticket create is rejected for an unknown catalog, urgency, impact or group, when you need a STATUS_GUID for set_status or close_ticket, or when you need to know which routes a deployment declares at all."
license: MIT
compatibility: "Requires Python 3.10+, easyvista-python-client, and network access to an EasyVista Service Manager REST API. Every call here is a GET; nothing is created, updated or deleted."
metadata:
  package: easyvista-python-client
  version: "0.3.0"
---

> **Sync and async.** Examples use `EasyvistaClient`. For `AsyncEasyvistaClient`,
> use `async with`, `await` every call, and `async for` over the `iter_*`
> methods — the method names and arguments are identical. See
> `easyvista-client-setup`.

**Every id in EasyVista is per-deployment configuration, not an API constant.**
`8` is *Clôturé* and `12` is *En cours* on the instance this package was
characterized against — adjacent numbers, opposite meanings. Resolve at
start-up and fail loudly; never freeze one into code.

## The four methods

- `get_api_spec(path="swagger")` → the instance's own OpenAPI document.
  `paths` is **tier 2** — authoritative for *this* deployment.
  `components.schemas` is **tier 3** — example-derived, illustrative only.
- `list_reference_table(path, search=, fields=, sort=, max_rows=, offset=,
  params=)` → `SearchResult[GenericRecord]` over any list route.
- `discover(name, strategy="auto", reference_path=, sample_size=, search=,
  reference_search=, max_rows=, with_guid=)` → `list[DiscoveredReference]`
  for one reference name.
- `describe_instance(names=, strategy=, reference_paths=, sample_size=,
  action_sample_tickets=, search=, max_rows=, include_spec=)` →
  `InstanceProfile`, which never raises for one part.

## Procedure

1. Run `describe_instance()` once at start-up. Read `.unavailable` **first** —
   a total outage looks exactly like a bare instance except that every gap is
   named there.
2. For one reference, `discover(name)`. Use `.id` for a write model's
   `*_id` field, `.code` for `PostRequest(catalog_code=...)`, and `.guid` for
   `set_status` / `close_ticket`.
3. For a route this package does not model at all, `list_reference_table(path)`
   — check `get_api_spec()["paths"]` to see which your deployment declares.
4. Never cache an id across deployments. Re-resolve, or fail loudly.

## Examples

```python
from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    profile = client.describe_instance()
    print(profile.version, len(profile.spec_paths))
    for gap, reason in profile.unavailable.items():
        print("gap:", gap, reason)

    for status in client.discover("STATUS"):
        # .guid is what set_status and close_ticket address a status by.
        print(status.id, status.label, status.guid)

    for catalog in client.discover("CATALOG_REQUEST"):
        # .code is what PostRequest(catalog_code=...) takes.
        print(catalog.code, catalog.label)

    rows = client.list_reference_table("urgency")
    print(rows.record_count, rows.total_record_count)
```

```python
from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    # The vendor documents GET /urgencies; this deployment declares
    # GET /urgency. The default is the one the instance declares, and
    # reference_path= reaches the other without forking the package.
    urgencies = client.discover("URGENCY", reference_path="urgencies")
    print([u.id for u in urgencies])

    # A custom column has no table, so it is read off sampled tickets.
    sites = client.discover("e_site", sample_size=500)
    print([(s.label or s.id, s.count) for s in sites])
```

## Gotchas

- **A 403 does not mean "denied".** This API answers 403 for a path that does
  not exist as well as for one a profile blocks, so the status code alone never
  distinguishes them. `get_api_spec()["paths"]` does.
- **`get_api_spec` answers HTTP 201, not 200.** This client is unaffected — its
  transport treats any 2xx as success — but code you write beside it that gates
  on `status_code == 200` skips the document in silence and concludes the
  instance publishes no spec.
- **`list_reference_table` lets a 403 propagate; it never returns `[]`.** An
  empty reference table is a legitimate answer on a lightly configured
  instance, so collapsing a denial into an empty list would make "you may not
  read this" indistinguishable from "there is nothing here". `describe_instance`
  is the layer that swallows it, and it names the gap in `.unavailable`.
- **Four names have no route at all**: `IMPACT`, `SEVERITY`, `ORIGIN` and
  `ACTION_TYPE`. That is a topology fact from the spec, not a 403 someone
  measured, so no strategy reaches a table for them. What you get is *the ids
  in use in the sample* — an id configured but unused is invisible, and a
  `count` is a sample count, never a population one. Priority is not
  discoverable at all: EasyVista derives it from urgency × impact.
- **`catalog_guid` is not discoverable.** No route returns one. Build with
  `catalog_code`, which `discover("CATALOG_REQUEST")` puts in `.code`.
- **A `STATUS_GUID` only ever comes from a sample.** No reference read returns
  one, but every ticket's nested `STATUS` object carries it. A status no
  sampled ticket currently holds keeps `guid=None` — the sample cannot reach
  it, and inventing one would hand you a GUID that addresses nothing.
- **Discovering `GROUP` by sampling gives ids with no labels.** An action
  carries `GROUP_ID` but no group label. That is stated rather than papered
  over with a fabricated one; grant the profile read access to `/groups` for
  real labels.
- **The ids for "internal note" vs "customer comment" are discoverable; the
  meaning is not.** `discover("ACTION_TYPE")` returns the types in use with
  their translated labels — a human still has to read which is which. See
  `easyvista-ticket-actions`.
- `GenericRecord` declares no columns, so `classify_fields()` puts every
  `E_`-prefixed column in the `custom` bucket, including an official one like
  `E_MAIL`. That is the trade for a model that assumes no schema.
- Read a `GenericRecord` column by its API name:
  `record.model_dump(by_alias=True)["STATUS_ID"]`, or generically with
  `record.reference(name)`.
- `describe_instance` samples **once**, not once per name, and issues roughly a
  dozen requests — all GETs. It catches only `EasyvistaError`, so a bug in this
  package still propagates rather than being buried as a fake instance limit.
