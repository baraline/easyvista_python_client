"""The read's ``rewrite_link`` hook, and the embedded image helpers built beside it.

A caller that mirrors memos between systems has to recognise an image the memo
embeds -- an attachment of the request, referred to by its ``DOCUMENT_ID`` --
and say what it becomes, without parsing the HTML or the Markdown itself. The
hook hands it each link and image as the reader meets it; ``document_image``
writes the native form back.
"""

from __future__ import annotations

import threading

import pytest

from easyvista_python_client.content import (
    EasyvistaContentConverter,
    Link,
    RewriteLink,
)
from easyvista_python_client.content.tests.test_round_trip import (
    E_MAIL_SHAPES,
    EARLIER_REGRESSIONS,
    REALISTIC,
)

read = EasyvistaContentConverter.from_transport
render = EasyvistaContentConverter.to_transport
document_image = EasyvistaContentConverter.document_image
document_id_of = EasyvistaContentConverter.document_id_of

#: An editor-pasted image's ``DOCUMENT_ID`` has this shape, and an uploaded file's
#: ``ACCOUNT``. Both synthetic.
PASTED = "0123456789abcdef0123456789abcdef01234567"
UPLOADED = "12345_" + "ab" * 32


def offered(html: str) -> list[Link]:
    """Read ``html`` with a callback that keeps everything, and return what it saw."""

    seen: list[Link] = []

    def keep(link: Link) -> None:
        seen.append(link)

    read(html, rewrite_link=keep)
    return seen


# ---------------------------------------------------------------------------
# What the callback is offered
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "html",
    REALISTIC
    + E_MAIL_SHAPES
    + [html for bodies in EARLIER_REGRESSIONS.values() for html in bodies],
)
def test_a_callback_answering_none_changes_nothing(html: str) -> None:
    assert read(html, rewrite_link=lambda link: None) == read(html)


def test_each_link_and_image_is_offered_once_an_image_before_its_link() -> None:
    html = (
        '<p><a href="https://x.example/p" title="t">'
        '<img src="https://x.example/i.png" alt=" un  logo " title="it"></a>'
        ' et <a href="https://y.example">le &amp; site</a></p>'
    )

    assert offered(html) == [
        Link(
            "https://x.example/i.png",
            "un logo",
            "it",
            image=True,
            enclosing_href="https://x.example/p",
        ),
        Link("https://x.example/p", "", "t"),
        Link("https://y.example", "le & site"),
    ]


def test_an_embedded_image_is_offered_with_its_document_id() -> None:
    html = (
        f'<p><img src="@@EMBEDDED_IMAGE_PATH@@{PASTED}" />'
        f'<img src="@@EMBEDDED_IMAGE_PATH@@{UPLOADED}" alt="x" /></p>'
    )

    assert [link.document_id for link in offered(html)] == [PASTED, UPLOADED]


@pytest.mark.parametrize(
    "src",
    [
        "https://x.example/i.png",
        f"/@@EMBEDDED_IMAGE_PATH@@{PASTED}",
        "@@EMBEDDED_IMAGE_PATH@@",
        "@@EMBEDDED_IMAGE_PATH@@a b",
        "@@EMBEDDED_IMAGE_PATH@@a)b",
        "@@embedded_image_path@@" + PASTED,
    ],
)
def test_any_other_src_carries_no_document_id(src: str) -> None:
    [link] = offered(f'<p><img src="{src}" alt="x"></p>')
    assert link.document_id is None


def test_a_link_carries_no_document_id_whatever_its_href() -> None:
    [link] = offered(f'<p><a href="@@EMBEDDED_IMAGE_PATH@@{PASTED}">x</a></p>')
    assert link.document_id is None
    assert not link.image


@pytest.mark.parametrize(
    "html",
    [
        '<pre><a href="https://x.example">x</a><img src="i.png"></pre>',
        '<p><code><a href="https://x.example">x</a></code></p>',
    ],
)
def test_nothing_inside_code_is_offered(html: str) -> None:
    # Code is displayed as written: what looks like a link there is not one.
    assert offered(html) == []


def test_nothing_is_offered_for_markdown_passed_through() -> None:
    assert offered("[x](https://x.example)") == []
    read("[x](https://x.example)", plain_text_is_markdown=True, rewrite_link=_fail)


