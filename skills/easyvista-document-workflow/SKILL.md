---
name: easyvista-document-workflow
description: "Attach, list, download and delete files on an EasyVista ticket with easyvista_python_client — add_document, list_documents, download_document and delete_document with the Document model. Use for ticket attachments, uploading evidence or logs to a request, fetching an attachment's bytes, or removing one."
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

Documents are attachments on a ticket. Four methods: `add_document(rfc,
filename=, content=)`, `list_documents(rfc)`, `download_document(document)`
and `delete_document(rfc, document_id)`. All are ticket-scoped — there is no
standalone document resource on this client.

## Procedure

1. Upload with `add_document(rfc, filename="name.ext", content=b"...")`.
   `content` is **bytes**, not a path and not `str`.
2. List with `list_documents(rfc)` → `list[Document]`.
3. Download with `download_document(document)` → `bytes`. Pass the `Document`
   from the list, or a raw href/path.
4. Write the bytes yourself; the client does not touch the filesystem.
5. Remove an attachment with `delete_document(rfc, document.document_id)`. It
   returns nothing (the API answers with an empty body) — re-list to confirm.

## The Document model

`filename` (falls back to `DOCUMENT` then `NAME`, so it is populated on every
observed shape), `name`, `document`, `document_id`, `download_href` (the API's
`DDL_HREF`, the direct-download URL), `href`.

`download_document` resolves the URL as `download_href or href` — it prefers
`DDL_HREF` and **falls back to `HREF`**. Either field on its own is enough, so
a record with an empty `download_href` may still be perfectly downloadable.

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
        # Both fields must be empty for the download to be impossible:
        # download_document falls back to href when DDL_HREF is unset.
        if document.download_href is None and document.href is None:
            continue
        payload = client.download_document(document)
        Path(document.filename or "attachment.bin").write_bytes(payload)
```

```python
from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    rfc = "YOUR_RFC_NUMBER"
    documents = client.list_documents(rfc)
    # DELETE requests/{rfc}/documents/{document_id} -- nested on the ticket,
    # like every other document operation. Returns nothing on success.
    client.delete_document(rfc, documents[0].document_id)
```

## Gotchas

- `content` must be `bytes`. Read files in binary mode.
- `download_document` raises `ValueError` only when **neither** `DDL_HREF` nor
  `HREF` is set. Guard on both (`download_href is None and href is None`), or
  catch the `ValueError`. Skipping a record because `download_href` alone is
  unset silently drops attachments the client would have fetched through
  `href`.
- A download URL pointing outside the configured instance raises
  `EasyvistaError`. Downloads follow redirects (signed URLs are common), and
  httpx strips the `Authorization` header on a cross-origin redirect, so a
  foreign host would receive the request unauthenticated — refusing is
  deliberate.
- A 403 on an attachment still surfaces as `EasyvistaAuthError`; the binary
  path reuses the same error mapping and retry policy as the JSON one.
- `filename` is derived, not always sent by the API. Fall back to a literal
  name before writing to disk.
- `delete_document(rfc, document_id)` is **ticket-scoped**: it calls the
  nested `DELETE requests/{rfc}/documents/{document_id}`. Both identifiers
  must be non-blank — a blank one would silently address the collection
  rather than one item, which `delete_document` refuses with `ValueError`
  before sending anything.
