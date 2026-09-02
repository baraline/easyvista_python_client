User Guide
==========

This guide walks through the EasyVista client's public surface with task-oriented examples. The
synchronous client is used throughout; the :ref:`sync-vs-async` section shows the asynchronous
equivalents, which mirror every method name.

.. note::

   Values such as the server host, ``account``, ``catalog_code``, the close ``status_guid``,
   ``group_id``, ``action_type_id``, ``department_id``, ``urgency_id`` and
   ``impact_id`` are **instance-specific**. The values below are illustrative; replace them with
   the ones from your EasyVista instance —
   :meth:`~easyvista_python_client.EasyvistaClient.describe_instance` finds them
   in one call.

   ``origin`` is the exception: the vendor documents it as a string naming the
   channel (``"Phone"``, ``"Email"``), so it is the one create field with a
   portable, human-readable form and needs no discovery.

Creating a client
------------------

Construct an :class:`~easyvista_python_client.EasyvistaConfig` and pass it to an
:class:`~easyvista_python_client.EasyvistaClient`. The client is a context manager and closes its
underlying HTTP connection on exit.

.. code-block:: python

   from easyvista_python_client import EasyvistaClient, EasyvistaConfig

   config = EasyvistaConfig(
       server="https://my.easyvista.com",
       account="12345",  # the instance id in the API root -- NOT a username
       token="...",  # static Bearer access token
   )
   with EasyvistaClient(config) as client:
       ticket = client.get_ticket("I240101_0001")

.. important::

   ``account`` is **not a user account**. It is the EasyVista *instance*
   identifier -- a number -- that forms the final path segment of the API root,
   ``https://host/api/{version}/{account}``. Nothing authenticates with it; that
   is the job of ``token``, or ``login`` + ``password``. If your instance URL
   already reads ``https://my.easyvista.com/api/v1/12345``, then ``12345`` is
   your ``account``.

Authentication
~~~~~~~~~~~~~~~

Authenticate with **either** a static Bearer access token (created in EasyVista under
*Admin → Access Management → Access Tokens*) **or** HTTP Basic credentials. When both are supplied,
the token wins.

.. code-block:: python

   # Bearer token
   EasyvistaConfig(server="https://my.easyvista.com", account="12345", token="...")

   # HTTP Basic -- note that ``login`` and ``account`` are unrelated values
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
       # Status ids are instance-specific -- read yours from a ticket's STATUS_ID.
       search = ev_equals_filter("STATUS_ID", 3)
       results = client.search_tickets(search=search, max_rows=50)

.. _first-steps:

First steps on your instance
----------------------------

Almost every value a write needs — the catalog, the status GUID, the action
type ids, the group ids — is configured on your EasyVista deployment and is not
portable from anyone else's. This section is the order to discover them in.
Steps 1 to 6 are reads and create nothing.

The short version is one call:

.. code-block:: python

   from easyvista_python_client import EasyvistaClient

   with EasyvistaClient.from_env() as client:
       profile = client.describe_instance()
       print(profile.version, len(profile.spec_paths))

       # Read the gaps FIRST. A total outage looks exactly like a bare
       # instance except that every gap is named here.
       for gap, reason in profile.unavailable.items():
           print("gap:", gap, reason)

       for status in profile.references["STATUS"]:
           # .guid is what close_ticket and set_status address a status by.
           print(status.id, status.label, status.guid)

That is :meth:`~easyvista_python_client.EasyvistaClient.describe_instance`; see
the ``easyvista-instance-discovery`` skill for the whole surface. The long
version, and what it is doing under the covers:

1. **Prove the connection** and get one real record.
2. **Read the ids off it.** ``reference(name)`` for id + label,
   ``classify_fields()`` for the instance's own ``e_*`` columns and its
   href-only memo links.
3. **Find a catalog you can create against** — see
   `Finding your catalog_code or catalog_guid`_. This is the step that most
   often needs an administrator.
4. **Find the action type ids**, and confirm which means "internal" with that
   administrator; the ids are discoverable, the meaning is not.
5. **Find the close status GUID.** It is a sub-key of the nested ``STATUS``
   object and is not searchable.
6. **Pin what you found, in your own configuration.**
7. **Do the first write on a throwaway, then re-read.**

Keep the reads in steps 1–2 **unprojected**. Passing ``fields=`` narrows a
record to the columns you name and drops the nested ``STATUS`` /
``DEPARTMENT`` / ``CATALOG_REQUEST`` objects that carry the labels and the GUID
(measured on one instance; it may not generalise). Projection is worth reaching
for later, when you know which columns you want — the default search projection
returns ``TITLE`` empty, for instance, so a listing wants
``fields=["RFC_NUMBER", "TITLE"]``.

.. code-block:: python

   from easyvista_python_client import EasyvistaClient

   with EasyvistaClient.from_env() as client:
       # 1. Prove the connection, and get one real record.
       probe = client.search_tickets(max_rows=1)
       sample = client.get_ticket(probe.records[0].rfc_number)

       # 2. The ids this instance uses, with their human labels.
       for name in ("STATUS", "DEPARTMENT", "URGENCY", "IMPACT", "CATALOG_REQUEST"):
           ref = sample.reference(name)
           print(name, "->", ref.id, ref.display)

       buckets = sample.classify_fields()
       print("instance columns:", sorted(buckets.custom))
       print("memo links:", sorted(buckets.links))

       # 5. The close GUID -- a sub-key of the nested STATUS object, present
       #    only on an unprojected read. Read it off a ticket already in the
       #    state you want to reach.
       status = (sample.model_extra or {}).get("STATUS") or {}
       print("status:", status.get("STATUS_ID"), status.get("STATUS_GUID"))

.. warning::

   ``reference("CATALOG_REQUEST").id`` is the catalog's ``SD_CATALOG_ID``, and
   :class:`~easyvista_python_client.PostRequest` accepts ``catalog_guid`` or
   ``catalog_code`` and **no id field at all**. Step 2 tells you which catalog
   a ticket used; it does not give you a value you can send. See
   `Finding your catalog_code or catalog_guid`_.

   **Never infer "closed" from a status id.** They are per-instance: on the
   verified instance ``8`` is *Clôturé* and ``12`` is *En cours* — adjacent
   numbers, opposite meanings. ``end_date_ut`` is the portable signal: empty on
   an open ticket, stamped on a closed one.

Step 6 — **pin what you found in your own configuration.** This package holds
no registry of instance values and never will: they belong to your deployment,
not to the library. Pass them the way you pass any other application setting,
preferring, in order, a method or constructor keyword, a field on your own
configuration object, a module constant a caller can override, and an
environment variable only as a last resort.
:meth:`~easyvista_python_client.EasyvistaConfig.from_env` is a convenience for
credentials in a script, not a configuration mechanism for a library you have
installed into an application.

Step 7 — **do the first write against a throwaway ticket, and re-read it.** Set
``external_reference`` on the create: a rejected create may still have created
the row, and that marker survives the failed insert and is searchable, so it is
what lets you reconcile instead of retrying and duplicating. And re-read after
every write: this API answers HTTP 200 and drops fields in silence, so a 200 is
not a receipt.

