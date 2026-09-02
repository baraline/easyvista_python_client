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
    # catalog_code, the *_id values and the close status_guid are
    # instance-specific -- `client.describe_instance()` finds them for you.
    # `external_reference` is your own marker, and it is what lets you
    # reconcile a create that failed: see the note below this block.
    ticket = client.create_ticket(
        PostRequest(
            catalog_code="INC_STANDARD",
            title="Printer down",
            description="The 3rd-floor printer is offline",
            # The vendor documents `origin` as a channel NAME, not an id --
            # the one create field with a portable form. An int is also
            # accepted (measured on one instance) and passes through as sent.
            origin="Phone",
            department_id=9,
            urgency_id=8,
            impact_id=28,
            external_reference="MYAPP-0001",  # your own marker; set it always
        )
    )
    fetched = client.get_ticket(ticket.rfc_number)
    open_status = ev_equals_filter("STATUS_ID", 3)
    results = client.search_tickets(search=open_status, max_rows=50)

    # page through everything with the iterator (follows the API's offset paging)
    for t in client.iter_tickets(search=open_status, page_size=100, max_records=1000):
        ...  # async: `async for t in client.iter_tickets(...)`

    # close it with your instance's "closed" status GUID. Every argument is
    # optional -- `client.close_ticket(ticket.rfc_number)` sends the close with
    # no status of its own, but where that lands the ticket is not established
    # by this package; see the user guide before relying on it.
    client.close_ticket(
        ticket.rfc_number,
        status_guid="{00000000-0000-0000-0000-000000000000}",
        delete_actions=1,
        comment="Resolved",
    )
```

> A create needs a subject: `catalog_guid` (the vendor's preferred identifier) or
> `catalog_code`. Anything beyond that is catalog-specific and enforced server-side, so a
> field a given catalog insists on raises `EasyvistaValidationError` (HTTP 590, code 2013)
> — it is not retried, and the message names no field.
>
> **Do not retry that 590 blindly.** Measured on one instance (2026-08-25), a rejected
> create may still have created the ticket: 12 attempts returned 3 `RFC_NUMBER`s and
> afterwards all 12 tickets existed. A 590 means *possibly created*, never *not created*.
> Set `external_reference` on every create and reconcile by that marker — it survives the
> failed insert and is searchable.

## Comments and actions

An action is a unit of work, and it is born **open** — an open action shows in the
UI as a pending row with its text *not* displayed, which reads as though the note
was lost. A comment is an action that has been **ended**.

```python
from easyvista_python_client import PostAction, PostTask

# A COMMENT: `create_task` posts the same record already ended, in one call.
# Put the text in `description` -- the UI renders one field per action and
# `description` shadows `comment`, so text in `comment` beside a populated
# `description` is stored, readable through the API, and displayed to nobody.
client.create_task(
    rfc,
    PostTask(action_type_id=94, group_id=3, description="Investigating now."),
)

# WORK SOMEONE MUST STILL DO: create it open, then end it when it is done.
client.create_action(
    rfc,
    PostAction(action_type_id=94, group_id=3, description="Chase the supplier."),
)
client.end_action(
    rfc,
    action_id=1234,                    # not recoverable from the create response
    start_date="01/09/2026 17:00:00",  # your instance's format, not ISO 8601
    end_date="01/09/2026 17:15:00",
    elapsed_time=15,                   # MINUTES
)
```

> **There is no private-comment flag.** Visibility is carried by the action
> *type*, which is per-deployment — read the ids off existing actions with
> `client.discover("ACTION_TYPE")` rather than hardcoding one.
>
> **`end_action` on a workflow action changes the ticket.** Ending your own
> action only ends it; ending the ticket's open workflow step advances the
> workflow and moves the ticket's status. Naming `action_id` is therefore
> required — the vendor's id-less "end every open action" form is behind an
> explicit `end_all=True`.

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

    # On the instance this package was characterized against, `~` needs an
    # explicit wildcard to mean "contains" -- a bare value is exact match,
    # identical to `:`. ev_contains_filter appends it for you; the vendor
    # documents `~` as plain Contains, so pass wildcard=None if that is your
    # deployment. It raises ValueError if the value carries `_` or `[` (both
    # are metacharacters to `~` itself, with no escape) or `*`/`%` while a
    # wildcard is being appended. For an exact match on a tag like
    # "LAPTOP_01", use ev_equals_filter: `:` does not expand a wildcard.
    partial = client.search_assets(search=ev_contains_filter("ASSET_TAG", "LAPTOP"))

    # attach a file to a ticket (uploaded as base64 inside the JSON body)
    pdf = Path("report.pdf")
    client.add_document("I240101_0001", filename=pdf.name, content=pdf.read_bytes())
    attachments = client.list_documents("I240101_0001")
```

## Usage (async)

```python
import asyncio

from easyvista_python_client import AsyncEasyvistaClient, EasyvistaConfig


async def main():
    async with AsyncEasyvistaClient(EasyvistaConfig.from_env()) as client:
        ticket = await client.get_ticket("I240101_0001")
        print(ticket.rfc_number)


asyncio.run(main())
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
