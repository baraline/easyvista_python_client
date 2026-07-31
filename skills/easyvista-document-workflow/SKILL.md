---
name: easyvista-document-workflow
description: "Attach, list and download files on an EasyVista ticket with easyvista_python_client — add_document, list_documents and download_document with the Document model. Use for ticket attachments, uploading evidence or logs to a request, or fetching an attachment's bytes."
license: MIT
compatibility: "Requires Python 3.10+, easyvista-python-client, network access to an EasyVista Service Manager REST API, and a profile authorized for the documents sub-resource."
metadata:
  package: easyvista-python-client
  version: "0.1.0"
---

> **Sync and async.** Examples use `EasyvistaClient`. For `AsyncEasyvistaClient`,
> use `async with`, `await` every call, and `async for` over the `iter_*`
> methods — the method names and arguments are identical. See
> `easyvista-client-setup`.

Documents are attachments on a ticket. Three methods: `add_document(rfc,
filename=, content=)`, `list_documents(rfc)`, `download_document(document)`.
All are ticket-scoped — there is no standalone document resource on this
client.

## Procedure

1. Upload with `add_document(rfc, filename="name.ext", content=b"...")`.
   `content` is **bytes**, not a path and not `str`.
2. List with `list_documents(rfc)` → `list[Document]`.
3. Download with `download_document(document)` → `bytes`. Pass the `Document`
   from the list, or a raw href/path.
4. Write the bytes yourself; the client does not touch the filesystem.

## The Document model

`filename` (falls back to `DOCUMENT` then `NAME`, so it is populated on every
observed shape), `name`, `document`, `document_id`, `download_href` (the API's
`DDL_HREF`, the direct-download URL), `href`.

## Examples

```python
from pathlib import Path

from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    document = client.add_document(
        "YOUR_RFC_NUMBER",
        filename="diagnostics.log",
        content=Path("diagnostics.log").read_bytes(),
    )
    print(document.filename, document.document_id)
```

```python
from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    for document in client.list_documents("YOUR_RFC_NUMBER"):
        print(document.document_id, document.filename, document.download_href)
```

```python
from pathlib import Path

from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    for document in client.list_documents("YOUR_RFC_NUMBER"):
        if document.download_href is None:
            continue
        payload = client.download_document(document)
        Path(document.filename or "attachment.bin").write_bytes(payload)
```

## Gotchas

- `content` must be `bytes`. Read files in binary mode.
- `download_document` raises `ValueError` when the record carries no download
  URL — check `download_href` first, or catch it.
- A download URL pointing outside the configured instance raises
  `EasyvistaError`. Downloads follow redirects (signed URLs are common), and
  httpx strips the `Authorization` header on a cross-origin redirect, so a
  foreign host would receive the request unauthenticated — refusing is
  deliberate.
- A 403 on an attachment still surfaces as `EasyvistaAuthError`; the binary
  path reuses the same error mapping and retry policy as the JSON one.
- `filename` is derived, not always sent by the API. Fall back to a literal
  name before writing to disk.
- There is no delete-document method on this client.
