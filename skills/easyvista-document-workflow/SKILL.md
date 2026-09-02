---
name: easyvista-document-workflow
description: "Attach, list, download, stream and delete files on an EasyVista ticket with easyvista_python_client — add_document, list_documents, download_document, stream_document and delete_document with the Document model. Use for ticket attachments, uploading evidence or logs to a request, fetching an attachment's bytes whole or chunk by chunk without buffering a large file, or removing one."
license: MIT
compatibility: "Requires Python 3.10+, easyvista-python-client, network access to an EasyVista Service Manager REST API, and a profile authorized for the documents sub-resource."
metadata:
  package: easyvista-python-client
  version: "0.3.0"
---

> **Sync and async.** Examples use `EasyvistaClient`. For `AsyncEasyvistaClient`,
> use `async with`, `await` every call, and `async for` over the `iter_*`
> methods and `stream_document` — the method names and arguments are identical.
> `stream_document` is an async generator, so `await client.stream_document(...)`
> is a `TypeError`; iterate it. See
> `easyvista-client-setup`.

Documents are attachments on a ticket. Five methods: `add_document(rfc,
filename=, content=)`, `list_documents(rfc)`, `download_document(document)`,
`stream_document(document, chunk_size=)` and `delete_document(rfc,
document_id, path_style=)`. Add, list and download are ticket-scoped; delete
can address the document by its id alone — see the gotcha below.

## Procedure

1. Upload with `add_document(rfc, filename="name.ext", content=b"...")`.
   `content` is **bytes**, not a path and not `str`.
2. List with `list_documents(rfc)` → `list[Document]`.
3. Download with `download_document(document)` → `bytes`. Pass the `Document`
   from the list, or a raw href/path.
4. For a large attachment, iterate `stream_document(document)` instead → byte
   chunks (64 KiB by default, `chunk_size=` to change it). Same accepted
   inputs and same URL resolution as `download_document`; the file never has
   to exist in memory whole.
5. Write the bytes yourself; the client does not touch the filesystem.
6. Remove an attachment with `delete_document(rfc, document.document_id)`, or
   pass the `Document` itself and let the client read the id off it. It
   returns nothing (the API answers with an empty body) — re-list to confirm.

## The Document model

`filename` (falls back to `DOCUMENT` then `NAME`, so it is populated on every
observed shape), `name`, `document`, `document_id`, `download_href` (the API's
`DDL_HREF`, the direct-download URL), `href`.

`download_document` resolves the URL as `download_href or href` — it prefers
`DDL_HREF` and **falls back to `HREF`**. Either field on its own is enough, so
a record with an empty `download_href` may still be perfectly downloadable.
`stream_document` resolves it exactly the same way.

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
from pathlib import Path

from easyvista_python_client import EasyvistaClient

# Streaming: the bytes go straight to disk, so a 32 MB attachment never sits
# in memory whole. Only the download streams -- see the Gotchas on upload.
with EasyvistaClient.from_env() as client:
    for document in client.list_documents("YOUR_RFC_NUMBER"):
        target = Path(document.filename or "attachment.bin")
        with target.open("wb") as sink:
            for chunk in client.stream_document(document, chunk_size=1024 * 1024):
                sink.write(chunk)
```

```python
from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    rfc = "YOUR_RFC_NUMBER"
    documents = client.list_documents(rfc)
    # DELETE requests/{rfc}/documents/{document_id} -- the default route.
    # Returns nothing on success. The Document itself is accepted too.
    client.delete_document(rfc, documents[0])
```

On a deployment that grants the other route instead, the document is addressed
by its id alone and the RFC is unused:

```python
from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    client.delete_document(None, "YOUR_DOCUMENT_ID", path_style="top_level")
```

## Gotchas

- `content` must be `bytes`. Read files in binary mode.
- **Upload cannot stream, and that is the API's constraint, not a gap here.**
  EasyVista takes an attachment as base64 inside a JSON body, so
  `add_document` has to materialise the whole payload before it can send
  anything. Only the download direction has a chunked form.
- **`stream_document` does not retry a mid-stream failure.** Opening the
  download is retried under the usual policy, but from the first chunk onwards
  the request is committed and a transport failure raises
  `EasyvistaConnectionError` instead of starting over — restarting would hand
  you bytes you already have. Nothing resumes a partly consumed stream, so
  either discard what you collected and stream again, or use
  `download_document`, which retries the whole fetch, when the file is small
  enough to buffer.
- `stream_document` is a generator: nothing is requested until you start
  iterating, so a `ValueError` for a missing URL or an `EasyvistaError` for a
  foreign one surfaces on the first step, not at the call. A non-positive
  `chunk_size` raises `ValueError` there too, rather than escaping as an httpx
  internal error.
- **Stopping early on the async client needs an explicit close.** After
  `break`ing out of an `async for`, the response stays checked out of the
  connection pool until the event loop's async-generator finalizer runs — a
  garbage-collection cycle later. Use
  `contextlib.aclosing(client.stream_document(doc))` or call `aclose()`, or a
  prefix-reading fan-out under a bounded `max_connections` will stall on
  connections it looks like it released. The sync client releases at the `break`.
- **Streamed bytes are not proof of instance origin.** An absolute URL in a
  response *body* is refused when it names another host, but an HTTP *redirect*
  off the instance is followed (signed-location hops need it); the credential is
  dropped on the foreign request, and the foreign bytes are returned as the
  attachment's content.
- It is `stream_document`, not `iter_document`: every `iter_*` method on this
  client iterates *records*, and this one iterates the bytes of one document.
- `download_document` raises `ValueError` only when **neither** `DDL_HREF` nor
  `HREF` is set. Guard on both (`download_href is None and href is None`), or
  catch the `ValueError`. Skipping a record because `download_href` alone is
  unset silently drops attachments the client would have fetched through
  `href`.
- A download URL pointing outside the configured instance raises
  `EasyvistaError`, on the streaming path as well as the buffered one.
  Downloads follow redirects (signed URLs are common), and httpx strips the
  `Authorization` header on a cross-origin redirect, so a foreign host would
  receive the request unauthenticated — refusing is deliberate.
- A 403 on an attachment still surfaces as `EasyvistaAuthError`; both binary
  paths reuse the same error mapping and the same retry policy as the JSON one.
- `filename` is derived, not always sent by the API. Fall back to a literal
  name before writing to disk.
- `delete_document(rfc, document_id)` sends the **nested** `DELETE
  requests/{rfc}/documents/{document_id}` by default. A second route,
  `DELETE documents/{id}`, also exists on this API; the verified instance
  denied it with 403, which is why `"nested"` is the default. Pass
  `path_style="top_level"` (or set
  `EasyvistaConfig(document_delete_path_style="top_level")`) on a deployment
  that grants the other one — there `rfc_number` is unused, so pass `None`.
  `document_id` must be non-blank in either style: a blank one would address
  the collection rather than one item, which `delete_document` refuses with
  `ValueError` before sending anything. You may pass the `Document` itself
  instead of its id.
- **A 403 on this API does not mean "denied".** It is also what an unknown
  path answers, so a 403 alone never distinguishes a route a profile blocks
  from one that does not exist. Both delete routes are declared in the
  instance's own OpenAPI document, so the 403 measured against the top-level
  one was a real denial — but that had to be established from the spec, not
  from the status code.