.. _sync-vs-async:

Synchronous vs asynchronous
---------------------------

:class:`~easyvista_python_client.AsyncEasyvistaClient` exposes the **same method names** as the
synchronous client, as coroutines. Use the synchronous client for scripts and CLI tools; use the
asynchronous client inside an event loop (FastAPI, aiohttp) or for concurrent fan-out.

.. note::

   The two aggregate readers — :meth:`~easyvista_python_client.AsyncEasyvistaClient.get_ticket_context`
   and :meth:`~easyvista_python_client.AsyncEasyvistaClient.get_department_context` — issue their
   independent sub-requests concurrently, so they are substantially faster than their synchronous
   twins rather than merely non-blocking (measured on a ticket with 19 actions: 13.4s sync, 5.3s
   async). Peak in flight is a handful of requests: at most 8 concurrent action-body resolutions for
   a ticket, 7 branches for a department.

   Two practical consequences. ``max_retries`` defaults to ``0``, so raise it if you fan out — a
   429 from a rate-limited instance is not retried otherwise. And share one open client across your
   tasks rather than opening one per task: ``aclose()`` is terminal and is not reference-counted, so
   the first ``async with`` block to exit closes the client for everyone still using it.

   ``create_tickets`` is deliberately **not** concurrent. Those are writes, EasyVista assigns the
   RFC number server-side, and a failure part-way through a concurrent batch would leave you unable
   to say which tickets exist.

.. code-block:: python

   import asyncio
   from easyvista_python_client import AsyncEasyvistaClient, EasyvistaConfig, ev_equals_filter

   async def main():
       async with AsyncEasyvistaClient(EasyvistaConfig.from_env()) as client:
           ticket = await client.get_ticket("I240101_0001")
           search = ev_equals_filter("STATUS_ID", 3)
           async for t in client.iter_tickets(search=search, page_size=100):
               print(t.rfc_number)

   asyncio.run(main())

Working with tickets
---------------------

Tickets are EasyVista *requests*. Create one with a
:class:`~easyvista_python_client.PostRequest`. The subject is the only part the vendor documents as
required, and it is named either by ``catalog_guid`` — the form the vendor documents as
**preferred** — or by ``catalog_code``; a body carrying neither is refused locally, before any
request goes out. Beyond the subject, which fields a catalog insists on is per-catalog
configuration enforced server-side, and a missing one raises
:class:`~easyvista_python_client.EasyvistaValidationError` (see :ref:`error-handling`) with a
message that names no field. The fuller body below is a hedge against that: it was accepted on
every catalog tried on one instance, which makes it a safe default rather than an API requirement.

.. code-block:: python

   from easyvista_python_client import PostRequest

   ticket = client.create_ticket(
       PostRequest(
           # Or catalog_guid="{...}", the vendor's preferred subject identifier.
           # GET /catalog-requests is 403 on a restricted profile -- that is a
           # grant to ask for, not a limit. See "Finding your catalog" below.
           catalog_code="INC_STANDARD",   # instance-specific catalog
           title="Printer down",
           description="The 3rd-floor printer is offline",
           # The vendor documents `origin` as a STRING naming the channel
           # ("Phone", "Email") -- the one create field with a portable,
           # human-readable form, so it needs no per-instance discovery. An
           # int id is also accepted (measured on one instance; it may not
           # generalise) and passes through unchanged if you prefer one.
           origin="Phone",
           department_id=9,               # instance-specific; see "Departments and employees"
           urgency_id=8,                  # instance-specific placeholder -- see the note below
           impact_id=28,                  # instance-specific placeholder -- see the note below
           recipient_mail="user@example.com",
       )
   )
   print(ticket.rfc_number)

.. note::

   ``department_id``, ``urgency_id`` and ``impact_id`` are ids, and what each id
   *means* is per-instance configuration: nothing above is a portable legend, and an id copied
   from this page is not guaranteed to name anything on your deployment. Read yours off a ticket
   that already carries the value you want — ``ticket.reference("URGENCY")`` and
   ``ticket.reference("IMPACT")`` yield the id, plus the human label when the instance projects
   one and ``None`` when it does not (``.display`` falls back to the id) — or ask your EasyVista
   administrator.

Finding your catalog_code or catalog_guid
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The subject is the one part of a create the vendor documents as required, and
it is the one field you cannot read off a ticket you already have.
``ticket.reference("CATALOG_REQUEST")`` resolves to the catalog's
``SD_CATALOG_ID`` and its title — useful for display, useless for a create,
because :class:`~easyvista_python_client.PostRequest` accepts ``catalog_guid``
and ``catalog_code`` and **no id field at all**. Reading a ticket tells you
*which* catalog it used; it does not give you a value you can send.

:meth:`~easyvista_python_client.EasyvistaClient.discover` reads the catalog
table for you and puts the code where you need it:

.. code-block:: python

   for catalog in client.discover("CATALOG_REQUEST"):
       # .code is what PostRequest(catalog_code=...) takes.
       print(catalog.code, catalog.label, catalog.path)

Three routes carry the catalog, and all three are declared in the instance's
own OpenAPI (read from ``GET {api_root}/swagger``, 2026-08-27, EasyVista 2025.3
— authoritative for that deployment): ``GET /catalog-requests`` (the list, which
``discover`` uses), ``GET /catalog-requests-paths`` (the same table addressed by
catalog path) and ``GET /catalog-requests/{catalog_id}`` (the item).

On the restricted profile this package was verified against, all three answer
**403** (measured on one instance; it may not generalise). That is a profile
denial, not a missing route — the route is declared in that same deployment's
spec. **If you cannot read your catalogs, ask your EasyVista administrator to
authorize the REST profile for ``catalog-requests``**; it is a grant, not a
limitation of the API. ``discover`` degrades to sampling meanwhile, which
returns only the catalogs already used by a ticket you can see; and
``describe_instance()`` records the denial in ``.unavailable`` rather than
returning a silently empty list.

.. note::

   **``catalog_guid`` is not discoverable at all.** No route returns one — the
   ``/catalog-requests`` response schema declares ``CODE``, ``SD_CATALOG_ID``,
   ``TITLE_EN`` and ``CATALOG_REQUEST_PATH``, and no ``CATALOG_GUID``. The
   vendor documents ``catalog_guid`` as the *preferred* identifier and
   ``close_ticket`` accepts one; you simply cannot read one back, so build with
   ``catalog_code``. Those column names come from the instance's OpenAPI
   *response schemas*, which are example-derived and illustrative only (see
   ``docs/vendor-api-reference.md``) — a different deployment may name them
   otherwise.

   ``SD_CATALOG_PATH_EN`` is a top-level column *of the catalog-requests-paths
   table*, so it filters there. The similarly named ``SD_CATALOG_PATH`` on a
   **ticket** is a denormalized display column and is silently ignored as a
   search condition.