def _fail(link: Link) -> None:
    raise AssertionError(f"offered {link!r}")


# ---------------------------------------------------------------------------
# What the answer writes
# ---------------------------------------------------------------------------


def test_a_link_answered_with_a_link_is_written_with_its_href_and_title() -> None:
    markdown = read(
        '<p><a href="https://a.example">le <b>site</b></a></p>',
        rewrite_link=lambda link: Link("https://b.example", title="T"),
    )

    assert markdown == '[le **site**](https://b.example "T")'


def test_a_link_answered_with_no_href_is_dropped_and_its_content_kept() -> None:
    markdown = read(
        '<p>voir <a href="https://a.example">le <b>site</b></a> ici</p>',
        rewrite_link=lambda link: Link(""),
    )

    assert markdown == "voir le **site** ici"


def test_an_image_answered_with_a_link_is_written_with_its_src_alt_and_title() -> None:
    markdown = read(
        '<p><img src="https://a.example/i.png" alt="a"></p>',
        rewrite_link=lambda link: Link("https://b.example/j.png", "b", "t", image=True),
    )

    assert markdown == '![b](https://b.example/j.png "t")'


def test_an_image_answered_with_no_href_is_written_as_its_text() -> None:
    markdown = read(
        '<p>voir <img src="https://a.example/i.png" alt="a"> ici</p>',
        rewrite_link=lambda link: Link("", "capture_1.png", image=True),
    )

    assert markdown == "voir capture_1.png ici"


@pytest.mark.parametrize(
    "html",
    ['<p><a href="https://a.example">x</a></p>', '<p><img src="i.png" alt="x"></p>'],
)
def test_a_string_answer_is_literal_text(html: str) -> None:
    # Escaped as the reader escapes a text node, so it displays as it is and
    # cannot become markup -- whatever the callback hands back.
    text = "**pas gras** [x](javascript:alert(1)) <b>"

    markdown = read(html, rewrite_link=lambda link: text)

    assert render(markdown) == "<p>**pas gras** [x](javascript:alert(1)) &lt;b&gt;</p>"
    assert read(render(markdown)) == markdown


def test_the_editor_wrap_collapses_to_the_image_alone() -> None:
    # A link around an image of the same attachment: the image is rewritten,
    # then the link around it dropped, its content -- the new image -- kept.
    html = (
        f'<p><a href="@@EMBEDDED_IMAGE_PATH@@{PASTED}">'
        f'<img src="@@EMBEDDED_IMAGE_PATH@@{PASTED}" alt="x"></a></p>'
    )

    def rewrite(link: Link) -> Link | None:
        if link.document_id is not None:
            return Link(f"https://files.example/{link.document_id}", image=True)
        if link.href.startswith("@@EMBEDDED_IMAGE_PATH@@"):
            return Link("")
        return None

    assert read(html, rewrite_link=rewrite) == f"![](https://files.example/{PASTED})"


# ---------------------------------------------------------------------------
# What a callback raises, and where its state lives
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error", [ValueError("bad id"), RecursionError(), KeyError("k")]
)
def test_what_the_callback_raises_reaches_the_caller_unchanged(
    error: Exception,
) -> None:
    # A ValueError above all: the reader answers markdownify's by reading the
    # body as its text, and a callback's must not pass for one and quietly
    # cost the body its formatting.
    def fail(link: Link) -> None:
        raise error

    with pytest.raises(type(error)) as caught:
        read('<p><b>gras</b> <a href="https://x.example">x</a></p>', rewrite_link=fail)

    assert caught.value is error


def test_an_answer_of_another_type_is_a_type_error() -> None:
    with pytest.raises(TypeError, match="rewrite_link returned int"):
        read('<p><a href="https://x.example">x</a></p>', rewrite_link=lambda link: 1)  # type: ignore[arg-type,return-value]


def test_the_callback_is_gone_once_the_read_ends_however_it_ends() -> None:
    with pytest.raises(ValueError):
        read(
            '<p><a href="https://x.example">x</a></p>', rewrite_link=_raise_value_error
        )

    assert read('<p><a href="https://x.example">x</a></p>') == "[x](https://x.example)"


