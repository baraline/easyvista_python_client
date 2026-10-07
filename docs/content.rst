.. _content-conversion:

Rich-text content
=================

EasyVista keeps a ticket's and an action's text in *memo* fields, and a memo
holds whatever it was sent: rich-text HTML or plain text (see below). The
optional ``content`` extra converts between that and Markdown in both
directions, so a caller can read memos as Markdown and write Markdown to them
without handling HTML itself.

.. code-block:: bash

   pip install "easyvista-python-client[content]"

The Markdown is **CommonMark with GFM tables**. Writing renders it with
``cmark-gfm``, GitHub's C fork of the CommonMark reference implementation, with
only its ``table`` extension.
Reading turns HTML into Markdown with ``markdownify``, then re-renders it with
``mdformat`` (CommonMark, plus ``mdformat-tables``) so that only the escapes
CommonMark needs remain. The extra installs ``beautifulsoup4``, ``cmarkgfm``,
``markdown-it-py``, ``markdownify``, ``mdformat`` and ``mdformat-tables``; their
bounds are explained under `Dependencies and their bounds`_.

The extra is optional so that the core package keeps its three runtime
dependencies. Nothing outside ``easyvista_python_client.content`` imports
these libraries, and importing that subpackage without them raises an
:class:`ImportError` naming the command above.
:class:`~easyvista_python_client.exceptions.EasyvistaContentError`, the error
the converter raises, is part of the core package, so it can be caught either
way.

What a memo holds
-----------------

A ticket's body lives in its ``COMMENT`` or its ``DESCRIPTION`` memo, depending
on the deployment. An action's body lives in ``DESCRIPTION``, or in ``COMMENT``
when ``DESCRIPTION`` is empty (see :doc:`the user guide <user_guide>`). The
client reads any of them with
:meth:`~easyvista_python_client.EasyvistaClient.resolve_memo`.

What a memo contains is whatever was written to it. **Tier 4** -- measured
2026-09-30 on one instance, which may not generalise: a ticket memo written
through the API with HTML was stored byte for byte, and the web UI rendered its
``<p>`` elements as paragraphs. Nothing forces a memo to be HTML. A caller can
write plain text, and the 367 memos read from one preproduction instance on
2026-10-01 included both shapes (tier 4, one instance, may not generalise). So
the reading direction accepts both.

**How the web UI displays a memo with no HTML in it is unverified.** **Tier 1**
-- the vendor's form-editor page (https://docs.easyvista.com/docs/form, read
2026-10-02) defines a *MEMO* object, "Identical to TEXT, of unlimited size",
and a *TEXT AREA* object, "Identical to MEMO, with the possibility of entering
HTML code for formatting text". It does not say which of the two the request
form or the action history uses. A second vendor page
(https://docs.easyvista.com/docs/service-manager-comment-log-creation, read
2026-10-02) has an administrator add a *custom* comment-log field to the
request form, filled by a business rule with the request's comments, and set
its type to "Text area". That leans towards the UI showing memo text as HTML,
the opposite of how the converter reads a memo with no HTML element (below),
but it is about that custom field: neither page says what the built-in
description or the action history is. ``docs/vendor-api-reference.md`` tracks
the question as open item ``O-MEMOFORMAT``.

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
returns ``""`` for an empty memo and otherwise the Markdown, stripped. It first
decides whether the memo is HTML. The test is the element *name*, not the
presence of angle brackets: ``use the <Enter> key`` and ``if x<y then z>0`` are
text, because neither ``Enter`` nor ``y`` is an HTML element. A memo holding a
single real HTML element is read as HTML throughout, so Markdown syntax in the
same memo, as in ``**bold** <b>x</b>``, is read as the literal characters it
is. Write a memo as HTML or as Markdown, not both.

**The text in a memo is literal.** The Markdown spells it so that rendering
it, with ``to_transport`` or any CommonMark renderer, displays what the memo
displayed. A character is escaped where CommonMark would otherwise read it as
syntax, and nowhere else:

.. code-block:: python

   EasyvistaContentConverter.from_transport(
       "<p>Voir __init__ et \\\\serveur\\partage</p><p># pas un titre</p>"
   )
   # 'Voir \\_\\_init\\_\\_ et \\\\\\serveur\\partage\n\n\\# pas un titre'

More of what the memo displays, and the Markdown it reads as:

.. code-block:: text

   memo displays                 Markdown
   ----------------------------  ----------------------------
   __init__                      \_\_init\_\_
   *important*                   \*important\*
   # 4521 (at a line start)      \# 4521
   1. pas une liste              1\. pas une liste
   - pas une liste               \- pas une liste
   > pas une citation            \> pas une citation
   [lien](x)                     \[lien\](x)
   <Entrée>                      \<Entrée>
   ~~~ (at a line start)         \~~~
   Attention!  then a link       Attention\![lien](https://example.org)

Ordinary prose carries no escape at all. ``fichier_de_test_v2.xlsx``,
``C:\Temp``, ``R&D``, ``snake_case``, ``Ticket #4521``, ``a * b``, ``[x]``,
``a | b``, and a ``#`` or a ``-`` mid-sentence come back exactly as typed.
Text a memo displays as markup is read back as that text, so
``&lt;b&gt;`` reads as ``\<b>``, never as a live ``<b>``.

What each kind of element becomes:

* **Bold and italic** become ``**`` and ``*``, or raw ``<strong>`` and
  ``<em>`` where CommonMark would not close the markers, for example bold that
  ends in punctuation directly followed by a letter:
  ``prix:<b>(10)</b>euros`` reads as ``prix:<strong>(10)</strong>euros``.
* **Underline, highlight and inserted text** (``<u>``, ``<mark>``, ``<ins>``)
  stay as those raw tags, and **struck text** (``<s>``, ``<del>``,
  ``<strike>``) as a raw ``<s>``. CommonMark has no spelling for any of them,
  and ``to_transport`` passes the tags through, so the formatting survives.
  The cost is raw HTML in the Markdown. Markdown has no inline tag round
  blocks, so a ``<u>``, ``<mark>`` or ``<ins>`` holding a table, a list, a
  heading, a quote, a ``<pre>``, a rule or paragraphs is dropped and its
  blocks kept; inside a table cell or a heading, which hold one line, it
  stays.
* **Links** become ``[text](https://... "title")``, and a link whose text is
  its own URL, a pasted link, becomes the autolink ``<https://...>``. No link
  target is filtered, ``javascript:`` included (see `It is not a sanitiser`_).
* **Lists** nest and keep their numbers, including an ``<ol start>``. A
  ``start`` that is not a decimal number counts from 1, as a browser counts
  one holding no digit, such as ``²``; a browser reads ``" 3"``, ``"+3"`` or
  ``"3abc"`` as 3. **Tables** become GFM tables, and a ``<br>`` inside a cell
  stays a raw ``<br>``, since a GFM cell is one line. **Preformatted blocks**
  become fences that keep the ``language-`` class ``cmark-gfm`` writes, with a
  fence longer than any run of backticks in the code.
* ``<head>``, ``<script>``, ``<style>``, ``<template>`` and ``<title>`` are
  dropped, as a browser does not display them. Styling such as ``<font>``
  colours or ``<span style>`` keeps its text and loses the style.

**Plain text is read as literal lines.** A memo with no HTML element is
escaped like the text of any other memo, and each of its lines is kept as a
line, joined by a hard break (a backslash at the end of the line). A character
reference in it, ``&nbsp;`` for one, is literal text and displays as typed.
Whether the web UI shows such a memo the same way is the unverified question
above. If the UI treated it as HTML, a line break inside a paragraph would
show as a space there, and as a break here.

When the value is your own Markdown, not a memo, pass
``plain_text_is_markdown=True``. The value then passes through, stripped,
unless it starts with ``<`` *and* holds a real HTML element anywhere. So
Markdown that carries an inline ``<kbd>`` or ``<br>`` is still treated as
Markdown, but Markdown that opens with an autolink or other angle-bracketed
text and carries inline HTML further on is read as HTML:
``<https://example.org> puis<br>suite`` loses the autolink, which the HTML
parser takes for an unknown element, and its Markdown syntax is escaped as
text. Start such a value with something other than ``<``.

**Deep nesting degrades to text.** ``markdownify`` walks the document
recursively, so a deeply nested memo can exhaust the interpreter's stack. From
a shallow stack, the deepest ``<div>`` document that still converts with its
structure is 245 levels on CPython 3.11.13 and 327 levels on 3.12.11, 3.13.13
and 3.14.6 (measured 2026-10-02, default recursion limit). The converter does
not predict that. It attempts the conversion and, if the walk does not fit,
reads the memo as its text instead, a line per block. Every word the
conversion would have produced is still there, in order. What is lost is
structure: link targets, image alt text, emphasis and code fencing. Any
``ValueError`` from the conversion takes the same path -- ``markdownify``
raises one for a ``colspan`` or ``start`` attribute it cannot read as a
number, such as a ``colspan`` of ``"²"`` -- and so does a document
``html.parser`` refuses outright, such as one carrying an unknown
``<![FOO[`` marked section.

Because the budget is whatever stack is left when the call starts, the same
memo can convert from one call site and degrade from a deeper one. A caller
already close to the recursion limit can get an error after all. Measured
2026-10-02 on CPython 3.11 to 3.14 with the default limit of 1000: an ordinary
memo converted when called from up to about 970 frames deep, and degraded to
text a few frames further down. From about 975 frames it raised
:class:`~easyvista_python_client.exceptions.EasyvistaContentError`, and from
about 995 a bare :class:`RecursionError` escaped.

Writing: ``to_transport``
-------------------------

:meth:`~easyvista_python_client.content.EasyvistaContentConverter.to_transport`
renders the Markdown with ``cmark-gfm``, with its ``table`` extension and two
options, ``HARDBREAKS`` and ``UNSAFE``:

* a lone newline becomes ``<br />``, as it does in a chat box, rather than a
  space;
* a fence becomes ``<pre><code>``, with the info string as a
  ``class="language-..."``;
* a table becomes a ``<table>`` with a ``<thead>``;
* a link opens in a new window: each ``<a href>`` the renderer writes carries
  ``target="_blank" rel="noopener noreferrer"``, as a link written in
  EasyVista's editor does. Without it the memo view opens the link in place,
  inside EasyVista's window (measured 2026-10-07). Reading ignores both
  attributes, so a round trip is unchanged;
* raw HTML, inline or as a block, is passed through as written;
* ``""``, or only whitespace, stays ``""`` rather than becoming ``<p></p>``.

Only the ``table`` extension is enabled. A ``~~struck~~`` span stays literal
tildes, so write ``<s>struck</s>`` instead. Bare ``www.`` or ``https://`` text
is not linked, so write ``<https://...>``. A ``- [ ]`` task item stays a list
item that starts with ``[ ]``. Everything else is CommonMark, so an unescaped
``__init__`` renders as a bold ``init`` and needs ``\_\_init\_\_``.

``cmark-gfm`` is C and does not use Python's stack, so this direction has no
degraded path. The Markdown is what the caller just wrote, so a failure is
reported as
:class:`~easyvista_python_client.exceptions.EasyvistaContentError`. A block
quote nested 100,000 levels deep rendered without one (measured 2026-10-02).

It is not a sanitiser
---------------------

Spelling literal text as text is not sanitising. The writing direction
neutralises nothing, by design, exactly as in ``glpi_python_client``: the
Markdown is the caller's own. ``cmark-gfm`` runs with its ``UNSAFE`` option,
which is what lets ``<u>`` or ``<br>`` in a table cell through. So:

* raw HTML in the Markdown is rendered verbatim, and
  ``<script>alert(1)</script>`` goes out as a live ``<script>``;
* a ``javascript:`` link target is rendered as a live ``href``;
* ``<javascript:alert(1)>`` is a CommonMark autolink, which accepts any
  scheme, so it too goes out as a live ``href``.

The reading direction does not filter either. A memo's ``javascript:`` link
reads back as a ``javascript:`` link. What reading does guarantee is that text
a memo *displays* stays text: ``&lt;script&gt;`` reads back as ``\<script>``,
and is written back as the same ``&lt;script&gt;``.

A caller relaying Markdown it did not write must neutralise raw HTML and
executable link schemes before calling ``to_transport``. A sync between two
ITSMs is one such caller.

What survives a round trip
--------------------------

**Markdown written and read back.** Paragraphs, ``*emphasis*`` and
``**strong**``, ATX headings, nested lists, numbered lists, block quotes,
fences with their language, links with titles, autolinks, raw ``<u>`` and
``<s>`` spans, accents and escaped literal text all come back as they were
written. Other spellings come back in mdformat's canonical form, and display
the same:

* ``_em_`` and ``__strong__`` as ``*em*`` and ``**strong**``;
* ``+`` and ``*`` bullets as ``-``, ``1)`` as ``1.``, and repeated ``1.``
  items numbered ``1.``, ``2.``, ``3.``;
* a setext heading as an ATX one, and ``***`` as ``---``;
* a table's delimiter row as ``| -- |``;
* a lone newline, or two trailing spaces, as a backslash hard break;
* a link target holding parentheses wrapped in ``<...>``;
* runs of blank lines as one, and a character reference such as ``&copy;`` as
  the character.

A few things do not come back:

* text in angle brackets that is not a URL, ``use the <Enter> key``, is sent as
  a live unknown tag, and the browser and the reader both drop it;
* an e-mail autolink comes back as an inline ``mailto:`` link;
* a ``[`` or ``]`` in a link target comes back percent-encoded, as ``%5B`` and
  ``%5D``, because ``cmark-gfm`` and markdown-it both encode them;
* a no-break space or hard break at the end of a paragraph is dropped;
* a line holding only ``*`` is an empty list item in CommonMark, and reads
  back as nothing.

After that first cycle, a further one changes nothing more, with two
exceptions (reproduced 2026-10-02): two adjacent lists with different
bullets read as one loose list, then as one tight list; and a fence whose
info string holds a character reference, such as ``&amp;amp;``, loses one
level of it on each cycle. A two-way sync relies on the rest: once a text
has made one trip, writing what was read back and reading it again gives
the same Markdown.

**A memo read, written back and read again.** This direction is held to more.
The aim is that what the Markdown displays is what the memo displayed, and
that the Markdown is a fixed point from the first read. The converter's tests
check both, by comparing what the HTML and the rendered Markdown display, on
realistic and generated bodies. It is an aim, not a guarantee for every memo:
the lists below say where it falls short.

On the 367 preproduction memos (tier 4: read 2026-10-01 and measured
2026-10-02, one instance, may not generalise), no memo changed a word and 367
of 367 were fixed points. 65 of them displayed differently from the memo, each
in a way listed below. In 62, a table gained an empty header row; 61 of those
are a notification template whose nested table was flattened. The other 3
have no HTML element and are read as literal lines, so they show a line break
or a literal ``&nbsp;`` where an HTML reading would show a space (see above).

A few structures have no Markdown spelling. All but the last keep their words
and lose only their shape:

* **a table nested in a table** has its grid flattened: each inner cell
  becomes text in the outer cell, spaced apart, with every word kept and in
  order. E-mail signatures and notification templates are often laid out
  so;
* **a table without a header row** gains an empty one, because GFM requires a
  header;
* a table cell holds one line, so the paragraphs inside a cell join, while a
  ``<br>`` in a cell is kept as a raw ``<br>``;
* a heading holds one line, so a ``<br>`` in a heading becomes a space;
* a ``[`` or ``]`` in a link target is percent-encoded, as above;
* trailing spaces at the end of a ``<pre>`` are dropped;
* underline, highlight, insertion and strike are kept only as raw
  ``<u>``, ``<mark>``, ``<ins>`` and ``<s>``, so a renderer that drops raw HTML
  shows their text without the formatting;
* two code spans with nothing between them become one span, which shows the
  two backticks that joined them.

**Known holes.** These shapes lose words, or display other than the memo did.
Each was found with synthetic input (reproduced 2026-10-02), and none occurs
in the preproduction sample:

* a table row with more cells than the table's first row loses the extra
  cells, with their words, at the first read;
* a ``|`` inside a ``<pre>``, a link target or a title in a table cell splits
  the row: the rest of the cell is lost or shows as Markdown source;
* a ``<caption>`` or ``<colgroup>`` directly inside a ``<table>``, with no
  ``<tbody>``, turns the table into lines of literal pipes;
* an image whose title holds a ``"`` is lost, and shows as its Markdown
  source;
* a list or an ``<hr>`` inside a table cell shows as ``-`` or ``---`` text;
* a heading followed by text in the same cell, or text sitting directly in a
  nested table after its rows, runs into the next word (``titresuite``);
* a table whose ``<td>`` and ``<tr>`` are never closed folds into one cell,
  keeping its words;
* a definition list (``<dl>``) reads as a ``term`` line and a
  ``: definition`` line, so its display gains the colon;
* bold, italic or struck text (``<b>``, ``<em>``, ``<s>`` and their
  synonyms) wrapped round blocks, other than a single paragraph, shows its
  markers or its tag as text, and a list, a table or a heading inside it as
  Markdown source; round a ``<pre>`` it leaves a fence open, so the rest of
  the memo shows as code.

Some shapes are not fixed points at the first read, and settle after one more
cycle. None broke a fixed point in the preproduction sample. Adjacent lists
read as one loose list, then as one tight list. A definition list's newline
becomes a hard break. Bold inside bold (``<b><b>gras</b></b>``) reads as
``****gras****``, then as ``**gras**``. A link or image title loses a
backslash before punctuation. The caption, colgroup and image-title shapes
above settle too, on what they already lost.

Dependencies and their bounds
-----------------------------

The reader overrides ``markdownify``'s converters and ``mdformat``'s renderer,
which are private surfaces that may move, so most bounds are upper bounds as
well. Two of them were measured against the next major release on 2026-10-02:
``markdown-it-py<4`` and ``mdformat<0.8``. The other two upper bounds,
``markdownify<1.3`` and ``mdformat-tables<1.1``, cap releases that do not exist
yet (none on PyPI on 2026-10-02): they are precautions, because the reader
overrides those libraries' private surfaces. Raise any bound only with the
converter's tests re-run against the new version.

``beautifulsoup4>=4.15``
   Older releases had a defect where a ``<br />`` in a body that also held a
   bare ``<br>`` swallowed the text after it. It no longer reproduced on 4.15.0
   (measured 2026-09-30), and the converter carries no workaround for it.

``cmarkgfm>=2025.10.22``
   The release the writer was measured with. It bundles ``cmark-gfm``
   ``0.29.0.gfm.13`` (read from the library on 2026-10-02). PyPI lists no wheel
   of that release for macOS x86_64 or Windows ARM64 (read 2026-10-02). Unless
   a later release adds one, ``pip`` builds it from source on those platforms,
   which needs a C compiler.

``markdown-it-py>=3.0,<4``
   The image alt-text fix relies on 3.x's ``text_special`` tokens, and 2.x
   measured worse. 4.x caps the cells it fills in, which ends a ragged table
   early.

``markdownify>=1.2.3,<1.3``
   The overrides rely on its ``process_tag`` signature, its ``_inline`` and
   ``_noformat`` pseudo-tags, and how its ``convert_div`` and ``convert_li``
   behave.

``mdformat>=0.7.22,<0.8``
   The escape kept before a ``!`` that precedes a link relies on 0.7.22, and
   ``mdformat-tables`` 1.0 requires ``mdformat<0.8``.

``mdformat-tables>=1.0,<1.1``
   GFM tables for ``mdformat``.

**CVE-2025-6069.** CPython's ``html.parser`` before 3.11.14, 3.12.12 and 3.13.6
takes quadratic time on some unfinished markup
(`python/cpython#135462 <https://github.com/python/cpython/issues/135462>`_,
fixed in those releases according to their changelogs). Many unfinished tags
after a memo's last ``>`` is the shape that reaches the converter, and a memo
is outside data. So ``from_transport`` spells every ``<`` after the last ``>``
as ``&lt;`` before parsing, since no ``<`` there can finish a tag. As a side
effect, whatever follows the memo's last ``>`` reads as text on every
interpreter, where a patched CPython drops some of it: an unfinished tag at
the very end, ``x <a``, reads as ``x \<a``; an unterminated comment,
``<!-- note``, as ``\<!-- note``; and a closing tag cut short inside a link,
``<a href="...">lien</a``, leaves ``\</a`` in the link's text. Prefer a
patched interpreter anyway: the guard covers the converter's input, and the
CPython fix covers the parser itself.

Where it comes from
-------------------

The converter is a port of ``glpi_python_client``'s ``content/conversion.py``
at commit ``917f030``, a file that commit ``524304a`` leaves unchanged. It keeps
the same helpers and the same libraries, and **the two should move together**:
the hard part of both is the behaviour of those libraries, not anything either
ITSM does. On top of ``917f030`` it carries 15 fixes, measured together on
this package's synthetic corpus and on the 367-memo sample, and still to be
proposed to ``glpi_python_client``. The fixes cover:

* image alt text that lost its escapes;
* a line opening with ``~~~``;
* a ``!`` before a link;
* an alt text starting with ``^``;
* a second ``<`` turning text into an autolink;
* ``<br>`` inside inline code;
* tables inside headings and links, and the spacing of flattened cells;
* ``<center>``;
* underline and highlight, as raw tags, except round a block (corrected in
  0.4.1);
* numbering a long ordered list in linear time;
* a quadratic pattern on runs of spaces;
* unreadable ``colspan`` and ``start`` values;
* the CVE-2025-6069 tail.

``CHANGELOG.md`` lists them under 0.4.0, and the correction under 0.4.1.
Apart from those fixes, the names and the error messages, the only
difference from ``glpi_python_client`` is that the libraries are an optional
extra here, not dependencies.