With no route access at all, the remaining option is to ask the administrator
for the code or GUID of each catalog you must create against, and pin those in
your configuration the way you pin any other instance-specific value.

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

   # Every argument is optional -- this sends the close with no status of its
   # own, letting the instance decide where the ticket lands.
   client.close_ticket(ticket.rfc_number)

   # Verify by re-reading, not by the return value: end_date_ut is empty on an
   # open ticket and stamped on a closed one, and is more portable than any
   # status id (on the verified instance 8 is "Clôturé" and 12 is "En cours").
   assert client.get_ticket(ticket.rfc_number).end_date_ut is not None

.. warning::

   Where a ticket lands when ``status_guid`` is omitted is **not established by
   this package**. The client simply omits the key; what the server does with a
   status-less ``closed`` body has never been measured against a live instance
   here, and the behaviour is not recorded in ``docs/vendor-api-reference.md``.
   Try it on a throwaway ticket and re-read before you build on it. Passing
   your instance's closed ``status_guid`` explicitly is the form this package's
   live suite actually exercises.

.. note::

   A ``description`` supplied at create time was not readable back through either
   Memo field on the instance this client was verified against.
   ``RequestUpdate.description`` writes the ticket's ``COMMENT`` Memo, not
   ``DESCRIPTION`` — read it back with ``TicketContext.comment`` (see
   :meth:`~easyvista_python_client.EasyvistaClient.get_ticket_context`).

Custom fields
~~~~~~~~~~~~~

EasyVista custom fields are prefixed ``e_``. Pass them through the ``custom_fields`` escape hatch on
any write model; keys are serialized to their ``e_*`` API names automatically.

.. code-block:: python

   PostRequest(catalog_code="INC_STANDARD", title="...", custom_fields={"e_location": "Paris"})

There are **two** escape hatches, and they are not interchangeable. ``custom_fields`` only ever
emits ``e_``-prefixed keys, so it cannot reach an *official* column this package declines to
declare. ``extra_payload`` — also on every write model — is the un-prefixed one: whatever you put
in it reaches the wire exactly as written.

.. code-block:: python

   from easyvista_python_client import RequestUpdate

   # An official column this model does not declare, sent anyway.
   RequestUpdate(title="New title", extra_payload={"URGENCY_ID": 4})

Three properties are worth knowing before you reach for it:

* It is merged **last and wins**. A key that matches a declared field, or a key ``custom_fields``
  produced, replaces it — matched **ignoring case**. So
  ``RequestUpdate(impact_id=8, extra_payload={"IMPACT_ID": 4})`` sends ``IMPACT_ID`` alone, not
  both. The case-insensitive match is what the vendor documents for the ticket *create* body; the
  other write bodies are assumed to match it, which is the safe assumption in either direction.
* It **bypasses this model's validation entirely**. Nothing checks the name, the type or a length
  cap; a typo reaches the server as a typo.
* Every field these models decline to declare rests on behaviour measured against a single
  instance. ``extra_payload`` is the supported way past those measurements on a deployment that
  behaves differently — including for the fields :class:`~easyvista_python_client.RequestUpdate`
  deliberately omits. Re-read the record afterwards: on this API a write can return HTTP 200,
  apply one field and drop another in silence.

Actions (comments / followups)
-------------------------------

Actions are EasyVista's followup/comment analog. Add one with a
:class:`~easyvista_python_client.PostAction`; list a ticket's actions with
:meth:`~easyvista_python_client.EasyvistaClient.list_actions`.

.. code-block:: python

   from easyvista_python_client import PostAction

   # An action is born OPEN, and an open action's text is not displayed --
   # so create and end are a pair. For a comment, use create_task instead.
   before = {a.action_id for a in client.list_actions(ticket.rfc_number)}
   client.create_action(
       ticket.rfc_number,
       PostAction(action_type_id=94, group_id=3, description="Triaged: on it"),
   )
   after = client.list_actions(ticket.rfc_number)
   created = [a for a in after if a.action_id not in before]
   client.end_action(
       ticket.rfc_number,
       action_id=created[0].action_id,
       start_date="01/09/2026 17:00:00",
       end_date="01/09/2026 17:15:00",
       elapsed_time=15,
   )

.. note::

   ``action_type_id`` and ``group_id`` are instance-specific — the ids above are
   placeholders, so look yours up on your own instance rather than copying them.
   Listing actions can be restricted by the access token's profile. An action's
   ``COMMENT`` field never carries the note text supplied as ``description`` —
   read it back with :meth:`~easyvista_python_client.EasyvistaClient.get_action`
   plus :meth:`~easyvista_python_client.EasyvistaClient.resolve_memo` (or let
   :meth:`~easyvista_python_client.EasyvistaClient.get_ticket_context` resolve it
   for you onto ``Action.description``).

Reading a whole action log
~~~~~~~~~~~~~~~~~~~~~~~~~~

:meth:`~easyvista_python_client.EasyvistaClient.list_actions` returns **one
page**. A ticket carrying more actions than ``default_max_rows`` is truncated
with no error, and the call discards the envelope's total, so nothing in the
result reveals it. That cap is easier to hit than it looks: a freshly created
ticket already carries about a dozen workflow-generated actions before anyone
has commented. Use
:meth:`~easyvista_python_client.EasyvistaClient.iter_actions` when the complete
log matters — a comment sync, an export, an audit — and keep ``list_actions``
for the cheap "show me the recent ones" read.

.. code-block:: python

   for action in client.iter_actions(ticket.rfc_number):
       print(action.action_id, action.action_label_fr)

.. warning::

   Unlike :meth:`~easyvista_python_client.EasyvistaClient.iter_tickets`, the
   offset pagination behind ``iter_actions`` has **not** been measured against a
   live instance — it assumes the ``offset``/``@next`` contract every other
   search on this API follows. If your instance's ``actions`` endpoint ignores
   ``offset``, page two repeats page one and the sweep will not end on its own.
   Bound it with ``max_records`` the first time you run it against a ticket
   whose action count you do not already know.

Two stored text fields, but only one is displayed
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

An action stores **two separate text fields**, ``description`` and
``comment``, each addressable afterwards as its own memo
(``actions/{id}/description``, ``actions/{id}/comment``).
:class:`~easyvista_python_client.PostAction` writes both, and both persist from
a single create — verified live on 2026-08-28, each reading back with exactly
the text sent.

They are independent in storage, not in visibility.

.. warning::

   **A non-empty** ``description`` **hides** ``comment`` **from every reader.**
   The UI shows one text field per action, under a header reading "comment or
   description": it renders ``DESCRIPTION`` when that memo has text, and falls
   back to ``COMMENT`` only when it is empty. Measured in the UI on
   2026-09-01 against one instance (Service Manager 2025.3) — one instance,
   one date, so it may not generalise.

   Text written to ``comment`` beside a populated ``description`` is stored,
   reads back cleanly through the API, and is never shown to anyone. There is
   no error and no dropped field, so nothing signals the loss. ``comment`` is
   not the private channel; it is the unread one. Visibility is carried by the
   action **type** instead — see :ref:`tasks-vs-actions`.

