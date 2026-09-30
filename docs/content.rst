.. _content-conversion:

Rich-text content
=================

EasyVista keeps a ticket's and an action's text in *memo* fields, and a memo
holds the HTML it was sent. The optional ``content`` extra converts between that
HTML and Markdown in both directions, so a caller can read memos as Markdown and
write Markdown to them without handling HTML itself.

.. code-block:: bash

   pip install "easyvista-python-client[content]"

The extra adds ``beautifulsoup4``, ``markdown`` and ``markdownify``. It is
optional so that the core package keeps its three runtime dependencies: nothing
outside ``easyvista_python_client.content`` imports them, and importing that
subpackage without them raises an :class:`ImportError` naming the command above.
:class:`~easyvista_python_client.exceptions.EasyvistaContentError`, the one error
the converter raises, is part of the core package, so it can be caught either
way.

What a memo holds
-----------------

A ticket's body lives in its ``COMMENT`` or its ``DESCRIPTION`` memo, depending
on the deployment, and an action's in ``DESCRIPTION``, or in ``COMMENT`` when
``DESCRIPTION`` is empty (see :doc:`the user guide <user_guide>`). The client
reads any of them with
:meth:`~easyvista_python_client.EasyvistaClient.resolve_memo`.

What a memo contains is whatever was written to it. **Tier 4** -- measured
2026-09-30 on one instance, which may not generalise: a ticket memo written
through the API with HTML was stored byte for byte, and the web UI rendered its
``<p>`` elements as paragraphs. No vendor documentation of the memo format is
recorded in ``docs/vendor-api-reference.md``. Nothing forces a memo to be HTML
either -- a caller can write plain text -- so the reading direction accepts
both.

Nothing in the client converts memos for you. The read models keep a memo
exactly as the API returned it, and
:meth:`~easyvista_python_client.context.TicketContext.to_markdown` still reduces
memos to plain text with the core package's dependency-free reducer. Convert
where you want Markdown:

.. code-block:: python

   from easyvista_python_client import EasyvistaClient, RequestUpdate
   from easyvista_python_client.content import EasyvistaContentConverter

   with EasyvistaClient(config) as client:
       # Read a memo as Markdown. `resolve_memo` may return None, which reads as "".
       memo = client.resolve_memo(f"requests/{rfc_number}/comment")
       markdown = EasyvistaContentConverter.from_transport(memo)

       # Write Markdown to it: render first, because a memo stores what it is sent.
       html = EasyvistaContentConverter.to_transport("The printer is **offline**.")
       client.update_ticket(rfc_number, RequestUpdate(description=html))

Reading: ``from_transport``
---------------------------

:meth:`~easyvista_python_client.content.EasyvistaContentConverter.from_transport`
returns ``""`` for an empty memo and a memo with no real HTML element unchanged,
so plain text and Markdown pass through. The test is the element *name*, not the
presence of angle brackets: ``use the <Enter> key`` and ``if x<y then z>0`` are
text, because neither ``Enter`` nor ``y`` is an HTML element.

Real HTML goes through ``markdownify`` with ATX headings, ``-`` bullets,
``<script>`` and ``<style>`` markup stripped, and underscores and asterisks in
prose left unescaped, so ``snake_case`` does not grow a backslash on every read.
An anchor whose text is its own URL -- a pasted link -- reads as the autolink
``<https://...>``; a ``title`` attribute reads as a link title,
``[text](https://... "title")``.

**Deep nesting degrades, it does not raise.** ``markdownify`` walks the document
recursively, so a deeply nested memo can exhaust the interpreter's stack: from a
shallow stack, the deepest ``<div>`` document that converts is 493 levels on
CPython 3.12 to 3.14 and 328 on 3.10 (measured 2026-09-30). The converter does
not predict that. It attempts the conversion and, if the walk does not fit,
strips the tags instead: every character of prose the conversion would have
produced is still there, in order, and what is lost is structure -- link
targets, image alt text, code fencing, ``&nbsp;`` alignment. Because the budget
is whatever stack is left when the call starts, the same memo can convert from
one call site and degrade from a deeper one. A document ``html.parser`` refuses
outright, such as one carrying an unknown ``<![FOO[`` marked section, takes the
same path.

Writing: ``to_transport``
-------------------------

:meth:`~easyvista_python_client.content.EasyvistaContentConverter.to_transport`
renders Markdown with python-markdown and the ``nl2br``, ``sane_lists``,
``fenced_code`` and ``tables`` extensions, as ``html5``: a lone newline becomes
``<br>``, a fence a ``<pre><code>`` block, a table a ``<table>``, and ``""``
stays ``""`` rather than becoming ``<p></p>``. There is no degraded path in this
direction -- the Markdown is what the caller just wrote, so a failure is
reported -- and a list nested around 500 levels deep raises
:class:`~easyvista_python_client.exceptions.EasyvistaContentError`.

It is not a sanitiser
---------------------

Neither direction neutralises anything, by design, exactly as in
``glpi_python_client``: the Markdown is the caller's own. So:

* raw HTML in the Markdown is rendered verbatim -- ``<script>alert(1)</script>``
  goes out as a live ``<script>``;
* a ``javascript:`` link target is rendered as a live ``href``;
* ``<javascript:alert(1)>`` is not made a link (python-markdown autolinks
  ``http``, ``https``, ``ftp`` and ``ftps`` only) but passes through as raw
  markup;
* text a memo *displays* as markup, ``&lt;script&gt;``, reads back as a raw
  ``<script>`` -- which the writing direction would then emit live.

A caller relaying Markdown it did not write -- a sync between two ITSMs, for one
-- must neutralise raw HTML and executable link schemes before calling
``to_transport``.

What survives a round trip
--------------------------

Markdown written and read back is the same Markdown for paragraphs, emphasis,
headings, lists, block quotes, fences, tables, links -- titled ones and URLs
containing parentheses included -- autolinks, underscores, lone asterisks,
accents and query strings. The exceptions, each pinned by a test:

* a lone newline comes back as a hard break (two trailing spaces);
* a nested list comes back indented by two spaces, which python-markdown does
  not nest, so a second cycle flattens it;
* a fence's language tag is dropped;
* text in angle brackets that is not a URL, ``use the <Enter> key``, is sent as
  a live unknown tag and does not come back;
* ``&lt;`` comes back as a raw ``<``, which renders the same;
* an e-mail autolink comes back as an inline ``mailto:`` link;
* a no-break space or hard break at the edge of a paragraph is dropped.

Past the first cycle, a second changes nothing more, except for the nested list
and the angle-bracket text above. That is the property a two-way sync relies on:
after the first write, reading back what was written gives exactly the Markdown
that was written.

Where it comes from
-------------------

The converter is a port of ``glpi_python_client``'s
``content/conversion.py`` at commit ``0d43528``, with the same options, the same
extensions and the same edge-case handling, and **the two should move
together**: the hard part of both is the behaviour of the same three libraries,
not anything either ITSM does. The only difference in code is that the three
libraries are an optional extra here rather than dependencies. One measurement
differs from the one recorded there: the ``beautifulsoup4`` defect that dropped
the text after a ``<br />`` in a body also using ``<br>`` no longer reproduces
on 4.15.0 (measured 2026-09-30); the converter keeps its workaround because the
extra accepts 4.12 and later.
