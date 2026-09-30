.. _content-conversion:

Rich-text content
=================

EasyVista keeps a ticket's and an action's text in *memo* fields, and a memo
holds whatever it was sent -- rich-text HTML, where that was measured (see
below). The optional ``content`` extra converts between that HTML and Markdown
in both directions, so a caller can read memos as Markdown and write Markdown to
them without handling HTML itself.

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
       # RequestUpdate.description is what writes the COMMENT memo on the
       # instance this was verified against -- see the user guide.
       html = EasyvistaContentConverter.to_transport("The printer is **offline**.")
       client.update_ticket(rfc_number, RequestUpdate(description=html))

Reading: ``from_transport``
---------------------------

:meth:`~easyvista_python_client.content.EasyvistaContentConverter.from_transport`
returns ``""`` for an empty memo, and a memo with no real HTML element as it is,
less leading and trailing whitespace, so plain text and Markdown pass through.
The test is the element *name*, not the
presence of angle brackets: ``use the <Enter> key`` and ``if x<y then z>0`` are
text, because neither ``Enter`` nor ``y`` is an HTML element.

Real HTML goes through ``markdownify``, and **the text in it is literal**: the
Markdown spells it so that rendering it -- with ``to_transport``, or any
python-markdown using the same four extensions -- displays what the memo
displayed. Markdown has one spelling for a ``__init__`` a user typed and for
bold ``init``, so a character is escaped exactly where python-markdown would
otherwise read it as syntax, and nowhere else:

.. code-block:: python

   EasyvistaContentConverter.from_transport(
       "<p>Voir __init__ et \\\\serveur\\partage</p><p># pas un titre</p>"
   )
   # 'Voir \\_\\_init\\_\\_ et \\\\\\serveur\\partage\n\n\\# pas un titre'

Ordinary prose carries no escape at all -- ``fichier_de_test_v2.xlsx``,
``C:\Temp``, ``R&D``, ``snake_case``, a ``#`` or a ``-`` mid-sentence come back
exactly as typed -- and the Markdown is a fixed point: rendering it and reading
it back gives the same Markdown again. A backslash is used wherever
python-markdown removes one; ``<``, ``&``, ``=`` and ``~`` are spelled as
character references (``&lt;``) where they would be read, since no backslash
escapes them. Nested lists nest, at four spaces, and keep their numbers;
``<script>``, ``<style>`` and ``<title>`` bodies are dropped, as a browser drops
them. An anchor whose text is its own URL -- a pasted link -- reads as the
autolink ``<https://...>``; a ``title`` attribute reads as a link title,
``[text](https://... "title")``.

A memo holding a single real HTML element is read as HTML throughout, so
Markdown syntax in the same memo -- ``**bold** <b>x</b>`` -- is read as the
literal characters it is: write a memo as HTML or as Markdown, not both.

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

Spelling literal text as text is not sanitising, and the writing direction
neutralises nothing, by design, exactly as in ``glpi_python_client``: the
Markdown is the caller's own. So:

* raw HTML in the Markdown is rendered verbatim -- ``<script>alert(1)</script>``
  goes out as a live ``<script>``;
* a ``javascript:`` link target is rendered as a live ``href``;
* ``<javascript:alert(1)>`` is not made a link (python-markdown autolinks
  ``http``, ``https``, ``ftp`` and ``ftps`` only) but passes through as raw
  markup.

What the reading direction does is keep text a memo *displays* as text:
``&lt;script&gt;`` reads back as ``&lt;script>``, and is written back as the
same ``&lt;script&gt;``. It used to read back as a raw ``<script>``, which the
writing direction then emitted live.

A caller relaying Markdown it did not write -- a sync between two ITSMs, for one
-- must still neutralise raw HTML and executable link schemes before calling
``to_transport``.

What survives a round trip
--------------------------

Markdown written and read back is the same Markdown for paragraphs, emphasis,
headings, lists -- nested ones included -- block quotes, fences, tables, links
-- titled ones and URLs containing parentheses included -- autolinks,
underscores, lone asterisks, accents, query strings and escaped literal text.
The exceptions, each pinned by a test:

* a lone newline comes back as a hard break (two trailing spaces);
* a fence's language tag is dropped;
* text in angle brackets that is not a URL, ``use the <Enter> key``, is sent as
  a live unknown tag and does not come back;
* a ``&lt;`` that opens no tag, ``a &lt; b``, comes back as a raw ``<``, which
  renders the same;
* an e-mail autolink comes back as an inline ``mailto:`` link;
* a no-break space or hard break at the end of a paragraph is dropped.

Past the first cycle, a second changes nothing more, except for the
angle-bracket text above. That is the property a two-way sync relies on: once
a text has made one trip, writing what was read back and reading it again gives
exactly the same Markdown.

The other direction -- a memo read, written back and read again -- is held to
more: what the Markdown displays is what the memo displayed, compared with an
HTML parser over realistic memos and a seeded fuzzer, and the Markdown is a
fixed point from the first read. A few structures have no Markdown spelling,
and the inventory in ``test_literal_text.py`` records each: struck-through and
underlined text keep their words and lose the line, adjacent lists or quotes
merge, two ``<br>`` in a row become a paragraph break, adjacent code spans
merge, strong inside emphasis loses its bold, a table without a header row
gains an empty one, a table cell or a heading holds one line, and a ``<pre>``
that opens a list item or directly follows a list inside the same item keeps
its lines as text rather than as code.

Where it comes from
-------------------

The converter is a port of ``glpi_python_client``'s
``content/conversion.py`` at commit ``4fc3bed``, the literal-safe converter,
with the same rules, the same extensions and the same edge-case handling, and
**the two should move together**: the hard part of both is the behaviour of the
same three libraries, not anything either ITSM does. Names and error messages aside, the only
difference in code is that the three libraries are an optional extra here
rather than dependencies. One measurement
differs from the one recorded there: the ``beautifulsoup4`` defect that dropped
the text after a ``<br />`` in a body also using ``<br>`` no longer reproduces
on 4.15.0 (measured 2026-09-30); the converter keeps its workaround because the
extra accepts 4.12 and later.
