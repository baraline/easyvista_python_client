from easyvista_python_client._html import html_to_text


def test_none_returns_empty_string():
    assert html_to_text(None) == ""


def test_empty_string_returns_empty():
    assert html_to_text("") == ""


def test_plain_text_passes_through():
    assert html_to_text("just text") == "just text"


def test_strips_tags_and_keeps_text():
    assert html_to_text("<p>Hello <b>world</b></p>") == "Hello world"


def test_unescapes_entities():
    assert html_to_text("Caf&eacute; &amp; co") == "Café & co"


def test_br_and_block_tags_become_newlines():
    assert html_to_text("line1<br>line2") == "line1\nline2"
    assert html_to_text("<p>a</p><p>b</p>") == "a\nb"


def test_collapses_excess_blank_lines():
    assert html_to_text("<div>a</div><br><br><br><div>b</div>") == "a\n\nb"


def test_self_closing_br_becomes_newline():
    assert html_to_text("a<br/>b") == "a\nb"
