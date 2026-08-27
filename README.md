# easyvista-python-client

[![CI](https://github.com/baraline/easyvista_python_client/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/baraline/easyvista_python_client/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/baraline/easyvista_python_client/branch/main/graph/badge.svg)](https://codecov.io/gh/baraline/easyvista_python_client)
[![License](https://img.shields.io/github/license/baraline/easyvista_python_client)](https://github.com/baraline/easyvista_python_client/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://github.com/baraline/easyvista_python_client)
[![Docs](https://readthedocs.org/projects/easyvista-python-client/badge/?version=latest)](https://easyvista-python-client.readthedocs.io/en/latest/)


Typed Python client for the EasyVista Service Manager REST API. Sync + async,
Pydantic models, Bearer or Basic auth.

While the package is preparing for 1.0, breaking changes may land between
minor versions; a deprecation policy will follow the 1.0 release.

## Documentation

Full documentation: https://easyvista-python-client.readthedocs.io/

Build it locally with `pip install -e ".[docs]"` then
`sphinx-build -b html -W docs docs/_build/html`.

## Install

```bash
pip install easyvista-python-client
```

## Usage (sync)

```python
from easyvista_python_client import (
    EasyvistaClient,
    EasyvistaConfig,
    PostRequest,
    ev_equals_filter,
)

# `account` is the instance id in the API root (https://host/api/v1/12345), not a username.
config = EasyvistaConfig(server="https://my.easyvista.com", account="12345", token="...")
with EasyvistaClient(config) as client:
    # catalog_code, the *_id values and the close status_guid are instance-specific.
    ticket = client.create_ticket(
        PostRequest(
            catalog_code="INC_STANDARD",
            title="Printer down",
            description="The 3rd-floor printer is offline",
            origin=7,
            department_id=9,
            urgency_id=8,
            impact_id=28,
        )
    )
    fetched = client.get_ticket(ticket.rfc_number)
    open_status = ev_equals_filter("STATUS_ID", 3)
    results = client.search_tickets(search=open_status, max_rows=50)

    # page through everything with the iterator (follows the API's offset paging)
    for t in client.iter_tickets(search=open_status, page_size=100, max_records=1000):
        ...  # async: `async for t in client.iter_tickets(...)`

    # close it with your instance's "closed" status GUID
    client.close_ticket(
        ticket.rfc_number,
        status_guid="{00000000-0000-0000-0000-000000000000}",
        delete_actions=1,
        comment="Resolved",
    )
```

> Minimum fields for a create are catalog-specific (server-side). `catalog_code` + `title`
> work for incident catalogs; a missing mandatory field raises `EasyvistaValidationError`
> (HTTP 590, code 2013) — it is not retried.

## Assets and documents

```python
from pathlib import Path
from easyvista_python_client import (
    EasyvistaClient,
    EasyvistaConfig,
    PostAsset,
    ev_contains_filter,
    ev_equals_filter,
)

with EasyvistaClient(EasyvistaConfig.from_env()) as client:
    asset = client.create_asset(PostAsset(catalog_id=3153, asset_tag="LAPTOP-001"))
    tag_filter = ev_equals_filter("ASSET_TAG", "LAPTOP-001")
    found = client.search_assets(search=tag_filter, max_rows=50)

    # `~` needs an explicit wildcard to mean "contains" -- a bare value is exact
    # match, identical to `:`. ev_contains_filter adds the wildcard for you, and
    # raises ValueError if the value itself carries one of * % _ [ (all four are
    # metacharacters to `~`, with no escape). For an exact match on a tag like
    # "LAPTOP_01", use ev_equals_filter: `:` does not expand a wildcard.
    partial = client.search_assets(search=ev_contains_filter("ASSET_TAG", "LAPTOP"))

    # attach a file to a ticket (uploaded as base64 inside the JSON body)
    pdf = Path("report.pdf")
    client.add_document("I240101_0001", filename=pdf.name, content=pdf.read_bytes())
    attachments = client.list_documents("I240101_0001")
```

## Usage (async)

```python
from easyvista_python_client import AsyncEasyvistaClient, EasyvistaConfig

async with AsyncEasyvistaClient(EasyvistaConfig.from_env()) as client:
    ticket = await client.get_ticket("I240101_0001")
```

## Configuration via environment

Set `EASYVISTA_URL` (or `EASYVISTA_SERVER`), `EASYVISTA_ACCOUNT`, and either
`EASYVISTA_TOKEN` / `EASYVISTA_TOKEN_FILE` or `EASYVISTA_LOGIN` + `EASYVISTA_PASSWORD`,
then call `EasyvistaConfig.from_env()`.

## Agent skills

`skills/` holds Agent Skills for driving this client from an AI agent — one per
domain (client setup, search syntax, tickets, actions, documents, assets,
directory, reporting and context). Each is a directory with a `SKILL.md`
following the Agent Skills specification; see [skills/README.md](https://github.com/baraline/easyvista_python_client/blob/main/skills/README.md)
for the index.

They are source-tree material: present in the git repository and the source
distribution, absent from the installed wheel.

## Contributing

See [CONTRIBUTING.md](https://github.com/baraline/easyvista_python_client/blob/main/CONTRIBUTING.md) for development setup and quality checks.

## License

MIT — see [LICENSE](https://github.com/baraline/easyvista_python_client/blob/main/LICENSE).

## Sponsoring

The development of this package is indirectly supported by
[Novahé](https://www.novahe.fr/) & [Constellation](https://www.constellation.fr/).