.. code-block:: python

   from easyvista_python_client import PostAction

   PostAction(
       action_type_id=94,                      # instance-specific
       # The field the history renders. Anything a person must read goes here.
       description="The text a reader will actually see.",
       # `comment` is a second memo on the same record. Set it only when you
       # deliberately leave `description` empty, or mean it as API-only
       # metadata -- with a description present, nobody reads it.
   )

To fix or extend text that is already posted, write
:class:`~easyvista_python_client.ActionUpdate` with ``description``: it applies
to an action that has already ended, and the new text renders (measured in the
UI on 2026-09-01, one instance).

.. _tasks-vs-actions:

Tasks vs. actions: use a task for a comment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A task and an action are the **same underlying record**. They differ only in
the state they are born in, and that difference decides whether a reader ever
sees the text:

.. list-table::
   :header-rows: 1
   :widths: 26 37 37

   * - ..
     - :meth:`~easyvista_python_client.EasyvistaClient.create_action`
     - :meth:`~easyvista_python_client.EasyvistaClient.create_task`
   * - endpoint
     - ``POST requests/{rfc}/actions``
     - ``POST requests/{rfc}/tasks``
   * - body shape
     - wrapped
     - flat at the root
   * - born
     - **open** — work still to do
     - **ended** — work reported
   * - in the UI
     - a pending row, text **not** shown
     - a history entry **with** its text
   * - needs ending after
     - yes
     - no
   * - ``parent_action_id``
     - resolved implicitly; needed when 0 or 2+ actions are open
     - not needed
   * - use it for
     - work someone must still do
     - **comments**

.. code-block:: python

   from easyvista_python_client import PostTask

   client.create_task(
       ticket.rfc_number,
       PostTask(
           action_type_id=95,           # instance-specific: the internal type
           group_id=3,                  # instance-specific
           description="Internal working note.",
       ),
   )

Verified live on 2026-08-28: tasks came back with ``END_DATE_UT`` and
``STATUS_ID_ON_TERMINATE`` already set, and their text appeared in the ticket
history.

.. warning::

   **Creating an action and stopping there loses nothing but shows nothing.**
   The text is stored; the row simply renders without it until the action is
   ended. Finish it with :meth:`~easyvista_python_client.EasyvistaClient.end_action`.
   An earlier revision of this guide said every documented form returned
   ``590 Action not found`` and suggested raising it with your administrator.
   That was wrong: the 590 is what the route answers when no *open* action
   matches, such as replaying it against one already ended. For comments, use a
   task and the question does not arise.

.. code-block:: python

   client.end_action(
       "YOUR_RFC_NUMBER",
       action_id=YOUR_ACTION_ID,
       start_date="01/09/2026 17:00:00",
       end_date="01/09/2026 17:15:00",
       elapsed_time=15,
   )

Measured 2026-09-01 on one instance (one instance, one date, so it may not
generalise): ``end_date`` takes your instance's ``DATE_FORMAT`` --
``dd/mm/yyyy hh:mm:ss`` there, and ISO 8601 is refused -- ``elapsed_time`` is
minutes, and you should send ``start_date`` explicitly because a derived one
comes back early by your instance's UTC offset.

.. warning::

   **Ending a workflow action advances the workflow.** On the same instance and
   date, ending a fresh ticket's open type-20 *Traitement Operation* action
   moved the **ticket** from *En cours* to *Résolu* and spawned a new open
   type-1 *Validation Self Service* action (2 tickets, 2/2); a control showed
   ending a type-94 action the caller had created changed neither the status
   nor the action count. Ending your own action is inert, ending a workflow
   step is not. Omitting ``action_id`` ends **every** open action, which on a
   ticket whose only open one is its workflow step means resolving it.

.. warning::

   **Neither text channel is inherently private.** The item-level action record
   carries 88 columns and none of them is a public/private boolean, so the API
   enforces no visibility distinction and there is no flag to set or read
   (measured on one instance, 2026-08-28 — it may not generalise).

   Visibility is a property of the action **type**. On the verified instance
   type 94 is ``Commentaire [Public]`` / ``Customer Comment`` and type 95 is
   ``Note Interne [Privé]`` / ``Internal Note`` (measured on one instance,
   2026-08-28). Those ids are per-deployment: yours will differ.

**There is no reference table, and the ids are still discoverable.** Both
halves matter, and an earlier revision of this guide asserted the first and
then denied the second a dozen lines later:

* The instance's own OpenAPI declares **no** ``action-types`` route at all
  (read from ``GET {api_root}/swagger``, 2026-08-27, EasyVista 2025.3 —
  authoritative for that deployment). ``GET action-types`` answers **403**, but
  on this API a forbidden path and an unknown one both answer 403, so that
  response never told you which it was. There is nothing to enumerate and
  nothing for an administrator to unblock here.
* Every action record nevertheless carries its own ``ACTION_TYPE_ID`` beside
  translated ``ACTION_LABEL_*`` columns, so the types an instance actually uses
  are recoverable from the data:

.. code-block:: python

   for found in client.discover("ACTION_TYPE"):
       print(found.id, found.label, found.count)

That is :meth:`~easyvista_python_client.EasyvistaClient.discover`, which samples
records for you; ``client.describe_instance()`` does every reference at once.
Sampling by hand is the same thing spelled out::

   for action in client.iter_actions(ticket.rfc_number):
       print(action.action_type_id, action.label, action.done_by_id)

Most of what comes back is workflow-generated steps rather than human notes;
those carry an empty ``DONE_BY_ID``.

.. note::

   **Two bracket conventions appear in ``ACTION_LABEL_*`` and they mean
   opposite things.**

   * A label wrapped **entirely** in brackets, echoing another language's text
     (``ACTION_LABEL_EN='[Analyse et résolution]'``), is an *untranslated
     placeholder*: on a single-language instance the unpopulated language
     columns echo the default-language text in brackets. It carries no
     visibility meaning, and
     :func:`~easyvista_python_client.localized_label` discards it.
   * A bracketed **suffix** on otherwise distinct text, with genuine
     translations in the sibling columns — ``ACTION_LABEL_FR='Commentaire
     [Public]'`` beside ``ACTION_LABEL_EN='Customer Comment'`` — is a real
     marker, written by whoever configured the instance.

   The test is whether the siblings are real translations or brackets, not
   whether brackets are present. Conflating the two once deleted a true finding
   from this documentation.

   A marker is still a **convention on one deployment**, not an API feature.
   Treat it as a strong hint while matching ids to meanings, and confirm the
   mapping with whoever administers the instance before relying on it for
   anything that must not leak.

So: discover the ids, confirm them with your EasyVista administrator, pin them
in your own configuration — a module constant, a settings field, whatever your
application already uses — and pass the one you want. For a comment, pass it to
``create_task`` rather than ``create_action``; see :ref:`tasks-vs-actions` for
why.

