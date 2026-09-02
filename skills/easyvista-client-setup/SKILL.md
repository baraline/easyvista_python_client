---
name: easyvista-client-setup
description: "Create and configure the synchronous easyvista_python_client.EasyvistaClient or the asynchronous AsyncEasyvistaClient — server/account/api_version, Bearer token or HTTP Basic credentials, EasyvistaConfig.from_env, timeouts, retries, TLS verification, default page size, and the EasyvistaError hierarchy. Use before calling any EasyVista API, or when the user asks how to connect to EasyVista with easyvista_python_client."
license: MIT
compatibility: "Requires Python 3.10+, easyvista-python-client, network access to an EasyVista Service Manager REST API, and valid EasyVista credentials."
metadata:
  package: easyvista-python-client
  version: "0.2.0"
---

`easyvista_python_client` ships both clients over one surface:
`EasyvistaClient` is blocking, and `AsyncEasyvistaClient` returns coroutines
and does real non-blocking I/O. Same method names, same arguments, same
results. Pick the one matching the runtime — synchronous script or async
event loop — and keep it consistent within one application.

Two exceptions to "returns coroutines": the `iter_*` methods and
`stream_document` are **async generators** on the async client. Iterate them
with `async for`; `await client.stream_document(...)` raises `TypeError`.

## Procedure

1. Pick the client class: `EasyvistaClient` for synchronous code,
   `AsyncEasyvistaClient` inside an event loop.
2. Build an `EasyvistaConfig`: `server` (the instance root, no `/api`
   segment) and `account` are always required. `account` is the **instance
   identifier**, not a login — see the gotcha below before guessing it.
3. Supply exactly one credential: `token=` for Bearer, or `login=` and
   `password=` for HTTP Basic. Neither present raises `ValueError` at
   construction.
4. Leave `api_version` at `"v1"` unless the instance says otherwise; the
   client builds `{server}/api/{api_version}/{account}`.
5. Prefer `EasyvistaConfig.from_env()` / `EasyvistaClient.from_env()` for
   anything with credentials in the environment.
6. Keep `verify_ssl=True` unless the user confirms an internal endpoint that
   cannot present a valid chain.
7. Raise `max_retries` above its `0` default only for flaky networks; 429 and
   5xx are retried with exponential backoff, and 590 deliberately is not.
8. Use the client as a context manager so its HTTP session closes; call
   `client.close()` (`await client.aclose()`) when it outlives the block.

## Configuration

Every `EasyvistaConfig` field, and its default:

| Field | Default | Notes |
| --- | --- | --- |
| `server` | required | Instance root, no `/api` segment |
| `account` | required | Instance id forming the last path segment of `api_root`, e.g. `"12345"`. **Not a login** — see Gotchas |
| `token` | `None` | Bearer credential |
| `login` | `None` | HTTP Basic credential, paired with `password` |
| `password` | `None` | HTTP Basic credential, paired with `login` |
| `timeout` | `30.0` | Seconds |
| `max_retries` | `0` | Applies to 429 and 5xx only |
| `verify_ssl` | `True` | `True`/`False`, a CA-bundle path, or an `ssl.SSLContext` — a private CA does **not** require disabling verification |
| `default_max_rows` | `100` | Page size when `max_rows` / `page_size` is omitted |
| `api_version` | `"v1"` | Used to build `api_root` |
| `document_delete_path_style` | `"nested"` | Which delete route `delete_document` sends: `"nested"` (`requests/{rfc}/documents/{id}`) or `"top_level"` (`documents/{id}`). Both routes exist on this API; which one a profile grants varies. Overridable per call. |
| `datetime_input_formats` | `()` | Extra `strptime` patterns for timestamp columns, tried only after EasyVista's own ISO-8601 form fails. Nothing is guessed — an unlisted format still raises. |
| `extra_headers` | `{}` | Merged over every header sent to the instance; an `Authorization` key raises at construction |
| `user_agent` | `None` | `None` sends `DEFAULT_USER_AGENT`; pass a string to replace it |
| `default_params` | `{}` | Query parameters on every JSON API request, **under** any the call sets; not applied to downloads |
| `additional_download_hosts` | `frozenset()` | https hosts `download_document` / `stream_document` may fetch from, **without** the credential |

`config.api_root` and `config.uses_basic_auth` are read-only properties
derived from the fields above, not settable inputs. The dataclass itself is
frozen — no field can be reassigned after construction.

## Adapting to a deployment that is not the default

The last four fields exist so a deployment differing from the common case
needs no fork. Every default is the value that works without them.

```python
import ssl

from easyvista_python_client import DEFAULT_USER_AGENT, EasyvistaClient, EasyvistaConfig

config = EasyvistaConfig(
    server="https://ev.example.com",
    account="12345",
    token="YOUR_TOKEN",
    # An API gateway in front of the instance needs its own key, and a WAF
    # asked to whitelist this integration needs something to whitelist.
    extra_headers={"Ocp-Apim-Subscription-Key": "YOUR_GATEWAY_KEY"},
    user_agent=f"{DEFAULT_USER_AGENT} my-app/1.4",
    # A corporate private CA — disabling verification is not the only answer.
    verify_ssl=ssl.create_default_context(cafile="/etc/ssl/corp-root.pem"),
)
```

## Reaching a route this package does not wrap

`client.send()` is the escape hatch. This package wraps roughly ten of the
paths an instance advertises; `send` reaches the rest with the same retries
and the same error mapping, returning the decoded JSON unchanged.

```python
with EasyvistaClient(config) as client:
    # A reference table this package has no model for.
    statuses = client.send("GET", "status", params={"max_rows": 200})

    # Per-call query parameters work on the wrapped methods too.
    ticket = client.get_ticket("YOUR_RFC_NUMBER", params={"formatDate": "iso"})
```

