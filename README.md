# easyvista-python-client

Typed Python client for the EasyVista Service Manager REST API. Sync + async,
Pydantic models, Bearer or Basic auth.

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
from easyvista_python_client import EasyvistaClient, EasyvistaConfig, PostRequest

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
    results = client.search_tickets(search="STATUS_EN~Open", max_rows=50)

    # page through everything with the iterator (follows the API's offset paging)
    for t in client.iter_tickets(search="STATUS_EN~Open", page_size=100, max_records=1000):
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
from easyvista_python_client import EasyvistaClient, EasyvistaConfig, PostAsset

with EasyvistaClient(EasyvistaConfig.from_env()) as client:
    asset = client.create_asset(PostAsset(catalog_id=3153, asset_tag="LAPTOP-001"))
    found = client.search_assets(search="ASSET_TAG~LAPTOP", max_rows=50)

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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and quality checks.

## License

MIT — see [LICENSE](LICENSE).

## Sponsoring

The development of this package is indirectly supported by
[Novahé](https://www.novahe.fr/) & [Constellation](https://www.constellation.fr/).