.. code-block:: python

   from easyvista_python_client import PostTask

   # Read off THIS instance and confirmed with its administrator. 94/95 are
   # what the verified instance uses; they are not portable.
   PUBLIC_COMMENT_TYPE_ID = 94
   INTERNAL_NOTE_TYPE_ID = 95

   client.create_task(
       ticket.rfc_number,
       PostTask(
           action_type_id=INTERNAL_NOTE_TYPE_ID,
           group_id=3,                     # instance-specific
           description="Internal note",
       ),
   )

Assets
------

.. code-block:: python

   from easyvista_python_client import PostAsset, ev_contains_filter, ev_equals_filter

   asset = client.create_asset(PostAsset(catalog_id=3153, asset_tag="LAPTOP-001"))
   one = client.get_asset(str(asset.asset_id))
   found = client.search_assets(search=ev_equals_filter("ASSET_TAG", "LAPTOP-001"), max_rows=50)

   # On the instance this package was characterized against, a bare '~' is exact
   # match, identical to ':' -- substring search needs an explicit wildcard, which
   # ev_contains_filter appends for you: ASSET_TAG~"*LAPTOP*". The vendor documents
   # '~' as plain Contains, so pass wildcard=None if that is your deployment.
   # The value itself must carry no '_' or '[' (metacharacters to '~' itself, at
   # every wildcard= setting) and no '*'/'%' while a wildcard is being appended;
   # ev_contains_filter raises ValueError rather than widening the match silently.
   # So "LAPTOP_01" raises; use ev_equals_filter for an exact match on a tag
   # containing '_'. See "Searching and pagination" below.
   laptops = client.search_assets(search=ev_contains_filter("ASSET_TAG", "LAPTOP"), max_rows=50)

Documents
---------

Attach a file to a ticket (uploaded as base64 inside the JSON body) and list a ticket's documents.

.. code-block:: python

   from pathlib import Path

   pdf = Path("report.pdf")
   client.add_document(ticket.rfc_number, filename=pdf.name, content=pdf.read_bytes())
   attachments = client.list_documents(ticket.rfc_number)
   content = client.download_document(attachments[0])
   Path("downloaded.pdf").write_bytes(content)

.. note::

   ``download_document`` accepts a :class:`~easyvista_python_client.Document` or a raw
   href. An absolute URL is followed only when its scheme and host match the configured
   ``server`` — every request carries the instance's Bearer token, so a URL naming
   another host is refused rather than followed. Multipart upload is still not
   implemented; uploads go as base64 inside the JSON body.

Streaming a large attachment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:meth:`~easyvista_python_client.EasyvistaClient.stream_document` yields the same bytes in
chunks instead of returning them in one object, so a large attachment never has to exist
in memory whole. It accepts exactly what ``download_document`` accepts and resolves the
URL the same way, including the same refusal of a URL outside the configured instance.

.. code-block:: python

   from pathlib import Path

   with Path("downloaded.pdf").open("wb") as sink:
       for chunk in client.stream_document(attachments[0], chunk_size=1024 * 1024):
           sink.write(chunk)

The name is ``stream_`` rather than ``iter_`` because every ``iter_*`` method on the
client iterates *records*; this one iterates the bytes of a single document.

The async client streams with ``async for`` — like the ``iter_*`` methods and unlike
every other method on it, ``stream_document`` is not awaited. ``aclient`` below is an
:class:`~easyvista_python_client.AsyncEasyvistaClient`; the two surfaces are not
interchangeable behind one name, because the synchronous ``stream_document`` returns a
plain iterator:

.. code-block:: python

   async def save(aclient, document):
       with Path("downloaded.pdf").open("wb") as sink:
           async for chunk in aclient.stream_document(document):
               sink.write(chunk)

.. note::

   **Stopping early on the async surface needs an explicit close.** If you
   ``break`` out of the ``async for`` — sniffing a magic number, hashing the
   first block, aborting on a size check — the response stays checked out of the
   connection pool until the event loop's async-generator finalizer runs, which
   is a garbage-collection cycle away (measured). Use
   ``contextlib.aclosing(client.stream_document(doc))``, or call ``aclose()``
   yourself, so the connection is released at the ``break``. The synchronous
   surface releases it immediately by refcounting and needs nothing.

.. note::

   **Only the download streams.** There is no streaming upload, and it is not an
   oversight: EasyVista takes an attachment as base64 inside a JSON body, so
   ``add_document`` has to materialise the whole payload before it can send anything.
   The asymmetry belongs to the API, not to this client.

.. warning::

   **A mid-stream failure is not retried.** Opening the download is retried under the
   usual policy, but from the first chunk onwards the request is committed: a transport
   failure raises :class:`~easyvista_python_client.EasyvistaConnectionError` rather than
   starting over, because starting over would hand you bytes you already have. Nothing
   resumes a partly consumed stream, so if you must survive a mid-stream failure, decide
   for yourself whether to discard what you collected and stream the document again.
   ``download_document`` retries the whole fetch and is the simpler choice when the file
   is small enough to buffer.

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

By default the bundle resolves the two Memo fields EasyVista populates out of the box,
``description`` and ``comment``. Which memo actually carries a ticket's body is per-deployment
configuration, so ``memo_fields`` lets you name the ones your instance uses; every resolved memo
lands in ``context.memos``, keyed by the name you asked for, and a memo requested this way is
rendered by ``to_markdown`` like any other body text.

.. code-block:: python

   context = client.get_ticket_context(ticket.rfc_number, memo_fields=("description", "solution"))
   context.memos["solution"]   # the resolved text, or None if the instance has no such memo

.. warning::

   Pass a tuple or list, never a bare string. ``str`` satisfies ``Sequence[str]``, so
   ``memo_fields="solution"`` type-checks and then iterates its letters, issuing one nonsense
   request per character instead of the one you meant.

.. note::

   By default ``get_ticket_context`` also resolves each action's note text
   (``resolve_action_bodies=True``), which costs two extra HTTP requests per
   action — roughly 22 on a ticket carrying this instance's ~11-action
   workflow baseline. Pass ``resolve_action_bodies=False`` to skip this and
   fetch only the action list.

The async client exposes the same method as a coroutine
(``context = await client.get_ticket_context(rfc)``) and issues those requests
concurrently — see :ref:`sync-vs-async`.