def _raise_value_error(link: Link) -> None:
    raise ValueError(link.href)


def test_a_read_inside_a_callback_has_its_own_callback() -> None:
    # And the outer read gets its own back: it is asked about its second link
    # after the nested read has ended.
    calls: list[str] = []

    def outer(link: Link) -> None:
        calls.append(f"outer {link.href}")
        read(
            f'<p><a href="{link.href}/inner">i</a></p>',
            rewrite_link=lambda seen: calls.append(f"inner {seen.href}"),  # type: ignore[func-returns-value]
        )

    read(
        '<p><a href="https://one.example">1</a> <a href="https://two.example">2</a></p>',
        rewrite_link=outer,
    )

    assert calls == [
        "outer https://one.example",
        "inner https://one.example/inner",
        "outer https://two.example",
        "inner https://two.example/inner",
    ]


def test_each_thread_reads_with_its_own_callback() -> None:
    # Both reads are inside their callbacks at once: a callback held on the
    # shared converter would be the other thread's by the time it is called.
    barrier = threading.Barrier(2, timeout=10)
    seen: dict[str, list[str]] = {"a": [], "b": []}
    failures: list[BaseException] = []

    def reader(name: str) -> None:
        def note(link: Link) -> None:
            barrier.wait()
            seen[name].append(link.href)

        try:
            read(f'<p><a href="https://{name}.example/1">1</a></p>', rewrite_link=note)
        except BaseException as exc:
            failures.append(exc)

    threads = [threading.Thread(target=reader, args=(name,)) for name in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert seen == {"a": ["https://a.example/1"], "b": ["https://b.example/1"]}


# ---------------------------------------------------------------------------
# Embedded images
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("document_id", [PASTED, UPLOADED])
def test_document_id_of_reads_an_embedded_images_src(document_id: str) -> None:
    assert document_id_of(f"@@EMBEDDED_IMAGE_PATH@@{document_id}") == document_id


@pytest.mark.parametrize(
    "src",
    [
        "",
        "@@EMBEDDED_IMAGE_PATH@@",
        "https://x.example/i.png",
        f" @@EMBEDDED_IMAGE_PATH@@{PASTED}",
    ],
)
def test_document_id_of_answers_none_for_anything_else(src: str) -> None:
    assert document_id_of(src) is None


def test_the_prefix_is_published() -> None:
    assert EasyvistaContentConverter.EMBEDDED_IMAGE_PREFIX == "@@EMBEDDED_IMAGE_PATH@@"


@pytest.mark.parametrize("document_id", [PASTED, UPLOADED])
def test_document_image_renders_as_the_editor_writes_a_pasted_image(
    document_id: str,
) -> None:
    assert render(document_image(document_id, alt="capture.png")) == (
        f'<p><img src="@@EMBEDDED_IMAGE_PATH@@{document_id}" alt="capture.png" /></p>'
    )


@pytest.mark.parametrize(
    "alt", ["", "capture.png", "a_b*c [d] `e` <f> !", "  deux   mots  "]
)
def test_document_image_is_what_the_reader_writes_for_the_native_image(
    alt: str,
) -> None:
    markdown = document_image(PASTED, alt=alt)

    assert read(render(markdown)) == markdown
    [link] = offered(render(markdown))
    assert (link.document_id, link.text) == (PASTED, " ".join(alt.split()))


@pytest.mark.parametrize("document_id", ["", "a b", "a)b", "x" * 129, "é"])
def test_document_image_refuses_what_is_not_a_document_id(document_id: str) -> None:
    with pytest.raises(ValueError, match="not an EasyVista DOCUMENT_ID"):
        document_image(document_id)


def test_document_image_is_not_rewritten_by_a_read_in_progress() -> None:
    written: list[str] = []

    def rewrite(link: Link) -> None:
        written.append(document_image(PASTED, alt="x"))

    read('<p><a href="https://x.example">x</a></p>', rewrite_link=rewrite)

    assert written == [f"![x](@@EMBEDDED_IMAGE_PATH@@{PASTED})"]


def test_rewrite_link_is_a_public_type() -> None:
    callback: RewriteLink = lambda link: None  # noqa: E731
    assert read("<p>x</p>", rewrite_link=callback) == "x"