`path` always joins to `api_root`, so an absolute URL is never followed — that
is what keeps the credential scoped to the configured instance. To fetch a URL
the API handed back, use `download_document` / `stream_document`.

## Environment defaults

`EasyvistaConfig.from_env()` and `EasyvistaClient.from_env()` read:

1. `EASYVISTA_URL` (or `EASYVISTA_SERVER`) for `server`.
2. `EASYVISTA_ACCOUNT` for `account`.
3. `EASYVISTA_TOKEN` for `token`; if unset, `EASYVISTA_TOKEN_FILE` (a path
   whose contents are read and stripped).
4. Otherwise `EASYVISTA_LOGIN` / `EASYVISTA_PASSWORD` for Basic auth.

A missing server or account raises `ValueError`. `from_env` takes **no
keyword overrides** — build an `EasyvistaConfig` directly when you need to
override one value.

It reads the connection settings only, and no tuning field: not `timeout`, not
`max_retries`, not `default_max_rows`, not `document_delete_path_style`, not
`datetime_input_formats`. That is deliberate — these are code decisions, not
deployment secrets, and the package is installed from PyPI rather than
configured by its environment. To keep `from_env`'s credential resolution and
change one of them:

```python
import dataclasses

from easyvista_python_client import EasyvistaClient, EasyvistaConfig

config = dataclasses.replace(
    EasyvistaConfig.from_env(), document_delete_path_style="top_level"
)
with EasyvistaClient(config) as client:
    ...
```

## Examples

```python
from easyvista_python_client import EasyvistaClient, EasyvistaConfig

config = EasyvistaConfig(
    server="https://my.easyvista.example.com",
    account="12345",
    token="YOUR_API_TOKEN",
)

with EasyvistaClient(config) as client:
    result = client.search_tickets(max_rows=10)
    print(result.record_count, "of", result.total_record_count)
```

```python
from easyvista_python_client import EasyvistaClient, EasyvistaConfig

config = EasyvistaConfig(
    server="https://my.easyvista.example.com",
    account="12345",
    login="rest.user",
    password="YOUR_PASSWORD",
)

with EasyvistaClient(config) as client:
    ticket = client.get_ticket("YOUR_RFC_NUMBER")
    print(ticket.rfc_number, ticket.title)
```

```python
from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    print(client.count_tickets())
```

```python
import asyncio

from easyvista_python_client import AsyncEasyvistaClient, EasyvistaConfig


async def main() -> None:
    config = EasyvistaConfig(
        server="https://my.easyvista.example.com",
        account="12345",
        token="YOUR_API_TOKEN",
    )
    async with AsyncEasyvistaClient(config) as client:
        result = await client.search_tickets(max_rows=10)
        print(result.total_record_count)
        async for ticket in client.iter_tickets(max_records=5):
            print(ticket.rfc_number)


asyncio.run(main())
```

```python
from easyvista_python_client import (
    EasyvistaAuthError,
    EasyvistaClient,
    EasyvistaError,
    EasyvistaNotFound,
    EasyvistaValidationError,
)

with EasyvistaClient.from_env() as client:
    try:
        ticket = client.get_ticket("YOUR_RFC_NUMBER")
    except EasyvistaNotFound:
        ticket = None
    except EasyvistaValidationError as exc:
        print("rejected:", exc.status_code, exc.ev_code, exc.ev_message)
        raise
    except EasyvistaAuthError as exc:
        print("profile not authorized:", exc.status_code)
        raise
    except EasyvistaError as exc:
        print("other API failure:", exc.status_code)
        raise
```

## Errors

| HTTP status | Exception | Meaning here |
| --- | --- | --- |
| 401 / 403 | `EasyvistaAuthError` | 403 is usually a *profile* restriction on the token, not a bad credential; the context bundles degrade around it rather than failing. |
| 404 | `EasyvistaNotFound` | The resource does not exist. |
| 400 | `EasyvistaValidationError` | The request was rejected as malformed. |
| **590** | `EasyvistaValidationError` | EasyVista's "Internal Easyvista Error" is in practice a rejected request — a missing mandatory field or an invalid catalog reference. It is deterministic, so it is **not** retried. |
| 429 | `EasyvistaRateLimitError` | Retried when `max_retries > 0`. |
| 5xx | `EasyvistaServerError` | Retried when `max_retries > 0`. |
| Transport failure (timeout, refused connection) | `EasyvistaConnectionError` | No response was obtained at all. |

Every one of these carries `status_code`, `ev_code` and `ev_message`, and all
derive from `EasyvistaError`.

## Gotchas

- `server` is the instance root. Do **not** append `/api/v1/<account>`; the
  client composes `config.api_root` from `server`, `api_version` and
  `account`.
- `account` is **not a user account**, despite sitting beside `login` and
  `password` in the same config. It is the EasyVista *instance* identifier — a
  number such as `"12345"` — that forms the last path segment of
  `https://host/api/{version}/{account}`. Nothing authenticates with it; that is
  `token`, or `login` + `password`, and those are unrelated values. If the
  instance URL you were handed already reads
  `https://my.easyvista.com/api/v1/12345`, then `server` is
  `https://my.easyvista.com` and `account` is `12345`.
- `EasyvistaConfig` is frozen. To change a setting, build a new config.
- Constructing a config with neither `token` nor a complete `login`/`password`
  pair raises `ValueError` immediately — a credential problem surfaces before
  any request.
- `from_env()` accepts no overrides, unlike the sister GLPI client's.
- `default_max_rows` (100) is the page size used when `max_rows` / `page_size`
  is omitted — it is not a total cap; the `iter_*` methods page past it.
- Retries are off by default (`max_retries=0`).
- Closing matters: the client owns an HTTP session. Prefer the context
  manager.