.. note::

   **Which heading a ticket's body gets.** ``to_markdown`` titles a block by the
   role it plays, not by the EasyVista field it came from. A ticket's body does
   not always arrive in ``DESCRIPTION``: which memo carries it is per-deployment
   configuration and is not reliably detectable at runtime, and
   ``RequestUpdate.description`` writes ``COMMENT`` on any instance. So when only
   one of the two memos has text, it is
   the body and is rendered under ``## Description`` whichever field it came
   from; when both have text the distinction is real and each keeps its own
   ``## Description`` / ``## Comment`` heading. The same rule covers a memo asked
   for through ``memo_fields``: when neither default memo has text, a single
   populated entry in ``context.memos`` becomes the body under ``## Description``,
   and several each get a heading derived from the name you requested
   (``## Solution``). The ``context.description`` and ``context.comment``
   attributes are unaffected and still name their source memo.

Searching and pagination
-------------------------

``search_*`` methods accept a ``search`` string, ``fields``, ``sort``, ``max_rows`` (page size), and
``offset``.

The verified search grammar is:

- ``FIELD:"value"`` — exact match.
- ``~`` — the vendor documents it as plain **Contains** (Oxygen 1.7+), one word, no example, no
  wildcard named. **On the instance this package was characterized against it is a pattern
  operator instead** (measured live 2026-08-17; one deployment, may not generalise): it acts as
  one only with an *explicit* wildcard in the value, and ``*`` and ``%`` both expand there
  (``~"I26081*"`` matched 32 rows, ``~"*260817*"`` matched 33, ``~"*0001"`` matched 432, and
  ``~"<prefix>%"`` reproduced the same count as the ``*`` equivalent, so ``%`` is a wildcard too).
  Given a **bare** value with no wildcard, ``~`` degenerates to exact match — identical to ``:`` —
  which is why this package once documented it as exact-match-only; that conclusion held only for
  the wildcard-free inputs it was tested with. ``:`` never expands a wildcard even when one is
  present in the value: ``:"I26081*"`` matched **0** rows on the same data. Build the pattern with
  :func:`~easyvista_python_client.ev_contains_filter` (``FIELD~"*value*"``) or
  :func:`~easyvista_python_client.ev_starts_with_filter` (``FIELD~"value*"``) rather than by hand.
  Both append ``*`` by default; on a deployment that follows the vendor's reading and compares
  ``*`` literally, that default returns **zero rows with HTTP 200 and no hint**, so pass
  ``wildcard=None`` there (or ``wildcard="%"`` for a LIKE-style backend). The two settings fail in
  opposite directions and neither failure is visible in the response — confirm which reading your
  deployment follows once, by comparing a filtered count against the unfiltered baseline. On
  ``ev_starts_with_filter``, ``wildcard=None`` removes the *anchor* rather than swapping a token:
  it is a substring match on a vendor-conformant deployment, not a prefix.
- ``*`` and ``%`` are **not** the only metacharacters under ``~``, and the other two belong to the
  **operator** rather than to the wildcard the builders append. ``_`` matches any **single**
  character and ``[`` opens a character class — measured live 2026-08-18 with a *wildcard-free*
  pattern: replacing one character of an RFC that matched 1 row with ``_``, or with ``[0-9]``,
  matched 9, while ``[<the real character>x]`` still matched 1. There is **no escape**: ``\_``
  matched 0 rows, i.e. the backslash is compared literally. Both builders above therefore raise
  ``ValueError`` for ``_`` or ``[`` in the value at **every** ``wildcard=`` setting, ``None``
  included, and additionally for ``*`` or ``%`` while a wildcard is being appended (a second one
  would compose with it); with ``wildcard=None`` those two pass through, which is how to
  hand-build a pattern. This bites on ordinary input: ``_`` is pervasive in EasyVista codes, and
  ``ev_contains_filter("ASSET_TAG", "LAPTOP_01")`` raises for that reason — unhandled, it would
  also have matched ``LAPTOP-01`` and ``LAPTOP001`` with HTTP 200 and no hint. For an **exact**
  match on such a value use :func:`~easyvista_python_client.ev_equals_filter`, since ``:`` does not
  expand a wildcard; to pattern-match *around* one, filter server-side on a wider condition and
  compare exactly in Python.
- ``,`` — combines conditions: **OR** when every condition names the same field, **AND** across
  different fields. ``;`` is *not* a combinator.

.. warning::

   EasyVista does **not** reject a ``search`` expression it cannot parse — it ignores the filter and
   returns **every** record. And because ``,`` combines conditions, an unescaped value can silently
   widen a result set rather than fail.

   A third outcome exists: a value whose **type** does not match the column raises
   ``EasyvistaValidationError`` (HTTP 590) rather than being ignored — e.g.
   ``ev_equals_filter("STATUS_ID", "Open")`` sends a status *name* to an integer column and fails
   loudly. That is the friendlier failure; the silent ones above are the dangerous ones.

   There is **no comparison operator** (``>=``, ``BETWEEN``, ``[a TO b]``…), and writing one has
   *two* different fates depending on its exact shape, not one:

   - drop the ``FIELD:`` colon entirely (e.g. ``LAST_UPDATE>="2026-01-01"``) and the expression is
     structurally unparseable, so it takes the **silent-drop** path above — the whole table comes
     back;
   - keep ``FIELD:"value"`` syntax but embed the operator *inside* the quoted value
     (``LAST_UPDATE:">=2026-01-01"`` or ``LAST_UPDATE:"[2026-01-01 TO *]"``) and the quoted text must
     still parse as the column's type — a date, here — so it instead trips the **type-mismatch**
     fate and raises ``EasyvistaValidationError`` (HTTP 590).

   Either way, no comparison operator ever narrows the result — see :ref:`change-window-filtering`
   for the interval grammar that does.

   Build filters with the helpers, not f-strings:

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

Only **top-level scalar columns** are searchable. Two kinds of field are returned but are *not*
searchable, and a filter naming one is silently ignored — so it matches **everything**:

- the denormalized ``*_PATH`` display columns (``SD_CATALOG_PATH``, ``DEPARTMENT_PATH``): searching a
  real ``SD_CATALOG_PATH`` value returns the whole table, while its ``SD_CATALOG_ID`` sibling filters
  correctly;
- the sub-keys of a nested reference object (``STATUS_EN`` / ``STATUS_FR``, ``STATUS_GUID`` inside
  ``STATUS``): they are not top-level columns at all. Filter on the top-level ``STATUS_ID`` instead.
  Which language sub-key your instance carries depends on how it was installed, but the language is
  not what makes it unsearchable: what the search layer cannot reach is the **nesting**. Verified by
  searching the sub-key an instance *does* populate, using a label read off one of its own tickets —
  the whole table came back. A language column that is *top-level* — ``DEPARTMENT_FR`` on
  ``departments`` — filters correctly, so the rule is about nesting, not about ``_EN`` / ``_FR``.

Prefer the ``*_ID`` column, and verify a field filters before relying on it. Status **ids** are
instance-specific, and there is no verified way to filter tickets by status *name*.

.. code-block:: python

   from easyvista_python_client import ev_equals_filter

   result = client.search_tickets(search=ev_equals_filter("STATUS_ID", 3), max_rows=50)
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

   status_open = ev_equals_filter("STATUS_ID", 3)
   for ticket in client.iter_tickets(search=status_open, page_size=100, max_records=1000):
       print(ticket.rfc_number)

   # Assets paginate the same way.
   tag_filter = ev_equals_filter("ASSET_TAG", "LAPTOP-001")
   for asset in client.iter_assets(search=tag_filter, page_size=100):
       print(asset.asset_tag)

The async client paginates with ``async for``. ``aclient`` is an
:class:`~easyvista_python_client.AsyncEasyvistaClient`: the synchronous ``iter_tickets``
returns a plain iterator, so the two cannot share one name.

.. code-block:: python

   from easyvista_python_client import ev_equals_filter

   async def sweep(aclient):
       async for ticket in aclient.iter_tickets(
           search=ev_equals_filter("STATUS_ID", 3), page_size=100
       ):
           print(ticket.rfc_number)

.. _change-window-filtering:

Filtering by a change window
-----------------------------

EasyVista has **no** comparison operator. ``LAST_UPDATE >= x`` in any spelling is
either structurally unparseable (silently dropped, every record comes back) or,
if it keeps ``FIELD:"value"`` syntax while embedding the operator inside the
quoted value, a type mismatch that raises HTTP 590 — see the warning above. A
range is instead an interval in the *value position*:

.. code-block:: python

   from easyvista_python_client import ev_since_filter

   search = ev_since_filter("LAST_UPDATE", watermark)   # LAST_UPDATE:(...;)
   if search is not None:
       seen = set()
       for ticket in client.iter_tickets(search=search, sort="LAST_UPDATE DESC"):
           if ticket.rfc_number in seen:
               continue
           seen.add(ticket.rfc_number)
           ...

``watermark`` may be a :class:`datetime.datetime` (preferred) or a timestamp
string. Pass a ``datetime`` and the bound cannot be malformed; ``Request``
timestamps are already aware datetimes (see :ref:`timestamps`), so a value read
from one ticket can be fed straight back in. A string naming a time is
re-rendered into the one form the wire honours (millisecond precision with an
offset), so a stored watermark string and the ``datetime`` it came from produce
byte-identical bounds.

The bound is **inclusive**, and milliseconds are honoured (verified live on
three independent boundaries). A watermark set to ``max(t.last_update)``
therefore re-reads that boundary record on the next sweep — hence the
de-duplication above.

.. warning::

   **Sort the sweep descending, and de-duplicate.** ``iter_tickets`` walks the
   result set by *offset*, and the rows a change window selects are by
   construction the rows that are changing, so a ticket touched between page N
   and page N+1 moves *within the very set being paged*. An unsorted sweep can
   drop such a row with no way to tell — and so can either sort direction. What
   differs is where the dropped row's own timestamp lands relative to the
   watermark this sweep records:

   - **Descending** (``LAST_UPDATE DESC``): the re-touched row jumps to the head,
     behind the read cursor, so this sweep misses it — but its ``LAST_UPDATE`` is
     now *above* the watermark, so the next sweep selects it again. The miss is
     **deferred and self-healing**.
   - **Ascending** (bare ``LAST_UPDATE``, or ``LAST_UPDATE ASC``): the re-touched
     row moves to the tail and everything behind it shifts one place head-ward,
     so the row that crosses the cursor is one whose own stamp did **not**
     change. It falls *below* the new watermark and no later sweep selects it.
     The miss is **permanent**.

   Both tokens are honoured (measured live); descending is chosen for the reason
   above, not for availability. De-duplicate by ``rfc_number``: the duplicates
   are the deferred rows arriving on a later sweep, plus the inclusive-boundary
   re-read described above.

   **A sweep that does not run to completion is a separate trap.** Descending
   yields the newest row first, so the watermark reaches its *final* value on
   page 1. A sweep that is interrupted, or capped with ``max_records`` (as the
   pagination examples above do), still ends up holding the newest stamp —
   advance the watermark from that and the next window's ``(newest;)`` bound
   permanently excludes every row the incomplete sweep never read. Only advance
   the watermark after a sweep runs to completion.

   Descending is the safe direction, not a guarantee. If even a deferred miss is
   unacceptable, page
   :meth:`~easyvista_python_client.EasyvistaClient.search_tickets` yourself with
   **keyset** pagination: sort ascending and, after each page, advance the
   *window* — ``ev_since_filter("LAST_UPDATE", max(stamps on the page))`` read
   again at ``offset=0`` — instead of incrementing an offset. With no offset there
   is no cursor for a row to shift past. ``iter_tickets`` cannot express this,
   because it owns its own offset.

   An earlier release of this guide recommended sorting *ascending* here, on the
   reasoning that it turns a permanent miss into a duplicate. That was wrong: the
   row an ascending sweep drops is not the re-touched one.

   The sort token must stay space-separated. ``LAST_UPDATE:DESC``,
   ``-LAST_UPDATE`` and ``DESC(LAST_UPDATE)`` are each **silently ignored**
   (measured live) and degrade to the server's default order with no error, so a
   sweep written with one of those forms is an unsorted sweep that looks sorted.

.. warning::

   **A bound that names a time must carry its UTC offset.** EasyVista accepts an
   offset-less literal and reads it in a different zone: measured live, the same
   wall-clock text with and without its offset returned 13 rows and 11 rows
   against one instance — the offset-less form moves the bound *later* and skips
   records, with no error of any kind. Both builders therefore refuse a naive
   time, whether it arrives as a ``datetime`` or as a string. A bare date
   (``"2026-01-31"``) stays accepted: day granularity has no time to misplace.

Use :func:`~easyvista_python_client.ev_between_filter` for a closed interval.
Both refuse a bound that is not a timestamp: the bound is interpolated
*unquoted*, so a ``;`` or ``)`` inside it would silently change the query.

.. code-block:: python

   from datetime import datetime, timezone
   from easyvista_python_client import ev_between_filter

   window = ev_between_filter(
       "LAST_UPDATE",
       datetime(2026, 1, 1, tzinfo=timezone.utc),
       datetime(2026, 2, 1, tzinfo=timezone.utc),
   )
   recent = client.search_tickets(search=window, max_rows=100)

.. _timestamps:

Timestamps
~~~~~~~~~~

``Request``'s timestamp fields (``submit_date_ut``, ``creation_date_ut``,
``max_resolution_date_ut``, ``expected_date_ut``, ``end_date_ut``,
``last_update``), ``Employee.last_update``, and ``Action.created_at`` /
``Action.updated_at`` are timezone-aware
:class:`datetime.datetime`, parsed from EasyVista's ISO-8601-with-offset wire
format (``2026-08-17T15:40:41.610+02:00``, millisecond precision — verified
live 2026-08-17). An unset date is ``None``. The ``_UT`` suffix is a naming
convention, **not** a promise of UTC normalization: these columns carry the
same local offset as ``LAST_UPDATE``. ``Action`` is easy to miss here: it names
the identical ``CREATION_DATE_UT`` / ``LAST_UPDATE`` wire columns
``created_at`` / ``updated_at``, so an action export is retyped exactly like a
ticket export and hits the JSON note below the same way.

Only the *read* path is parsed. The accepted *write* format is still
unverified, so no write model accepts a ``datetime`` — set a date-typed field
with a raw request if you need to. That includes ``custom_fields``: a
``datetime`` placed there is not serialisable and fails inside the HTTP layer
with a bare ``TypeError``, so render it yourself first.

Only the *declared* columns are parsed. An instance-specific date column reached
through ``classify_fields().custom`` or plain ``extra="allow"`` attribute access
is still the raw wire string, so within one record dump
``official["CREATION_DATE_UT"]`` is a ``datetime`` while
``official["EXPECTED_START_DATE_UT"]`` is a ``str`` — comparing the two raises
``TypeError``. Pass the undeclared one through
:func:`~easyvista_python_client.parse_ev_datetime` before comparing them.

.. note::

   **A record dump is no longer directly JSON-serialisable.** This is true of
   *any* record carrying one of the columns above — a ``Request``, an
   ``Employee`` or an ``Action`` alike. ``model_dump()`` and
   ``classify_fields()`` yield ``datetime`` objects, so both
   ``json.dumps(record.model_dump(by_alias=True))`` and
   ``json.dumps(record.classify_fields().official)`` raise
   ``TypeError: Object of type datetime is not JSON serializable``. For a dump,
   pass ``model_dump(mode="json")``. ``classify_fields()`` takes **no arguments**,
   so there is nowhere to put that keyword: render the ``datetime`` values with
   :func:`~easyvista_python_client.format_ev_datetime` before serialising the
   bucket, or classify the JSON-mode dump yourself — the buckets are keyed by
   wire column name, so ``{k: dumped[k] for k in record.classify_fields().official}``
   over ``dumped = record.model_dump(mode="json", by_alias=True)`` gives the same
   split with serialisable values.

Use :func:`~easyvista_python_client.format_ev_datetime` to render a
``datetime`` back into the literal EasyVista's grammar accepts (e.g. as an
interval bound above), and :func:`~easyvista_python_client.parse_ev_datetime`
to parse a raw string yourself.

