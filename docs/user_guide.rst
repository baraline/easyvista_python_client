User Guide
==========

This guide walks through the EasyVista client's public surface with task-oriented examples. The
synchronous client is used throughout; the :ref:`sync-vs-async` section shows the asynchronous
equivalents, which mirror every method name.

.. note::

   Values such as the server host, ``account``, ``catalog_code``, the close ``status_guid``, and
   ``group_id`` are **instance-specific**. The values below are illustrative; replace them with the
   ones from your EasyVista instance.

Creating a client
------------------

Construct an :class:`~easyvista_python_client.EasyvistaConfig` and pass it to an
:class:`~easyvista_python_client.EasyvistaClient`. The client is a context manager and closes its
underlying HTTP connection on exit.

.. code-block:: python

   from easyvista_python_client import EasyvistaClient, EasyvistaConfig

   config = EasyvistaConfig(
       server="https://my.easyvista.com",
       account="12345",
       token="...",  # static Bearer access token
   )
   with EasyvistaClient(config) as client:
       ticket = client.get_ticket("I240101_0001")

Authentication
~~~~~~~~~~~~~~~

Authenticate with **either** a static Bearer access token (created in EasyVista under
*Admin → Access Management → Access Tokens*) **or** HTTP Basic credentials. When both are supplied,
the token wins.

.. code-block:: python

   # Bearer token
   EasyvistaConfig(server="https://my.easyvista.com", account="12345", token="...")

   # HTTP Basic
   EasyvistaConfig(server="https://my.easyvista.com", account="12345",
                   login="rest.user", password="...")

Configuration from the environment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:meth:`~easyvista_python_client.EasyvistaConfig.from_env` reads configuration from environment
variables, so credentials stay out of source. It reads, in order: ``EASYVISTA_URL`` (or
``EASYVISTA_SERVER``), ``EASYVISTA_ACCOUNT``, then ``EASYVISTA_TOKEN`` / ``EASYVISTA_TOKEN_FILE``
(a path to read the token from), else ``EASYVISTA_LOGIN`` + ``EASYVISTA_PASSWORD``.

.. code-block:: python

   from easyvista_python_client import EasyvistaClient, ev_equals_filter

   with EasyvistaClient.from_env() as client:
       search = ev_equals_filter("STATUS_EN", "Open")
       results = client.search_tickets(search=search, max_rows=50)

.. _sync-vs-async:

Synchronous vs asynchronous
---------------------------

:class:`~easyvista_python_client.AsyncEasyvistaClient` exposes the **same method names** as the
synchronous client, as coroutines. Use the synchronous client for scripts and CLI tools; use the
asynchronous client inside an event loop (FastAPI, aiohttp) or for concurrent fan-out.

.. code-block:: python

   import asyncio
   from easyvista_python_client import AsyncEasyvistaClient, EasyvistaConfig, ev_equals_filter

   async def main():
       async with AsyncEasyvistaClient(EasyvistaConfig.from_env()) as client:
           ticket = await client.get_ticket("I240101_0001")
           search = ev_equals_filter("STATUS_EN", "Open")
           async for t in client.iter_tickets(search=search, page_size=100):
               print(t.rfc_number)

   asyncio.run(main())

Working with tickets
---------------------

Tickets are EasyVista *requests*. Create one with a
:class:`~easyvista_python_client.PostRequest`. The minimum fields are catalog-specific and enforced
server-side; ``catalog_code`` + ``title`` work for incident catalogs. A missing mandatory field
raises :class:`~easyvista_python_client.EasyvistaValidationError` (see :ref:`error-handling`).

.. code-block:: python

   from easyvista_python_client import PostRequest

   ticket = client.create_ticket(
       PostRequest(
           catalog_code="INC_STANDARD",   # instance-specific catalog
           title="Printer down",
           description="The 3rd-floor printer is offline",
           origin=7,
           department_id=9,               # instance-specific; see "Departments and employees"
           urgency_id=8,                  # 4 = total outage, 7 = penalizing, 8 = invisible
           impact_id=28,                  # 17 = critical-prod, 21 = non-critical, 28 = test
           recipient_mail="user@example.com",
       )
   )
   print(ticket.rfc_number)

Create several tickets in one call with :meth:`~easyvista_python_client.EasyvistaClient.create_tickets`:

.. code-block:: python

   created = client.create_tickets([
       PostRequest(catalog_code="INC_STANDARD", title="Printer A down"),
       PostRequest(catalog_code="INC_STANDARD", title="Printer B down"),
   ])

Fetch, update, and close a ticket by its RFC number:

.. code-block:: python

   from easyvista_python_client import RequestUpdate

   fetched = client.get_ticket(ticket.rfc_number)
   client.update_ticket(ticket.rfc_number, RequestUpdate(description="Updated details"))

   # Close with your instance's "closed" status GUID.
   client.close_ticket(
       ticket.rfc_number,
       status_guid="{00000000-0000-0000-0000-000000000000}",
       delete_actions=1,
       comment="Resolved",
   )

Custom fields
~~~~~~~~~~~~~

EasyVista custom fields are prefixed ``e_``. Pass them through the ``custom_fields`` escape hatch on
any write model; keys are serialized to their ``e_*`` API names automatically.

.. code-block:: python

   PostRequest(catalog_code="INC_STANDARD", title="...", custom_fields={"e_location": "Paris"})

Actions (comments / followups)
-------------------------------

Actions are EasyVista's followup/comment analog. Add one with a
:class:`~easyvista_python_client.PostAction`; list a ticket's actions with
:meth:`~easyvista_python_client.EasyvistaClient.list_actions`.

.. code-block:: python

   from easyvista_python_client import PostAction

   client.create_action(
       ticket.rfc_number,
       PostAction(action_type_id=94, group_id=3, description="Triaged: on it"),
   )
   for action in client.list_actions(ticket.rfc_number):
       print(action.action_id, action.comment)

.. note::

   ``action_type_id`` and ``group_id`` are instance-specific — the ids above are
   placeholders, so look yours up on your own instance rather than copying them.
   Listing actions can be restricted by the access token's profile.

Assets
------

.. code-block:: python

   from easyvista_python_client import PostAsset, ev_equals_filter

   asset = client.create_asset(PostAsset(catalog_id=3153, asset_tag="LAPTOP-001"))
   one = client.get_asset(str(asset.asset_id))
   found = client.search_assets(search=ev_equals_filter("ASSET_TAG", "LAPTOP-001"), max_rows=50)

Documents
---------

Attach a file to a ticket (uploaded as base64 inside the JSON body) and list a ticket's documents.

.. code-block:: python

   from pathlib import Path

   pdf = Path("report.pdf")
   client.add_document(ticket.rfc_number, filename=pdf.name, content=pdf.read_bytes())
   attachments = client.list_documents(ticket.rfc_number)

.. note::

   Binary **download** and multipart upload are not implemented yet — see the GLPI-parity roadmap.

Exporting a ticket to Markdown
------------------------------

:meth:`~easyvista_python_client.EasyvistaClient.get_ticket_context` bundles a ticket with its
resolved narrative content — EasyVista returns most of that content as href references, so the
bundle follows them for you. :meth:`~easyvista_python_client.TicketContext.to_markdown` renders the
bundle as Markdown containing only content and human labels (no API URLs).

.. code-block:: python

   context = client.get_ticket_context(ticket.rfc_number)
   print(context.to_markdown())

   # The resolved pieces are also available directly:
   context.description   # plain/raw description text (HTML reduced to text by to_markdown)
   context.actions       # list[Action]
   context.documents     # list[Document]  (rendered as filenames)

The async client exposes the same method as a coroutine
(``context = await client.get_ticket_context(rfc)``).

Searching and pagination
-------------------------

``search_*`` methods accept a ``search`` string, ``fields``, ``sort``, ``max_rows`` (page size), and
``offset``.

The verified search grammar is:

- ``FIELD:"value"`` — exact match. ``~`` is a synonym: despite its appearance it is **exact match**,
  not "contains". EasyVista offers no substring operator.
- ``,`` — combines conditions: **OR** when every condition names the same field, **AND** across
  different fields. ``;`` is *not* a combinator.

.. warning::

   EasyVista does **not** reject a ``search`` expression it cannot parse — it ignores the filter and
   returns **every** record. And because ``,`` combines conditions, an unescaped value can silently
   widen a result set rather than fail. Build filters with the helpers, not f-strings:

.. code-block:: python

   from easyvista_python_client import ev_equals_filter, ev_in_filter

   search = ev_equals_filter("DEPARTMENT_CODE", user_supplied)   # DEPARTMENT_CODE:"ACME"
   if search is not None:                    # None when the value is blank
       result = client.search_departments(search=search)

   # "code is one of these" - ',' is OR within a single field
   client.search_departments(search=ev_in_filter("DEPARTMENT_CODE", ["ACME", "GLOBEX"]))

A value that cannot be expressed in the grammar raises ``ValueError``; use
:func:`~easyvista_python_client.is_safe_ev_value` to check first when you would rather skip the
filter than fail.

Not every returned field is searchable: some (e.g. ``CATALOG_GUID``) are silently ignored as search
conditions, so a filter on them matches everything. Verify a field filters before relying on it.

.. code-block:: python

   from easyvista_python_client import ev_equals_filter

   result = client.search_tickets(search=ev_equals_filter("STATUS_EN", "Open"), max_rows=50)
   print(result.record_count, "of", result.total_record_count)
   for ticket in result.records:
       print(ticket.rfc_number)

The result is a :class:`~easyvista_python_client.SearchResult`: it carries ``records``,
``record_count``, ``total_record_count``, ``href``, and ``next_url`` (the API's ``@next`` link), so
you always know whether more records exist than were returned.

To walk every matching record without managing offsets yourself, use the ``iter_*`` generators. They
follow the API's offset pagination until ``@next`` is exhausted or ``max_records`` is reached.

.. code-block:: python

   from easyvista_python_client import ev_equals_filter

   status_open = ev_equals_filter("STATUS_EN", "Open")
   for ticket in client.iter_tickets(search=status_open, page_size=100, max_records=1000):
       print(ticket.rfc_number)

   # Assets paginate the same way.
   tag_filter = ev_equals_filter("ASSET_TAG", "LAPTOP-001")
   for asset in client.iter_assets(search=tag_filter, page_size=100):
       print(asset.asset_tag)

The async client paginates with ``async for``:

.. code-block:: python

   from easyvista_python_client import ev_equals_filter

   async for ticket in client.iter_tickets(
       search=ev_equals_filter("STATUS_EN", "Open"), page_size=100
   ):
       print(ticket.rfc_number)

Counting and statistics
-----------------------

:meth:`~easyvista_python_client.EasyvistaClient.count_tickets` returns how many tickets match a
search with a single cheap call (it reads the envelope's ``total_record_count`` and fetches no
records).

.. code-block:: python

   from easyvista_python_client import ev_equals_filter

   open_count = client.count_tickets(search=ev_equals_filter("STATUS_EN", "Open"))

:meth:`~easyvista_python_client.EasyvistaClient.ticket_statistics` aggregates matching tickets into a
:class:`~easyvista_python_client.TicketStatistics` — a ``total`` plus per-dimension ``breakdowns``
(``{dimension: {label: count}}``). Dimensions are **raw EasyVista field names** — the reference-bearing
ones give human labels (``STATUS``, ``DEPARTMENT``, ``CATALOG_REQUEST``), and id-only ones
(``URGENCY``, ``IMPACT``) bucket by id. Custom ``e_*`` fields work too. ``created_since`` /
``created_until`` apply an inclusive window on the ticket creation date.

.. code-block:: python

   from easyvista_python_client import ev_equals_filter

   stats = client.ticket_statistics(
       search=ev_equals_filter("STATUS_EN", "Open"),
       dimensions=["STATUS", "DEPARTMENT"],   # omit to compute the defaults
       created_since="2025-01-01T00:00:00+00:00",
   )
   print(stats.total)
   print(stats.breakdowns["STATUS"])          # e.g. {"En cours": 12, "Résolu": 5}

.. note::

   ``ticket_statistics`` fetches the matching tickets to aggregate them and caps at
   ``max_records=100`` by default. Pass a larger value to widen the window or ``max_records=None`` to
   aggregate all matches. When the cap truncates, ``stats.total`` describes the fetched subset; use
   ``count_tickets`` for the true total (and compare the two to detect truncation).

Classifying and resolving fields
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:meth:`~easyvista_python_client.EasyvistaModel.classify_fields` partitions a record's fields into
four buckets: ``official``, ``custom`` (``e_*`` fields not declared by the model), ``available``
(``AVAILABLE_FIELD_n`` slots), and ``links`` (href-only sub-resource references). Use
:meth:`~easyvista_python_client.EasyvistaClient.resolve_memo` to fetch a link field's text.

.. code-block:: python

   ticket = client.get_ticket("I240101_0001")
   fields = ticket.classify_fields()
   print(fields.custom)          # {'E_CUSTOM_REF': '...', ...} instance-specific
   for name, href in fields.links.items():
       print(name, client.resolve_memo(href))   # Memo text (e.g. DESCRIPTION)

Any read model normalizes a reference field to an id + human label via ``reference(name)``:

.. code-block:: python

   ticket.reference("STATUS").display    # "En cours" (label when available)
   ticket.reference("URGENCY").display   # "1" (id-only fields fall back to the id)
   ticket.reference("URGENCY").id        # "1"

The async client exposes both methods as coroutines
(``await client.count_tickets(...)`` / ``await client.ticket_statistics(...)``).

Departments and employees
--------------------------

Resolve a department by a fuzzy, language-agnostic name, then pull its full context::

    from easyvista_python_client import EasyvistaClient

    with EasyvistaClient.from_env() as client:
        matches = client.find_departments("Acme Corp")   # "ACME-CORP", "acmecorp" also match
        dept = matches[0]

        ctx = client.get_department_context(dept.department_id)
        print(dept.name, ctx.ticket_count, len(ctx.employees))
        if ctx.manager:
            print("manager:", ctx.manager.last_name)

``get_department_context`` degrades gracefully: only the department itself is
required; employees, manager, note, tickets, statistics and assets each fall back to
``[]`` / ``None`` / ``0`` when a profile restriction blocks them.

A department's free-text note is a *Memo* sub-resource; read it directly with::

    note = client.get_department_comment(dept.department_id)   # "" if empty

Both clients also expose ``get_department`` / ``search_departments`` /
``iter_departments`` and ``get_employee`` / ``search_employees`` / ``iter_employees``,
plus provisional ``create_*`` / ``update_*`` writes (profile-gated).

.. _error-handling:

Error handling
--------------

All errors derive from :class:`~easyvista_python_client.EasyvistaError`, which carries
``status_code``, ``ev_code``, and ``ev_message``. Catch the specific subclass you care about.

.. code-block:: python

   from easyvista_python_client import (
       EasyvistaError,
       EasyvistaNotFound,
       EasyvistaValidationError,
   )

   try:
       client.create_ticket(PostRequest(catalog_code="INC_STANDARD"))  # missing mandatory title
   except EasyvistaValidationError as exc:
       # HTTP 590, EasyVista error_code 2013 — a rejected create. Deterministic, not retried.
       print("Validation failed:", exc.ev_message)
   except EasyvistaNotFound:
       print("No such record")
   except EasyvistaError as exc:
       print("EasyVista error:", exc.status_code, exc)

The hierarchy is: :class:`~easyvista_python_client.EasyvistaAuthError` (401/403),
:class:`~easyvista_python_client.EasyvistaNotFound` (404),
:class:`~easyvista_python_client.EasyvistaValidationError` (400 / HTTP 590 rejected create),
:class:`~easyvista_python_client.EasyvistaRateLimitError` (429),
:class:`~easyvista_python_client.EasyvistaServerError` (5xx), and
:class:`~easyvista_python_client.EasyvistaConnectionError` (transport / timeout).

End-to-end workflow
-------------------

Create a ticket, add a comment, close it, and read it back:

.. code-block:: python

   from easyvista_python_client import EasyvistaClient, PostAction, PostRequest

   with EasyvistaClient.from_env() as client:
       ticket = client.create_ticket(
           PostRequest(
               catalog_code="INC_STANDARD",
               title="VPN drops",
               description="Daily VPN drops at 11:00",
               origin=7,
               department_id=9,
               urgency_id=7,
               impact_id=21,
           )
       )
       client.create_action(
           ticket.rfc_number,
           PostAction(action_type_id=94, group_id=3, description="Investigating"),
       )
       client.close_ticket(
           ticket.rfc_number,
           status_guid="{00000000-0000-0000-0000-000000000000}",
           comment="Replaced the VPN concentrator",
       )
       resolved = client.get_ticket(ticket.rfc_number)
       print(resolved.rfc_number, resolved.status_id)