.. code-block:: python

   from easyvista_python_client import format_ev_datetime, parse_ev_datetime

   ticket = client.get_ticket(ticket.rfc_number)
   watermark = ticket.last_update                 # already an aware datetime
   literal = format_ev_datetime(watermark)         # "2026-08-17T15:40:41.610+02:00"
   assert parse_ev_datetime(literal) == watermark

Counting and statistics
-----------------------

:meth:`~easyvista_python_client.EasyvistaClient.count_tickets` returns how many tickets match a
search with a single cheap call (it reads the envelope's ``total_record_count`` and fetches no
records).

.. code-block:: python

   from easyvista_python_client import ev_equals_filter

   open_count = client.count_tickets(search=ev_equals_filter("STATUS_ID", 3))

:meth:`~easyvista_python_client.EasyvistaClient.ticket_statistics` aggregates matching tickets into a
:class:`~easyvista_python_client.TicketStatistics` — a ``total`` plus per-dimension ``breakdowns``
(``{dimension: {label: count}}``). Dimensions are **raw EasyVista field names** — the reference-bearing
ones give human labels (``STATUS``, ``DEPARTMENT``, ``CATALOG_REQUEST``), and id-only ones
(``URGENCY``, ``IMPACT``) bucket by id. Custom ``e_*`` fields work too. ``created_since`` /
``created_until`` apply an inclusive window on the ticket creation date.

.. code-block:: python

   from easyvista_python_client import ev_equals_filter

   stats = client.ticket_statistics(
       search=ev_equals_filter("STATUS_ID", 3),
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

``classify_fields()`` — available on every read model — partitions a record's fields into the
four buckets of a :class:`~easyvista_python_client.field_model.FieldClassification`: ``official``,
``custom`` (``e_*`` fields not declared by the model), ``available`` (``AVAILABLE_FIELD_n``
slots), and ``links`` (href-only sub-resource references). Use
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
``status_code``, ``ev_code``, ``ev_message``, and ``body``. Catch the specific subclass
you care about.

``ev_code`` / ``ev_message`` are populated only when the response body matches a
recognized EasyVista error shape; the exception message itself never includes the raw
response body, so it cannot leak an unrecognized body's contents into a log or a
traceback. ``body`` (``bytes | None``) is the raw response body, for the cases
``ev_code`` / ``ev_message`` cannot parse — an upstream proxy's HTML error page, a
plain-text 503, or any other shape this client does not recognize.

.. code-block:: python

   from easyvista_python_client import (
       EasyvistaError,
       EasyvistaNotFound,
       EasyvistaValidationError,
       PostRequest,
   )

   try:
       # Under-specified: a subject but no origin/department_id/urgency_id/impact_id.
       # `title` is not what makes a create complete -- the fuller body above was
       # accepted with no title.
       client.create_ticket(PostRequest(catalog_code="INC_STANDARD"))
   except EasyvistaValidationError as exc:
       # HTTP 590, EasyVista error_code 2013 — a rejected create. This client does
       # not retry it; read the warning below before you retry it yourself.
       print("Validation failed:", exc.ev_message)
   except EasyvistaNotFound:
       print("No such record")
   except EasyvistaError as exc:
       print("EasyVista error:", exc.status_code, exc)

.. warning::

   **A rejected create may still have created the ticket.** Measured on one instance
   (2026-08-25): 12 under-specified attempts returned 3 ``RFC_NUMBER``\ s, and afterwards all 12
   tickets existed — 9 of the 9 failures had written a row, with the ids they were missing left
   null. So an :class:`~easyvista_python_client.EasyvistaValidationError` from ``create_ticket``
   means *possibly created*, never *not created*: wrapping this ``except`` in a retry duplicates
   tickets, and the caller never learns the id of the one it just made. Set
   ``external_reference`` on every create — it survives the failed insert and is searchable — and
   reconcile by that marker rather than trusting the error. This is a single-instance measurement,
   not a vendor-documented behaviour; treat it as the floor, not the ceiling, of what a 590 can
   leave behind.

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

   from easyvista_python_client import EasyvistaClient, PostRequest, PostTask

   with EasyvistaClient.from_env() as client:
       ticket = client.create_ticket(
           PostRequest(
               catalog_code="INC_STANDARD",
               title="VPN drops",
               description="Daily VPN drops at 11:00",
               # The vendor documents `origin` as a STRING naming the channel
               # ("Phone", "Email") -- the one create field with a portable,
               # human-readable form. An int id is also accepted (measured on
               # one instance) and passes through unchanged.
               origin="Phone",
               department_id=9,
               urgency_id=7,
               impact_id=21,
               external_reference="MYAPP-0002",  # your marker; set it always
           )
       )
       # A COMMENT is a task, not an action: a task is born already ended, so
       # its text shows in the ticket history. An action is born open, and an
       # open action renders as a pending row with its text NOT shown.
       client.create_task(
           ticket.rfc_number,
           PostTask(action_type_id=94, group_id=3, description="Investigating"),
       )
       client.close_ticket(
           ticket.rfc_number,
           status_guid="{00000000-0000-0000-0000-000000000000}",
           comment="Replaced the VPN concentrator",
       )
       resolved = client.get_ticket(ticket.rfc_number)
       print(resolved.rfc_number, resolved.status_id)

.. note::

   The ``description`` passed to ``PostRequest`` above is not guaranteed readable
   back on every instance — see the note under "Working with tickets". If you need
   to read the body text back, write it with ``update_ticket`` /
   ``RequestUpdate.description`` and fetch it via ``TicketContext.comment``.
